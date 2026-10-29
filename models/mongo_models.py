"""SkyCast AI - Optional MongoDB persistence layer.

This module backs three features with MongoDB documents:

  * ``user_health_thresholds`` - per-user health alert sensitivity rules
  * ``event_plans``            - saved event-feasibility queries + snapshot
  * ``api_key_telemetry``       - time-series API usage / latency log

It is **strictly optional**. If ``pymongo`` is not installed or MongoDB is
unreachable, every helper returns ``None`` and the caller falls back to the
existing SQLite / in-memory behaviour, so the app keeps working unchanged.

Enable by setting the ``MONGO_URI`` environment variable, e.g.::

    MONGO_URI=mongodb://localhost:27017/skycast_db

The database name is taken from the URI path, defaulting to ``skycast_db``.
"""

import os
from datetime import datetime, timedelta, timezone

_MONGO_URI = os.environ.get("MONGO_URI")
_DB_NAME = "skycast_db"

_client = None
_db = None
_available = None  # tri-state: None = not yet probed


def is_available():
    """Return True only if pymongo is importable and Mongo is reachable."""
    global _client, _db, _available
    if _available is not None:
        return _available
    if not _MONGO_URI:
        _available = False
        return False
    try:
        from pymongo import MongoClient
        from pymongo.errors import PyMongoError
        _client = MongoClient(_MONGO_URI, serverSelectionTimeoutMS=1500)
        # Force a connection attempt to validate reachability.
        _client.admin.command("ping")
        _db = _client.get_default_database() if _client.get_default_database() else _client[_DB_NAME]
        _available = True
    except Exception:
        _client = None
        _db = None
        _available = False
    return _available


def get_db():
    """Return the active Mongo database, or ``None`` if unavailable."""
    return _db if is_available() else None


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class HealthThresholdModel:
    """Per-user health alert sensitivity rules."""

    COLLECTION = "user_health_thresholds"

    @staticmethod
    def get_default_profile(user_id):
        return {
            "user_id": user_id,
            "migraine": {"enabled": True, "pressure_drop_hpa": 3.0},
            "asthma": {"enabled": True, "pm25_threshold": 50.0, "humidity_max": 80.0},
            "joint_pain": {"enabled": False, "temp_drop_c": 5.0},
            "uv_safety": {"enabled": True, "max_uv": 6.0, "skin_type_fitzpatrick": 3},
            "updated_at": datetime.utcnow(),
        }

    @classmethod
    def get_or_create(cls, user_id):
        db = get_db()
        if db is None:
            return cls.get_default_profile(user_id)
        col = db[cls.COLLECTION]
        doc = col.find_one({"user_id": user_id})
        if doc is None:
            doc = cls.get_default_profile(user_id)
            col.insert_one(doc)
        doc.pop("_id", None)
        return doc

    @classmethod
    def save(cls, user_id, profile):
        db = get_db()
        if db is None:
            return None
        profile = dict(profile)
        profile["user_id"] = user_id
        profile["updated_at"] = datetime.utcnow()
        db[cls.COLLECTION].update_one(
            {"user_id": user_id}, {"$set": profile}, upsert=True
        )
        return True


class EventPlanModel:
    """Saved event-feasibility queries and weather snapshots."""

    COLLECTION = "event_plans"

    @staticmethod
    def create_document(user_id, event_type, city, event_date, score, label, weather_data):
        return {
            "user_id": user_id,
            "event_type": event_type,
            "event_name": "%s in %s" % (str(event_type).capitalize(), city),
            "target_city": city,
            "event_date": event_date,
            "feasibility_score": int(score),
            "status_label": label,
            "forecast_snapshot": {
                "temp_c": float(weather_data.get("temp", 0) or 0),
                "rain_prob": float(weather_data.get("rain_prob", 0) or 0),
                "wind_speed_kmh": float(weather_data.get("wind_speed", 0) or 0),
                "cloud_cover_pct": float(weather_data.get("cloud_cover", 0) or 0),
            },
            "created_at": datetime.utcnow(),
        }

    @classmethod
    def save(cls, document):
        db = get_db()
        if db is None:
            return None
        db[cls.COLLECTION].insert_one(document)
        return True


class ApiTelemetryModel:
    """Time-series API usage / latency log."""

    COLLECTION = "api_key_telemetry"

    @staticmethod
    def create_log(key_hash, endpoint, method, status_code, latency_ms, ip_address):
        return {
            "api_key_hash": key_hash,
            "endpoint": endpoint,
            "http_method": method,
            "status_code": status_code,
            "latency_ms": latency_ms,
            "ip_address": ip_address,
            "timestamp": datetime.utcnow(),
        }

    @classmethod
    def log(cls, key_hash, endpoint, method="GET", status_code=200, latency_ms=0.0, ip_address=None):
        db = get_db()
        if db is None:
            return None
        db[cls.COLLECTION].insert_one(
            cls.create_log(key_hash, endpoint, method, status_code, latency_ms, ip_address)
        )
        return True


# ---------------------------------------------------------------------------
# Simulation logs (analyst alert-simulator dry-runs) — optional MongoDB
# ---------------------------------------------------------------------------

