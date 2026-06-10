# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

RTL-METEOR is a satellite ground station system for capturing and decoding digital weather satellite imagery from METEOR-M2-3 using RTL-SDR receivers. The observer location is hardcoded to Yaroslavl, Russia (57.582914°N, 39.907135°E).

The project originally targeted NOAA satellites (NOAA-18, NOAA-19), but they were decommissioned — the scripts still carry the `noaa_` prefix as a legacy artifact. The current and only target is the Russian METEOR-M2-3 satellite.

## Running

All scripts run directly with Python — there is no build step, Makefile, or package manager.

```bash
python noaa_daemon.py          # Main daemon: continuous METEOR-M2-3 capture loop
python noaa_capture.py         # One-shot NOAA-18 APT capture
python check_passes.py         # Show upcoming passes (next 12 hours)
python noaa_forecast.py --print  # Print 10-day forecast table
python noaa_forecast.py --pdf out.pdf  # Generate forecast PDF
python noaa_check.py           # Show current satellite position & region description
python generate_seas_json.py   # Regenerate seas.json from Natural Earth shapefiles
```

Docker is used only for SatDump (satellite signal decoder):
```bash
docker-compose build
docker-compose run satdump
```

## Dependencies

Listed in `requirements.txt`: `skyfield`, `numpy`, `pyrtlsdr`. Additional unlisted imports used across scripts: `rich`, `reportlab`, `geopy`, `shapely`, `fiona`, `deep_translator`, `pymorphy3`.

## Architecture

**Signal capture pipeline:**
RTL-SDR hardware (137.900 MHz) → `rtl_sdr`/`rtl_fm` subprocess → raw IQ file → SatDump Docker container → decoded products in `records/YYYYMMDD_HHMMSS/`

**Key scripts and their roles:**

- `noaa_daemon.py` — Main orchestrator. Runs an infinite loop: loads TLE from Celestrak, predicts next visible METEOR-M2-3 pass via Skyfield, sleeps until AOS, records IQ samples via `rtl_sdr` subprocess, then invokes SatDump via Docker to decode. Uses `fcntl.flock()` to prevent concurrent instances. Kills stuck processes after timeout.

- `noaa_capture.py` — Alternative one-shot capture for NOAA-18 APT. Uses `rtl_fm | sox` pipeline instead of raw IQ. Detects whether currently inside a pass window before recording.

- `noaa_forecast.py` — Generates 10-day pass forecast tables. Outputs to CLI (Rich) or PDF (ReportLab with DejaVuSans font for Cyrillic).

- `check_passes.py` / `noaa_check.py` — Pass prediction and live satellite position tracking with geographic context descriptions.

- `geo_context/geo_context.py` — Geolocation module. Given a lat/lon, determines the nearest sea/ocean (Shapely polygon containment against `seas.json`), nearest country (geopy Nominatim), and generates Russian-language descriptions using `pymorphy3` for morphological inflection (instrumental case).

- `generate_seas_json.py` — Builds `seas.json` from Natural Earth shapefiles + Google Translate for Russian names.

**Pass visibility filtering:** Passes are filtered by azimuth window (16°–90°, NE sector) and minimum elevation (18°–30°) to match the observer's physical window view. This logic appears in multiple scripts.

**Satellite parameters (hardcoded):**
- Satellite: METEOR-M2-3, NORAD catalog 57166
- Frequency: 137.900 MHz, sample rate 2.88 MS/s, gain 40 dB
- Timezone: MSK (UTC+3)

## Output Structure

Decoded satellite data is stored in `records/` with per-pass subdirectories containing `MSU-MR/` products, `dataset.json`, `telemetry.json`, and raw `.cadu` frames.

Raw IQ recordings are very large (gigabytes per pass). The daemon deletes `.raw` files after successful decoding and runs `cleanup_old_records()` each cycle, removing records older than `MAX_RECORD_AGE_DAYS` (default 30) and any orphaned `.raw` files.
