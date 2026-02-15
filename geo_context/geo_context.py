import json
import math
from shapely.geometry import Point, Polygon, MultiPolygon
import pymorphy3
morph = pymorphy3.MorphAnalyzer()

# -----------------------------
# Загрузка морей из seas.json
# -----------------------------
with open("seas.json", "r", encoding="utf-8") as f:
    SEAS = json.load(f)

def inflect_sea(name):
    # Пример: "Баренцево море" → "Баренцевым морем"
    words = name.split()
    if len(words) == 2 and words[1].lower() == "море":
        adj = morph.parse(words[0])[0].inflect({"ins"})  # творительный падеж
        return f"{adj.word} морем"
    return name

def inflect_ocean(name):
    # "Тихий океан" → "Тихим океаном"
    words = name.split()
    if len(words) == 2 and words[1].lower() == "океан":
        adj = morph.parse(words[0])[0].inflect({"ins"})
        return f"{adj.word} океаном"
    return name

def inflect_ocean_region(region, ocean):
    # region: "южной частью"
    # ocean: "Тихого океана"
    return f"{region} {ocean}"

def inflect_country(country):
    p = morph.parse(country)[0]
    return p.inflect({"gen"}).word  # родительный падеж


# -----------------------------
# Определение расстояния
# -----------------------------
def haversine(lat1, lon1, lat2, lon2):
    R = 6371  # km
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# -----------------------------
# Определение направления
# -----------------------------
def bearing_direction(lat1, lon1, lat2, lon2):
    dlon = math.radians(lon2 - lon1)
    lat1 = math.radians(lat1)
    lat2 = math.radians(lat2)

    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1)*math.sin(lat2) - math.sin(lat1)*math.cos(lat2)*math.cos(dlon)

    brng = (math.degrees(math.atan2(x, y)) + 360) % 360

    dirs = [
        (22.5, "к северу"),
        (67.5, "к северо-востоку"),
        (112.5, "к востоку"),
        (157.5, "к юго-востоку"),
        (202.5, "к югу"),
        (247.5, "к юго-западу"),
        (292.5, "к западу"),
        (337.5, "к северо-западу"),
        (360, "к северу")
    ]

    for angle, name in dirs:
        if brng <= angle:
            return name

    return "к северу"


# -----------------------------
# Определение моря по полигону
# -----------------------------
def find_sea(lat, lon):
    point = Point(lon, lat)

    for sea in SEAS:
        poly = sea["polygon"]
        if poly["type"] == "Polygon":
            polygon = Polygon(poly["coordinates"][0])
        else:
            polygon = MultiPolygon([Polygon(coords) for coords in poly["coordinates"]])

        if polygon.contains(point):
            return sea["name"]

    return None


# -----------------------------
# Определение океана
# -----------------------------
def find_ocean(lat, lon):
    if lat < -55:
        return "Южный океан"

    if -60 <= lon <= 20:
        return "Атлантический океан"
    if 20 < lon <= 150:
        return "Индийский океан"
    return "Тихий океан"


# -----------------------------
# Определение части океана
# -----------------------------
def ocean_region(lat):
    if lat > 20:
        return "северной частью"
    if -20 <= lat <= 20:
        return "центральной частью"
    return "южной частью"


# -----------------------------
# Ближайшие страны и города
# -----------------------------
COUNTRIES = [
    ("Россия", 55.75, 37.61),
    ("Норвегия", 59.91, 10.75),
    ("Чили", -33.45, -70.66),
    ("Япония", 35.68, 139.69),
    ("США", 38.90, -77.03),
    ("Канада", 45.42, -75.69),
    ("Австралия", -35.28, 149.13),
]

CITIES = [
    ("Осло", 59.91, 10.75),
    ("Токио", 35.68, 139.69),
    ("Сантьяго", -33.45, -70.66),
    ("Владивосток", 43.12, 131.88),
    ("Мурманск", 68.97, 33.08),
]


def find_nearest(lat, lon, items):
    best = None
    best_dist = 999999

    for name, lat2, lon2 in items:
        d = haversine(lat, lon, lat2, lon2)
        if d < best_dist:
            best_dist = d
            best = (name, d, lat2, lon2)

    return best


# -----------------------------
# Основная функция
# -----------------------------
def geo_context(lat, lon):
    sea = find_sea(lat, lon)

    if sea:
        # море найдено
        country, dist, clat, clon = find_nearest(lat, lon, COUNTRIES)

        if dist > 1000:
            return f"над открытой частью {sea}"

        direction = bearing_direction(lat, lon, clat, clon)
        sea_ins = inflect_sea(sea)
        country_gen = inflect_country(country)
        return f"над {sea_ins}, на расстоянии около {int(dist)} км {direction} от {country_gen}"

    # иначе — океан
    ocean = find_ocean(lat, lon)
    region = ocean_region(lat)

    country, dist, clat, clon = find_nearest(lat, lon, COUNTRIES)
    direction = bearing_direction(lat, lon, clat, clon)

    return f"над {region} {ocean}, на расстоянии около {int(dist)} км {direction} от {country}"
