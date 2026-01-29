import time
import os
import subprocess
from datetime import datetime, timedelta, timezone
from skyfield.api import load, wgs84

# -----------------------------
# Настройки
# -----------------------------
RECORD_DIR = "records"
os.makedirs(RECORD_DIR, exist_ok=True)

CENTER_FREQ = 137.9125e6
SAMPLE_RATE = 60000
GAIN = 40

MSK = timezone(timedelta(hours=3))

LAT = 57.582914
LON = 39.907135
ALT = 0.1  # км

def fmt_msk(dt):
    return dt.astimezone(MSK).strftime("%Y-%m-%d %H:%M:%S %Z")


# -----------------------------
# Поиск бинарников
# -----------------------------
def find_rtl_fm():
    candidates = [
        "/usr/local/bin/rtl_fm",
        "/opt/homebrew/bin/rtl_fm",
        "/usr/bin/rtl_fm",
    ]
    for d in os.environ.get("PATH", "").split(":"):
        candidates.append(os.path.join(d, "rtl_fm"))
    for p in candidates:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    raise FileNotFoundError("rtl_fm не найден")


def find_sox():
    candidates = [
        "/usr/local/bin/sox",
        "/opt/homebrew/bin/sox",
        "/usr/bin/sox",
    ]
    for d in os.environ.get("PATH", "").split(":"):
        candidates.append(os.path.join(d, "sox"))
    for p in candidates:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    raise FileNotFoundError("sox не найден")


RTL_FM = find_rtl_fm()
SOX = find_sox()


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

    wav_name = f"noaa18_{aos_dt.strftime('%Y%m%d_%H%M%S')}.wav"
    wav_path = os.path.join(RECORD_DIR, wav_name)

    cmd_rtl = [
        RTL_FM,
        "-f", str(CENTER_FREQ),
        "-s", str(SAMPLE_RATE),
        "-g", str(GAIN),
        "-E", "deemp",
        "-F", "9",
        "-A", "fast",
        "-"
    ]

    cmd_sox = [
        SOX,
        "-t", "raw",
        "-r", str(SAMPLE_RATE),
        "-e", "signed",
        "-b", "16",
        "-c", "1",
        "-",
        wav_path
    ]

    print(f"▶ Начинаю запись {duration} сек → {wav_path}")

    try:
        p1 = subprocess.Popen(cmd_rtl, stdout=subprocess.PIPE)
    except Exception as e:
        print("❌ rtl_fm не запустился:", e)
        return None


    p2 = subprocess.Popen(cmd_sox, stdin=p1.stdout)

    p1.stdout.close()

    # Ждём rtl_fm (он завершится ровно в LOS)
    p1.wait()

    # Закрываем stdin sox
    try:
        p2.stdin.close()
    except:
        pass

    # Ждём sox
    try:
        p2.wait(timeout=10)
    except subprocess.TimeoutExpired:
        print("⚠ sox завис — убиваю")
        p2.kill()

    return wav_path


# -----------------------------
# Декодирование через SatDump
# -----------------------------
def decode_apt(wav_path, aos_dt):
    img_name = f"NOAA18_{aos_dt.strftime('%Y%m%d_%H%M%S')}.png"
    img_path = os.path.join(RECORD_DIR, img_name)

    cmd = [
        "satdump",
        "apt",
        "-i", wav_path,
        "-o", img_path
    ]

    print(f"🖼 Декодирую → {img_path}")
    subprocess.run(cmd, check=False)

    return img_path


# -----------------------------
# Главный цикл демона
# -----------------------------
def run_daemon():
    print("🚀 NOAA‑18 демон запущен")

    while True:
        try:
            ts, sat = load_noaa_sat()
            p = next_pass(ts, sat)

            if not p:
                print("Нет пролётов, сплю 10 минут")
                time.sleep(600)
                continue

            # Извлекаем события, но они могут отсутствовать
            aos = p.get("aos")
            tca = p.get("tca")
            los = p.get("los")

            # LOS обязателен — без него нет смысла писать
            if los is None:
                print("❌ Пролёт без LOS — пропускаю")
                time.sleep(60)
                continue

            los = los.utc_datetime().replace(tzinfo=timezone.utc)

            now = datetime.now(timezone.utc)

            # Если AOS есть — отлично
            if aos is not None:
                aos = aos.utc_datetime().replace(tzinfo=timezone.utc)

            # Если AOS нет, но есть TCA → стартуем сейчас
            elif tca is not None:
                print("⚠ Нет AOS, но есть TCA — начинаю запись немедленно")
                aos = now

            # Если есть только LOS → тоже стартуем сейчас
            else:
                print("⚠ Нет AOS/TCA — стартую сейчас, пока не поздно")
                aos = now

            now = datetime.now(timezone.utc)

            if now < aos:
                wait = (aos - now).total_seconds()

                aos_msk = aos.astimezone(MSK)
                now_msk = now.astimezone(MSK)
                delta = aos - now
                total = int(delta.total_seconds())
                h = total // 3600
                m = (total % 3600) // 60
                s = total % 60
                print(f"⏳ Жду до AOS: {fmt_msk(aos)} (через {h:02d}:{m:02d}:{s:02d})")

                time.sleep(wait)

            print("📡 Начинаю приём")
            wav = record_pass(aos, los)

            print("🧩 Декодирование")
            decode_apt(wav, aos)

            print("✔ Готово. Жду следующий пролёт.\n")

        except Exception as e:
            print("❌ Ошибка:", e)
            print("Сплю 60 секунд и продолжаю…")
            time.sleep(60)


if __name__ == "__main__":
    run_daemon()
