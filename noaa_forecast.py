import argparse
import os
from datetime import datetime, timedelta, timezone
from skyfield.api import load, wgs84

# PDF
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# --- РЕГИСТРАЦИЯ ЛОКАЛЬНОГО ШРИФТА ---
FONT_PATH = os.path.join(os.path.dirname(__file__), "fonts", "DejaVuSans.ttf")

if os.path.exists(FONT_PATH):
    pdfmetrics.registerFont(TTFont("DejaVu", FONT_PATH))
    FONT_NAME = "DejaVu"
    print(f"✔ Использую локальный шрифт: {FONT_PATH}")
else:
    print("⚠ Не найден fonts/DejaVuSans.ttf — PDF будет без кириллицы")
    FONT_NAME = "Helvetica"

# --- Настройки ---
LAT = 57.582914
LON = 39.907135

WINDOW_MIN_AZ = 16
WINDOW_MAX_AZ = 90

ALT = 0.29  # км

MSK = timezone(timedelta(hours=3))

SAT_IDS = {
    "NOAA-18": 28654,
    "NOAA-19": 33591
}

# -----------------------------
# PDF генератор
# -----------------------------
def generate_pdf(filename, rows):
    c = canvas.Canvas(filename, pagesize=A4)
    width, height = A4

    banner = "■■■■■■■■■■ NOAA — прогноз на 10 дней ■■■■■■■■■■"
    c.setFont(FONT_NAME, 18)
    text_width = c.stringWidth(banner, FONT_NAME, 18)
    c.drawString((width - text_width) / 2, height - 20*mm, banner)

    c.setFont(FONT_NAME, 12)
    c.drawString(
        20*mm,
        height - 30*mm,
        "Координаты: 57.582914, 39.907135  |  Окно: 16°–90°  |  Высота: 290 м"
    )

    c.setFont(FONT_NAME, 10)
    y = height - 45*mm

    headers = ["Дата", "AOS", "TCA", "LOS", "Азимут TCA", "Высота", "Окно"]
    col_widths = [25*mm, 20*mm, 20*mm, 20*mm, 25*mm, 20*mm, 15*mm]

    x = 20*mm
    for h, w in zip(headers, col_widths):
        c.drawString(x, y, h)
        x += w
    y -= 7*mm

    for row in rows:
        x = 20*mm
        for cell, w in zip(row, col_widths):
            c.drawString(x, y, str(cell))
            x += w
        y -= 6*mm

        if y < 20*mm:
            c.showPage()
            c.setFont(FONT_NAME, 10)
            y = height - 20*mm

    c.save()
    print(f"📄 PDF сохранён: {filename}")


# -----------------------------
# Загрузка TLE
# -----------------------------
def load_sat(catnr):
    ts = load.timescale()
    url = f"https://celestrak.org/NORAD/elements/gp.php?CATNR={catnr}&FORMAT=tle"
    sats = load.tle_file(url)
    return ts, sats[0]


def visible_from_window(az):
    return WINDOW_MIN_AZ <= az <= WINDOW_MAX_AZ


# -----------------------------
# Прогноз пролётов
# -----------------------------
def forecast_satellite(name, catnr, days=10, pretty=False, pdf_rows=None):
    ts, sat = load_sat(catnr)
    observer = wgs84.latlon(LAT, LON, ALT)

    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days)

    # чуть захватываем прошлое, чтобы не терять AOS
    t0 = ts.from_datetime(now - timedelta(minutes=5))
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

    if pretty:
        print(f"\n=== {name} — прогноз на {days} дней ===")
        print("-" * 80)
        print(f"{'Дата':<12} {'AOS':<8} {'TCA':<8} {'LOS':<8} {'Азимут TCA':<12} {'Высота':<8} {'Окно':<6}")
        print("-" * 80)

    for p in passes:
        aos = p.get("aos")
        tca = p.get("tca")
        los = p.get("los")

        # без TCA или LOS пролёт нам не интересен
        if tca is None or los is None:
            continue

        aos_alt = aos_az = None
        if aos is not None:
            aos_alt, aos_az, _ = (sat - observer).at(aos).altaz()

        tca_alt, tca_az, _ = (sat - observer).at(tca).altaz()
        los_alt, los_az, _ = (sat - observer).at(los).altaz()

        visible = (
            (aos_az is not None and visible_from_window(aos_az.degrees)) or
            visible_from_window(tca_az.degrees) or
            visible_from_window(los_az.degrees)
        )

        date_str = tca.utc_datetime().astimezone(MSK).strftime("%Y-%m-%d")
        aos_str = aos.utc_datetime().astimezone(MSK).strftime("%H:%M") if aos is not None else "--:--"
        tca_str = tca.utc_datetime().astimezone(MSK).strftime("%H:%M")
        los_str = los.utc_datetime().astimezone(MSK).strftime("%H:%M")

        # PDF row
        if pdf_rows is not None:
            pdf_rows.append([
                date_str,
                aos_str,
                tca_str,
                los_str,
                f"{tca_az.degrees:.1f}°",
                f"{tca_alt.degrees:.1f}°",
                "ДА" if visible else "нет"
            ])

        # Console output
        if pretty:
            print(
                f"{date_str} "
                f"{aos_str} "
                f"{tca_str} "
                f"{los_str} "
                f"{tca_az.degrees:10.1f}° "
                f"{tca_alt.degrees:6.1f}° "
                f"{'ДА' if visible else 'нет':<6}"
            )
        else:
            print(f"\n===== Пролёт {name} =====")
            print(f"Дата: {date_str}")
            if aos is not None:
                print(f"AOS: {aos_str}:00  азимут {aos_az.degrees:.1f}°")
            else:
                print("AOS: нет данных (пролёт уже начался)")
            print(f"TCA: {tca.utc_datetime().astimezone(MSK):%H:%M:%S}  азимут {tca_az.degrees:.1f}°  высота {tca_alt.degrees:.1f}°")
            print(f"LOS: {los.utc_datetime().astimezone(MSK):%H:%M:%S}  азимут {los_az.degrees:.1f}°")
            print(f"Видимость из окна: {'ДА' if visible else 'нет'}")

    if pretty:
        print("-" * 80)


# -----------------------------
# MAIN
# -----------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--print", action="store_true", help="Вывод таблицы в консоль")
    parser.add_argument("--pdf", type=str, help="Сохранить прогноз в PDF")
    args = parser.parse_args()

    pdf_rows = [] if args.pdf else None

    for name, catnr in SAT_IDS.items():
        forecast_satellite(name, catnr, days=10, pretty=args.print, pdf_rows=pdf_rows)

    if args.pdf:
        generate_pdf(args.pdf, pdf_rows)
