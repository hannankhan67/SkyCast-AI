"""SkyCast AI — Analytics Command Center Blueprint.

Serves both user-facing climate trends and administrative system metrics.

User & Public Climate Analytics:
  GET /api/v1/analytics/weather-trends   7-day temperature, humidity, rainfall trends
  GET /api/v1/analytics/air-quality-history  24-hour AQI trend metrics

Administrative & System Analytics:
  GET /api/v1/analytics/system/usage      Platform usage metrics, active sessions
  GET /api/v1/analytics/system/api-health  Latency logs, third-party API status
"""

from datetime import datetime, timedelta
from flask import Blueprint, g, jsonify, request

import database
from routes.auth import admin_required, analyst_required, min_role_required

analytics_bp = Blueprint("analytics", __name__)


# ====================================================================
# USER & PUBLIC CLIMATE ANALYTICS ENDPOINTS
# ====================================================================


@analytics_bp.route("/api/v1/analytics/weather-trends", methods=["GET"])
def get_weather_trends():
    """
    Returns 7-day temperature, humidity, and rainfall trend historical data
    for interactive visual charts (e.g., Chart.js).
    """
    location = request.args.get("location", "Karachi")

    # Generate 7-day historical timeline
    dates = [
        (datetime.now() - timedelta(days=i)).strftime("%b %d")
        for i in range(6, -1, -1)
    ]

    data = {
        "location": location,
        "timeline": dates,
        "temperature_max": [33, 34, 32, 35, 36, 33, 31],
        "temperature_min": [26, 27, 26, 28, 27, 25, 24],
        "humidity_avg": [65, 70, 72, 68, 60, 75, 80],
        "precipitation_mm": [0.0, 0.0, 1.2, 4.5, 0.0, 0.0, 12.0],
    }
    return jsonify({"status": "success", "data": data}), 200


@analytics_bp.route("/api/v1/analytics/air-quality-history", methods=["GET"])
def get_aqi_history():
    """Returns 24-hour historical AQI trend metrics."""
    hours = [f"{i:02d}:00" for i in range(0, 24, 3)]
    return jsonify(
        {
            "status": "success",
            "hours": hours,
            "pm2_5": [42, 38, 35, 40, 55, 68, 62, 48],
            "pm10": [80, 75, 70, 82, 110, 135, 120, 95],
            "aqi_index": [115, 108, 100, 112, 145, 162, 155, 128],
        }
    ), 200


# ====================================================================
# ANALYST SIMULATION AUDIT (dry-run history for the audit table)
# ====================================================================


@analytics_bp.route("/api/v1/analytics/simulate-alert/history", methods=["GET"])
@min_role_required("analyst")
def get_simulate_alert_history():
    """Recent analyst dry-run simulations from the rule-engine audit log."""
    limit = request.args.get("limit", default=10, type=int)
    return jsonify(
        {
            "status": "success",
            "data": database.get_simulation_history(limit=limit),
        }
    ), 200


# Simulation parameter keys (order preserved for the parameters payload).
_SIM_PARAM_KEYS = ("temperature", "aqi", "wind_speed", "humidity")


def _sim_parameters(data):
    """Coerce simulation inputs ({temperature, aqi, wind_speed, humidity}).

    Missing/empty values default to 0; malformed values raise
    (TypeError, ValueError) so the calling route can answer 400.
    """
    defaults = {"temperature": 0.0, "aqi": 0, "wind_speed": 0.0, "humidity": 0.0}
    params = {}
    for key in _SIM_PARAM_KEYS:
        raw = data.get(key)
        if raw is None or str(raw).strip() == "":
            params[key] = defaults[key]
            continue
        params[key] = int(raw) if key == "aqi" else float(raw)
    return params


@analytics_bp.route("/api/v1/analytics/simulate-alert", methods=["POST"])
@min_role_required("analyst")
def run_alert_simulation():
    """Execute a dry-run rule-engine evaluation and log it to MongoDB.

    The run is persisted to the SQLite audit history (feeding the audit table)
    and mirrored into Mongo's ``simulation_logs`` collection (feeding the
    stats aggregation) when MongoDB is available.
    """
    data = request.get_json(silent=True) or {}
    city = (data.get("city") or "karachi").strip()
    try:
        parameters = _sim_parameters(data)
    except (TypeError, ValueError):
        return jsonify(
            {"error": "temperature/aqi/wind_speed/humidity must be numbers"}
        ), 400

    doc = database.run_alert_simulation(city, parameters, g.user["id"])

    from models.mongo_models import SimulationLogModel

    SimulationLogModel.insert(
        city=doc["city"],
        parameters=doc["parameters"],
        rules_triggered=doc["rules_triggered"],
        triggered_count=doc["triggered_count"],
        highest_severity=doc["highest_severity"],
        processing_latency_ms=doc["processing_latency_ms"],
    )

    return jsonify({
        "status": "success",
        "data": {
            "city": doc["city"],
            "highest_severity": doc["highest_severity"],
            "rules_triggered": doc["rules_triggered"],
            "processing_latency_ms": doc["processing_latency_ms"],
        },
    }), 200


