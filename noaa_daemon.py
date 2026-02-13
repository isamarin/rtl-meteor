import time
import os
import subprocess
from datetime import datetime, timedelta, timezone
from skyfield.api import load, wgs84
from rich.progress import Progress
import fcntl, sys

LOCK_FILE = "/tmp/rtl_meteor.lock"

fp = open(LOCK_FILE, "w")

try:
    fcntl.flock(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    print("⚠ Скрипт уже запущен, выходим.")
    sys.exit(0)

# Записываем PID внутрь файла (не обязательно, но удобно)
fp.write(str(os.getpid()))
fp.flush()

# -----------------------------
# Настройки
# -----------------------------
RECORD_DIR = "records"
os.makedirs(RECORD_DIR, exist_ok=True)

CENTER_FREQ = 137.9125e6
GAIN = 40

MSK = timezone(timedelta(hours=3))

LAT = 57.582914
LON = 39.907135
ALT = 0.1  # км

# Сектор окна: север (0°) → северо-восток (70°)
WINDOW_MIN_AZ = 0
WINDOW_MAX_AZ = 70




def analyze_pass(ts, sat, p):
    observer = wgs84.latlon(LAT, LON, ALT)

    aos = p["aos"]
    tca = p["tca"]
    los = p["los"]

    aos_alt, aos_az, _ = (sat - observer).at(aos).altaz()
    tca_alt, tca_az, _ = (sat - observer).at(tca).altaz()
    los_alt, los_az, _ = (sat - observer).at(los).altaz()

    return {
        "aos": aos.utc_datetime(),
        "tca": tca.utc_datetime(),
        "los": los.utc_datetime(),
        "aos_az": aos_az.degrees,
        "tca_az": tca_az.degrees,
        "los_az": los_az.degrees,
        "tca_alt": tca_alt.degrees
    }

def pass_visible(info):



    # Высота слишком низкая
    if info["tca_alt"] < 30:
        return False, "низкая высота (<30°)"

    # TCA в секторе окна
    if WINDOW_MIN_AZ <= info["tca_az"] <= WINDOW_MAX_AZ:
        return True, "TCA в секторе окна"

    # AOS или LOS в секторе — слабый, но возможный
    if WINDOW_MIN_AZ <= info["aos_az"] <= WINDOW_MAX_AZ:
        return True, "видно начало пролёта"
    if WINDOW_MIN_AZ <= info["los_az"] <= WINDOW_MAX_AZ:
        return True, "виден конец пролёта"

    return False, "пролёт вне сектора окна"


def fmt_msk(dt):
    return dt.astimezone(MSK).strftime("%Y-%m-%d %H:%M:%S %Z")


# -----------------------------
# Загрузка TLE
# -----------------------------
def load_noaa_sat(catnr=28654):  # NOAA‑18
    ts = load.timescale()
    url = f'https://celestrak.org/NORAD/elements/gp.php?CATNR={catnr}&FORMAT=tle'
    sats = load.tle_file(url)
    return ts, sats[0]


# -----------------------------
# Поиск следующего пролёта
# -----------------------------
def next_pass(ts, sat, minutes_ahead=180):
    now = datetime.now(timezone.utc)
    end = now + timedelta(minutes=minutes_ahead)

    t0 = ts.from_datetime(now)
    t1 = ts.from_datetime(end)

    observer = wgs84.latlon(LAT, LON, ALT)
    t, events = sat.find_events(observer, t0, t1, altitude_degrees=5.0)

    passes = []
    cur = {}

    for ti, ev in zip(t, events):
        if ev == 0:
            cur = {"aos": ti}
        elif ev == 1:
            cur["tca"] = ti
        elif ev == 2:
            cur["los"] = ti
            passes.append(cur)
            cur = {}

    return passes[0] if passes else None


# -----------------------------
# Запись сигнала
# -----------------------------
def record_pass(aos_dt, los_dt):
    duration = int((los_dt - aos_dt).total_seconds()) + 20

    RAW_SAMPLE_RATE = 1920000
    samples = RAW_SAMPLE_RATE * duration

    raw_name = f"noaa18_{aos_dt.strftime('%Y%m%d_%H%M%S_%f')}.raw"
    raw_path = os.path.join(RECORD_DIR, raw_name)

    if os.path.exists(raw_path):
        try:
            os.remove(raw_path)
        except:
            pass

    print(f"▶ Начинаю запись {duration} сек → RAW {raw_path}")

    cmd_rtl = [
        "rtl_sdr",
        "-f", str(int(CENTER_FREQ)),
        "-s", str(RAW_SAMPLE_RATE),
        "-g", str(GAIN),
        "-n", str(samples),
        raw_path
    ]

    try:
        p = subprocess.Popen(cmd_rtl)
        p.wait(timeout=duration + 30)
    except subprocess.TimeoutExpired:
        print("⚠ rtl_sdr завис — убиваю")
        p.kill()

    if not os.path.exists(raw_path):
        print("❌ RAW файл не создан")
        return None

    size = os.path.getsize(raw_path)
    if size < 5_000_000:
        print(f"❌ RAW слишком маленький ({size} байт) — запись не удалась")
        try:
            os.remove(raw_path)
            print(f"🗑 Удалил пустой RAW: {raw_path}")
        except:
            pass
        return None

    return raw_path



# -----------------------------
# Декодирование через SatDump
# -----------------------------
def decode_apt(raw_path, aos_dt):
    # Папка для результата
    out_dir = os.path.join(RECORD_DIR, aos_dt.strftime("%Y%m%d_%H%M%S"))
    os.makedirs(out_dir, exist_ok=True)

    # Абсолютный путь к RECORD_DIR (монтируется как /data)
    mount_dir = os.path.abspath(RECORD_DIR)

    # Имя RAW внутри контейнера
    raw_name = os.path.basename(raw_path)

    # Имя выходной папки внутри контейнера
    out_name = aos_dt.strftime("%Y%m%d_%H%M%S")

    cmd = [
        "docker", "compose", "run", "--rm",
        "satdump",
        "satdump",
        "noaa_apt",
        "baseband",
        f"/data/{raw_name}",
        f"/data/{out_name}",
        "--samplerate", "1920000",
        "--baseband_format", "u8"
    ]

    print(f"🖼 Декодирую RAW → {out_dir}")
    subprocess.run(cmd, check=False)

    # Ищем PNG
    pngs = [f for f in os.listdir(out_dir) if f.lower().endswith(".png")]
    if not pngs:
        print("❌ SatDump не создал PNG — декодирование не удалось")
        return None

    img_path = os.path.join(out_dir, pngs[0])
    print(f"🖼 PNG готов: {img_path}")
    return img_path

# -----------------------------
# Главный цикл демона
# -----------------------------
def run_daemon():
    print("🚀 NOAA‑18 демон запущен")

    try:
        while True:
            ts, sat = load_noaa_sat()
            p = next_pass(ts, sat)

            if not p:
                print("Нет пролётов, сплю 10 минут")
                time.sleep(600)
                continue

            aos = p.get("aos")
            tca = p.get("tca")
            los = p.get("los")

            # Если нет AOS — пропускаем пролёт
            if aos is None:
                print("⚠ Пролёт без AOS — пропускаю")
                time.sleep(60)
                continue

            # 1) Проверяем, что есть LOS
            if los is None:
                print("❌ Пролёт без LOS — пропускаю")
                time.sleep(60)
                continue

            # 2) Анализируем пролёт
            info = analyze_pass(ts, sat, p)

            # Пролёт проходит по южной стороне — точно не видно
            if info["tca_az"] > 180:
                print("❌ Пролёт проходит по южной стороне — из окна не видно\n")
                time.sleep(60)
                continue

            # Высота TCA слишком низкая
            if info["tca_alt"] < 60:
                print("❌ Высота TCA слишком низкая — сигнал будет слабым\n")
                time.sleep(60)
                continue

            # Ни одна часть пролёта не проходит через сектор окна
            if not (WINDOW_MIN_AZ <= info["aos_az"] <= WINDOW_MAX_AZ or
                    WINDOW_MIN_AZ <= info["tca_az"] <= WINDOW_MAX_AZ or
                    WINDOW_MIN_AZ <= info["los_az"] <= WINDOW_MAX_AZ):
                print("❌ Ни одна часть пролёта не проходит через сектор окна\n")
                time.sleep(60)
                continue

            visible, reason = pass_visible(info)

            print(f"🛰 Пролёт NOAA-18:")
            print(f" AOS азимут {info['aos_az']:.1f}°")
            print(f" TCA азимут {info['tca_az']:.1f}° высота {info['tca_alt']:.1f}°")
            print(f" LOS азимут {info['los_az']:.1f}°")
            print(f" ➜ Оценка: {reason}")

            # 3) Проверяем видимость
            if not visible:
                print("❌ Пролёт не виден из окна — пропускаю\n")
                time.sleep(60)
                continue

            print("👍 Пролёт виден — готовлюсь к приёму\n")

            los = los.utc_datetime().replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)

            if aos is not None:
                aos = aos.utc_datetime().replace(tzinfo=timezone.utc)
            elif tca is not None:
                print("⚠ Нет AOS, но есть TCA — начинаю запись немедленно")
                aos = now
            else:
                print("⚠ Нет AOS/TCA — стартую сейчас, пока не поздно")
                aos = now

            now = datetime.now(timezone.utc)

            if now < aos:
                wait_seconds = int((aos - now).total_seconds())



                with Progress() as progress:
                    task = progress.add_task(
                        f"⏳ Жду до AOS: {fmt_msk(aos)}",
                        total=wait_seconds
                    )

                    for _ in range(wait_seconds):
                        progress.update(task, advance=1)
                        time.sleep(1)

            print("📡 Начинаю приём")

            raw = record_pass(aos, los)
            if raw is None:
                print("⚠ Пропускаю декодирование — нет RAW")
                continue

            print("🧩 Декодирование")
            decode_apt(raw, aos)

            print("✔ Готово. Жду следующий пролёт.\n")

    except KeyboardInterrupt:
        print("\n🛑 Остановка демона по запросу пользователя. Завершаю работу...")
        fp.close()
        sys.exit(130)
    except Exception as e:
        print("❌ Необработанная ошибка в демоне:", e)
        fp.close()
        sys.exit(1)


if __name__ == "__main__":
    run_daemon()
