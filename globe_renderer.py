"""
globe_renderer.py — ASCII-рендер 3D-глобуса в ортографической проекции.

Чистый модуль без зависимостей от Textual. Используется GlobeTab в meteor_tui.py.
"""

import math


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _darken(r, g, b, factor):
    """Apply brightness factor (0..1) to RGB color."""
    return (
        int(r * factor),
        int(g * factor),
        int(b * factor),
    )


# Colors (RGB tuples)
COLOR_OCEAN = (20, 40, 80)
COLOR_LAND = (30, 80, 30)
COLOR_SAT = (255, 60, 60)
COLOR_OBSERVER = (255, 230, 50)
COLOR_TRACK_FUTURE = (80, 220, 255)
COLOR_TRACK_PAST = (40, 100, 120)


def render_globe(
    width,
    height,
    center_lat,
    center_lon,
    land_mask,
    sat_lat=None,
    sat_lon=None,
    observer_lat=None,
    observer_lon=None,
    track_future=None,
    track_past=None,
):
    """Render a 3D globe as Rich-compatible markup text.

    Parameters
    ----------
    width, height : int
        Terminal character dimensions for the widget.
    center_lat, center_lon : float
        Center of orthographic projection (degrees).
    land_mask : list[list[bool]]
        180×360 boolean grid from land_mask module.
    sat_lat, sat_lon : float or None
        Satellite sub-point (degrees).
    observer_lat, observer_lon : float or None
        Observer position (degrees).
    track_future : list[(lat, lon)] or None
        Future ground track points.
    track_past : list[(lat, lon)] or None
        Past ground track points.

    Returns
    -------
    str
        Rich markup text ready for Static.update().
    """
    # Pixel grid: 2× vertical resolution via half-block technique
    # Each terminal row = 2 pixel rows
    pixel_h = height * 2
    pixel_w = width

    # Radius in pixels (leave 1 char margin)
    radius = min(pixel_w, pixel_h) / 2 - 1
    if radius < 2:
        return ""

    cx = pixel_w / 2
    cy = pixel_h / 2

    # Precompute trig for center point
    phi0 = math.radians(center_lat)
    lam0 = math.radians(center_lon)
    sin_phi0 = math.sin(phi0)
    cos_phi0 = math.cos(phi0)

    # Build pixel color buffer
    pixels = [[(0, 0, 0)] * pixel_w for _ in range(pixel_h)]
    # None means "outside globe"
    outside = (None, None, None)
    pixel_flags = [[False] * pixel_w for _ in range(pixel_h)]  # True = inside globe

    mask_h = len(land_mask)
    mask_w = len(land_mask[0]) if mask_h > 0 else 0

    for py in range(pixel_h):
        y_norm = (py - cy) / radius  # aspect ratio already handled by half-block
        for px in range(pixel_w):
            x_norm = (px - cx) / radius * 0.5  # terminal chars ~2:1 aspect

            rho_sq = x_norm * x_norm + y_norm * y_norm
            if rho_sq > 1.0:
                continue

            pixel_flags[py][px] = True

            # Inverse orthographic projection
            rho = math.sqrt(rho_sq)
            if rho < 1e-10:
                lat = center_lat
                lon = center_lon
            else:
                c = math.asin(_clamp(rho, -1, 1))
                sin_c = math.sin(c)
                cos_c = math.cos(c)

                lat_rad = math.asin(_clamp(
                    cos_c * sin_phi0 + y_norm * sin_c * cos_phi0 / rho,
                    -1, 1
                ))
                lon_rad = lam0 + math.atan2(
                    x_norm * sin_c,
                    rho * cos_phi0 * cos_c - y_norm * sin_phi0 * sin_c
                )

                lat = math.degrees(lat_rad)
                lon = math.degrees(lon_rad)

            # Normalize longitude to -180..180
            lon = ((lon + 180) % 360) - 180

            # Land/ocean lookup
            row = int(90 - lat)
            col = int(lon + 180)
            row = _clamp(row, 0, mask_h - 1)
            col = _clamp(col, 0, mask_w - 1)

            if land_mask[row][col]:
                base_color = COLOR_LAND
            else:
                base_color = COLOR_OCEAN

            # Limb darkening: brightness = sqrt(1 - rho²)
            brightness = math.sqrt(1.0 - rho_sq)
            brightness = _clamp(brightness, 0.15, 1.0)

            pixels[py][px] = _darken(*base_color, brightness)

    # --- Overlay markers ---
    def project_point(lat_deg, lon_deg):
        """Project lat/lon to pixel coords. Returns (px, py) or None if on far side."""
        phi = math.radians(lat_deg)
        lam = math.radians(lon_deg)

        cos_c = sin_phi0 * math.sin(phi) + cos_phi0 * math.cos(phi) * math.cos(lam - lam0)
        if cos_c < 0:
            return None  # on far side

        x = math.cos(phi) * math.sin(lam - lam0)
        y = cos_phi0 * math.sin(phi) - sin_phi0 * math.cos(phi) * math.cos(lam - lam0)

        px = int(cx + x * radius / 0.5)  # inverse of the 0.5 aspect correction
        py = int(cy + y * radius)

        if 0 <= px < pixel_w and 0 <= py < pixel_h:
            return (px, py)
        return None

    # Track (past)
    if track_past:
        for pt_lat, pt_lon in track_past:
            pos = project_point(pt_lat, pt_lon)
            if pos:
                pixels[pos[1]][pos[0]] = COLOR_TRACK_PAST

    # Track (future)
    if track_future:
        for pt_lat, pt_lon in track_future:
            pos = project_point(pt_lat, pt_lon)
            if pos:
                pixels[pos[1]][pos[0]] = COLOR_TRACK_FUTURE

    # Observer marker (3×2 pixel block)
    observer_pixel = None
    if observer_lat is not None and observer_lon is not None:
        observer_pixel = project_point(observer_lat, observer_lon)
        if observer_pixel:
            ox, oy = observer_pixel
            for dy in range(-1, 2):
                for dx in range(-1, 2):
                    nx, ny = ox + dx, oy + dy
                    if 0 <= nx < pixel_w and 0 <= ny < pixel_h and pixel_flags[ny][nx]:
                        pixels[ny][nx] = COLOR_OBSERVER

    # Satellite marker (3×2 pixel block)
    sat_pixel = None
    if sat_lat is not None and sat_lon is not None:
        sat_pixel = project_point(sat_lat, sat_lon)
        if sat_pixel:
            sx, sy = sat_pixel
            for dy in range(-1, 2):
                for dx in range(-1, 2):
                    nx, ny = sx + dx, sy + dy
                    if 0 <= nx < pixel_w and 0 <= ny < pixel_h and pixel_flags[ny][nx]:
                        pixels[ny][nx] = COLOR_SAT

    # --- Half-block rendering ---
    lines = []
    for row in range(height):
        top_y = row * 2
        bot_y = row * 2 + 1

        line_parts = []
        for col in range(pixel_w):
            top_inside = pixel_flags[top_y][col]
            bot_inside = bot_y < pixel_h and pixel_flags[bot_y][col]

            if not top_inside and not bot_inside:
                line_parts.append(" ")
            elif top_inside and bot_inside:
                tr, tg, tb = pixels[top_y][col]
                br, bg_, bb = pixels[bot_y][col]
                if (tr, tg, tb) == (br, bg_, bb):
                    # Same color — full block with bg
                    line_parts.append(f"[on rgb({tr},{tg},{tb})] [/]")
                else:
                    # Different — use ▀ with fg=top, bg=bottom
                    line_parts.append(
                        f"[rgb({tr},{tg},{tb}) on rgb({br},{bg_},{bb})]▀[/]"
                    )
            elif top_inside and not bot_inside:
                tr, tg, tb = pixels[top_y][col]
                line_parts.append(f"[rgb({tr},{tg},{tb})]▀[/]")
            else:
                br, bg_, bb = pixels[bot_y][col]
                line_parts.append(f"[rgb({br},{bg_},{bb})]▄[/]")

        lines.append("".join(line_parts))

    return "\n".join(lines)
