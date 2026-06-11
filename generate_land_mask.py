"""
generate_land_mask.py — генерация растровой маски суши для глобуса TUI.

Скачивает Natural Earth 110m land shapefile, растеризует в bitmap 360×180
(1° разрешение), сжимает zlib + base64, записывает в land_mask.py как
Python-модуль с константой и функциями доступа.

Запуск: python generate_land_mask.py
"""

import io
import json
import math
import urllib.request
import zlib
import base64
import zipfile

NE_URL = "https://naturalearth.s3.amazonaws.com/110m_physical/ne_110m_land.zip"
OUTPUT_FILE = "land_mask.py"
WIDTH = 360   # 1° per pixel
HEIGHT = 180  # 1° per pixel


def download_zip(url):
    print(f"Downloading {url} ...")
    with urllib.request.urlopen(url) as resp:
        return resp.read()


def point_in_polygon(px, py, polygon):
    """Ray-casting algorithm for point-in-polygon test."""
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def read_geojson_from_zip(zip_bytes):
    """Read features from the shapefile zip (via embedded .shp or .geojson)."""
    try:
        from fiona.io import ZipMemoryFile
        from shapely.geometry import shape as shp_shape
        print("Reading shapefile with fiona/shapely...")
        with ZipMemoryFile(zip_bytes) as memfile:
            with memfile.open() as shp:
                polygons = []
                for feature in shp:
                    geom = shp_shape(feature["geometry"])
                    if geom.geom_type == "Polygon":
                        polygons.append([list(geom.exterior.coords)])
                    elif geom.geom_type == "MultiPolygon":
                        for poly in geom.geoms:
                            polygons.append([list(poly.exterior.coords)])
                return polygons
    except ImportError:
        pass

    # Fallback: look for GeoJSON inside the zip
    print("fiona not available, looking for GeoJSON in zip...")
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    geojson_name = None
    for name in zf.namelist():
        if name.endswith(".geojson") or name.endswith(".json"):
            geojson_name = name
            break

    if geojson_name is None:
        raise RuntimeError(
            "No GeoJSON found in zip and fiona is not installed. "
            "Install fiona+shapely: pip install fiona shapely"
        )

    data = json.loads(zf.read(geojson_name))
    polygons = []
    for feature in data["features"]:
        geom = feature["geometry"]
        if geom["type"] == "Polygon":
            polygons.append(geom["coordinates"])
        elif geom["type"] == "MultiPolygon":
            for poly_coords in geom["coordinates"]:
                polygons.append(poly_coords)
    return polygons


def rasterize(polygons, width, height):
    """Rasterize polygon list into a width×height boolean grid.

    Grid convention: row 0 = 90°N, row 179 = 89°S
                     col 0 = 180°W, col 359 = 179°E
    """
    grid = [[False] * width for _ in range(height)]

    for poly_rings in polygons:
        exterior = poly_rings[0]  # outer ring, [(lon, lat), ...]

        # Bounding box for early reject
        lons = [p[0] for p in exterior]
        lats = [p[1] for p in exterior]
        min_lon, max_lon = min(lons), max(lons)
        min_lat, max_lat = min(lats), max(lats)

        col_min = max(0, int(math.floor(min_lon + 180)))
        col_max = min(width - 1, int(math.floor(max_lon + 180)))
        row_min = max(0, int(math.floor(90 - max_lat)))
        row_max = min(height - 1, int(math.floor(90 - min_lat)))

        for row in range(row_min, row_max + 1):
            lat = 90 - row - 0.5  # center of pixel
            for col in range(col_min, col_max + 1):
                if grid[row][col]:
                    continue
                lon = col - 180 + 0.5  # center of pixel
                if point_in_polygon(lon, lat, exterior):
                    grid[row][col] = True

    return grid


def pack_grid(grid, width, height):
    """Pack boolean grid into bytes (bit-packed), then zlib+base64."""
    bits = bytearray()
    byte = 0
    bit_idx = 0
    for row in range(height):
        for col in range(width):
            if grid[row][col]:
                byte |= (1 << bit_idx)
            bit_idx += 1
            if bit_idx == 8:
                bits.append(byte)
                byte = 0
                bit_idx = 0
    if bit_idx > 0:
        bits.append(byte)

    compressed = zlib.compress(bytes(bits), 9)
    encoded = base64.b64encode(compressed).decode("ascii")
    return encoded


def write_module(b64_data, width, height, output_file):
    code = f'''"""
land_mask.py — растровая маска суши 360×180 (1° разрешение).

Сгенерировано скриптом generate_land_mask.py из Natural Earth 110m land.
НЕ РЕДАКТИРОВАТЬ ВРУЧНУЮ.
"""

import base64
import zlib

LAND_WIDTH = {width}
LAND_HEIGHT = {height}

LAND_MASK_B64 = (
    "{b64_data}"
)


def load_land_mask():
    """Распаковывает маску суши в list[list[bool]] (180 строк × 360 столбцов).

    row 0 = 90°N, row 179 = 89°S
    col 0 = 180°W, col 359 = 179°E
    """
    raw = zlib.decompress(base64.b64decode(LAND_MASK_B64))
    grid = [[False] * LAND_WIDTH for _ in range(LAND_HEIGHT)]
    for row in range(LAND_HEIGHT):
        for col in range(LAND_WIDTH):
            bit_index = row * LAND_WIDTH + col
            byte_index = bit_index // 8
            bit_offset = bit_index % 8
            if raw[byte_index] & (1 << bit_offset):
                grid[row][col] = True
    return grid


def is_land(lat, lon, mask=None):
    """Проверяет, является ли точка (lat, lon) сушей.

    Если mask не передана, загружает и кеширует при первом вызове.
    """
    if mask is None:
        if not hasattr(is_land, "_cache"):
            is_land._cache = load_land_mask()
        mask = is_land._cache

    row = int(90 - lat)
    col = int(lon + 180)

    row = max(0, min(LAND_HEIGHT - 1, row))
    col = max(0, min(LAND_WIDTH - 1, col))

    return mask[row][col]
'''

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(code)

    print(f"Written {output_file} ({len(b64_data)} chars base64)")


def main():
    zip_bytes = download_zip(NE_URL)
    polygons = read_geojson_from_zip(zip_bytes)
    print(f"Got {len(polygons)} polygon(s), rasterizing {WIDTH}×{HEIGHT} ...")
    grid = rasterize(polygons, WIDTH, HEIGHT)

    land_count = sum(sum(row) for row in grid)
    total = WIDTH * HEIGHT
    print(f"Land pixels: {land_count}/{total} ({100*land_count/total:.1f}%)")

    b64_data = pack_grid(grid, WIDTH, HEIGHT)
    write_module(b64_data, WIDTH, HEIGHT, OUTPUT_FILE)
    print("Done!")


if __name__ == "__main__":
    main()
