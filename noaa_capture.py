from datetime import datetime, timedelta, timezone
from skyfield.api import load, wgs84
import subprocess
import os

# -----------------------------
# Настройки
# -----------------------------
RECORD_DIR = "records"
os.makedirs(RECORD_DIR, exist_ok=True)

CENTER_FREQ = 137.9125e6  # NOAA-18
SAMPLE_RATE = 60000
GAIN = 40

MSK = timezone(timedelta(hours=3))

LAT = 57.582914
LON = 39.907135
ALT = 0.1  # км


# -----------------------------
# Загрузка TLE
# -----------------------------
def load_noaa_sat(catnr=28654):  # NOAA-18
    ts = load.timescale()
    url = f'https://celestrak.org/NORAD/elements/gp.php?CATNR={catnr}&FORMAT=tle'
    sats = load.tle_file(url)
    return ts, sats[0]


# -----------------------------
# Форматирование времени
# -----------------------------
def fmt(dt):
    return dt.astimezone(MSK).strftime("%Y-%m-%d %H:%M:%S %Z")


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
    current = {}

    for ti, ev in zip(t, events):
        if ev == 0:
            current = {'aos': ti}
        elif ev == 1:
            current['tca'] = ti
        elif ev == 2:
            current['los'] = ti
            passes.append(current)
            current = {}

    return passes[0] if passes else None


# -----------------------------
# Запись сигнала RTL-SDR
# -----------------------------
def record_pass(aos_dt, los_dt):
    duration = int((los_dt - aos_dt).total_seconds()) + 20

    wav_name = f"noaa18_{aos_dt.strftime('%Y%m%d_%H%M%S')}.wav"
    wav_path = os.path.join(RECORD_DIR, wav_name)

    cmd_rtl = [
        "rtl_fm",
        "-f", str(CENTER_FREQ),
        "-s", str(SAMPLE_RATE),
        "-g", str(GAIN),
        "-E", "deemp",
        "-F", "9",
        "-A", "fast",
        "-"
    ]

    cmd_sox = [
        "sox",
        "-t", "raw",
        "-r", str(SAMPLE_RATE),
        "-e", "signed",
        "-b", "16",
        "-c", "1",
        "-",
        wav_path
    ]

    print(f"Записываю сигнал {duration} секунд → {wav_path}")

    p1 = subprocess.Popen(cmd_rtl, stdout=subprocess.PIPE)
    p2 = subprocess.Popen(cmd_sox, stdin=p1.stdout)
    p1.stdout.close()
    p2.wait(timeout=duration + 60)

    return wav_path


# -----------------------------
# Декодирование через SatDump
# -----------------------------
def decode_apt_satdump(wav_path, sat_name, aos_dt_msk):
    img_name = f"{sat_name}_{aos_dt_msk.strftime('%Y%m%d_%H%M%S')}.png"
    img_path = os.path.join(RECORD_DIR, img_name)

    cmd = [
        "satdump",
        "apt",
        "-i", wav_path,
        "-o", img_path
    ]

    print(f"Декодирую через SatDump → {img_path}")
    subprocess.run(cmd, check=True)

    return img_path


# ------------------------------------------------------------
# AOS / TCA / LOS — ключевые точки спутникового пролёта
#
# AOS (Acquisition of Signal) — момент появления сигнала.
# TCA (Time of Closest Approach) — максимальная высота.
# LOS (Loss of Signal) — момент потери сигнала.
# ------------------------------------------------------------


# -----------------------------
# Основной запуск
# -----------------------------
if __name__ == "__main__":
    ts, sat = load_noaa_sat()
    p = next_pass(ts, sat)

    if not p:
        print("Пролётов в ближайшие часы нет.")
        exit(0)

    now_utc = datetime.now(timezone.utc)

    # Извлекаем события (могут отсутствовать)
    aos_utc = p.get('aos')
    tca_utc = p.get('tca')
    los_utc = p.get('los')

    # Преобразуем только существующие
    if aos_utc:
        aos_utc = aos_utc.utc_datetime().replace(tzinfo=timezone.utc)
    if tca_utc:
        tca_utc = tca_utc.utc_datetime().replace(tzinfo=timezone.utc)
    if los_utc:
        los_utc = los_utc.utc_datetime().replace(tzinfo=timezone.utc)

    # Определяем, внутри ли мы пролёта
    inside_pass = False

    if aos_utc and los_utc:
        inside_pass = aos_utc <= now_utc <= los_utc
    elif (not aos_utc) and tca_utc and los_utc:
        inside_pass = now_utc <= los_utc

    # Вывод информации о пролёте
    print("Следующий пролёт NOAA‑18:")
    if aos_utc:
        print("AOS:", fmt(aos_utc))
    if tca_utc:
        print("TCA:", fmt(tca_utc))
    if los_utc:
        print("LOS:", fmt(los_utc))

    if inside_pass:
        print("Мы внутри окна пролёта — начинаем запись и декодирование.")

        # Если AOS отсутствует — используем текущее время как начало
        start_time = aos_utc if aos_utc else now_utc

        wav_path = record_pass(start_time, los_utc)

        sat_name = sat.name.replace(" ", "")
        aos_msk = start_time.astimezone(MSK)

        img_path = decode_apt_satdump(wav_path, sat_name, aos_msk)

        print(f"Готово! Картинка сохранена: {img_path}")
    else:
        print("Сейчас не время пролёта.")
