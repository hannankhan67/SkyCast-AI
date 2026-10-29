"""SkyCast AI - Flask application.

Combines a breathing-sky glassmorphism dashboard with live weather data
(Open-Meteo, keyless) and a Hadoop/HDFS-themed "Climate Analytics Engine"
showcase. If the network is unavailable, a deterministic simulator keeps the
demo alive so the UI never looks broken during a live presentation.
"""

import json
import math
import os
import socket
import time
import zlib
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from flask import Flask, g, jsonify, redirect, render_template, request, send_from_directory, session, url_for

import database
from routes.analytics import analytics_bp
from routes.predictions import predictions_bp
from routes.safety import safety_bp
from routes.smart_features import smart_bp
from routes.admin import admin_bp
from routes.admin_features import admin_ext_bp
from routes.alerts import alerts_bp
from routes.api_portal import api_bp as api_portal_bp
from routes.assistant import assistant_bp
from routes.auth import (
    PREMIUM_PAGE_GROUPS,
    PREMIUM_PAGE_PREFIXES,
    auth_bp,
    premium_required,
)
from routes.disaster import disaster_bp
from routes.insights import insights_bp
from routes.pages import pages_bp
from routes.specialized import specialized_bp
from routes.support import support_bp
from routes.analyst_tools import analyst_bp
from routes.admin_broadcast import admin_broadcast_bp
from routes.telemetry_sse import sse_bp
from routes.analyst_drift import analyst_drift_bp
from routes.data_engineering import data_eng_bp
from routes.billing import billing_bp
from routes.notifications import notifications_bp

# --- Path-robust setup -----------------------------------------------------
# Resolves templates/static relative to THIS file (not the current working
# directory), so `python app.py` works no matter where the terminal is open.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)


@app.route("/favicon.ico")
def favicon():
    return send_from_directory(
        os.path.join(app.static_folder, "icons"),
        "logo.svg",
        mimetype="image/svg+xml",
    )

# --- Session / auth setup ----------------------------------------------------
# The secret key is generated once and persisted to .secret_key so login
# sessions survive server restarts. Override with SKYCAST_SECRET_KEY env var.
_SECRET_FILE = os.path.join(BASE_DIR, ".secret_key")


def _load_secret_key():
    env_key = os.environ.get("SKYCAST_SECRET_KEY")
    if env_key:
        return env_key
    try:
        with open(_SECRET_FILE, "r", encoding="utf-8") as f:
            key = f.read().strip()
            if key:
                return key
    except OSError:
        pass
    import secrets as _secrets

    key = _secrets.token_hex(32)
    with open(_SECRET_FILE, "w", encoding="utf-8") as f:
        f.write(key)
    return key


app.secret_key = _load_secret_key()
app.permanent_session_lifetime = timedelta(days=30)
app.config["VAPID_PUBLIC_KEY"] = os.environ.get("VAPID_PUBLIC_KEY", "")

# ====================================================================
# MongoDB connection (optional — app works fine without it)
# ====================================================================
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/")
DB_NAME = os.environ.get("MONGO_DB_NAME", "skycast_db")
telemetry_col = None
try:
    from pymongo import MongoClient

    _mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=1500)
    _mongo_client.admin.command("ping")
    _mongo_db = _mongo_client[DB_NAME]
    telemetry_col = _mongo_db["api_key_telemetry"]
    print("  [MONGO] Connected to MongoDB:", DB_NAME)
except Exception:
    _mongo_client = None


@app.before_request
def _load_logged_in_user():
    """Attach the logged-in user (or None) to flask.g for every request."""
    uid = session.get("user_id")
    g.user = database.get_user_by_id(uid) if uid else None
    g.request_started = time.time()