@analytics_bp.route("/api/v1/analytics/simulate-alert/stats", methods=["GET"])
@min_role_required("analyst")
def get_simulation_stats():
    """Aggregated severity breakdown + latency stats from MongoDB.

    Query params:
        timeframe (str) — 24h | 7d | all (default: 24h)

    Uses a single ``$facet`` aggregation pipeline so severity counts and
    latency metrics are computed in one database round-trip.
    """
    from models.mongo_models import SimulationLogModel, timeframe_cutoff

    try:
        timeframe = (request.args.get("timeframe") or "24h").lower()
        cutoff = timeframe_cutoff(timeframe)
    except ValueError as ve:
        return jsonify({"status": "error", "message": str(ve)}), 400

    try:
        data, mongo_available = SimulationLogModel.stats(cutoff=cutoff)
    except Exception as exc:  # noqa: BLE001 - keep the API honest on failure
        return jsonify(
            {"status": "error", "message": "Server error: %s" % exc}
        ), 500

    data["mongo_available"] = mongo_available
    return jsonify(
        {"status": "success", "timeframe": timeframe, "data": data}
    ), 200


# ====================================================================
# ADMINISTRATIVE & SYSTEM ANALYTICS ENDPOINTS
# ====================================================================


@analytics_bp.route("/api/v1/analytics/system/usage", methods=["GET"])
@min_role_required("analyst")
def get_system_analytics():
    """
    Returns platform usage metrics, active session counts,
    and popular feature distributions for the Admin Dashboard.
    """
    metrics = {
        "active_users_current": 142,
        "total_api_requests_24h": 28450,
        "api_response_time_ms": 118,
        "cache_hit_ratio": "88.4%",
        "top_searched_cities": [
            {"city": "Karachi", "queries": 9420},
            {"city": "Lahore", "queries": 7310},
            {"city": "Islamabad", "queries": 5120},
            {"city": "Peshawar", "queries": 2100},
        ],
        "feature_usage_distribution": {
            "live_weather": "40%",
            "radar_map": "25%",
            "smart_commute": "15%",
            "shelter_finder": "10%",
            "solar_calculator": "10%",
        },
    }
    return jsonify({"status": "success", "analytics": metrics}), 200


@analytics_bp.route("/api/v1/analytics/system/api-health", methods=["GET"])
@min_role_required("analyst")
def get_api_health_analytics():
    """
    Returns latency logs and third-party API provider status metrics
    (e.g., Open-Meteo, Leaflet tile servers).
    """
    health_data = {
        "timestamp": datetime.utcnow().isoformat(),
        "providers": [
            {
                "name": "Open-Meteo Weather API",
                "status": "Operational",
                "latency": "145ms",
                "uptime_24h": "99.9%",
            },
            {
                "name": "CARTO Dark Tile Server",
                "status": "Operational",
                "latency": "62ms",
                "uptime_24h": "100.0%",
            },
            {
                "name": "SQLite / MongoDB Mirror Sync",
                "status": "In Sync",
                "sync_lag": "0.02s",
                "last_synced": "1 second ago",
            },
        ],
    }
    return jsonify({"status": "success", "system_health": health_data}), 200


# ============================================================================
# MODEL ACCURACY / FORECAST VERIFICATION (MongoDB-backed, optional)
# ===============================================================================

@analytics_bp.route("/api/v1/analytics/model-accuracy", methods=["GET"])
@min_role_required("analyst")
def get_model_accuracy():
    """
    Returns model drift analytics computed from MongoDB aggregation.

    Query params:
        city      (str)  — optional city filter (lowercase)
        model     (str)  — optional model_source filter (e.g. "open-meteo")
        days      (int)  — lookback window in days, clamped 1..90

    Returns:
        {
          "status": "success",
          "data": {
            "summary": {
              "sample_count": <int>,
              "mae_temp_celsius": <float>,
              "rmse_temp_celsius": <float>,
              "city_filter": <str>,
              "model_source": <str>,
              "days_window": <int>,
              "mongo_available": <bool>
            },
            "timeseries": {
              "dates": [<str YYYY-MM-DD>, ...],
              "mae": [<float>, ...],
              "rmse": [<float>, ...],
              "sample_counts": [<int>, ...]
            }
          }
        }
    """
    city = (request.args.get("city") or "").strip().lower()
    model_source = (request.args.get("model") or "").strip().lower()
    try:
        days = int(request.args.get("days", 7))
        days = max(1, min(90, days))
    except (TypeError, ValueError):
        days = 7

    from database import get_model_drift_analytics

    data = get_model_drift_analytics(
        city=city if city else None,
        days=days,
        model_source=model_source if model_source else None,
    )
    return jsonify({"status": "success", "data": data}), 200


@analytics_bp.route("/api/v1/analytics/model-accuracy/log", methods=["POST"])
@min_role_required("analyst")
def ingest_verification_entry():
    """
    Persists a single predicted-vs-actual observation into MongoDB.

    Required JSON fields:
        city, predicted_temp, actual_temp, forecast_time

    Optional:
        model_source, predicted_humidity, actual_humidity
    """
    payload = request.get_json(silent=True) or {}

    required_fields = ["city", "predicted_temp", "actual_temp", "forecast_time"]
    missing = [f for f in required_fields if not payload.get(f)]
    if missing:
        return jsonify(
            {"error": "Missing required fields", "missing": missing}
        ), 400

    from database import log_forecast_verification_mongo

    success = log_forecast_verification_mongo(
        city=payload["city"],
        predicted_temp=float(payload["predicted_temp"]),
        actual_temp=float(payload["actual_temp"]),
        forecast_time=payload["forecast_time"],
        model_source=(payload.get("model_source") or "open-meteo"),
        predicted_humidity=payload.get("predicted_humidity"),
        actual_humidity=payload.get("actual_humidity"),
    )

    if success:
        return jsonify(
            {"message": "Observation persisted to MongoDB"}
        ), 201
    return jsonify({"error": "Failed to persist observation"}), 500
