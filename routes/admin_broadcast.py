import os
from flask import Blueprint, request, jsonify
from security.permissions import require_permission, Permission
from datetime import datetime, timezone


admin_broadcast_bp = Blueprint('admin_broadcast', __name__)

@admin_broadcast_bp.route('/api/admin/broadcast/geofence', methods=['POST'])
@require_permission(Permission.ADMIN_BROADCAST)
def create_geofenced_broadcast():
    """
    Creates a geofenced emergency alert broadcast for users located within a defined polygon.
    Payload: { "alert_title": "...", "severity": "CRITICAL", "polygon": [[[lon, lat], ...]] }
    """
    try:
        from database import mongo_db
    except ImportError:
        return jsonify({"error": "Database module unavailable"}), 503

    data = request.get_json() or {}
    title = data.get('alert_title')
    severity = data.get('severity', 'WARNING')
    polygon_coordinates = data.get('polygon')

    if not polygon_coordinates:
        return jsonify({"error": "Polygon geometry is required"}), 400

    broadcast_doc = {
        "title": title,
        "severity": severity,
        "message": data.get('message'),
        "geofence": {
            "type": "Polygon",
            "coordinates": polygon_coordinates
        },
        "created_at": datetime.now(timezone.utc),
        "is_active": True
    }

    result = mongo_db.active_broadcasts.insert_one(broadcast_doc)

    affected_users_count = mongo_db.users.count_documents({
        "last_known_location": {
            "$geoWithin": {
                "$geometry": broadcast_doc["geofence"]
            }
        }
    })

    return jsonify({
        "status": "broadcast_published",
        "broadcast_id": str(result.inserted_id),
        "targeted_users_in_zone": affected_users_count
    }), 201