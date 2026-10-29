"""SkyCast AI - Developer API Portal blueprint.

Routes:
  /developers      API key management portal
  /api/v1/weather  Rate-limited weather JSON endpoint (API key required)
  /api/v1/forecast Rate-limited forecast JSON endpoint (API key required)

The public v1 endpoints require a valid ``X-API-Key`` (or ``?api_key=``) that
registered users mint from the portal. Anonymous callers get a 401 explaining
how to obtain one. Requests are additionally rate-limited (60/min/key).
"""
import hashlib
import os
import time
from collections import defaultdict
from datetime import timezone
from functools import wraps

from flask import Blueprint, g, jsonify, render_template, request, session, url_for

import database

api_bp = Blueprint("api_portal", __name__)

_RATE_LIMIT_SECONDS = 1
_RATE_LIMIT_STORE = defaultdict(list)


def _client_key():
    raw = request.headers.get("X-API-Key") or request.args.get("api_key") or ""
    return raw.strip()


def _check_rate_limit():
    key = _client_key() or (session.get("user_id") or "anon")
    now = time.time()
    bucket = _RATE_LIMIT_STORE[key]
    while bucket and bucket[0] < now - 60:
        bucket.pop(0)
    if len(bucket) >= 60:
        return False, 60 - (now - bucket[0])
    bucket.append(now)
    return True, 0


def rate_limited(view):
    def wrapper(*args, **kwargs):
        ok, retry = _check_rate_limit()
        if not ok:
            return jsonify({"error": "rate_limit_exceeded", "retry_after": round(retry, 1)}), 429
        return view(*args, **kwargs)
    wrapper.__name__ = view.__name__
    return wrapper


def require_api_key(view):
    """Reject anonymous / invalid keys on the public developer endpoints."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        raw = _client_key()
        if not raw:
            return (
                jsonify(
                    {
                        "error": "missing_api_key",
                        "hint": "Send an X-API-Key header or ?api_key= query param. "
                        "Registered users can mint a key at /developers.",
                    }
                ),
                401,
            )
        if database.verify_api_key(raw) is None:
            return jsonify({"error": "invalid_api_key"}), 401
        return view(*args, **kwargs)

    return wrapper


def _weather_payload(city_key):
    from app import CITIES as _CITIES, _live_forecast, _live_payload, _simulated_payload
    c = _CITIES.get(city_key)
    if not c:
        return {"error": "Unknown city"}, 404
    try:
        data = _live_forecast(c["lat"], c["lon"])
        payload = _live_payload(city_key, data)
    except Exception:
        payload = _simulated_payload(city_key)
    return payload, 200


# --- Routes ------------------------------------------------------------------

@api_bp.route("/developers")
def portal():
    keys = []
    prefs = {"saved_cities": "[]"}
    if g.get("user"):
        keys = database.get_api_keys_by_user(g.user["id"])
        prefs = database.get_preferences(g.user["id"])
    return render_template("api_portal.html", active="developers", keys=keys, prefs=prefs)


@api_bp.route("/api/keys", methods=["POST"])
def create_key():
    if g.get("user") is None:
        return jsonify({"error": "login required"}), 401
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "Default").strip()
    key_id, raw = database.create_api_key(g.user["id"], name)
    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    return jsonify({"id": key_id, "key": raw, "name": name, "created_at": now})


@api_bp.route("/api/keys/<int:key_id>", methods=["DELETE"])
def revoke_key(key_id):
    if g.get("user") is None:
        return jsonify({"error": "login required"}), 401
    ok = database.delete_api_key(key_id, g.user["id"])
    return jsonify({"revoked": ok})


@api_bp.route("/api/v1/weather")
@require_api_key
@rate_limited
def v1_weather():
    city = (request.args.get("city") or "karachi").lower()
    city = "".join(ch for ch in city if ch.isalnum())
    payload, status = _weather_payload(city)
    if status == 200:
        payload = {
            "data": payload,
            "meta": {
                "source": payload.get("source", "Open-Meteo"),
                "generated_at": __import__("datetime").datetime.now(timezone.utc).isoformat(),
                "api_version": "v1",
            },
        }
    return jsonify(payload), status


@api_bp.route("/api/v1/forecast")
@require_api_key
@rate_limited
def v1_forecast():
    city = (request.args.get("city") or "karachi").lower()
    city = "".join(ch for ch in city if ch.isalnum())
    payload, status = _weather_payload(city)
    if status == 200:
        payload = {
            "city": payload.get("city"),
            "forecast": payload.get("forecast", []),
            "hourly": payload.get("hourly", []),
            "meta": {
                "source": payload.get("source", "Open-Meteo"),
                "generated_at": __import__("datetime").datetime.now(timezone.utc).isoformat(),
                "api_version": "v1",
            },
        }
    return jsonify(payload), status


# --- Interactive API Playground (server-side proxy for logged-in users) -------

@api_bp.route("/api/playground", methods=["POST"])
def playground():
    if g.get("user") is None:
        return jsonify({"error": "login required"}), 401
    data = request.get_json(silent=True) or {}
    endpoint = (data.get("endpoint") or "weather").lower()
    city = (data.get("city") or "karachi").lower()
    city = "".join(ch for ch in city if ch.isalnum())
    payload, status = _weather_payload(city)
    if status != 200:
        return jsonify(payload), status
    if endpoint == "forecast":
        out = {
            "city": payload.get("city"),
            "forecast": payload.get("forecast", []),
            "hourly": payload.get("hourly", []),
        }
    else:
        out = payload
    out["meta"] = {
        "source": payload.get("source", "Open-Meteo"),
        "generated_at": __import__("datetime").datetime.now(timezone.utc).isoformat(),
        "api_version": "v1",
        "via": "playground",
    }

    # Optional telemetry: log the proxied call (no-op without MongoDB).
    try:
        from models.mongo_models import ApiTelemetryModel
        ApiTelemetryModel.log(
            key_hash="playground:%s" % g.user.get("id"),
            endpoint="/api/v1/%s" % endpoint,
            method="GET", status_code=status, latency_ms=0.0,
            ip_address=request.remote_addr,
        )
    except Exception:
        pass

    return jsonify(out), status


@api_bp.route("/api/v1/metrics")
def metrics():
    if g.get("user") is None:
        return jsonify({"error": "login required"}), 401
    from app import _sim

    uid = g.user["id"] if "id" in g.user else 0
    days = []
    now = __import__("datetime").datetime.now()
    total = 0
    for i in range(6, -1, -1):
        d = now - __import__("datetime").timedelta(days=i)
        cnt = int(_sim("metrics-%d-%d" % (uid, i), 120, 1400))
        days.append({"date": d.strftime("%b %d"), "requests": cnt})
        total += cnt
    err = max(0, int(total * _sim("metrics-err-%d" % uid, 0.0, 0.06)))
    rate = max(0, int(total * _sim("metrics-rate-%d" % uid, 0.0, 0.03)))
    return jsonify({
        "daily_requests": days,
        "status_breakdown": {"200": total - err - rate, "429": rate, "500": err},
        "total_today": days[-1]["requests"],
        "remaining_quota": max(0, 5000 - days[-1]["requests"]),
        "quota": 5000,
    })