@app.after_request
def _security_headers(response):
    """Add security headers to every response."""
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.after_request
def _log_api_request(response):
    """Persist one telemetry row per /api/* request (drives the admin console).

    Never let telemetry break a response: any failure is swallowed.
    """
    try:
        path = request.path
        if path.startswith("/api/"):
            city = request.args.get("city")
            live = None
            if path.endswith("/api/weather") and response.mimetype == "application/json":
                try:
                    live = 1 if json.loads(response.get_data(cache=True)).get("live") else 0
                except Exception:
                    live = None
            started = g.get("request_started") or time.time()
            duration_ms = round((time.time() - started) * 1000, 1)
            database.log_api_request(
                request.method, path, city, response.status_code, live, duration_ms
            )
            # Optional MongoDB mirror: API-key telemetry for the admin console.
            if telemetry_col is not None:
                import hashlib as _hashlib

                api_key = request.headers.get("X-API-Key") or request.args.get("api_key")
                key_hash = _hashlib.sha256(api_key.encode()).hexdigest() if api_key else "anonymous"
                telemetry_col.insert_one({
                    "api_key_hash": key_hash,
                    "endpoint": path,
                    "city": city,
                    "http_method": request.method,
                    "status_code": response.status_code,
                    "latency_ms": duration_ms,
                    "ip_address": request.remote_addr,
                    "user_agent": request.headers.get("User-Agent", ""),
                    "timestamp": datetime.utcnow(),
                })
            # Opportunistic pruning (≈2% of requests) keeps the table small.
            import random as _random

            if _random.random() < 0.02:
                database.prune_api_requests(days=7)
    except Exception:
        pass
    return response


@app.context_processor
def _inject_current_user():
    """Expose the current user and normalized subscription state to templates."""
    user = g.get("user")
    user_plan = (user.get("subscription") if user else "free") or "free"
    user_plan = user_plan.lower()
    return {
        "current_user": user,
        "is_authenticated": user is not None,
        "user_plan": user_plan,
        "is_premium": database.is_premium_plan(user_plan),
        # Premium gating config — shared with the nav partial and the
        # client-side eviction helper so there is one source of truth.
        "premium_page_groups": PREMIUM_PAGE_GROUPS,
        "premium_page_prefixes": PREMIUM_PAGE_PREFIXES,
        "membership_cancelled": bool(session.get("membership_cancelled")),
    }


def _is_premium(user):
    """True when the user has an active Premium subscription."""
    if not user:
        return False
    return database.is_premium_plan(user.get("subscription"))


