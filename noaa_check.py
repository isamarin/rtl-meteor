from skyfield.api import load, wgs84
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter
from geopy.distance import geodesic
from geo_context.geo_context import geo_context

geolocator = Nominatim(user_agent="noaa_locator")
reverse = RateLimiter(geolocator.reverse, min_delay_seconds=1)


# Определение океана по координатам
def ocean_by_coords(lat, lon):
    if -60 <= lat <= 60 and -180 <= lon <= -70:
        return "Тихим океаном"
    if -60 <= lat <= 70 and -70 <= lon <= 20:
        return "Атлантическим океаном"
    if -60 <= lat <= 30 and 20 <= lon <= 150:
        return "Индийским океаном"
    if lat < -60:
        return "Южным океаном"
    return None

# Ближайшие страны (центры)
NEARBY_COUNTRIES = {
    "Чили": (-35.7, -71.5),
    "Перу": (-9.2, -75.0),
    "Эквадор": (-1.8, -78.2),
    "Колумбия": (4.5, -74.1),
    "Французская Полинезия": (-17.7, -149.4),
    "Остров Пасхи": (-27.1, -109.3),
}

# Определение континента по координатам
def get_continent(lat, lon):
    if lat < -60:
        return "Антарктида"
    if lat > 60:
        return "Арктика"
    if -30 <= lat <= 60 and -170 <= lon <= -30:
        return "Северная Америка"
    if -60 <= lat <= 15 and -90 <= lon <= -30:
        return "Южная Америка"
    if 0 <= lat <= 70 and -30 <= lon <= 60:
        return "Европа"
    if 5 <= lat <= 80 and 60 <= lon <= 180:
        return "Азия"
    if -40 <= lat <= 35 and 10 <= lon <= 55:
        return "Африка"
    if -50 <= lat <= 10 and 110 <= lon <= 180:
        return "Австралия"
    return None

# Преобразование направления в русское "юго‑восточнее"
def direction_name(dlat, dlon):
    ns = "севернее" if dlat > 0 else "южнее"
    ew = "восточнее" if dlon > 0 else "западнее"

    if ns == "севернее" and ew == "восточнее":
        return "северо‑восточнее"
    if ns == "севернее" and ew == "западнее":
        return "северо‑западнее"
    if ns == "южнее" and ew == "восточнее":
        return "юго‑восточнее"
    if ns == "южнее" and ew == "западнее":
        return "юго‑западнее"

    return f"{ns} и {ew}"

def describe_location(lat, lon):
    try:

        context = geo_context(lat, lon)
        if context:
            return context

        location = reverse((lat, lon), language="ru")
        addr = location.raw.get("address", {}) if location else {}


        # 1. Океаны и моря из Nominatim
        if "ocean" in addr:
            return f"над {addr['ocean']}"
        if "sea" in addr:
            return f"над {addr['sea']}"

        country = addr.get("country")
        state = addr.get("state")
        city = addr.get("city") or addr.get("town") or addr.get("village")

        # 2. Если есть город
        if city:
            city_lat = location.latitude
            city_lon = location.longitude
            dist_km = int(geodesic((lat, lon), (city_lat, city_lon)).km)

            dlat = lat - city_lat
            dlon = lon - city_lon
            direction = direction_name(dlat, dlon)

            return (
                f"над территорией {country}, примерно в {dist_km} км "
                f"{direction} города {city}"
            )

        # 3. Если есть регион
        if state and country:
            return f"в регионе {state}, {country}"

        # 4. Если есть страна
        if country:
            return f"над территорией {country}"

        # 5. Океан по координатам (fallback)
        ocean = ocean_by_coords(lat, lon)
        if ocean:
            best_country = None
            best_dist = 999999
            best_dir = None

            for cname, (clat, clon) in NEARBY_COUNTRIES.items():
                dist = geodesic((lat, lon), (clat, clon)).km
                if dist < best_dist:
                    best_dist = dist
                    dlat = lat - clat
                    dlon = lon - clon
                    best_dir = direction_name(dlat, dlon)
                    best_country = cname

            return (
                f"над {ocean}, примерно в {int(best_dist)} км "
                f"{best_dir} {best_country}"
            )

        # 6. Континент (fallback)
        continent = get_continent(lat, lon)
        if continent:
            return f"над континентом {continent}"

        # 7. Совсем ничего
        return "неизвестный регион"

    except Exception:
        return "ошибка определения региона"


LAT = 57.582914
LON = 39.907135
ALT = 0.29  # км

ts = load.timescale()
sat = load.tle_file("https://celestrak.org/NORAD/elements/gp.php?CATNR=28654&FORMAT=tle")[0]

#t = ts.utc(2026, 2, 14, 14, 15, 53)
t = ts.now()


observer = wgs84.latlon(LAT, LON, ALT)
difference = sat - observer
topo = difference.at(t)

alt, az, distance = topo.altaz()  # вот тут берём дистанцию

sub = wgs84.subpoint(sat.at(t))

lat = sub.latitude.degrees
lon = sub.longitude.degrees

region = describe_location(lat, lon)




print("Subsatellite LAT:", sub.latitude.degrees, "LON:", sub.longitude.degrees)
print("Регион:", region)

print("From window: ALT:", alt.degrees, "AZ:", az.degrees)
print("Slant range (km):", distance.km)
