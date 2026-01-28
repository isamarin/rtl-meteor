from datetime import datetime, timedelta, timezone
from skyfield.api import load, wgs84
from datetime import timezone, timedelta



MSK = timezone(timedelta(hours=3))
# Координаты твоей точки (пример: Ярославская область)
# 57.582914, 39.907135 Мой текущий адрес
LAT = 57.582914
LON = 39.907135
ALT = 0.1  # км



def load_noaa_sat(catnr=28654):  # по умолчанию NOAA-18
    ts = load.timescale()
    url = f'https://celestrak.org/NORAD/elements/gp.php?CATNR={catnr}&FORMAT=tle'
    sats = load.tle_file(url)
    sat = sats[0]  # в ответе всегда один спутник
    return ts, sat




def fmt(dt):
    return dt.astimezone(MSK).strftime("%Y-%m-%d %H:%M:%S %Z")


def next_pass(ts, sat, minutes_ahead=180):
    # Текущее время в UTC с tzinfo
    now = datetime.now(timezone.utc)

    # Конец окна поиска
    end = now + timedelta(minutes=minutes_ahead)

    # Skyfield принимает timezone-aware datetime
    t0 = ts.from_datetime(now)
    t1 = ts.from_datetime(end)

    observer = wgs84.latlon(LAT, LON, ALT)

    t, events = sat.find_events(observer, t0, t1, altitude_degrees=10.0)

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

# ------------------------------------------------------------
# AOS / TCA / LOS — ключевые точки спутникового пролёта
#
# AOS (Acquisition of Signal) — момент появления сигнала.
#     Спутник поднимается над горизонтом и становится доступен
#     для приёма. С этого момента можно начинать запись.
#
# TCA (Time of Closest Approach) — момент максимального сближения.
#     Спутник проходит на минимальной дистанции и максимальной
#     высоте над горизонтом. Лучшее качество сигнала и изображения.
#
# LOS (Loss of Signal) — момент потери сигнала.
#     Спутник опускается ниже горизонта, приём прекращается.
#     После этого запись можно останавливать.
#
# Типичный цикл:
#   AOS → спутник появляется → TCA (пик сигнала) → LOS → исчезает.
# ------------------------------------------------------------.

if __name__ == "__main__":
    ts, noaa18 = load_noaa_sat()
    p = next_pass(ts, noaa18)
    if p:
        print("Следующий пролёт NOAA‑18:")
        for k, v in p.items():
            # Skyfield → datetime без tzinfo → добавляем UTC
            dt_utc = v.utc_datetime().replace(tzinfo=timezone.utc)

            # Выводим сразу в московском времени
            print(f"{k.upper()}: {fmt(dt_utc)}")
    else:
        print("Пролётов в ближайшие часы нет.")