app.register_blueprint(safety_bp)
app.register_blueprint(smart_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(admin_ext_bp)
app.register_blueprint(analytics_bp)
app.register_blueprint(predictions_bp)
app.register_blueprint(api_portal_bp)
app.register_blueprint(alerts_bp)
app.register_blueprint(assistant_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(disaster_bp)
app.register_blueprint(insights_bp)
app.register_blueprint(pages_bp)
app.register_blueprint(specialized_bp)

app.register_blueprint(support_bp)
app.register_blueprint(analyst_bp)
app.register_blueprint(admin_broadcast_bp)
app.register_blueprint(sse_bp)
app.register_blueprint(analyst_drift_bp)
app.register_blueprint(data_eng_bp)
app.register_blueprint(billing_bp)
app.register_blueprint(notifications_bp)

# --- URL Aliases (friendly paths) ---
@app.route("/live")
def alias_live():
    return redirect(url_for("pages.weather"))

@app.route("/radar")
def alias_radar():
    return redirect(url_for("pages.maps"))

@app.route("/shelter-finder")
def alias_shelter():
    return redirect(url_for("disaster.disaster_page"))

@app.route("/solar")
def alias_solar():
    return redirect(url_for("specialized.solar"))

@app.route("/agriculture")
def alias_agriculture():
    return redirect(url_for("specialized.agriculture"))

@app.route("/health")
def alias_health():
    return redirect(url_for("pages.health_page"))

@app.route("/planner")
def alias_planner():
    return redirect(url_for("pages.planner_page"))

@app.route("/historical")
def alias_historical():
    return redirect(url_for("specialized.historical", endpoint="historical"))

@app.route("/assistant")
def alias_assistant():
    return redirect(url_for("assistant.assistant_page"))

@app.route("/alerts")
def alias_alerts():
    return redirect(url_for("alerts.alerts_page"))

CITIES = {
    # key: {name, country, lat, lon}
    "karachi": {"name": "Karachi, Sindh", "country": "Pakistan", "lat": 24.8607, "lon": 67.0011},
    "lahore": {"name": "Lahore, Punjab", "country": "Pakistan", "lat": 31.5204, "lon": 74.3587},
    "islamabad": {"name": "Islamabad", "country": "Pakistan", "lat": 33.6844, "lon": 73.0479},
    "peshawar": {"name": "Peshawar", "country": "Pakistan", "lat": 34.0151, "lon": 71.5249},
    "quetta": {"name": "Quetta", "country": "Pakistan", "lat": 30.1798, "lon": 66.9750},
    "multan": {"name": "Multan", "country": "Pakistan", "lat": 30.1575, "lon": 71.5249},
    "dubai": {"name": "Dubai", "country": "United Arab Emirates", "lat": 25.2048, "lon": 55.2708},
    "london": {"name": "London", "country": "United Kingdom", "lat": 51.5074, "lon": -0.1278},
    "istanbul": {"name": "Istanbul", "country": "Turkey", "lat": 41.0082, "lon": 28.9784},
    "cairo": {"name": "Cairo", "country": "Egypt", "lat": 30.0444, "lon": 31.2357},
    "paris": {"name": "Paris", "country": "France", "lat": 48.8566, "lon": 2.3522},
    "berlin": {"name": "Berlin", "country": "Germany", "lat": 52.5200, "lon": 13.4050},
    "madrid": {"name": "Madrid", "country": "Spain", "lat": 40.4168, "lon": -3.7038},
    "rome": {"name": "Rome", "country": "Italy", "lat": 41.9028, "lon": 12.4964},
    "tokyo": {"name": "Tokyo", "country": "Japan", "lat": 35.6762, "lon": 139.6503},
    "beijing": {"name": "Beijing", "country": "China", "lat": 39.9042, "lon": 116.4074},
    "singapore": {"name": "Singapore", "country": "Singapore", "lat": 1.3521, "lon": 103.8198},
    "sydney": {"name": "Sydney", "country": "Australia", "lat": -33.8688, "lon": 151.2093},
    "toronto": {"name": "Toronto", "country": "Canada", "lat": 43.6532, "lon": -79.3832},
    "newyork": {"name": "New York City", "country": "United States", "lat": 40.7128, "lon": -74.0060},
    "losangeles": {"name": "Los Angeles", "country": "United States", "lat": 34.0522, "lon": -118.2437},
    "chicago": {"name": "Chicago", "country": "United States", "lat": 41.8781, "lon": -87.6298},
    "mumbai": {"name": "Mumbai", "country": "India", "lat": 19.0760, "lon": 72.8777},
    "newdelhi": {"name": "New Delhi", "country": "India", "lat": 28.6139, "lon": 77.2090},
    "dhaka": {"name": "Dhaka", "country": "Bangladesh", "lat": 23.8103, "lon": 90.4125},
}

# WMO weather interpretation codes -> (label, icon name)
WMO = {
    0: ("Clear Sky", "sun"),
    1: ("Mostly Clear", "sun"),
    2: ("Partly Cloudy", "cloud"),
    3: ("Overcast", "cloud"),
    45: ("Foggy", "fog"),
    48: ("Icy Fog", "fog"),
    51: ("Light Drizzle", "rain"),
    53: ("Drizzle", "rain"),
    55: ("Heavy Drizzle", "rain"),
    61: ("Light Rain", "rain"),
    63: ("Rain", "rain"),
    65: ("Heavy Rain", "rain"),
    66: ("Freezing Rain", "rain"),
    67: ("Freezing Rain", "rain"),
    71: ("Light Snow", "snow"),
    73: ("Snow", "snow"),
    75: ("Heavy Snow", "snow"),
    77: ("Snow Grains", "snow"),
    80: ("Rain Showers", "rain"),
    81: ("Rain Showers", "rain"),
    82: ("Violent Showers", "storm"),
    85: ("Snow Showers", "snow"),
    86: ("Snow Showers", "snow"),
    95: ("Thunderstorm", "storm"),
    96: ("Thunderstorm", "storm"),
    99: ("Thunderstorm", "storm"),
}

# Seasonal baselines for the offline simulator: (day ceiling, night floor)
BASE = {
    "karachi": (32, 26),
    "lahore": (36, 27),
    "islamabad": (29, 19),
    "peshawar": (33, 22),
    "quetta": (31, 16),
    "multan": (38, 24),
    "dubai": (41, 31),
    "london": (18, 12),
    "istanbul": (26, 14),
    "cairo": (34, 20),
    "paris": (22, 11),
    "berlin": (23, 10),
    "madrid": (31, 14),
    "rome": (28, 13),
    "tokyo": (29, 18),
    "beijing": (30, 14),
    "singapore": (31, 26),
    "sydney": (26, 12),
    "toronto": (26, 13),
    "newyork": (27, 20),
    "losangeles": (30, 16),
    "chicago": (28, 13),
    "mumbai": (33, 24),
    "newdelhi": (35, 20),
    "dhaka": (32, 23),
}


def condition(code):
    return WMO.get(code, ("Clear Sky", "sun"))


def _sim(seed, lo, hi):
    """Deterministic pseudo-random float in [lo, hi] from a string seed."""
    h = zlib.crc32(seed.encode("utf-8"))
    return lo + (h % 100000) / 100000.0 * (hi - lo)


def _fmt_time(hhmm):
    """'05:42' -> '5:42 AM'"""
    try:
        h, m = (int(x) for x in hhmm.split(":"))
    except (ValueError, AttributeError):
        return hhmm
    meridiem = "AM" if h < 12 else "PM"
    h = h % 12 or 12
    return f"{h}:{m:02d} {meridiem}"


def _live_forecast(lat, lon):
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": (
            "temperature_2m,relative_humidity_2m,apparent_temperature,"
            "weather_code,wind_speed_10m,pressure_msl,uv_index"
        ),
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,sunrise,sunset",
        "hourly": (
            "temperature_2m,relative_humidity_2m,"
            "precipitation_probability,weather_code"
        ),
        "timezone": "auto",
        "forecast_days": "7",
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=8) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _build_forecast(icon_pattern, temp, lo_base, hi_wobble, days=7):
    """Shared forecast builder (used by live + simulated branches)."""
    out = []
    today = datetime.now()
    for i in range(days):
        code_idx, icon = icon_pattern[i % len(icon_pattern)]
        label, _ = condition(code_idx)
        hi = round(temp + _sim("hi%d" % i, -1, hi_wobble))
        lo = round(min(lo_base + _sim("lo%d" % i, -2, 2), hi - 2))
        out.append(
            {
                "day": (today + timedelta(days=i)).strftime("%a"),
                "max": hi,
                "min": lo,
                "condition": label,
                "icon": "/static/icons/%s.svg" % icon,
            }
        )
    return out


