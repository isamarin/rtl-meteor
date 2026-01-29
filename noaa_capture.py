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


def find_rtl_fm():
    # Возможные пути для macOS (Intel и ARM)
    candidates = [
        "/usr/local/bin/rtl_fm",
        "/opt/homebrew/bin/rtl_fm",
        "/usr/bin/rtl_fm",
        "/usr/local/sbin/rtl_fm",
        "/opt/homebrew/sbin/rtl_fm",
    ]

    # Проверяем стандартный PATH
    for path_dir in os.environ.get("PATH", "").split(":"):
        candidates.append(os.path.join(path_dir, "rtl_fm"))

    # Проверяем каждый путь
    for path in candidates:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path

    # Если не нашли — выводим понятную ошибку
    raise FileNotFoundError(
        "rtl_fm не найден. Убедись, что пакет rtl-sdr установлен через Homebrew.\n"
        "Попробуй: brew reinstall rtl-sdr"
    )

def find_sox():
    candidates = [
        "/usr/local/bin/sox",
        "/opt/homebrew/bin/sox",
        "/usr/bin/sox",
        "/usr/local/sbin/sox",
        "/opt/homebrew/sbin/sox",
    ]

    for path_dir in os.environ.get("PATH", "").split(":"):
        candidates.append(os.path.join(path_dir, "sox"))

    for path in candidates:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path

    raise FileNotFoundError(
        "sox не найден. Установи через Homebrew: brew install sox"
    )


# -----------------------------
# Запись сигнала RTL-SDR
# -----------------------------
def record_pass(aos_dt, los_dt):
    duration = int((los_dt - aos_dt).total_seconds()) + 20

    wav_name = f"noaa18_{aos_dt.strftime('%Y%m%d_%H%M%S')}.wav"
    wav_path = os.path.join(RECORD_DIR, wav_name)

    rtl_fm_path = find_rtl_fm()
    sox_path = find_sox()

    cmd_rtl = [
        rtl_fm_path,
        "-f", str(CENTER_FREQ),
        "-s", str(SAMPLE_RATE),
        "-g", str(GAIN),
        "-E", "deemp",
        "-F", "9",
        "-A", "fast",
        "-"
    ]

    cmd_sox = [
        sox_path,
        "-t", "raw",
        "-r", str(SAMPLE_RATE),
        "-e", "signed",
        "-b", "16",
        "-c", "1",
        "-",
        wav_path
    ]

    print(f"Записываю сигнал {duration} секунд → {wav_path}")

    # Запускаем rtl_fm → stdout → sox
    p1 = subprocess.Popen(cmd_rtl, stdout=subprocess.PIPE)
    p2 = subprocess.Popen(cmd_sox, stdin=p1.stdout)

    # rtl_fm больше не должен писать в stdout напрямую
    p1.stdout.close()

    # Ждём rtl_fm (он завершится ровно в LOS)
    p1.wait()

    # Закрываем stdin sox, чтобы он понял, что поток закончился
    try:
        p2.stdin.close()
    except Exception:
        pass

    # Ждём sox, но недолго
    try:
        p2.wait(timeout=10)
    except subprocess.TimeoutExpired:
        print("⚠️ sox не завершился вовремя — принудительно завершаю.")
        p2.kill()

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

def delta_str(target_dt, now_dt):
    delta = target_dt - now_dt
    total_seconds = int(delta.total_seconds())

    if total_seconds < 0:
        return "(уже прошло)"

    h = total_seconds // 3600
    m = (total_seconds % 3600) // 60
    s = total_seconds % 60

    return f"({h:02d}:{m:02d}:{s:02d})"


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
    if aos_utc is not None:
        aos_utc = aos_utc.utc_datetime().replace(tzinfo=timezone.utc)

    if tca_utc is not None:
        tca_utc = tca_utc.utc_datetime().replace(tzinfo=timezone.utc)

    if los_utc is not None:
        los_utc = los_utc.utc_datetime().replace(tzinfo=timezone.utc)


    # Определяем, внутри ли мы пролёта
    inside_pass = False

    if aos_utc is not None and los_utc is not None:
        inside_pass = aos_utc <= now_utc <= los_utc

    elif aos_utc is None and tca_utc is not None and los_utc is not None:
        inside_pass = now_utc <= los_utc

    # Вывод информации о пролёте
    print("Следующий пролёт NOAA‑18:")
    if aos_utc is not None:
        print("AOS:", fmt(aos_utc), delta_str(aos_utc, now_utc))
    if tca_utc is not None:
        print("TCA:", fmt(tca_utc), delta_str(tca_utc, now_utc))
    if los_utc is not None:
        print("LOS:", fmt(los_utc), delta_str(los_utc, now_utc))

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

