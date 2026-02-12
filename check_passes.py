from datetime import datetime, timedelta, timezone
from skyfield.api import load, wgs84

# Координаты Ярославля
LAT = 57.582914
LON = 39.907135
ALT = 0.1  # км

# Сектор окна: север (0°) → северо-восток (70°)
WINDOW_MIN_AZ = 0
WINDOW_MAX_AZ = 70

MSK = timezone(timedelta(hours=3))

def fmt(dt):
    return dt.astimezone(MSK).strftime("%Y-%m-%d %H:%M:%S")

def load_sat(catnr):
    ts = load.timescale()
    url = f'https://celestrak.org/NORAD/elements/gp.php?CATNR={catnr}&FORMAT=tle'
    sats = load.tle_file(url)
    return ts, sats[0]

def find_passes(ts, sat, hours=12):
    now = datetime.now(timezone.utc)
    end = now + timedelta(hours=hours)

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

    return passes

def analyze_pass(ts, sat, p):
    observer = wgs84.latlon(LAT, LON, ALT)

    aos = p["aos"]
    tca = p["tca"]
    los = p["los"]

    # Вычисляем азимуты и высоту
    aos_alt, aos_az, _ = (sat - observer).at(aos).altaz()
    tca_alt, tca_az, _ = (sat - observer).at(tca).altaz()
    los_alt, los_az, _ = (sat - observer).at(los).altaz()

    return {
        "aos": aos.utc_datetime(),
        "los": los.utc_datetime(),
        "tca": tca.utc_datetime(),
        "aos_az": aos_az.degrees,
        "tca_az": tca_az.degrees,
        "los_az": los_az.degrees,
        "tca_alt": tca_alt.degrees
    }

def in_window(az):
    if WINDOW_MIN_AZ <= az <= WINDOW_MAX_AZ:
        return True
    return False

def main():
    print("🔭 Проверка пролётов NOAA над Ярославлем\n")

    ts, sat = load_sat(28654)  # NOAA-18
    passes = find_passes(ts, sat, hours=12)

    if not passes:
        print("Нет пролётов в ближайшие 12 часов")
        return

    for p in passes:
        info = analyze_pass(ts, sat, p)

        print("──────────────────────────────")
        print(f"🛰 Пролёт NOAA-18")
        print(f"AOS: {fmt(info['aos'])}  азимут {info['aos_az']:.1f}°")
        print(f"TCA: {fmt(info['tca'])}  азимут {info['tca_az']:.1f}°  высота {info['tca_alt']:.1f}°")
        print(f"LOS: {fmt(info['los'])}  азимут {info['los_az']:.1f}°")

        # Оценка видимости из окна
        if info["tca_alt"] < 30:
            print("❌ Низкий пролёт — из окна почти не видно")
        elif in_window(info["tca_az"]):
            print("👍 Отличный пролёт — видно из окна, можно ловить")
        elif in_window(info["aos_az"]) or in_window(info["los_az"]):
            print("⚠ Видно только начало или конец — сигнал слабый")
        else:
            print("❌ Пролёт проходит вне сектора окна")

    print("──────────────────────────────")

if __name__ == "__main__":
    main()