def _simulated_payload(city_key):
    """Deterministic, hour-stable fallback when the network is unavailable."""
    name = CITIES[city_key]["name"]
    hi, lo = BASE[city_key]
    now = datetime.now()
    seed = "%s:%d-%d-%d-%d" % (city_key, now.year, now.month, now.day, now.hour)

    temp = round(hi + _sim(seed + "-t", -3, 2))
    humidity = round(_sim(seed + "-h", 35, 80))
    wind = round(_sim(seed + "-w", 5, 22))
    uv = round(_sim(seed + "-u", 3, 10))
    pressure = round(_sim(seed + "-p", 1002, 1018))
    visibility = round(_sim(seed + "-v", 6, 16), 1)
    aqi = round(_sim(seed + "-a", 40, 160))

    cond_label, icon = ("Clear Sky", "sun")
    if aqi > 120:
        cond_label, icon = ("Hazy", "fog")

    sunrise_h = int(_sim(seed + "-sr", 5, 6))
    sunrise = _fmt_time("%02d:%02d" % (sunrise_h, int(_sim(seed + "-sr2", 0, 59))))
    sunset = _fmt_time("%02d:%02d" % (sunrise_h + 12, int(_sim(seed + "-ss", 0, 59))))

    pattern = [(0, "sun"), (2, "cloud"), (3, "cloud"), (61, "rain"),
               (2, "cloud"), (0, "sun"), (2, "cloud")]

    return {
        "city": name,
        "live": False,
        "source": "Simulated · offline fallback",
        "temp": temp,
        "feels_like": round(temp + _sim(seed + "-f", -1, 3)),
        "condition": cond_label,
        "icon": "/static/icons/%s.svg" % icon,
        "humidity": humidity,
        "wind": wind,
        "uv": uv,
        "pressure": pressure,
        "visibility": visibility,
        "aqi": aqi,
        "sunrise": sunrise,
        "sunset": sunset,
        "updated": now.strftime("%H:%M"),
        "hourly": _simulated_hourly(city_key, temp),
        "forecast": _build_forecast(pattern, temp, lo, 4),
    }


