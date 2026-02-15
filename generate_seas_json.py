import json
import urllib.request
import zipfile
import io
import fiona
from fiona.io import ZipMemoryFile
from shapely.geometry import shape, Polygon, MultiPolygon
from deep_translator import GoogleTranslator
translator = GoogleTranslator(source='en', target='ru')


NE_URL = "https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_geography_marine_polys.zip"
OUTPUT_FILE = "seas.json"
SIMPLIFY_TOLERANCE = 0.02  # degrees


def download_zip(url):
    print("Downloading Natural Earth marine polygons ZIP...")
    with urllib.request.urlopen(url) as response:
        return response.read()


def read_shapes_from_memory(zip_bytes):
    print("Reading shapefile from memory...")

    with ZipMemoryFile(zip_bytes) as memfile:
        with memfile.open() as shp:
            seas = []

            for feature in shp:
                name = feature["properties"].get("name")
                if not name:
                    continue

                geom = shape(feature["geometry"])
                geom_simplified = geom.simplify(SIMPLIFY_TOLERANCE, preserve_topology=True)

                if isinstance(geom_simplified, Polygon):
                    coords = [list(map(list, geom_simplified.exterior.coords))]
                    poly_type = "Polygon"

                elif isinstance(geom_simplified, MultiPolygon):
                    coords = []
                    for poly in geom_simplified.geoms:
                        coords.append(list(map(list, poly.exterior.coords)))
                    poly_type = "MultiPolygon"

                else:
                    continue

                name_ru = translator.translate(name)

                seas.append({
                    "name_en": name,
                    "name": name_ru,
                    "polygon": {
                        "type": poly_type,
                        "coordinates": coords
                    }
                })

            return seas


def write_json(seas):
    print(f"Writing {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(seas, f, ensure_ascii=False, indent=2)
    print(f"Done! Generated {OUTPUT_FILE} with {len(seas)} seas.")


def main():
    zip_bytes = download_zip(NE_URL)
    seas = read_shapes_from_memory(zip_bytes)
    write_json(seas)


if __name__ == "__main__":
    main()
