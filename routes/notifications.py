"""Authenticated Web Push subscription endpoints."""

from flask import Blueprint, g, jsonify, request

import database
from routes.auth import login_required

notifications_bp = Blueprint("notifications", __name__)


@notifications_bp.route("/api/notifications/subscribe", methods=["POST"])
@login_required
def subscribe():
    subscription = request.get_json(silent=True) or {}
    if not isinstance(subscription, dict) or not subscription.get("endpoint"):
        return jsonify({"success": False, "error": "Invalid push subscription."}), 400
    keys = subscription.get("keys") or {}
    if not keys.get("p256dh") or not keys.get("auth"):
        return jsonify({"success": False, "error": "Incomplete push subscription."}), 400
    try:
        database.save_push_subscription(g.user["id"], subscription)
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Invalid push subscription."}), 400
    return jsonify({"success": True, "message": "Push subscription saved."}), 201


@notifications_bp.route("/api/notifications/unsubscribe", methods=["POST"])
@login_required
def unsubscribe():
    subscription = request.get_json(silent=True) or {}
    endpoint = subscription.get("endpoint")
    if endpoint:
        database.delete_push_subscription(endpoint)
    return jsonify({"success": True})