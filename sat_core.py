"""
sat_core.py — общий модуль для RTL-METEOR.

Константы наблюдателя, загрузка TLE, поиск и анализ пролётов,
логика видимости из окна, очистка записей.
"""

import os
import time
import shutil
from datetime import datetime, timedelta, timezone
import numpy as np
from skyfield.api import load, wgs84

# -----------------------------
# Константы наблюдателя (Ярославль)
# -----------------------------
LAT = 57.582914
LON = 39.907135
ALT = 0.29  # км (290 м)

MSK = timezone(timedelta(hours=3))

# Сектор окна по данным Apple Watch
WINDOW_MIN_AZ = 16   # левая кромка
WINDOW_MAX_AZ = 90   # правая кромка

# Параметры SDR
CENTER_FREQ = 137.900e6
RAW_SAMPLE_RATE = 2880000
GAIN = 40

# Целевой спутник
SAT_NAME = "METEOR-M2-3"
SAT_CATNR = 57166

# Записи
RECORD_DIR = "records"
MAX_RECORD_AGE_DAYS = 30

# Lock-файл демона
LOCK_FILE = "/tmp/rtl_meteor.lock"


# -----------------------------
# Утилиты
# -----------------------------
def normalize_time(t):
    """Гарантируем: либо None, либо одиночный Skyfield Time."""
    if t is None:
        return None
    try:
        shape = getattr(t, 'shape', None)
        if shape is not None and shape != ():
            return t[0]
    except Exception:
        pass
    return t


def fmt_msk(dt):
    """Форматирует datetime в строку MSK."""
    return dt.astimezone(MSK).strftime("%Y-%m-%d %H:%M:%S %Z")


# -----------------------------
# Загрузка TLE
# -----------------------------
def load_sat(catnr=SAT_CATNR):
    """Загружает TLE с Celestrak, возвращает (ts, sat)."""
    ts = load.timescale()
    url = f'https://celestrak.org/NORAD/elements/gp.php?CATNR={catnr}&FORMAT=tle'
    sats = load.tle_file(url)
    return ts, sats[0]


# -----------------------------
# Поиск пролётов
# -----------------------------
def find_passes(ts, sat, hours_ahead=12):
    """Возвращает список пролётов [{aos, tca, los}, ...] на hours_ahead часов."""
    now = datetime.now(timezone.utc)
    start = now - timedelta(minutes=5)
    end = now + timedelta(hours=hours_ahead)

    t0 = ts.from_datetime(start)
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

    return passes


def next_pass(ts, sat, minutes_ahead=180):
    """Возвращает ближайший будущий пролёт или None."""
    passes = find_passes(ts, sat, hours_ahead=minutes_ahead / 60)
    now_ts = ts.from_datetime(datetime.now(timezone.utc))

    for p in passes:
        tca = normalize_time(p.get("tca"))
        los = normalize_time(p.get("los"))
        if tca is not None and tca > now_ts:
            return p
        if tca is None and los is not None and los > now_ts:
            return p

    return None


# -----------------------------
# Анализ пролёта
# -----------------------------
def analyze_pass(ts, sat, p):
    """Рассчитывает азимуты и высоты для AOS/TCA/LOS."""
    observer = wgs84.latlon(LAT, LON, ALT)

    aos = normalize_time(p.get("aos"))
    tca = normalize_time(p.get("tca"))
    los = normalize_time(p.get("los"))

    if tca is None or los is None:
        raise ValueError("В analyze_pass нет TCA или LOS")

    if aos is not None:
        aos_alt, aos_az, _ = (sat - observer).at(aos).altaz()
        aos_alt = aos_alt.degrees
        aos_az = aos_az.degrees
    else:
        aos_alt = None
        aos_az = None

    tca_alt, tca_az, _ = (sat - observer).at(tca).altaz()
    tca_alt = tca_alt.degrees
    tca_az = tca_az.degrees

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
# Логика видимости
# -----------------------------
def pass_visible(aos_az, tca_az, los_az, tca_alt):
    """Возвращает (visible: bool, reason: str)."""
    if tca_alt < 25:
        return False, "низкая высота (<25\u00b0)"

    if WINDOW_MIN_AZ <= tca_az <= WINDOW_MAX_AZ:
        return True, "TCA в секторе окна"

    if aos_az is not None and WINDOW_MIN_AZ <= aos_az <= WINDOW_MAX_AZ:
        return True, "видно начало пролёта"

    if WINDOW_MIN_AZ <= los_az <= WINDOW_MAX_AZ:
        return True, "виден конец пролёта"

    return False, "пролёт вне сектора окна"


# -----------------------------
# Очистка старых записей
# -----------------------------
def cleanup_old_records():
    """Удаляет записи старше MAX_RECORD_AGE_DAYS и осиротевшие .raw файлы."""
    if not os.path.isdir(RECORD_DIR):
        return 0

    cutoff = time.time() - MAX_RECORD_AGE_DAYS * 86400
    removed = 0

    for name in os.listdir(RECORD_DIR):
        path = os.path.join(RECORD_DIR, name)

        if name.endswith(".raw"):
            try:
                os.remove(path)
                removed += 1
            except OSError:
                pass
            continue

        if os.path.isdir(path) and os.path.getmtime(path) < cutoff:
            try:
                shutil.rmtree(path)
                removed += 1
            except OSError:
                pass

    return removed


# -----------------------------
# Позиция спутника
# -----------------------------
def satellite_position(ts, sat):
    """Возвращает текущие координаты подспутниковой точки и данные от наблюдателя."""
    t = ts.now()
    observer = wgs84.latlon(LAT, LON, ALT)

    sub = wgs84.subpoint(sat.at(t))
    alt, az, distance = (sat - observer).at(t).altaz()

    return {
        "lat": sub.latitude.degrees,
        "lon": sub.longitude.degrees,
        "alt_deg": alt.degrees,
        "az_deg": az.degrees,
        "distance_km": distance.km,
    }


def satellite_ground_track(ts, sat, minutes_back=30, minutes_ahead=90, step=1):
    """Возвращает подспутниковые точки трассы: (past_points, future_points).

    Каждый список — [(lat, lon), ...].
    Использует векторизованный skyfield для быстрого расчёта.
    """
    now = ts.now()
    now_jd = now.tt

    back_offsets = np.arange(-minutes_back, 0, step) / (24 * 60)
    ahead_offsets = np.arange(0, minutes_ahead + step, step) / (24 * 60)

    past_times = ts.tt_jd(now_jd + back_offsets)
    future_times = ts.tt_jd(now_jd + ahead_offsets)

    past_sub = wgs84.subpoint_of(sat.at(past_times))
    future_sub = wgs84.subpoint_of(sat.at(future_times))

    past_points = list(zip(
        past_sub.latitude.degrees.tolist(),
        past_sub.longitude.degrees.tolist(),
    ))
    future_points = list(zip(
        future_sub.latitude.degrees.tolist(),
        future_sub.longitude.degrees.tolist(),
    ))

    return past_points, future_points
