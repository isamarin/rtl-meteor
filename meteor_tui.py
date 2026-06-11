"""
meteor_tui.py — Textual TUI for RTL-METEOR ground station.

Tabs:
  1. Dashboard  — next pass countdown, satellite position, daemon status
  2. Forecast   — 10-day pass table
  3. Records    — decoded image archive
  4. Map        — real-time 3D globe with satellite track
"""

import os
import subprocess
from datetime import datetime, timezone

from textual.app import App
from textual.containers import Vertical
from textual.widgets import (
    Header,
    Footer,
    TabbedContent,
    TabPane,
    Static,
    Digits,
    DataTable,
    Button,
    Label,
)
from textual.binding import Binding

from sat_core import (
    LAT, LON, ALT, MSK, SAT_NAME, SAT_CATNR,
    WINDOW_MIN_AZ, WINDOW_MAX_AZ,
    RECORD_DIR, LOCK_FILE,
    CENTER_FREQ, RAW_SAMPLE_RATE, GAIN,
    load_sat, find_passes, next_pass, analyze_pass, pass_visible,
    normalize_time, fmt_msk, satellite_position, satellite_ground_track,
)
from land_mask import load_land_mask
from globe_renderer import render_globe as _render_globe


# -----------------------------
# Fade animation widgets
# -----------------------------
class FadeDigits(Digits):
    """Digits widget with fade animation on value change."""

    DEFAULT_CSS = """
    FadeDigits {
        opacity: 1.0;
    }
    """

    def __init__(self, value="", **kwargs):
        super().__init__(value, **kwargs)
        self._current_value = value

    def update_value(self, new_value: str) -> None:
        if new_value == self._current_value:
            return
        self._current_value = new_value
        self.styles.animate("opacity", 0.3, duration=0.15, easing="out_cubic")
        self.set_timer(0.15, lambda: self._apply_value(new_value))

    def _apply_value(self, value: str) -> None:
        self.update(value)
        self.styles.animate("opacity", 1.0, duration=0.25, easing="in_cubic")


class FadeStatic(Static):
    """Static widget with fade animation on content change."""

    DEFAULT_CSS = """
    FadeStatic {
        opacity: 1.0;
    }
    """

    def __init__(self, content="", **kwargs):
        super().__init__(content, **kwargs)
        self._current_content = content

    def update_content(self, new_content: str) -> None:
        if new_content == self._current_content:
            return
        self._current_content = new_content
        self.styles.animate("opacity", 0.3, duration=0.15, easing="out_cubic")
        self.set_timer(0.15, lambda: self._apply_content(new_content))

    def _apply_content(self, content: str) -> None:
        self.update(content)
        self.styles.animate("opacity", 1.0, duration=0.25, easing="in_cubic")