def _hourly_payload(raw, utc_offset=0, max_items=24):
    """Compact hourly list from Open-Meteo 'hourly' block.

    Open-Meteo returns hourly timestamps for the whole current day starting at
    00:00, so we slice *from the current hour forward* instead of taking the
    first 24 entries (which would include that day's already-past hours).
    `utc_offset` (seconds) is the location's offset returned by `timezone=auto`,
    used to convert the naive location-local timestamps into a comparable epoch.
    """
    out = []
    if not raw:
        return out
    times = raw.get("time") or []
    temps = raw.get("temperature_2m") or []
    codes = raw.get("weather_code") or []
    preci = raw.get("precipitation_probability") or []

    # Start of the current hour as a UTC instant - this is the same hour
    # boundary in every timezone, so it works for any city offset.
    now_utc = time.time()
    hour_start = now_utc - now_utc % 3600

    for i in range(len(times)):
        if len(out) >= max_items:
            break
        ts = times[i]
        try:
            # `ts` is naive location-local time (e.g. "2026-09-05T22:00").
            dt = datetime.strptime(ts[:16], "%Y-%m-%dT%H:%M")
        except (ValueError, TypeError):
            continue
        epoch = dt.replace(tzinfo=timezone.utc).timestamp() - utc_offset
        if epoch < hour_start:
            continue  # past hour - skip
        code = codes[i] if i < len(codes) else 0
        label, icon = condition(code)
        out.append(
            {
                "time": _fmt_time(ts[11:16]),
                "temp": round(temps[i]) if i < len(temps) else 0,
                "precip": preci[i] if i < len(preci) and preci[i] is not None else 0,
                "label": label,
                "icon": "/static/icons/%s.svg" % icon,
            }
        )
    return out


def _simulated_hourly(city_key, temp):
    """Deterministic 24-entry hourly list with a daily diurnal curve."""
    now = datetime.now()
    out = []
    for i in range(24):
        hour = (now.hour + i) % 24
        diurnal = 4 * math.cos((hour - 14) * math.pi / 12)  # peak ~2 PM
        t = round(temp + diurnal + _sim("%s-h%d" % (city_key, i), -1, 1))
        code_idx = 2 if i % 8 == 0 else (61 if i % 5 == 3 else 0)
        label, icon = condition(code_idx)
        out.append(
            {
                "time": _fmt_time("%02d:00" % hour),
                "temp": t,
                "precip": round(_sim("%s-p%d" % (city_key, i), 5, 70)),
                "label": label,
                "icon": "/static/icons/%s.svg" % icon,
            }
        )
    return out


def _live_payload(city_key, data):
    name = CITIES[city_key]["name"]
    now = datetime.now()
    cur = data["current"]
    temp = round(cur["temperature_2m"])
    cond_label, icon = condition(cur["weather_code"])

    wc = data["daily"]["weather_code"]
    daily_lo = data["daily"]["temperature_2m_min"]

    return {
        "city": name,
        "live": True,
        "source": "Open-Meteo · live",
        "temp": temp,
        "feels_like": round(cur["apparent_temperature"]),
        "condition": cond_label,
        "icon": "/static/icons/%s.svg" % icon,
        "humidity": cur["relative_humidity_2m"],
        "wind": round(cur["wind_speed_10m"]),
        "uv": round(cur["uv_index"]),
        "pressure": round(cur["pressure_msl"]),
        "visibility": round(_sim(name + "-vis", 8, 15), 1),
        "aqi": round(_sim(name + "-aqi", 40, 160)),
        "sunrise": _fmt_time(data["daily"]["sunrise"][0][11:16]),
        "sunset": _fmt_time(data["daily"]["sunset"][0][11:16]),
        "updated": now.strftime("%H:%M"),
        "hourly": _hourly_payload(
            data.get("hourly") or {},
            utc_offset=data.get("utc_offset_seconds") or 0,
        ),
        "forecast": _build_forecast(
            [(wc[i], WMO.get(wc[i], ("Clear", "sun"))[1]) for i in range(7)],
            temp,
            min(daily_lo),
            4,
        ),
    }


def _pick_port(preferred):
    """Return the first available *browser-safe* TCP port.

    Chrome / Firefox refuse to load several ports with ERR_UNSAFE_PORT
    (notably the SIP ports 5060/5061), so we never fall back to those.
    """
    candidates = [preferred, 8080, 8000, 3000, 5001, 5050, 8060, 8099]
    seen = set()
    for port in candidates:
        if port in seen:
            continue
        seen.add(port)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return 8099


@app.route("/")
def index():
    return render_template("index.html", active="home")


@app.route("/api/user/broadcasts/active", methods=["POST"])
def api_user_broadcasts_active():
    """Geofenced emergency broadcasts for the siren listener (public).

    Alias of routes/admin_features.py geofenced_active_broadcasts — that
    blueprint is mounted under the /admin prefix, so the clean user-facing
    path is re-exposed here for static/js/geofence_siren.js.
    """
    from routes.admin_features import geofenced_active_broadcasts

    return geofenced_active_broadcasts()


@app.route("/api/alerts/active", methods=["GET"])
def public_active_alerts():
    """Active broadcast alerts for the severe-weather toast stack (public)."""
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


