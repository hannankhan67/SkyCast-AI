"""SkyCast AI — Analyst drift & anomaly API routes.

Both endpoints are gated by the ``ANALYST_METRICS`` permission bit
(security/permissions.py): analysts and admins pass; anonymous callers get
401 and other roles get 403.

    GET /api/analyst/drift/metrics?city=&days=7
        Runs a trailing-24h MAE/RMSE backtest, upserts the snapshot and
        returns the stored daily time-series for the requested window.
    GET /api/analyst/drift/anomalies?days=7&city=&limit=50
        Runs Z-score detection over the rolling 30-day window, upserts
        flags and returns the most recent stored anomalies.
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from security.permissions import Permission, require_permission
from services import anomaly, drift_engine

logger = logging.getLogger(__name__)

analyst_drift_bp = Blueprint("analyst_drift", __name__)


def _int_arg(name: str, default: int, lo: int, hi: int) -> int:
    """Read and validate an integer query parameter.

    Raises:
        ValueError: when the value is present but not an integer in range.
    """
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("%s must be an integer" % name) from exc
    if not lo <= value <= hi:
        raise ValueError("%s must be between %d and %d" % (name, lo, hi))
    return value


@analyst_drift_bp.route("/api/analyst/drift/metrics", methods=["GET"])
@require_permission(Permission.ANALYST_METRICS)
def drift_metrics():
    """Time-series MAE / RMSE per city (analyst+ only)."""
    try:
        days = _int_arg("days", 7, 1, 90)
    except ValueError as exc:
        return jsonify({"status": "error", "error": str(exc)}), 400
    city = (request.args.get("city") or "").strip() or None

    try:
        current = drift_engine.backtest(hours=24)
        history = drift_engine.recent_metrics(city=city, days=days)
    except Exception as exc:  # noqa: BLE001
        logger.exception("drift metrics computation failed")
        return jsonify({"status": "error", "error": str(exc)}), 503

    return jsonify({
        "status": "success",
        "current": current,
        "history": history,
        "count": len(history),
    })


@analyst_drift_bp.route("/api/analyst/drift/anomalies", methods=["GET"])
@require_permission(Permission.ANALYST_METRICS)
def drift_anomalies():
    """Recent flagged microclimate anomalies (analyst+ only)."""
    try:
        days = _int_arg("days", 7, 1, 30)
        limit = _int_arg("limit", 50, 1, 200)
    except ValueError as exc:
        return jsonify({"status": "error", "error": str(exc)}), 400
    city = (request.args.get("city") or "").strip() or None

    try:
        detected = anomaly.detect_anomalies(days=30)
        anomaly.store_anomalies(detected)
        recent = anomaly.recent_anomalies(city=city, days=days, limit=limit)
    except Exception as exc:  # noqa: BLE001
        logger.exception("anomaly detection failed")
        return jsonify({"status": "error", "error": str(exc)}), 503

    return jsonify({
        "status": "success",
        "detected_now": len(detected),
        "count": len(recent),
        "anomalies": recent,
    })