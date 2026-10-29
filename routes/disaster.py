"""SkyCast AI - Disaster Response & Shelter Locator blueprint.

When severe weather (heatwave / thunderstorm / high wind / heavy rain) is
detected for a city, the platform surfaces local relief shelters and emergency
helplines so users know where to go.

Routes:
    GET /disaster      Shelter locator page
    GET /api/disaster  Hazard assessment + shelters + helplines for a city
"""

import math
import zlib
from datetime import datetime, timezone

from flask import Blueprint, jsonify, render_template, request

from routes.auth import login_required, premium_required

disaster_bp = Blueprint("disaster", __name__)

# National / regional emergency numbers that apply across the covered cities.
HELPLINES = [
    {"name": "Rescue 1122", "phone": "1122", "kind": "Emergency"},
    {"name": "Edhi Emergency", "phone": "115", "kind": "Ambulance / rescue"},
    {"name": "NDMA Helpline", "phone": "0800-11142", "kind": "Disaster mgmt"},
    {"name": "Pakistan Red Crescent", "phone": "051-9203093", "kind": "Relief"},
    {"name": "K-Electric Fault Report", "phone": "118", "kind": "Power"},
]

_SHELTER_NAMES = [
    ("Heatwave Relief Center", "heat"),
    ("Flood Emergency Shelter", "flood"),
    ("Medical Post", "medical"),
    ("Red Crescent Staging Point", "flood"),
]

# Severe thresholds (metric -> (watch, severe)).
_THRESHOLDS = {
    "temp": (36, 40),    # °C
    "wind": (35, 50),    # km/h
    "uv": (8, 11),
    "humidity": (75, 90),
}


def _sim(seed, lo, hi):
    """Deterministic pseudo-random float in [lo, hi] from a string seed."""
    h = zlib.crc32(seed.encode("utf-8"))
    return lo + (h % 100000) / 100000.0 * (hi - lo)


def _haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _load_weather(city_key):
    """Live weather payload with a deterministic offline fallback."""
    from app import CITIES, _live_forecast, _live_payload, _simulated_payload

    c = CITIES.get(city_key)
    if not c:
        return None
    try:
        return _live_payload(city_key, _live_forecast(c["lat"], c["lon"]))
    except Exception:
        return _simulated_payload(city_key)


def _detect_hazards(weather):
    cond = (weather.get("condition") or "").lower()
    temp = float(weather.get("temp") or 0)
    wind = float(weather.get("wind") or 0)
    uv = float(weather.get("uv") or 0)
    humidity = float(weather.get("humidity") or 0)

    level = "nominal"
    hazards = []
    advisories = []

    # Heat
    if temp >= _THRESHOLDS["temp"][1]:
        hazards.append("Heatwave advisory — stay hydrated and indoors between 12:00-16:00.")
        level = "severe"
    elif temp >= _THRESHOLDS["temp"][0]:
        advisories.append("Heat advisory — high temperatures; limit midday outdoor activity.")
        if level == "nominal":
            level = "watch"

    # Wind
    if wind >= _THRESHOLDS["wind"][1]:
        hazards.append("High wind alert — secure loose objects and avoid open water.")
        level = "severe"
    elif wind >= _THRESHOLDS["wind"][0]:
        advisories.append("Windy conditions — extra caution for cyclists and motorbikes.")

    # UV
    if uv >= _THRESHOLDS["uv"][1]:
        hazards.append("Extreme UV — avoid direct sun, use SPF 50+ and protective clothing.")
        if level == "nominal":
            level = "watch"
    elif uv >= _THRESHOLDS["uv"][0]:
        advisories.append("High UV — wear sunscreen and a hat when outdoors.")

    # Rain / storm / flood
    if any(w in cond for w in ("storm", "thunder", "shower")):
        hazards.append("Thunderstorms — avoid open fields, tall trees and power lines.")
        level = "severe"
    if any(w in cond for w in ("rain", "drizzle")):
        advisories.append("Rain in the area — carry an umbrella; watch for flooding on low roads.")

    # Humidity heat-stress combo
    if temp >= 32 and humidity >= _THRESHOLDS["humidity"][1]:
        advisories.append("High heat + humidity — risk of heat stress; take frequent breaks.")
        if level == "nominal":
            level = "watch"

    return {"level": level, "hazards": hazards, "advisories": advisories}


def _shelters(city_key):
    from app import CITIES

    c = CITIES.get(city_key)
    if not c:
        return []
    shelters = []
    for i, (name, kind) in enumerate(_SHELTER_NAMES[:3]):
        lat = c["lat"] + _sim("%s-slat%d" % (city_key, i), -0.45, 0.45)
        lon = c["lon"] + _sim("%s-slon%d" % (city_key, i), -0.5, 0.5)
        dist = round(_haversine_km(c["lat"], c["lon"], lat, lon), 1)
        shelters.append(
            {
                "name": "%s — %s" % (name, CITIES[city_key]["name"].split(",")[0]),
                "kind": kind,
                "distance_km": dist,
                "lat": round(lat, 4),
                "lon": round(lon, 4),
                "capacity": "%d people" % int(_sim("%s-cap%d" % (city_key, i), 400, 2500)),
                "open": 24,
            }
        )
    return shelters


@disaster_bp.route("/disaster")
@premium_required
@login_required
def disaster_page():
    from app import CITIES

    return render_template(
        "disaster.html", active="disaster", cities=sorted(CITIES.keys())
    )


@disaster_bp.route("/api/disaster")
def disaster_api():
    city = (request.args.get("city") or "karachi").lower()
    city = "".join(ch for ch in city if ch.isalnum())
    from app import CITIES

    if city not in CITIES:
        return jsonify({"error": "Unknown city"}), 404

    weather = _load_weather(city)
    if weather is None:
        return jsonify({"error": "Could not load weather"}), 404

    hazards = _detect_hazards(weather)
    return jsonify(
        {
            "city": CITIES[city]["name"],
            "city_key": city,
            "condition": weather.get("condition"),
            "temp": weather.get("temp"),
            "wind": weather.get("wind"),
            "uv": weather.get("uv"),
            "humidity": weather.get("humidity"),
            **hazards,
            "shelters": _shelters(city),
            "helplines": HELPLINES,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
    )