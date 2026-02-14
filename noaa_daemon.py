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

# Сектор окна по данным Apple Watch
WINDOW_MIN_AZ = 16      # левая кромка
WINDOW_MAX_AZ = 90      # правая кромка

# Высота точки наблюдения
ALT = 0.29  # км (290 м)


def normalize_time(t):
    """Гарантируем: либо None, либо одиночный Time."""
    if t is None:
        return None
    # Skyfield Time может быть массивом — берём первый элемент
    try:
        # У Time есть атрибут shape: () — скаляр, (N,) — массив
        shape = getattr(t, 'shape', None)
        if shape is not None and shape != ():
            return t[0]
    except Exception:
        pass
    return t


def log_status(msg):
    now = datetime.now(MSK).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{now}] {msg}"
    sys.stdout.write("\r" + line)
    sys.stdout.flush()


# -----------------------------
# Анализ пролёта (безопасный)
# -----------------------------
def analyze_pass(ts, sat, p):
    observer = wgs84.latlon(LAT, LON, ALT)

    aos = normalize_time(p.get("aos"))
    tca = normalize_time(p.get("tca"))
    los = normalize_time(p.get("los"))

    if tca is None or los is None:
        raise ValueError("В analyze_pass нет TCA или LOS")

    # AOS
    if aos is not None:
        aos_alt, aos_az, _ = (sat - observer).at(aos).altaz()
        aos_alt = aos_alt.degrees
        aos_az = aos_az.degrees
    else:
        aos_alt = None
        aos_az = None

    # TCA
    tca_alt, tca_az, _ = (sat - observer).at(tca).altaz()
    tca_alt = tca_alt.degrees
    tca_az = tca_az.degrees

    # LOS
    los_alt, los_az, _ = (sat - observer).at(los).altaz()
    los_alt = los_alt.degrees
    los_az = los_az.degrees

    return {
        "aos_time": aos,
        "tca_time": tca,
        "los_time": los,
        "aos_az": aos_az,
        "tca_az": tca_az,
        "los_az": los_az,
        "tca_alt": tca_alt,
    }


# -----------------------------
# Логика видимости (как в прогнозе)
# -----------------------------
def pass_visible(aos_az, tca_az, los_az, tca_alt):
    # Порог по высоте
    if tca_alt < 18:
        return False, "низкая высота (<18°)"

    # TCA в секторе окна
    if WINDOW_MIN_AZ <= tca_az <= WINDOW_MAX_AZ:
        return True, "TCA в секторе окна"

    # AOS или LOS в секторе — слабый, но возможный
    if aos_az is not None and WINDOW_MIN_AZ <= aos_az <= WINDOW_MAX_AZ:
        return True, "видно начало пролёта"

    if WINDOW_MIN_AZ <= los_az <= WINDOW_MAX_AZ:
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
    start = now - timedelta(minutes=5)  # чуть в прошлое
    end = now + timedelta(minutes=minutes_ahead)

    t0 = ts.from_datetime(start)
    t1 = ts.from_datetime(end)

    observer = wgs84.latlon(LAT, LON, ALT)
    t, events = sat.find_events(observer, t0, t1, altitude_degrees=5.0)

    passes = []
    cur = {}

    for ti, ev in zip(t, events):
        if ev == 0:          # AOS
            cur = {"aos": ti}
        elif ev == 1:        # TCA
            cur["tca"] = ti
        elif ev == 2:        # LOS
            cur["los"] = ti
            passes.append(cur)
            cur = {}

    now_ts = ts.from_datetime(now)
    for p in passes:
        tca = normalize_time(p.get("tca"))
        los = normalize_time(p.get("los"))
        if tca is not None and tca > now_ts:
            return p
        if tca is None and los is not None and los > now_ts:
            return p

    return None


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
        log_status("❌ RAW файл не создан")
        return None

    size = os.path.getsize(raw_path)
    if size < 5_000_000:
        log_status(f"❌ RAW слишком маленький ({size} байт) — запись не удалась")
        try:
            os.remove(raw_path)
        except:
            pass
        return None

    return raw_path


# -----------------------------
# Декодирование через SatDump
# -----------------------------
def decode_apt(raw_path, aos_dt):
    out_dir = os.path.join(RECORD_DIR, aos_dt.strftime("%Y%m%d_%H%M%S"))
    os.makedirs(out_dir, exist_ok=True)

    raw_name = os.path.basename(raw_path)
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
                log_status("Нет пролётов, сплю 10 минут")
                time.sleep(600)
                continue

            # Нормализуем времена сразу
            aos = normalize_time(p.get("aos"))
            tca = normalize_time(p.get("tca"))
            los = normalize_time(p.get("los"))

            if los is None:
                log_status("❌ Пролёт без LOS — пропускаю")
                time.sleep(60)
                continue

            # Безопасный анализ пролёта
            try:
                info = analyze_pass(ts, sat, {
                    "aos": aos,
                    "tca": tca,
                    "los": los,
                })
            except Exception as e:
                print("⚠ Ошибка в analyze_pass:", e)
                print("  raw pass:", p)
                time.sleep(60)
                continue

            # Отсекаем южные пролёты
            if 90 <= info["tca_az"] <= 270:
                log_status("❌ Пролёт проходит по южной стороне — из окна не видно")
                time.sleep(60)
                continue

            # Порог по высоте
            if info["tca_alt"] < 18:
                log_status("❌ Высота TCA слишком низкая — сигнал будет слабым")
                time.sleep(60)
                continue

            visible, reason = pass_visible(
                info["aos_az"],
                info["tca_az"],
                info["los_az"],
                info["tca_alt"]
            )

            if not visible:
                log_status("❌ Пролёт не виден из окна — пропускаю")
                time.sleep(60)
                continue

            print("🛰 Пролёт NOAA-18:")
            if info["aos_az"] is not None:
                print(f" AOS азимут {info['aos_az']:.1f}°")
            else:
                print(" AOS: нет данных (пролёт уже начался)")
            print(f" TCA азимут {info['tca_az']:.1f}° высота {info['tca_alt']:.1f}°")
            print(f" LOS азимут {info['los_az']:.1f}°")
            print(f" ➜ Оценка: {reason}")
            print("👍 Пролёт виден — готовлюсь к приёму\n")

            # Время для записи
            los_dt = info["los_time"].utc_datetime().replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)

            if info["aos_time"] is not None:
                aos_dt = info["aos_time"].utc_datetime().replace(tzinfo=timezone.utc)
            else:
                print("⚠ Нет AOS — начинаю запись немедленно")
                aos_dt = now

            now = datetime.now(timezone.utc)

            if now < aos_dt:
                wait_seconds = int((aos_dt - now).total_seconds())
                with Progress() as progress:
                    task = progress.add_task(
                        f"⏳ Жду до AOS: {fmt_msk(aos_dt)}",
                        total=wait_seconds
                    )
                    for _ in range(wait_seconds):
                        progress.update(task, advance=1)
                        time.sleep(1)

            print("📡 Начинаю приём")

            raw = record_pass(aos_dt, los_dt)
            if raw is None:
                print("⚠ Пропускаю декодирование — нет RAW")
                continue

            print("🧩 Декодирование")
            decode_apt(raw, aos_dt)

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
