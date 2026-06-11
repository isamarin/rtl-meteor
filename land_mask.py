"""
land_mask.py — растровая маска суши 360×180 (1° разрешение).

Сгенерировано скриптом generate_land_mask.py из Natural Earth 110m land.
НЕ РЕДАКТИРОВАТЬ ВРУЧНУЮ.
"""

import base64
import zlib

LAND_WIDTH = 360
LAND_HEIGHT = 180

LAND_MASK_B64 = (
    "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"
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
