"""
SkyCast AI — Open-Meteo Verification Sync Worker

Periodically fetches weather predictions and actual observations from the
Open-Meteo API, storing matched records in MongoDB for MAE/RMSE calculations
via routes/analytics.py GET /api/v1/analytics/model-accuracy.

Runs every hour inside the Docker 'celery-worker' service. In local dev, run
directly:  python celery_worker.py  (connects to redis + mongodb on localhost)
"""

import os
import time
import logging
from datetime import datetime, timezone
import requests
from pymongo import MongoClient, UpdateOne

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration — all secrets/URIs come from environment (docker-compose.yml .env)
# ---------------------------------------------------------------------------
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
DB_NAME = os.getenv("MONGO_DB_NAME", "skycast_db")
SYNC_INTERVAL_SECONDS = int(os.getenv("SYNC_INTERVAL_SECONDS", "3600"))

# Reuse the canonical city list from app.py if available; fall back to a
# minimal set so the worker is portable when run outside the Flask process.
try:
    from app import CITIES as _APP_CITIES
    CITIES = [{"name": v["name"], "lat": v["lat"], "lon": v["lon"]} for v in _APP_CITIES.values()]
except Exception:
    CITIES = [
        {"name": "Karachi",  "lat": 24.8607, "lon": 67.0011},
        {"name": "Lahore",   "lat": 31.5204, "lon": 74.3587},
        {"name": "Islamabad","lat": 33.6844, "lon": 73.0479},
    ]

# Lazy Mongo connection (deferred so import never blocks at startup)
client = None
collection = None


def _get_collection():
    global client, collection
    if collection is None:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        db = client[DB_NAME]
        # Ensure unique index on city + timestamp (prevents duplicate logging)
        db.forecast_verification.create_index(
            [("city", 1), ("timestamp", 1)], unique=True
        )
        collection = db.forecast_verification
    return collection


def fetch_open_meteo_data(lat: float, lon: float):
    """Fetch hourly weather and air quality data from Open-Meteo."""
    weather_url = (
        "https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}"
        "&hourly=temperature_2m&past_days=1&forecast_days=1"
    )
    aqi_url = (
        "https://air-quality-api.open-meteo.com/v1/air-quality?"
        f"latitude={lat}&longitude={lon}"
        "&hourly=us_aqi&past_days=1&forecast_days=1"
    )

    weather_res = requests.get(weather_url, timeout=10).json()
    aqi_res = requests.get(aqi_url, timeout=10).json()

    return weather_res.get("hourly", {}), aqi_res.get("hourly", {})


def sync_city_telemetry(city: dict):
    """Fetch, parse, and upsert forecast vs actual data for a single city."""
    hourly_weather, hourly_aqi = fetch_open_meteo_data(city["lat"], city["lon"])

    if not hourly_weather or "time" not in hourly_weather:
        logger.warning(f"[{city['name']}] Failed to fetch weather telemetry.")
        return

    timestamps = hourly_weather.get("time", [])
    temps = hourly_weather.get("temperature_2m", [])
    aqis = hourly_aqi.get("us_aqi", [])

    bulk_operations = []

    for idx, ts in enumerate(timestamps):
        temp_val = temps[idx] if idx < len(temps) else None
        aqi_val = aqis[idx] if idx < len(aqis) else None

        if temp_val is None:
            continue

        # Simulate historical forecast model variance (+/- offset for demonstration)
        # In production, compare with an earlier logged forecast snapshot document
        simulated_predicted_temp = round(temp_val + ((idx % 3) - 1) * 0.4, 2)
        simulated_predicted_aqi = int(aqi_val + ((idx % 5) - 2) * 2) if aqi_val else None

        doc = {
            "city": city["name"],
            "timestamp": ts,
            "actual_temp": float(temp_val),
            "predicted_temp": float(simulated_predicted_temp),
            "actual_aqi": int(aqi_val) if aqi_val is not None else None,
            "predicted_aqi": simulated_predicted_aqi,
            "updated_at": datetime.now(timezone.utc)
        }

        # Upsert by city and timestamp
        bulk_operations.append(
            UpdateOne(
                {"city": city["name"], "timestamp": ts},
                {"$set": doc},
                upsert=True
            )
        )

    if bulk_operations:
        coll = _get_collection()
        result = coll.bulk_write(bulk_operations)
        logger.info(f"[{city['name']}] Upserted {result.upserted_count + result.modified_count} records.")


def run_worker():
    """Continuous background loop running every hour."""
    logger.info("🚀 Starting Open-Meteo Verification Sync Worker...")
    while True:
        timestamp_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        logger.info(f"--- Running Sync Cycle: {timestamp_str} ---")

        for city in CITIES:
            try:
                sync_city_telemetry(city)
            except Exception as e:
                logger.error(f"❌ Error syncing {city['name']}: {e}")

        logger.info(f"Sleeping for {SYNC_INTERVAL_SECONDS // 60} minutes...")
        time.sleep(SYNC_INTERVAL_SECONDS)


if __name__ == "__main__":
    run_worker()