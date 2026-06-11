import time
import os
import subprocess
from datetime import datetime, timezone
from rich.progress import Progress
import fcntl, sys

from sat_core import (
    LAT, LON, ALT, MSK,
    CENTER_FREQ, RAW_SAMPLE_RATE, GAIN,
    RECORD_DIR, LOCK_FILE,
    normalize_time, fmt_msk, log_status as _unused_log,
    load_sat, next_pass, analyze_pass, pass_visible,
    cleanup_old_records,
)

os.makedirs(RECORD_DIR, exist_ok=True)

fp = open(LOCK_FILE, "w")

try:
    fcntl.flock(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    print("⚠ Скрипт уже запущен, выходим.")
    sys.exit(0)

fp.write(str(os.getpid()))
fp.flush()


def log_status(msg):
    now = datetime.now(MSK).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{now}] {msg}"
    sys.stdout.write("\r" + line)
    sys.stdout.flush()


# -----------------------------
# Запись сигнала
# -----------------------------
def record_pass(aos_dt, los_dt):
    duration = int((los_dt - aos_dt).total_seconds()) + 20

    samples = RAW_SAMPLE_RATE * duration

    raw_name = f"meteor_m2_3_{aos_dt.strftime('%Y%m%d_%H%M%S_%f')}.raw"
    raw_path = os.path.join(RECORD_DIR, raw_name)

    if os.path.exists(raw_path):
        try:
            os.remove(raw_path)
        except:
            pass

    print(f"▶ Начинаю запись {duration} сек → RAW {raw_path}")

    cmd_rtl = [
        "rtl_sdr",
        "-f", str(int(CENTER_FREQ)),
        "-s", str(RAW_SAMPLE_RATE),
        "-g", str(GAIN),
        "-n", str(samples),
        raw_path
    ]

    try:
        p = subprocess.Popen(cmd_rtl)
        p.wait(timeout=duration + 30)
    except subprocess.TimeoutExpired:
        print("⚠ rtl_sdr завис — убиваю")
        p.kill()

    if not os.path.exists(raw_path):
        log_status("❌ RAW файл не создан")
        return None

    size = os.path.getsize(raw_path)
    if size < 5_000_000:
        log_status(f"❌ RAW слишком маленький ({size} байт) — запись не удалась")
        try:
            os.remove(raw_path)
        except:
            pass
        return None

    return raw_path


# -----------------------------
# Декодирование через SatDump
# -----------------------------
def decode_meteor(raw_path, aos_dt):
    out_dir = os.path.join(RECORD_DIR, aos_dt.strftime("%Y%m%d_%H%M%S"))
    os.makedirs(out_dir, exist_ok=True)

    raw_name = os.path.basename(raw_path)
    out_name = aos_dt.strftime("%Y%m%d_%H%M%S")

    cmd = [
        "docker", "compose", "run", "--rm",
        "satdump",
        "satdump",
        "meteor_m2_lrpt",
        "baseband",
        f"/data/{raw_name}",
        f"/data/{out_name}",
        "--samplerate", str(RAW_SAMPLE_RATE),
        "--baseband_format", "u8"
    ]

    print(f"🖼 Декодирую RAW → {out_dir}")
    subprocess.run(cmd, check=False)

    pngs = [f for f in os.listdir(out_dir) if f.lower().endswith(".png")]
    if not pngs:
        print("❌ SatDump не создал PNG — декодирование не удалось")
        return None

    img_path = os.path.join(out_dir, pngs[0])
    print(f"🖼 PNG готов: {img_path}")
    return img_path


# -----------------------------
# Главный цикл демона
# -----------------------------
def run_daemon():
    print("🚀 METEOR‑M2‑3 демон запущен")

    try:
        while True:
            cleanup_old_records()
            ts, sat = load_sat()
            p = next_pass(ts, sat)

            if not p:
                log_status("Нет пролётов, сплю 10 минут")
                time.sleep(600)
                continue

            # Нормализуем времена сразу
            aos = normalize_time(p.get("aos"))
            tca = normalize_time(p.get("tca"))
            los = normalize_time(p.get("los"))

            if los is None:
                log_status("❌ Пролёт без LOS — пропускаю")
                time.sleep(60)
                continue

            # Безопасный анализ пролёта
            try:
                info = analyze_pass(ts, sat, {
                    "aos": aos,
                    "tca": tca,
                    "los": los,
                })
            except Exception as e:
                print("⚠ Ошибка в analyze_pass:", e)
                print("  raw pass:", p)
                time.sleep(60)
                continue

            # Отсекаем южные пролёты
            if 90 <= info["tca_az"] <= 270:
                log_status("❌ Пролёт проходит по южной стороне — из окна не видно")
                time.sleep(60)
                continue

            # Порог по высоте
            if info["tca_alt"] < 18:
                log_status("❌ Высота TCA слишком низкая — сигнал будет слабым")
                time.sleep(60)
                continue

            visible, reason = pass_visible(
                info["aos_az"],
                info["tca_az"],
                info["los_az"],
                info["tca_alt"]
            )

            if not visible:
                log_status("❌ Пролёт не виден из окна — пропускаю")
                time.sleep(60)
                continue

            print("🛰 Пролёт METEOR:")
            if info["aos_az"] is not None:
                print(f" AOS азимут {info['aos_az']:.1f}°")
            else:
                print(" AOS: нет данных (пролёт уже начался)")
            print(f" TCA азимут {info['tca_az']:.1f}° высота {info['tca_alt']:.1f}°")
            print(f" LOS азимут {info['los_az']:.1f}°")
            print(f" ➜ Оценка: {reason}")
            print("👍 Пролёт виден — готовлюсь к приёму\n")

            # Время для записи
            los_dt = info["los_time"].utc_datetime().replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)

            if info["aos_time"] is not None:
                aos_dt = info["aos_time"].utc_datetime().replace(tzinfo=timezone.utc)
            else:
                print("⚠ Нет AOS — начинаю запись немедленно")
                aos_dt = now

            now = datetime.now(timezone.utc)

            if now < aos_dt:
                wait_seconds = int((aos_dt - now).total_seconds())
                with Progress() as progress:
                    task = progress.add_task(
                        f"⏳ Жду до AOS: {fmt_msk(aos_dt)}",
                        total=wait_seconds
                    )
                    for _ in range(wait_seconds):
                        progress.update(task, advance=1)
                        time.sleep(1)

            print("📡 Начинаю приём")

            raw = record_pass(aos_dt, los_dt)
            if raw is None:
                print("⚠ Пропускаю декодирование — нет RAW")
                continue

            print("🧩 Декодирование")
            result = decode_meteor(raw, aos_dt)

            # Удаляем RAW после успешного декодирования — он огромный
            if result and os.path.exists(raw):
                try:
                    size_mb = os.path.getsize(raw) / (1024 * 1024)
                    os.remove(raw)
                    print(f"🗑 RAW удалён: {os.path.basename(raw)} ({size_mb:.0f} МБ)")
                except OSError:
                    pass

            print("✔ Готово. Жду следующий пролёт.\n")

    except KeyboardInterrupt:
        print("\n🛑 Остановка демона по запросу пользователя. Завершаю работу...")
        fp.close()
        sys.exit(130)
    except Exception as e:
        print("❌ Необработанная ошибка в демоне:", e)
        fp.close()
        sys.exit(1)


if __name__ == "__main__":
    run_daemon()
