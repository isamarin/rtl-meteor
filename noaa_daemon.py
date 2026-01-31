import time
import os
import subprocess
from datetime import datetime, timedelta, timezone
from skyfield.api import load, wgs84

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

    # Делаем имя уникальным за счёт микросекунд
    raw_name = f"noaa18_{aos_dt.strftime('%Y%m%d_%H%M%S_%f')}.raw"
    raw_path = os.path.join(RECORD_DIR, raw_name)

    # Если по какой-то причине файл уже есть — удалим
    if os.path.exists(raw_path):
        try:
            os.remove(raw_path)
        except OSError as e:
            print(f"⚠ Не удалось удалить существующий RAW {raw_path}: {e}")
            return None

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
        print(f"❌ RAW файл не создан: {raw_path}")
        return None

    size = os.path.getsize(raw_path)
    if size < 1_000_000:
        print(f"❌ RAW файл слишком маленький ({size} байт) — запись не удалась")
        return None

    return raw_path


# -----------------------------
# Декодирование через SatDump
# -----------------------------
def decode_apt(raw_path, aos_dt):
    img_name = f"NOAA18_{aos_dt.strftime('%Y%m%d_%H%M%S')}.png"
    img_path = os.path.join(RECORD_DIR, img_name)

    cmd = [
        "satdump",
        "apt",
        "-i", raw_path,
        "-o", img_path,
        "--samplerate", "1920000",
        "--frequency", str(int(CENTER_FREQ)),
        "--opencl-device", "1",
        "--no-config",
    ]

    print(f"🖼 Декодирую RAW → {img_path}")
    subprocess.run(cmd, check=False)

    if not os.path.exists(img_path):
        print("❌ SatDump не создал PNG — декодирование не удалось")
        return None

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

            if los is None:
                print("❌ Пролёт без LOS — пропускаю")
                time.sleep(60)
                continue

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
                delta = aos - now
                total = int(delta.total_seconds())
                h = total // 3600
                m = (total % 3600) // 60
                s = total % 60
                print(f"⏳ Жду до AOS: {fmt_msk(aos)} (через {h:02d}:{m:02d}:{s:02d})")
                time.sleep(delta.total_seconds())

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