# -----------------------------
# Dashboard tab
# -----------------------------
class DashboardTab(Static):
    """Next pass info, satellite position, daemon status."""

    DEFAULT_CSS = """
    DashboardTab {
        padding: 1 2;
    }
    #next-pass-panel {
        border: solid green;
        padding: 1 2;
        margin-bottom: 1;
        height: auto;
    }
    #next-pass-label {
        margin-bottom: 1;
    }
    #countdown-digits {
        margin-bottom: 1;
    }
    #sat-position-panel {
        border: solid cyan;
        padding: 1 2;
        margin-bottom: 1;
        height: auto;
    }
    #sat-subpoint {
        margin-bottom: 0;
    }
    #sat-region {
        margin-bottom: 0;
    }
    #sat-numbers {
        margin-bottom: 0;
    }
    #daemon-status-panel {
        border: solid yellow;
        padding: 1 2;
        margin-bottom: 1;
        height: auto;
    }
    #record-btn {
        margin-top: 1;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._pass_info = None
        self._aos_dt = None

    def compose(self):
        with Vertical(id="next-pass-panel"):
            yield FadeStatic(id="next-pass-label")
            yield FadeDigits("--:--:--", id="countdown-digits")
            yield FadeStatic(id="next-pass-visibility")
        with Vertical(id="sat-position-panel"):
            yield FadeStatic(id="sat-subpoint")
            yield FadeStatic(id="sat-region")
            yield FadeStatic(id="sat-numbers")
        with Vertical(id="daemon-status-panel"):
            yield FadeStatic(id="daemon-status-text")
        yield Button("Записать сейчас", id="record-btn", variant="primary")

    def update_next_pass(self, ts, sat):
        label = self.query_one("#next-pass-label", FadeStatic)
        digits = self.query_one("#countdown-digits", FadeDigits)
        vis = self.query_one("#next-pass-visibility", FadeStatic)
        try:
            p = next_pass(ts, sat)
            if p is None:
                label.update_content(
                    f"[bold]Следующий пролёт {SAT_NAME}[/bold]\n"
                    "Нет пролётов в ближайшие 3 часа"
                )
                digits.update_value("--:--:--")
                vis.update_content("")
                self._pass_info = None
                self._aos_dt = None
                return

            info = analyze_pass(ts, sat, p)
            visible, reason = pass_visible(
                info["aos_az"], info["tca_az"], info["los_az"], info["tca_alt"]
            )

            self._pass_info = info

            # AOS
            if info["aos_time"] is not None:
                aos_dt = info["aos_time"].utc_datetime().replace(tzinfo=timezone.utc)
                aos_str = fmt_msk(aos_dt)
                self._aos_dt = aos_dt
            else:
                aos_str = "нет данных"
                self._aos_dt = None

            # TCA / LOS
            tca_dt = info["tca_time"].utc_datetime().replace(tzinfo=timezone.utc)
            los_dt = info["los_time"].utc_datetime().replace(tzinfo=timezone.utc)
            tca_str = fmt_msk(tca_dt)
            los_str = fmt_msk(los_dt)

            label.update_content(
                f"[bold]Следующий пролёт {SAT_NAME}[/bold]\n"
                f"AOS: {aos_str}\n"
                f"TCA: {tca_str}   Азимут: {info['tca_az']:.1f}°  Высота: {info['tca_alt']:.1f}°\n"
                f"LOS: {los_str}"
            )

            self.refresh_countdown()

            vis_mark = "[green]ВИДЕН[/green]" if visible else "[red]НЕ ВИДЕН[/red]"
            vis.update_content(f"Видимость: {vis_mark} ({reason})")

        except Exception as e:
            label.update_content(
                f"[bold]Следующий пролёт[/bold]\n[red]Ошибка: {e}[/red]"
            )
            digits.update_value("--:--:--")
            vis.update_content("")
            self._pass_info = None
            self._aos_dt = None

    def refresh_countdown(self):
        digits = self.query_one("#countdown-digits", FadeDigits)
        if self._aos_dt is None:
            digits.update_value("--:--:--")
            return
        now = datetime.now(timezone.utc)
        total = int((self._aos_dt - now).total_seconds())
        if total > 0:
            h, rem = divmod(total, 3600)
            m, s = divmod(rem, 60)
            digits.update_value(f"{h:02d}:{m:02d}:{s:02d}")
        else:
            digits.update_value("00:00:00")

    def update_sat_position(self, ts, sat):
        subpoint = self.query_one("#sat-subpoint", FadeStatic)
        region_w = self.query_one("#sat-region", FadeStatic)
        numbers = self.query_one("#sat-numbers", FadeStatic)
        try:
            pos = satellite_position(ts, sat)

            above_horizon = pos["alt_deg"] > 0
            horizon_mark = "[green]над горизонтом[/green]" if above_horizon else "[dim]под горизонтом[/dim]"

            region = _describe_region(pos["lat"], pos["lon"])

            subpoint.update_content(
                f"[bold]Позиция {SAT_NAME}[/bold]\n"
                f"Подспутниковая точка: {pos['lat']:.2f}°N  {pos['lon']:.2f}°E"
            )
            region_w.update_content(f"Регион: {region}")
            numbers.update_content(
                f"Высота: {pos['alt_deg']:.1f}°  Азимут: {pos['az_deg']:.1f}°  "
                f"Дальность: {pos['distance_km']:.0f} км  {horizon_mark}"
            )

        except Exception as e:
            subpoint.update_content(
                f"[bold]Позиция спутника[/bold]\n[red]Ошибка: {e}[/red]"
            )
            region_w.update_content("")
            numbers.update_content("")

    def update_daemon_status(self):
        status = self.query_one("#daemon-status-text", FadeStatic)
        try:
            if not os.path.exists(LOCK_FILE):
                status.update_content(
                    "[bold]Статус демона[/bold]\n"
                    "[dim]Остановлен[/dim] (lock-файл отсутствует)"
                )
                return

            with open(LOCK_FILE, "r") as f:
                pid_str = f.read().strip()

            if not pid_str:
                status.update_content(
                    "[bold]Статус демона[/bold]\n"
                    "[dim]Остановлен[/dim] (lock-файл пуст)"
                )
                return

            pid = int(pid_str)

            try:
                os.kill(pid, 0)
                status.update_content(
                    f"[bold]Статус демона[/bold]\n"
                    f"[green]Запущен[/green] (PID {pid})"
                )
            except ProcessLookupError:
                status.update_content(
                    f"[bold]Статус демона[/bold]\n"
                    f"[dim]Остановлен[/dim] (PID {pid} не найден)"
                )
            except PermissionError:
                status.update_content(
                    f"[bold]Статус демона[/bold]\n"
                    f"[green]Запущен[/green] (PID {pid})"
                )

        except Exception as e:
            status.update_content(
                f"[bold]Статус демона[/bold]\n[red]Ошибка: {e}[/red]"
            )


# -----------------------------
# Globe tab
# -----------------------------
class GlobeWidget(Static):
    """Renders a 3D globe with satellite track."""

    DEFAULT_CSS = """
    GlobeWidget {
        width: 1fr;
        height: 1fr;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._land_mask = None
        self._last_markup = ""

    def render_globe(self, ts, sat):
        if self._land_mask is None:
            self._land_mask = load_land_mask()

        w = self.size.width
        h = self.size.height
        if w < 4 or h < 4:
            return

        pos = satellite_position(ts, sat)
        sat_lat = pos["lat"]
        sat_lon = pos["lon"]

        past, future = satellite_ground_track(ts, sat, minutes_back=30, minutes_ahead=90, step=1)

        markup = _render_globe(
            width=w,
            height=h,
            center_lat=sat_lat,
            center_lon=sat_lon,
            land_mask=self._land_mask,
            sat_lat=sat_lat,
            sat_lon=sat_lon,
            observer_lat=LAT,
            observer_lon=LON,
            track_future=future,
            track_past=past,
        )

        if markup != self._last_markup:
            self._last_markup = markup
            self.update(markup)


class GlobeTab(Static):
    """Map tab with real-time 3D globe."""

    DEFAULT_CSS = """
    GlobeTab {
        padding: 0;
        height: 1fr;
    }
    #globe-info {
        height: 1;
        dock: bottom;
        padding: 0 1;
        background: $surface;
    }
    """

    def compose(self):
        yield GlobeWidget(id="globe-widget")
        yield Static(id="globe-info")

    def refresh_globe(self, ts, sat):
        globe = self.query_one("#globe-widget", GlobeWidget)
        globe.render_globe(ts, sat)

        pos = satellite_position(ts, sat)
        info = self.query_one("#globe-info", Static)
        above = "[green]▲[/]" if pos["alt_deg"] > 0 else "[dim]▼[/]"
        info.update(
            f"{SAT_NAME}  {pos['lat']:+.1f}°N {pos['lon']:+.1f}°E  "
            f"Высота: {pos['alt_deg']:.1f}°  Азимут: {pos['az_deg']:.1f}°  "
            f"Дальность: {pos['distance_km']:.0f} км {above}"
        )


def _describe_region(lat, lon):
    """Attempt to get region description via geo_context, fallback to coords."""
    try:
        from geo_context.geo_context import geo_context
        result = geo_context(lat, lon)
        if result:
            return result
    except Exception:
        pass
    return f"{lat:.1f}°N, {lon:.1f}°E"


# -----------------------------
# Forecast tab
# -----------------------------
class ForecastTab(Static):
    """10-day pass forecast table."""

    DEFAULT_CSS = """
    ForecastTab {
        padding: 1 2;
    }
    #forecast-table {
        height: 1fr;
    }
    """

    def compose(self):
        yield DataTable(id="forecast-table")

    def load_forecast(self, ts, sat):
        table = self.query_one("#forecast-table", DataTable)
        table.clear(columns=True)

        table.add_columns(
            "Дата", "AOS", "TCA", "LOS",
            "Азимут TCA", "Высота", "Видимость"
        )

        try:
            passes = find_passes(ts, sat, hours_ahead=240)  # 10 days
        except Exception:
            return

        from skyfield.api import wgs84 as _wgs84
        observer = _wgs84.latlon(LAT, LON, ALT)

        for p in passes:
            aos = p.get("aos")
            tca = p.get("tca")
            los = p.get("los")

            if tca is None or los is None:
                continue

            # Compute altaz
            aos_az_val = None
            if aos is not None:
                _, aos_az_obj, _ = (sat - observer).at(aos).altaz()
                aos_az_val = aos_az_obj.degrees

            tca_alt_obj, tca_az_obj, _ = (sat - observer).at(tca).altaz()
            _, los_az_obj, _ = (sat - observer).at(los).altaz()

            tca_alt_val = tca_alt_obj.degrees
            tca_az_val = tca_az_obj.degrees
            los_az_val = los_az_obj.degrees

            visible, reason = pass_visible(
                aos_az_val, tca_az_val, los_az_val, tca_alt_val
            )

            date_str = tca.utc_datetime().astimezone(MSK).strftime("%Y-%m-%d")
            aos_str = aos.utc_datetime().astimezone(MSK).strftime("%H:%M") if aos is not None else "--:--"
            tca_str = tca.utc_datetime().astimezone(MSK).strftime("%H:%M")
            los_str = los.utc_datetime().astimezone(MSK).strftime("%H:%M")

            vis_str = "ДА" if visible else "нет"

            style = "green" if visible else "dim"

            table.add_row(
                date_str, aos_str, tca_str, los_str,
                f"{tca_az_val:.1f}°", f"{tca_alt_val:.1f}°", vis_str,
            )


# -----------------------------
# Records tab
# -----------------------------
class RecordsTab(Static):
    """Archive of decoded recordings."""

    DEFAULT_CSS = """
    RecordsTab {
        padding: 1 2;
    }
    #records-table {
        height: 1fr;
    }
    #delete-btn {
        margin-top: 1;
    }
    """

    def compose(self):
        yield DataTable(id="records-table")
        yield Button("Удалить выбранную", id="delete-btn", variant="error")

    def load_records(self):
        table = self.query_one("#records-table", DataTable)
        table.clear(columns=True)
        table.cursor_type = "row"

        table.add_columns("Дата", "Размер", "PNG")

        if not os.path.isdir(RECORD_DIR):
            return

        entries = []
        for name in os.listdir(RECORD_DIR):
            path = os.path.join(RECORD_DIR, name)
            if not os.path.isdir(path):
                continue
            entries.append((name, path))

        # Sort by name descending (newest first)
        entries.sort(key=lambda x: x[0], reverse=True)

        for name, path in entries:
            # Calculate folder size
            total_size = 0
            png_count = 0
            for dirpath, dirnames, filenames in os.walk(path):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    try:
                        total_size += os.path.getsize(fp)
                    except OSError:
                        pass
                    if f.lower().endswith(".png"):
                        png_count += 1

            if total_size > 1024 * 1024:
                size_str = f"{total_size / (1024 * 1024):.1f} MB"
            elif total_size > 1024:
                size_str = f"{total_size / 1024:.1f} KB"
            else:
                size_str = f"{total_size} B"

            png_str = f"{png_count} шт." if png_count > 0 else "нет"

            table.add_row(name, size_str, png_str, key=name)


# -----------------------------
# Main App
# -----------------------------
class MeteorApp(App):
    """RTL-METEOR TUI."""

    TITLE = "RTL-METEOR Ground Station"
    SUB_TITLE = f"{SAT_NAME} | {LAT}°N {LON}°E"

    CSS = """
    Screen {
        background: $surface;
    }
    TabbedContent {
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Выход"),
        Binding("r", "refresh", "Обновить"),
        Binding("d", "tab_dashboard", "Дашборд", show=True),
        Binding("f", "tab_forecast", "Прогноз", show=True),
        Binding("a", "tab_records", "Архив", show=True),
        Binding("m", "tab_globe", "Карта", show=True),
    ]

    def __init__(self):
        super().__init__()
        self._ts = None
        self._sat = None

    def compose(self):
        yield Header()
        with TabbedContent():
            with TabPane("Дашборд", id="tab-dashboard"):
                yield DashboardTab()
            with TabPane("Прогноз", id="tab-forecast"):
                yield ForecastTab()
            with TabPane("Записи", id="tab-records"):
                yield RecordsTab()
            with TabPane("Карта", id="tab-globe"):
                yield GlobeTab()
        yield Footer()

    def on_mount(self):
        self._load_tle()
        self._refresh_dashboard()
        self._refresh_forecast()
        self._refresh_records()

        # Periodic updates
        self.set_interval(1, self._refresh_countdown)
        self.set_interval(30, self._refresh_dashboard)
        self.set_interval(10, self._refresh_sat_position)
        self.set_interval(30, self._refresh_daemon_status)
        self.set_interval(2, self._refresh_globe)

    def _load_tle(self):
        try:
            self._ts, self._sat = load_sat()
        except Exception as e:
            self.notify(f"Ошибка загрузки TLE: {e}", severity="error")

    def _refresh_countdown(self):
        dashboard = self.query_one(DashboardTab)
        dashboard.refresh_countdown()

    def _refresh_dashboard(self):
        if self._ts is None:
            return
        dashboard = self.query_one(DashboardTab)
        dashboard.update_next_pass(self._ts, self._sat)
        dashboard.update_sat_position(self._ts, self._sat)
        dashboard.update_daemon_status()

    def _refresh_sat_position(self):
        if self._ts is None:
            return
        dashboard = self.query_one(DashboardTab)
        dashboard.update_sat_position(self._ts, self._sat)

    def _refresh_daemon_status(self):
        dashboard = self.query_one(DashboardTab)
        dashboard.update_daemon_status()

    def _refresh_globe(self):
        if self._ts is None:
            return
        # Only render when the globe tab is active
        tabs = self.query_one(TabbedContent)
        if tabs.active != "tab-globe":
            return
        globe = self.query_one(GlobeTab)
        globe.refresh_globe(self._ts, self._sat)

    def _refresh_forecast(self):
        if self._ts is None:
            return
        forecast = self.query_one(ForecastTab)
        forecast.load_forecast(self._ts, self._sat)

    def _refresh_records(self):
        records = self.query_one(RecordsTab)
        records.load_records()

    # --- Actions ---

    def action_refresh(self):
        self._load_tle()
        self._refresh_dashboard()
        self._refresh_forecast()
        self._refresh_records()
        self.notify("Данные обновлены")

    def action_tab_dashboard(self):
        self.query_one(TabbedContent).active = "tab-dashboard"

    def action_tab_forecast(self):
        self.query_one(TabbedContent).active = "tab-forecast"

    def action_tab_records(self):
        self.query_one(TabbedContent).active = "tab-records"

    def action_tab_globe(self):
        self.query_one(TabbedContent).active = "tab-globe"
        self._refresh_globe()

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "record-btn":
            self._start_manual_record()
        elif event.button.id == "delete-btn":
            self._delete_selected_record()

    def _start_manual_record(self):
        if self._ts is None:
            self.notify("TLE не загружено", severity="error")
            return

        pos = satellite_position(self._ts, self._sat)
        if pos["alt_deg"] <= 0:
            self.notify("Спутник под горизонтом — запись невозможна", severity="warning")
            return

        # Find current pass to determine LOS
        p = next_pass(self._ts, self._sat)
        if p is None:
            self.notify("Нет активного пролёта", severity="warning")
            return

        info = analyze_pass(self._ts, self._sat, p)
        los_dt = info["los_time"].utc_datetime().replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        duration = int((los_dt - now).total_seconds()) + 10

        if duration <= 0:
            self.notify("Пролёт уже завершился", severity="warning")
            return

        raw_name = f"meteor_m2_3_{now.strftime('%Y%m%d_%H%M%S_%f')}.raw"
        raw_path = os.path.join(RECORD_DIR, raw_name)
        os.makedirs(RECORD_DIR, exist_ok=True)

        samples = RAW_SAMPLE_RATE * duration

        cmd = [
            "rtl_sdr",
            "-f", str(int(CENTER_FREQ)),
            "-s", str(RAW_SAMPLE_RATE),
            "-g", str(GAIN),
            "-n", str(samples),
            raw_path,
        ]

        self.notify(f"Запись запущена ({duration} сек): {raw_name}")

        try:
            subprocess.Popen(cmd)
        except FileNotFoundError:
            self.notify("rtl_sdr не найден", severity="error")

    def _delete_selected_record(self):
        records_tab = self.query_one(RecordsTab)
        table = records_tab.query_one("#records-table", DataTable)

        if table.row_count == 0:
            self.notify("Нет записей для удаления", severity="warning")
            return

        try:
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        except Exception:
            self.notify("Выберите запись для удаления", severity="warning")
            return

        name = str(row_key.value)
        path = os.path.join(RECORD_DIR, name)

        if os.path.isdir(path):
            import shutil
            shutil.rmtree(path)
            self.notify(f"Удалено: {name}")
            self._refresh_records()
        else:
            self.notify(f"Папка не найдена: {name}", severity="warning")


if __name__ == "__main__":
    app = MeteorApp()
    app.run()