def timeframe_cutoff(timeframe):
    """UTC datetime threshold for ?timeframe=24h|7d|all (None for 'all').

    Raises ValueError for any other value so routes can answer 400.
    """
    now = datetime.now(timezone.utc)
    key = (timeframe or "").lower()
    if key == "24h":
        return now - timedelta(hours=24)
    if key == "7d":
        return now - timedelta(days=7)
    if key == "all":
        return None
    raise ValueError("Invalid timeframe parameter. Choose '24h', '7d', or 'all'.")


# Reuses the same connection defaults as app.py so a local mongod on the
# default port activates the feature even when MONGO_URI is not exported.
_SIM_MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/")
_SIM_DB_NAME = os.environ.get("MONGO_DB_NAME", "skycast_db")
_sim_client = None
_sim_db = None
_sim_available = None  # tri-state: None = not yet probed


def _simulation_database():
    """Return the simulation Mongo database, or ``None`` when unavailable."""
    global _sim_client, _sim_db, _sim_available
    if _sim_available is not None:
        return _sim_db if _sim_available else None
    try:
        from pymongo import MongoClient

        _sim_client = MongoClient(_SIM_MONGO_URI, serverSelectionTimeoutMS=1500)
        # Force a connection attempt to validate reachability.
        _sim_client.admin.command("ping")
        _sim_db = _sim_client[_SIM_DB_NAME]
        _sim_available = True
    except Exception:
        _sim_client = None
        _sim_db = None
        _sim_available = False
    return _sim_db if _sim_available else None


class SimulationLogModel:
    """Optional MongoDB mirror of alert-simulator dry-run executions.

    Each document records one rule-engine evaluation in the ``simulation_logs``
    collection, powering ``GET /api/v1/analytics/simulate-alert/stats``.
    MongoDB is strictly optional: when unreachable every method returns ``None``
    (or zeroed stats) and the calling routes degrade gracefully.
    """

    COLLECTION = "simulation_logs"

    @staticmethod
    def insert(city, parameters, rules_triggered, triggered_count,
               highest_severity, processing_latency_ms, executed_at=None):
        """Persist one execution record. Returns ``True``, or ``None`` offline."""
        db = _simulation_database()
        if db is None:
            return None
        db[SimulationLogModel.COLLECTION].insert_one({
            "city": str(city).strip().lower(),
            "parameters": dict(parameters or {}),
            "rules_triggered": rules_triggered or [],
            "triggered_count": int(triggered_count or 0),
            "highest_severity": str(highest_severity or "NONE"),
            "processing_latency_ms": float(processing_latency_ms or 0.0),
            "executed_at": executed_at or datetime.now(timezone.utc),
        })
        return True

    @staticmethod
    def stats(cutoff=None):
        """Single ``$facet`` aggregation: severity counts + latency metrics.

        Returns ``(data, mongo_available)``. When MongoDB is offline the data
        dict is zero-filled so dashboards degrade gracefully.
        """
        db = _simulation_database()
        zeros = {
            "critical": 0,
            "high": 0,
            "warning": 0,
            "total_alerts": 0,
            "total_simulations": 0,
            "latency": {"avg_ms": 0.0, "min_ms": 0.0, "max_ms": 0.0},
        }
        if db is None:
            return zeros, False

        match_stage = {"executed_at": {"$gte": cutoff}} if cutoff else {}
        pipeline = [
            {"$match": match_stage},
            {
                "$facet": {
                    # Branch A: group counts by highest_severity level.
                    "severity_breakdown": [
                        {"$group": {
                            "_id": "$highest_severity",
                            "count": {"$sum": 1},
                        }}
                    ],
                    # Branch B: execution latency metrics.
                    "latency_metrics": [
                        {"$group": {
                            "_id": None,
                            "avg_ms": {"$avg": "$processing_latency_ms"},
                            "min_ms": {"$min": "$processing_latency_ms"},
                            "max_ms": {"$max": "$processing_latency_ms"},
                            "total_runs": {"$sum": 1},
                        }}
                    ],
                }
            },
        ]

        results = list(db[SimulationLogModel.COLLECTION].aggregate(pipeline))
        facet = results[0] if results else {}

        severity_counts = {"critical": 0, "high": 0, "warning": 0, "none": 0}
        for item in facet.get("severity_breakdown") or []:
            key = (item["_id"] or "none").lower()
            if key in severity_counts:
                severity_counts[key] = item["count"]

        latency_raw = facet.get("latency_metrics") or []
        if latency_raw:
            metrics = latency_raw[0]
            latency = {
                "avg_ms": round(metrics.get("avg_ms") or 0.0, 2),
                "min_ms": round(metrics.get("min_ms") or 0.0, 2),
                "max_ms": round(metrics.get("max_ms") or 0.0, 2),
            }
            total_simulations = metrics.get("total_runs", 0)
        else:
            latency = {"avg_ms": 0.0, "min_ms": 0.0, "max_ms": 0.0}
            total_simulations = 0

        return {
            "critical": severity_counts["critical"],
            "high": severity_counts["high"],
            "warning": severity_counts["warning"],
            "total_alerts": (severity_counts["critical"]
                             + severity_counts["high"]
                             + severity_counts["warning"]),
            "total_simulations": total_simulations,
            "latency": latency,
        }, True
