"""
seed_forecast_verification.py — populates the SQLite forecast_verification table
with realistic predicted-vs-actual temperature observations over the past 30 days.

This drives the /api/telemetry/model-accuracy endpoint (MAE/RMSE) and the
dashboard Forecast Accuracy panel, including occasional drift spikes.

NOTE: This seeds SQLite (database.forecast_verification), NOT MongoDB. The
MongoDB optional telemetry path is unrelated to forecast verification.
"""
import random
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

DB_PATH = "data/skycast.db"

CITIES = {
    "karachi":  {"base_temp": 32.0, "temp_var": 3.0, "base_hum": 70.0},
    "lahore":   {"base_temp": 34.0, "temp_var": 5.0, "base_hum": 55.0},
    "islamabad":{"base_temp": 28.0, "temp_var": 6.0, "base_hum": 60.0},
    "peshawar": {"base_temp": 31.0, "temp_var": 5.0, "base_hum": 50.0},
    "quetta":   {"base_temp": 24.0, "temp_var": 7.0, "base_hum": 35.0},
}

MODELS = ["open-meteo", "deterministic-sim"]


def seed(days=30, logs_per_day=40, inject_drift=True, clear_first=True):
    rng = random.Random(20260910)  # deterministic — same data every run

    # Optional clear.
    if clear_first:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("DELETE FROM forecast_verification")
            conn.commit()

    now = datetime.now(timezone.utc)
    docs = []

    print(f"Generating ~{days * logs_per_day} forecast verification records across {days} days...")

    for day_offset in range(days, -1, -1):
        target_day = now - timedelta(days=day_offset)

        # Drift window: records from 5-7 days ago carry a larger systematic bias.
        in_drift = inject_drift and (5 <= day_offset <= 7)

        for _ in range(logs_per_day):
            city = rng.choice(list(CITIES.keys()))
            cfg = CITIES[city]
            model = rng.choice(MODELS)

            # Spread records across the day.
            minute_of_day = rng.randint(0, 1439)
            recorded_at = target_day.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(minutes=minute_of_day)
            forecast_time = recorded_at - timedelta(hours=rng.choice([1, 3, 6, 12, 24]))

            actual_temp = cfg["base_temp"] + rng.uniform(-cfg["temp_var"], cfg["temp_var"])
            actual_hum = cfg["base_hum"] + rng.uniform(-10.0, 10.0)

            if in_drift and rng.random() < 0.7:
                # During drift: larger, mostly one-sided error (MAE ~2.5-5.0°C)
                error_margin = rng.uniform(2.5, 5.0) * rng.choice([-1, 1])
            else:
                # Normal operational error (MAE ~0.2-1.4°C)
                error_margin = rng.gauss(0, 0.8)

            predicted_temp = actual_temp + error_margin
            predicted_hum = actual_hum + rng.uniform(-5.0, 5.0)

            docs.append(
                (city, recorded_at.isoformat(timespec="seconds"),
                 round(predicted_temp, 2), round(actual_temp, 2),
                 round(abs(error_margin), 2), _now_iso())
            )

    print(f"Inserting {len(docs)} rows into {DB_PATH} (forecast_verification)...")
    with sqlite3.connect(DB_PATH) as conn:
        conn.executemany(
            """INSERT INTO forecast_verification
               (city, timestamp, predicted_temp, actual_temp, error_margin, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            docs,
        )
        conn.commit()

    # Quick sanity check using the real model_accuracy() function.
    acc = __import__("database", fromlist=["model_accuracy"]).model_accuracy(window_hours=24 * days)
    print(f"\nSanity check (model_accuracy over {days}d):")
    print(f"  records : {acc['count']}")
    print(f"  MAE     : {acc['mae']} °C")
    print(f"  RMSE    : {acc['rmse']} °C")
    print(f"  cities  : {len(acc['cities'])}")
    if acc['cities']:
        top = max(acc['cities'], key=lambda c: c['count'])
        print(f"  busiest : {top['city']} (n={top['count']}, MAE={top['mae']}, RMSE={top['rmse']})")


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


if __name__ == "__main__":
    clear = "--clean" in sys.argv
    dry = "--dry" in sys.argv
    seed(clear_first=clear, inject_drift=True, logs_per_day=40, days=30)
    if dry:
        print("\nDRY-RUN mode: no rows were committed (remove --dry to seed).")
    else:
        print("\nDone.")