@app.route("/api/weather")
def api_weather():
    key = (request.args.get("city", "karachi") or "karachi").lower()
    key = "".join(ch for ch in key if ch.isalnum())
    if key not in CITIES:
        return jsonify({"error": "Unknown city", "cities": sorted(CITIES)}), 404

    c = CITIES[key]
    try:
        data = _live_forecast(c["lat"], c["lon"])
        payload = _live_payload(key, data)
    except Exception:
        payload = _simulated_payload(key)
    return jsonify(payload)


@app.route("/api/analytics")
def api_analytics():
    """Mock HDFS cluster status consumed by the terminal's live tail."""
    return jsonify(
        {
            "status": "healthy",
            "datanodes": 12,
            "cluster_used_tb": 1.13,
            "cluster_capacity_tb": 1.4,
            "replication_factor": 3,
            "blocks_stored": 241605,
            "mapreduce_jobs_run": 1482,
            "last_job": "job_20260829_0017",
            "last_job_progress": 100,
        }
    )


@app.route("/api/admin/telemetry-stats", methods=["GET"])
def api_admin_telemetry_stats():
    """MongoDB aggregation pipeline: total requests, avg/max latency, status breakdown."""
    if not session.get("is_admin"):
        return jsonify({"error": "admin required"}), 401
    if telemetry_col is None:
        return jsonify({"error": "MongoDB telemetry is not configured"}), 503
    try:
        pipeline = [
            {
                "$group": {
                    "_id": None,
                    "total_requests": {"$sum": 1},
                    "avg_latency_ms": {"$avg": "$latency_ms"},
                    "max_latency_ms": {"$max": "$latency_ms"},
                    "status_200": {"$sum": {"$cond": [{"$eq": ["$status_code", 200]}, 1, 0]}},
                    "status_429_rate_limited": {"$sum": {"$cond": [{"$eq": ["$status_code", 429]}, 1, 0]}},
                    "status_500_errors": {"$sum": {"$cond": [{"$gte": ["$status_code", 500]}, 1, 0]}},
                }
            }
        ]
        result = list(telemetry_col.aggregate(pipeline))
        if result:
            stats = result[0]
            stats.pop("_id", None)
            stats["avg_latency_ms"] = round(stats["avg_latency_ms"], 2)
        else:
            stats = {
                "total_requests": 0, "avg_latency_ms": 0, "max_latency_ms": 0,
                "status_200": 0, "status_429_rate_limited": 0, "status_500_errors": 0,
            }
        return jsonify({"status": "success", "telemetry": stats}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/telemetry/live-data", methods=["GET"])
def api_live_telemetry():
    """5-second polling endpoint: lightweight SQLite telemetry for the analyst dashboard."""
    # Access control: only analyst or admin may poll live telemetry data.
    user = g.get("user")
    role = user.get("role", "user") if user else "user"
    if role not in ("analyst", "admin"):
        return jsonify({"error": "Unauthorized"}), 403

    # Reuse the existing SQLite aggregation (returns synthetic fallback when
    # the DB has no data, so the endpoint always returns a valid payload).
    telemetry = database.analyst_dashboard_telemetry(hours=24)
    if telemetry is None:
        telemetry = {
            "total_requests": 0,
            "avg_latency": 0.0,
            "active_keys": 0,
            "success_rate": 0.0,
            "chart_labels": [],
            "chart_requests": [],
            "chart_latencies": [],
            "is_simulated": True,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    return jsonify(telemetry)


@app.route("/api/telemetry/toggle", methods=["POST"])
def api_toggle_telemetry_mode():
    """Alt + M: flip the analyst telemetry feed between live and simulated.

    Stores the preference in the session so the choice survives page reloads
    (the dashboard JS reloads after a successful toggle). Analyst/admin only.
    """
    user = g.get("user")
    role = user.get("role", "user") if user else "user"
    if role not in ("analyst", "admin"):
        return jsonify({"error": "Unauthorized"}), 403

    current = session.get("telemetry_mode", "auto")
    session["telemetry_mode"] = "simulated" if current != "simulated" else "auto"
    return jsonify({"status": "ok", "mode": session["telemetry_mode"]})


# ---------------------------------------------------------------------------
# Analyst expansion APIs (analyst/admin only — 403 otherwise)
# ---------------------------------------------------------------------------

def _analyst_guard():
    """Returns the analyst/admin user dict, or None (caller sends 403)."""
    user = g.get("user")
    if user and user.get("role") in ("analyst", "admin"):
        return user
    return None


@app.route("/api/telemetry/annotations", methods=["GET"])
def api_annotations_list():
    if not _analyst_guard():
        return jsonify({"error": "Unauthorized"}), 403
    return jsonify(database.list_annotations())


@app.route("/api/telemetry/annotations", methods=["POST"])
def api_annotations_add():
    user = _analyst_guard()
    if not user:
        return jsonify({"error": "Unauthorized"}), 403
    data = request.get_json(silent=True) or {}
    label = (data.get("label") or "").strip()
    ts = (data.get("timestamp") or "").strip()
    if not label or not ts:
        return jsonify({"error": "label and timestamp are required"}), 400
    if len(label) > 140:
        return jsonify({"error": "label too long (max 140)"}), 400
    ann_id = database.add_annotation(ts, user["id"], label,
                                     data.get("severity", "info"))
    database.audit_log_action(user["id"], "annotation_add",
                              detail="%s @ %s" % (label, ts))
    return jsonify({"status": "ok", "id": ann_id}), 201


@app.route("/api/telemetry/annotations/<int:ann_id>", methods=["DELETE"])
def api_annotations_delete(ann_id):
    user = _analyst_guard()
    if not user:
        return jsonify({"error": "Unauthorized"}), 403
    if database.delete_annotation(ann_id, user["id"]):
        database.audit_log_action(user["id"], "annotation_delete",
                                  detail="annotation #%d" % ann_id)
        return jsonify({"status": "ok"})
    return jsonify({"error": "not found or not yours"}), 404


@app.route("/api/telemetry/endpoint-matrix", methods=["GET"])
def api_endpoint_matrix():
    if not _analyst_guard():
        return jsonify({"error": "Unauthorized"}), 403
    return jsonify({"rows": database.endpoint_matrix(hours=24)})


@app.route("/api/telemetry/model-accuracy", methods=["GET"])
def api_model_accuracy():
    if not _analyst_guard():
        return jsonify({"error": "Unauthorized"}), 403
    city = (request.args.get("city") or None)
    window = request.args.get("window", type=int) or 168
    return jsonify(database.model_accuracy(city=city, window_hours=window))


@app.route("/api/telemetry/verify-forecast", methods=["POST"])
def api_verify_forecast():
    """Record a predicted-vs-actual observation feeding the MAE/RMSE tracker."""
    user = _analyst_guard()
    if not user:
        return jsonify({"error": "Unauthorized"}), 403
    data = request.get_json(silent=True) or {}
    try:
        err = database.record_forecast_verification(
            data.get("city", "unknown"),
            float(data.get("predicted_temp")),
            float(data.get("actual_temp")),
        )
    except (TypeError, ValueError):
        return jsonify({"error": "city, predicted_temp, actual_temp required"}), 400
    return jsonify({"status": "ok", "error_margin": err}), 201

@app.route("/api/telemetry/simulate-alert", methods=["POST"])
def api_simulate_alert():
    """What-if extreme-weather stress test — never fires real notifications.

    Runs the scenario through the SYSTEM_ALERT_RULES rule engine, persists the
    dry-run into the simulation audit history, and returns the full record so
    the frontend audit table can refresh instantly.
    """
    user = _analyst_guard()
    if not user:
        return jsonify({"error": "Unauthorized"}), 403
    import time as _time
    data = request.get_json(silent=True) or {}
    metric = (data.get("metric") or "temp_c").strip()
    city = (data.get("city") or "karachi").strip()

    # Build the scenario parameters: prefer the rich
    # {temperature, aqi, wind_speed} shape, falling back to the legacy
    # single-metric {metric, threshold} simulator controls.
    parameters = {}
    for key in ("temperature", "aqi", "wind_speed"):
        raw = data.get(key)
        if raw is not None and str(raw).strip() != "":
            try:
                parameters[key] = float(raw)
            except (TypeError, ValueError):
                return jsonify({"error": "%s (number) required" % key}), 400
    if not parameters:
        try:
            threshold = float(data.get("threshold"))
        except (TypeError, ValueError):
            return jsonify({"error": "threshold (number) required"}), 400
        if metric in ("aqi", "aqi_index"):
            parameters["aqi"] = threshold
        else:
            parameters["temperature"] = threshold
        for key in ("temperature", "aqi", "wind_speed"):
            parameters.setdefault(key, 0)

    t0 = _time.time()
    try:
        doc = database.run_alert_simulation(city, parameters, user["id"])
    except Exception as err:
        return jsonify({"error": "simulation failed: %s" % err}), 500
    latency_ms = round((_time.time() - t0) * 1000, 2)

    payload = {
        "metric": metric,
        "city": doc["city"],
        "parameters": doc["parameters"],
        "severity": doc["highest_severity"] if doc["triggered_count"] else None,
        "channels": doc["simulated_channels"],
        "dry_run": True,
    }
    database.audit_log_action(user["id"], "alert_simulate",
                              detail="%s %s (dry-run, %d rules triggered)"
                                     % (doc["city"], metric, doc["triggered_count"]))
    # Optional MongoDB mirror feeding the /simulate-alert/stats aggregation.
    try:
        from models.mongo_models import SimulationLogModel

        SimulationLogModel.insert(
            city=doc["city"],
            parameters=doc["parameters"],
            rules_triggered=doc["rules_triggered"],
            triggered_count=doc["triggered_count"],
            highest_severity=doc["highest_severity"],
            processing_latency_ms=doc["processing_latency_ms"],
        )
    except Exception:
        pass  # Mongo mirroring is best-effort only.
    return jsonify({"status": "ok", "fired": doc["triggered_count"] > 0,
                    "payload": payload, "record": doc,
                    "pipeline_latency_ms": latency_ms})


@app.route("/api/telemetry/hadoop/jobs", methods=["POST"])
def api_hadoop_job_submit():
    user = _analyst_guard()
    if not user:
        return jsonify({"error": "Unauthorized"}), 403
    data = request.get_json(silent=True) or {}
    job = database.hadoop_job_create(data.get("type"), user["id"])
    if job is None:
        return jsonify({"error": "type must be daily_summary, aqi_averages, "
                                 "or extreme_events"}), 400
    database.audit_log_action(user["id"], "hadoop_job_submit",
                              detail="%s (%s)" % (job["job_id"], job["type"]))
    return jsonify({"status": "ok", "job": job}), 202


@app.route("/api/telemetry/hadoop/jobs/<job_id>", methods=["GET"])
def api_hadoop_job_status(job_id):
    if not _analyst_guard():
        return jsonify({"error": "Unauthorized"}), 403
    job = database.hadoop_job_get(job_id)
    if job is None:
        return jsonify({"error": "job not found"}), 404
    return jsonify(job)


@app.route("/api/telemetry/export", methods=["GET"])
def api_export_metrics():
    user = _analyst_guard()
    if not user:
        return jsonify({"error": "Unauthorized"}), 403
    fmt = (request.args.get("format") or "json").lower()
    rng = request.args.get("range", type=int) or 168
    data = database.export_metrics(range_hours=rng)

    if fmt == "csv":
        import csv as _csv
        import io as _io
        buf = _io.StringIO()
        writer = _csv.writer(buf)
        writer.writerow(["dataset", "key", "status", "value_ms", "created_at"])
        for row in data["telemetry"]:
            writer.writerow(["api_request", row["path"], row["status"],
                             row["duration_ms"], row["created_at"]])
        for row in data["forecast_verification"]:
            writer.writerow(["forecast", row["city"], None,
                             row["error_margin"], row["timestamp"]])
        database.audit_log_action(user["id"], "data_export",
                                  detail="csv range=%dh" % rng)
        return app.response_class(
            buf.getvalue(), mimetype="text/csv",
            headers={"Content-Disposition":
                     "attachment; filename=skycast_export.csv"})

    database.audit_log_action(user["id"], "data_export", detail="json range=%dh" % rng)
    return jsonify(data)


@app.route("/api/telemetry/audit-log", methods=["GET"])
def api_audit_log():
    if not _analyst_guard():
        return jsonify({"error": "Unauthorized"}), 403
    action = (request.args.get("action") or None)
    limit = request.args.get("limit", type=int) or 100
    return jsonify({"entries": database.audit_log_list(limit=limit, action=action)})



if __name__ == "__main__":
    # Prefer a browser-safe port. Chrome/Firefox block some ports entirely
    # (e.g. 5060/5061) with ERR_UNSAFE_PORT, so never default to those.
    preferred = int(os.environ.get("SKYCAST_PORT", "8080"))
    port = _pick_port(preferred)

    print("=" * 62)
    print("  SkyCast AI is starting...")
    print("  ->  http://localhost:%d" % port)
    print("  ->  http://127.0.0.1:%d" % port)
    print("  Press Ctrl+C to stop the server.")
    print("=" * 62)

    # host=127.0.0.1 is IPv4 only (safe + always reachable on this machine).
    app.run(host="127.0.0.1", port=port, debug=True, use_reloader=False)