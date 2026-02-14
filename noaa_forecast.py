from datetime import datetime, timedelta, timezone
from skyfield.api import load, wgs84

# --- Настройки ---
LAT = 57.582914
LON = 39.907135
# Сектор окна по данным Apple Watch
WINDOW_MIN_AZ = 16      # левая кромка
WINDOW_MAX_AZ = 90      # правая кромка

# Высота точки наблюдения
ALT = 0.29  # км (290 м)

MSK = timezone(timedelta(hours=3))

# NOAA-18 = 28654
# NOAA-19 = 33591
SAT_IDS = {
    "NOAA-18": 28654,
    "NOAA-19": 33591
}

def load_sat(catnr):
    ts = load.timescale()
    url = f"https://celestrak.org/NORAD/elements/gp.php?CATNR={catnr}&FORMAT=tle"
    sats = load.tle_file(url)
    return ts, sats[0]

def visible_from_window(az):
    return WINDOW_MIN_AZ <= az <= WINDOW_MAX_AZ

def forecast_satellite(name, catnr, days=10):
    print(f"\n===== Прогноз пролётов {name} на {days} дней =====\n")

    ts, sat = load_sat(catnr)
    observer = wgs84.latlon(LAT, LON, ALT)

    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days)

    t0 = ts.from_datetime(now)
    t1 = ts.from_datetime(end)

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

    for p in passes:
        aos = p["aos"]
        tca = p["tca"]
        los = p["los"]

        aos_alt, aos_az, _ = (sat - observer).at(aos).altaz()
        tca_alt, tca_az, _ = (sat - observer).at(tca).altaz()
        los_alt, los_az, _ = (sat - observer).at(los).altaz()

        visible = (
            visible_from_window(aos_az.degrees) or
            visible_from_window(tca_az.degrees) or
            visible_from_window(los_az.degrees)
        )

        print(f"Дата: {tca.utc_datetime().astimezone(MSK):%Y-%m-%d}")
        print(f" AOS: {aos.utc_datetime().astimezone(MSK):%H:%M:%S}  азимут {aos_az.degrees:5.1f}°")
        print(f" TCA: {tca.utc_datetime().astimezone(MSK):%H:%M:%S}  азимут {tca_az.degrees:5.1f}°  высота {tca_alt.degrees:4.1f}°")
        print(f" LOS: {los.utc_datetime().astimezone(MSK):%H:%M:%S}  азимут {los_az.degrees:5.1f}°")

        print(f" Видимость из окна: {'ДА' if visible else 'нет'}")
        print("-" * 50)

if __name__ == "__main__":
    for name, catnr in SAT_IDS.items():
        forecast_satellite(name, catnr, days=10)
