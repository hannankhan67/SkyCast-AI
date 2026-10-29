"""SkyCast AI — Data engineering routes (analyst/admin gated).

    POST /api/analyst/ingest              multipart CSV/JSON/JSONL upload
    GET  /api/analyst/climate/correlations?city=&days=30
    GET  /api/analyst/climate/trends?city=&horizon=24
    POST /api/admin/data/backup           on-demand gzip'd DB backup
    GET  /api/admin/data/backups          backup inventory
    POST /api/admin/data/vacuum           SQLite VACUUM

Role model: ingestion and analytics need the analyst tier, the
data-maintenance actions are admin-only — matching the existing RBAC in
routes/auth.py.
"""

from __future__ import annotations

import logging

from flask import Blueprint, g, jsonify, request

import database
from security.permissions import Permission, require_permission
from services import forecast_trends, ingest, maintenance, mapreduce

logger = logging.getLogger(__name__)

data_eng_bp = Blueprint("data_engineering", __name__)


@data_eng_bp.route("/api/analyst/ingest", methods=["POST"])
@require_permission(Permission.ANALYST_METRICS)
def ingest_observations():
    """POST /api/analyst/ingest — bulk climate data ingestion.

    Accepts either a multipart upload (field name ``file``; CSV, JSON
    array/JSONL) or a JSON body ``{"rows": [...]}``. Rows are validated
    and persisted to SQLite + the partitioned lake (+ optional Mongo
    mirror). Corrupt rows are skipped and counted, never fatal.
    """
    try:
        upload = request.files.get("file")
        if upload is not None:
            summary = ingest.ingest_upload(upload.read())
        else:
            payload = request.get_json(silent=True) or {}
            rows = payload.get("rows")
            if not isinstance(rows, list) or not rows:
                return jsonify({
                    "status": "error",
                    "error": "provide a multipart 'file' upload or JSON {\"rows\": [...]}"
                }), 400
            summary = ingest.ingest_rows(rows)
        if summary.get("accepted"):
            try:
                database.audit_log_action(
                    g.user["id"], "data_ingest",
                    detail="accepted=%(accepted)s skipped=%(skipped)s" % summary
                )
            except Exception:  # noqa: BLE001 - audit is best-effort
                pass
        return jsonify({
            "status": "success" if summary.get("accepted") else "error",
            **summary,
        }), (200 if summary.get("accepted") else 400)
    except ingest.IngestError as exc:
        return jsonify({"status": "error", "error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        logger.exception("ingestion failed")
        return jsonify({"status": "error", "error": str(exc)}), 500


@data_eng_bp.route("/api/analyst/climate/correlations", methods=["GET"])
@require_permission(Permission.ANALYST_METRICS)
def climate_correlations():
    """GET /api/analyst/climate/correlations?city=&days=30&workers=1

    MapReduce job computing per-city Pearson correlations between
    temperature, AQI, humidity and wind over the trailing window.
    """
    city = (request.args.get("city") or "").strip() or None
    try:
        days = max(1, min(int(request.args.get("days", 30)), 365))
        workers = max(1, min(int(request.args.get("workers", 1)), 8))
    except ValueError:
        return jsonify({"status": "error",
                        "error": "days and workers must be integers"}), 400

    try:
        records = ingest.load_observations(city=city, days=days)
        correlations = mapreduce.city_pearson_job(
            mapreduce.build_pair_records(records), workers=workers
        )
        if city:
            correlations = {city: correlations.get(city, {})}
    except Exception as exc:  # noqa: BLE001
        logger.exception("correlation job failed")
        return jsonify({"status": "error", "error": str(exc)}), 500

    return jsonify({
        "status": "success",
        "window_days": days,
        "records": len(records),
        "correlations": correlations,
    })


@data_eng_bp.route("/api/analyst/climate/trends", methods=["GET"])
@require_permission(Permission.ANALYST_METRICS)
def climate_trends():
    """GET /api/analyst/climate/trends?city=karachi&horizon=24

    Trains a per-city linear trend model on ingested observations and
    forecasts the requested horizon (sklearn when available, closed-form
    least squares otherwise).
    """
    city = (request.args.get("city") or "").strip()
    if not city:
        return jsonify({"status": "error", "error": "city parameter is required"}), 400
    try:
        horizon = max(1, min(int(request.args.get("horizon", 24)), 168))
    except ValueError:
        return jsonify({"status": "error", "error": "horizon must be an integer"}), 400

    result = forecast_trends.forecast_trend(city, horizon_hours=horizon)
    if result.get("error"):
        return jsonify({"status": "error", "error": result["error"]}), 400
    return jsonify({"status": "success", **result})


@data_eng_bp.route("/api/admin/data/backup", methods=["POST"])
@require_permission(Permission.ADMIN_FLAGS)
def run_backup():
    """POST /api/admin/data/backup[?keep=14] — on-demand gzipped DB backup."""
    try:
        keep = max(1, min(int(request.args.get("keep", 14)), 90))
    except ValueError:
        return jsonify({"status": "error", "error": "keep must be an integer"}), 400
    result = maintenance.create_backup(keep=keep)
    return jsonify({"status": "success" if result.get("ok") else "error",
                    **result}), (200 if result.get("ok") else 500)


@data_eng_bp.route("/api/admin/data/backups", methods=["GET"])
@require_permission(Permission.ADMIN_FLAGS)
def backup_inventory():
    """GET /api/admin/data/backups — backup archive inventory."""
    return jsonify({"status": "success", "backups": maintenance.list_backups()})


@data_eng_bp.route("/api/admin/data/vacuum", methods=["POST"])
@require_permission(Permission.ADMIN_FLAGS)
def run_vacuum():
    """POST /api/admin/data/vacuum — reclaim free pages in SQLite."""
    result = maintenance.vacuum_database()
    return jsonify({"status": "success" if result.get("ok") else "error",
                    **result}), (200 if result.get("ok") else 500)