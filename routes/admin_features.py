"""SkyCast AI — Admin command-center features.

Three dynamic admin tools:
  1. System feature flags / toggles
  2. Broadcast warning alert center
  3. Live API key rate-limiter & tier manager

Built on the existing SQLite schema (dynamic, works now) with the same
document shape the MongoDB collections use, so swapping to Mongo later is a
storage-only change.
"""

import math
import os
import time
import zlib
from datetime import datetime, timedelta, timezone

from flask import (
    Blueprint,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

import database

admin_ext_bp = Blueprint("admin_ext", __name__, url_prefix="/admin")

_STARTED_AT = time.time()

# --- Feature flags defaults ----------------------------------------------
_FLAG_DEFAULTS = {
    "radar_map_enabled": True,
    "ai_assistant_enabled": True,
    "offline_simulation_mode": False,
    "maintenance_banner": False,
}

# --- Tier -> rate limit (req/min) ----------------------------------------
_TIER_LIMITS = {"Free": 60, "Pro": 500, "Enterprise": 5000}


def _sim(seed):
    return (zlib.crc32(str(seed).encode("utf-8")) % 100000) / 100000.0


# ====================================================================
# Feature flags
# ====================================================================

@admin_ext_bp.before_request
def _require_admin():
    public = {"admin.login", "admin.logout", "static"}
    if request.endpoint in public:
        return None
    if not session.get("is_admin"):
        if request.path.startswith("/api/"):
            return jsonify({"error": "admin required"}), 401
        flash("Please log in to access the admin console.", "warning")
        return redirect(url_for("auth.login", next=request.path))
    return None


def _all_flags():
    """Return every flag with its current value (seeding defaults as needed)."""
    with database._connect() as conn:
        rows = conn.execute(
            "SELECT flag_key, flag_value FROM system_feature_flags"
        ).fetchall()
        stored = {r["flag_key"]: bool(r["flag_value"]) for r in rows}
    flags = {}
    for key, default in _FLAG_DEFAULTS.items():
        flags[key] = stored.get(key, default)
        if key not in stored:
            conn = database._connect()
            try:
                conn.execute(
                    "INSERT INTO system_feature_flags (flag_key, flag_value, updated_at) VALUES (?, ?, ?)",
                    (key, int(default), datetime.now(timezone.utc).isoformat(timespec="seconds")),
                )
                conn.commit()
            except Exception:
                conn.rollback()
            finally:
                conn.close()
    return flags


@admin_ext_bp.route("/api/admin/feature-flags", methods=["GET", "POST"])
def manage_feature_flags():
    if request.method == "GET":
        flags = _all_flags()
        flags["uptime_seconds"] = round(time.time() - _STARTED_AT, 1)
        return jsonify({"status": "success", "flags": flags}), 200

    data = request.get_json() or {}
    updated = {}
    with database._connect() as conn:
        for key in _FLAG_DEFAULTS:
            if key in data:
                val = bool(data[key])
                conn.execute(
                    "INSERT INTO system_feature_flags (flag_key, flag_value, updated_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(flag_key) DO UPDATE SET flag_value=excluded.flag_value, updated_at=excluded.updated_at",
                    (key, int(val), datetime.now(timezone.utc).isoformat(timespec="seconds")),
                )
                updated[key] = val
        conn.commit()
    updated["uptime_seconds"] = round(time.time() - _STARTED_AT, 1)
    return jsonify({"status": "success", "message": "Feature flags updated", "flags": updated}), 200


# ====================================================================
# Broadcast alerts
# ====================================================================

@admin_ext_bp.route("/api/admin/broadcast-alert", methods=["GET", "POST", "DELETE"])
def broadcast_alert():
    if request.method == "POST":
        data = request.get_json() or {}
        title = (data.get("title") or "Severe Weather Warning").strip()
        message = (data.get("message") or "").strip()
        severity = data.get("severity") or "warning"
        target_city = data.get("target_city") or data.get("target_cities")
        if isinstance(target_city, list):
            target_city = ", ".join(target_city)
        target_city = (target_city or "All").strip()
        if severity not in ("info", "warning", "emergency"):
            severity = "warning"
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with database._connect() as conn:
            cur = conn.execute(
                "INSERT INTO broadcast_alerts (title, message, severity, target_city, is_active, created_at) "
                "VALUES (?, ?, ?, ?, 1, ?)",
                (title, message, severity, target_city, now),
            )
            conn.commit()
            alert_id = cur.lastrowid
        try:
            import notifications
            notifications.trigger_global_push_alert(title, message, "/alerts")
        except Exception:
            pass
        return jsonify({
            "status": "success", "alert_id": alert_id,
            "alert": {"id": alert_id, "title": title, "message": message,
                      "severity": severity, "target_city": target_city, "is_active": True},
        }), 201

    if request.method == "DELETE":
        alert_id = request.args.get("id")
        if alert_id:
            with database._connect() as conn:
                conn.execute("UPDATE broadcast_alerts SET is_active = 0 WHERE id = ?", (int(alert_id),))
                conn.commit()
            return jsonify({"status": "success", "message": "Alert deactivated"}), 200
        return jsonify({"status": "error", "message": "Missing alert ID"}), 400

    # GET — active alerts
    with database._connect() as conn:
        rows = conn.execute(
            "SELECT id, title, message, severity, target_city, is_active, created_at "
            "FROM broadcast_alerts WHERE is_active = 1 ORDER BY id DESC"
        ).fetchall()
    alerts = [
        {"id": r["id"], "title": r["title"], "message": r["message"],
         "severity": r["severity"], "target_city": r["target_city"],
         "is_active": bool(r["is_active"]), "created_at": r["created_at"]}
        for r in rows
    ]
    return jsonify({"status": "success", "alerts": alerts}), 200


@admin_ext_bp.route("/api/alerts/active", methods=["GET"])
def public_active_alerts():
    """Public endpoint: active broadcast alerts for the severe-weather toast stack."""
    with database._connect() as conn:
        rows = conn.execute(
            "SELECT id, title, message, severity, target_city, created_at "
            "FROM broadcast_alerts WHERE is_active = 1 ORDER BY id DESC LIMIT 10"
        ).fetchall()
    return jsonify({"alerts": [
        {"id": r["id"], "title": r["title"], "message": r["message"],
         "severity": r["severity"], "target_city": r["target_city"],
         "created_at": r["created_at"]} for r in rows
    ]}), 200


# ====================================================================
# Geofenced emergency broadcast delivery (client: geofence_siren.js)
# ====================================================================

_GEO_CITY_ZONE_KM = 100.0  # "in the affected city" = within 100 km of its center


def _haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in km between two points (same as disaster.py)."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return r * 2 * math.asin(min(1.0, math.sqrt(a)))


def _city_lookup():
    """slug/first-word -> CITIES meta, tolerant of 'Karachi' vs 'Karachi, Sindh'."""
    from app import CITIES

    lookup = {}
    for key, meta in CITIES.items():
        lookup["".join(ch for ch in key.lower() if ch.isalnum())] = meta
        first = meta.get("name", "").split(",")[0].strip().lower()
        if first:
            lookup["".join(ch for ch in first if ch.isalnum())] = meta
    return lookup


@admin_ext_bp.route("/api/user/broadcasts/active", methods=["POST"])
def geofenced_active_broadcasts():
    """POST /api/user/broadcasts/active  body: {"latitude": .., "longitude": ..}

    Returns the active emergency broadcasts that affect the given point:
      1. SQLite `broadcast_alerts` — global ('All') rows always, plus rows
         targeting a known city when the point is within
         _GEO_CITY_ZONE_KM of that city's center.
      2. MongoDB `active_broadcasts` — polygons created via
         POST /api/admin/broadcast/geofence that contain the point
         ($geoIntersects). Skipped silently when Mongo is down.

    Public + read-only (SQLite is only SELECTed); response shape matches
    static/js/geofence_siren.js: {status, count, alerts:[{id, title, ...}]}.
    """
    data = request.get_json(silent=True) or {}
    try:
        lat = float(data.get("latitude"))
        lon = float(data.get("longitude"))
    except (TypeError, ValueError):
        return jsonify({"status": "error",
                        "error": "latitude and longitude are required numbers"}), 400
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        return jsonify({"status": "error", "error": "coordinates out of range"}), 400

    try:
        cities = _city_lookup()
    except Exception:
        cities = {}

    alerts = []
    with database._connect() as conn:
        rows = conn.execute(
            "SELECT id, title, message, severity, target_city, created_at "
            "FROM broadcast_alerts WHERE is_active = 1 ORDER BY id DESC LIMIT 25"
        ).fetchall()

    for r in rows:
        target = (r["target_city"] or "All").strip()
        entry = {
            "id": r["id"], "title": r["title"], "message": r["message"],
            "severity": r["severity"], "target_city": target,
            "created_at": r["created_at"], "source": "global",
        }
        if target.lower() not in ("", "all", "all cities"):
            key = "".join(ch for ch in target.lower() if ch.isalnum())
            meta = cities.get(key)
            if meta is None:
                # Unknown target string: over-notify rather than silently
                # drop an admin-issued emergency from the client's feed.
                entry["source"] = "city-zone"
                alerts.append(entry)
                continue
            dist = _haversine_km(lat, lon, meta["lat"], meta["lon"])
            if dist > _GEO_CITY_ZONE_KM:
                continue
            entry["source"] = "city-zone"
            entry["distance_km"] = round(dist, 1)
        alerts.append(entry)

    # GeoJSON polygon broadcasts (Mongo, optional)
    try:
        from app import _mongo_db  # only bound when Mongo connected at boot

        col = _mongo_db["active_broadcasts"]
        try:
            col.create_index([("geofence", "2dsphere")])
        except Exception:
            pass
        point = {"type": "Point", "coordinates": [lon, lat]}
        cursor = col.find(
            {"geofence": {"$geoIntersects": {"$geometry": point}},
             "is_active": True}
        ).limit(10)
        for doc in cursor:
            alerts.append({
                "id": str(doc.get("_id")),
                "title": doc.get("title") or "Emergency broadcast",
                "message": doc.get("message") or "",
                "severity": (doc.get("severity") or "WARNING").upper(),
                "target_city": "Geofenced zone",
                "created_at": str(doc.get("created_at") or ""),
                "source": "geofence-polygon",
            })
    except Exception:
        pass  # Mongo optional — city-zone + global alerts already collected

    return jsonify({"status": "success", "count": len(alerts),
                    "alerts": alerts[:15]}), 200


# ====================================================================
# API key tier / rate-limiter manager
# ====================================================================

@admin_ext_bp.route("/api/admin/api-keys", methods=["GET", "PATCH"])
def manage_api_keys():
    if request.method == "GET":
        with database._connect() as conn:
            rows = conn.execute(
                "SELECT k.id, k.user_id, u.email, u.name AS owner_name, k.name, "
                "k.key_prefix, k.tier, k.rate_limit_rpm, k.is_active, "
                "k.created_at, k.last_used_at "
                "FROM api_keys k LEFT JOIN users u ON u.id = k.user_id ORDER BY k.id DESC"
            ).fetchall()
        keys = [
            {
                "id": r["id"], "user_id": r["user_id"], "email": r["email"],
                "owner_name": r["owner_name"], "name": r["name"],
                # Never ship key_hash to the browser — only the short display
                # prefix kept at creation time is safe to expose.
                "masked_key": (r["key_prefix"] or "") + "…" if r["key_prefix"] else "—",
                "tier": r["tier"], "rate_limit_rpm": r["rate_limit_rpm"],
                "is_active": bool(r["is_active"]), "created_at": r["created_at"],
                "last_used_at": r["last_used_at"],
            }
            for r in rows
        ]
        return jsonify({"status": "success", "keys": keys, "tiers": list(_TIER_LIMITS.keys())}), 200

    # PATCH — update tier / active status
    data = request.get_json() or {}
    key_id = data.get("id")
    if not key_id:
        return jsonify({"status": "error", "message": "Missing key id"}), 400

    updates = {}
    tier = data.get("tier")
    if tier in _TIER_LIMITS:
        updates["tier"] = tier
        updates["rate_limit_rpm"] = _TIER_LIMITS[tier]
    if "is_active" in data:
        updates["is_active"] = 1 if data["is_active"] else 0

    if not updates:
        return jsonify({"status": "error", "message": "Nothing to update"}), 400

    set_clause = ", ".join("%s = ?" % k for k in updates)
    vals = list(updates.values()) + [int(key_id)]
    with database._connect() as conn:
        conn.execute("UPDATE api_keys SET %s WHERE id = ?" % set_clause, vals)
        conn.commit()
    return jsonify({"status": "success", "message": "Key updated", "updated": updates}), 200


# ====================================================================
# Command-center page
# ====================================================================

@admin_ext_bp.route("/command-center")
def command_center():
    return render_template("admin/command-center.html", active="command-center")
