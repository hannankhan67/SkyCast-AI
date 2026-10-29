"""SkyCast AI - Smart Alerts blueprint.

Lets registered users create custom threshold alerts ("notify me when wind
> 30 km/h in Karachi") and monitor the notification delivery log.

Routes:
    GET    /alerts                 Alert manager page (login required)
    GET    /api/alerts             List alerts + recent notification log
    POST   /api/alerts             Create a threshold alert (JSON)
    DELETE /api/alerts/<id>        Revoke an alert
    POST   /api/alerts/test        Evaluate alerts against live weather now
"""

from flask import Blueprint, g, jsonify, render_template, request

import database
import notifications
from routes.auth import login_required, premium_required

alerts_bp = Blueprint("alerts", __name__)

METRICS = ["temp", "uv", "wind", "humidity", "pressure"]
OPERATORS = [">", "<", ">=", "<="]
CHANNELS = ["browser", "email", "sms"]


def _valid_channels(channels):
    if not isinstance(channels, list):
        return False
    parts = [str(c).strip() for c in channels if str(c).strip()]
    return bool(parts) and all(c in CHANNELS for c in parts)


@alerts_bp.route("/alerts")
@premium_required
@login_required
def alerts_page():
    from app import CITIES

    return render_template(
        "alerts.html",
        active="alerts",
        cities=sorted(CITIES.keys()),
        metrics=METRICS,
        operators=OPERATORS,
        channels=CHANNELS,
    )


@alerts_bp.route("/api/alerts", methods=["GET"])
@login_required
def list_alerts():
    rows = database.get_alerts_by_user(g.user["id"])
    return jsonify(
        {
            "alerts": [dict(r) for r in rows],
            "notification_log": [
                dict(r)
                for r in database.get_notification_log(g.user["id"], limit=25)
            ],
        }
    )


@alerts_bp.route("/api/alerts", methods=["POST"])
@login_required
def create_alert():
    data = request.get_json(silent=True) or {}
    city = "".join(ch for ch in (data.get("city") or "").lower() if ch.isalnum())
    metric = (data.get("metric") or "").strip().lower()
    operator = (data.get("operator") or "").strip()
    channels = data.get("channels")

    from app import CITIES

    errors = []
    if city not in CITIES:
        errors.append("Unknown city.")
    if metric not in METRICS:
        errors.append("Metric must be one of: %s." % ", ".join(METRICS))
    if operator not in OPERATORS:
        errors.append("Operator must be one of: %s." % ", ".join(OPERATORS))
    try:
        threshold = float(data.get("threshold"))
    except (TypeError, ValueError):
        threshold = None
    if threshold is None:
        errors.append("Threshold must be a number.")
    if not _valid_channels(channels):
        errors.append("Pick at least one channel: %s." % ", ".join(CHANNELS))
    if errors:
        return jsonify({"error": " ".join(errors)}), 400

    alert_id = database.create_alert(
        g.user["id"],
        city,
        metric,
        threshold,
        operator,
        ",".join(str(c).strip() for c in channels),
    )
    return jsonify({"id": alert_id, "ok": True})


@alerts_bp.route("/api/alerts/<int:alert_id>", methods=["DELETE"])
@login_required
def revoke_alert(alert_id):
    ok = database.delete_alert(alert_id, g.user["id"])
    return jsonify({"revoked": ok})


@alerts_bp.route("/api/alerts/test", methods=["POST"])
@login_required
def test_alerts():
    """Evaluate the user's alerts against live weather for each configured city.

    Returns which alerts fired (with the live metric value used), so the UI can
    render native browser notifications and delivery results.
    """
    fired = notifications.evaluate_user_cities(g.user["id"])
    return jsonify({"fired": fired})