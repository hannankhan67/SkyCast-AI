"""SkyCast AI — Smart Commute & AI Outfit Recommendation Engine.

Two dynamic features:
  1. Smart Commute & Time-Series Route Weather Engine
  2. AI Outfit & Activity Recommendation Engine

Uses urllib (stdlib) to match the codebase — no extra dependencies.
"""

import urllib.parse
import urllib.request
import json
from datetime import datetime, timedelta, timezone

from flask import Blueprint, request, jsonify

smart_bp = Blueprint("smart_features", __name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


def _fetch_open_meteo(params, timeout=6):
    """Fetch JSON from Open-Meteo with stdlib urllib."""
    try:
        url = OPEN_METEO_URL + "?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


# ====================================================================
# FEATURE 1: Smart Commute & Time-Series Route Weather Engine
# ====================================================================

def _fetch_waypoint_weather(lat, lng, target_time):
    """Hourly forecast for a coordinate at a specific time."""
    data = _fetch_open_meteo({
        "latitude": lat, "longitude": lng,
        "hourly": "temperature_2m,precipitation_probability,precipitation,wind_speed_10m,weather_code",
        "timezone": "auto",
    })
    if not data:
        return None
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    target_str = target_time.strftime("%Y-%m-%dT%H:00")
    idx = times.index(target_str) if target_str in times else 0
    return {
        "temp": (hourly.get("temperature_2m") or [0])[idx],
        "precip_prob": (hourly.get("precipitation_probability") or [0])[idx],
        "precip_mm": (hourly.get("precipitation") or [0])[idx],
        "wind_speed": (hourly.get("wind_speed_10m") or [0])[idx],
        "weather_code": (hourly.get("weather_code") or [0])[idx],
    }


@smart_bp.route("/api/route/smart-commute", methods=["POST"])
def calculate_smart_commute():
    """
    Weather hazards along route waypoints shifted over travel time.
    Payload:
    {
       "departure_time": "2026-08-31T18:00",
       "waypoints": [
          {"name": "Karachi", "lat": 24.8607, "lng": 67.0011, "eta_minutes": 0},
          {"name": "Hyderabad", "lat": 25.3960, "lng": 68.3578, "eta_minutes": 120}
       ]
    }
    """
    data = request.get_json() or {}
    departure_str = data.get("departure_time")
    waypoints = data.get("waypoints", [])
    if not waypoints or not departure_str:
        return jsonify({"status": "error", "message": "Missing waypoints or departure time"}), 400

    try:
        departure_time = datetime.fromisoformat(departure_str)
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "Invalid departure_time format"}), 400

    route_schedule = []
    has_hazard = False
    hazards_summary = []

    for point in waypoints:
        eta_time = departure_time + timedelta(minutes=int(point.get("eta_minutes", 0)))
        weather = _fetch_waypoint_weather(point["lat"], point["lng"], eta_time)
        hazard_level = "Safe"
        hazard_msg = "Clear weather along route."

        if weather:
            if weather["precip_prob"] > 60 or weather["precip_mm"] > 2.0:
                hazard_level = "High Risk"
                hazard_msg = f"Heavy rain risk ({weather['precip_prob']}%) around {eta_time.strftime('%I:%M %p')}."
                has_hazard = True
                hazards_summary.append(f"{point['name']}: {hazard_msg}")
            elif weather["wind_speed"] > 35:
                hazard_level = "Moderate Risk"
                hazard_msg = f"High crosswinds ({weather['wind_speed']} km/h)."
                has_hazard = True
                hazards_summary.append(f"{point['name']}: {hazard_msg}")

        route_schedule.append({
            "waypoint": point["name"],
            "eta": eta_time.strftime("%I:%M %p"),
            "weather": weather,
            "hazard_level": hazard_level,
            "hazard_msg": hazard_msg,
        })

    recommendation = ("Hazard detected along your route. Consider delaying departure by 30-45 minutes."
                      if has_hazard else "Optimal departure time. Proceed as planned.")

    return jsonify({
        "status": "success",
        "departure_time": departure_time.strftime("%Y-%m-%d %I:%M %p"),
        "has_hazards": has_hazard,
        "recommendation": recommendation,
        "hazards": hazards_summary,
        "route_timeline": route_schedule,
    }), 200


# ====================================================================
# FEATURE 2: AI Outfit & Activity Recommendation Engine
# ====================================================================

@smart_bp.route("/api/outfit/recommend", methods=["GET", "POST"])
def recommend_outfit_and_activities():
    """Rule-based outfit + activity recommendations from live climate data."""
    if request.method == "GET":
        lat = float(request.args.get("lat", 24.8607))
        lng = float(request.args.get("lng", 67.0011))
    else:
        data = request.get_json() or {}
        lat = float(data.get("lat", 24.8607))
        lng = float(data.get("lng", 67.0011))

    w_data = _fetch_open_meteo({
        "latitude": lat, "longitude": lng,
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,wind_speed_10m,weather_code",
        "daily": "uv_index_max",
        "timezone": "auto",
    })
    if not w_data:
        return jsonify({"status": "error", "message": "Weather provider unreachable"}), 502

    current = w_data.get("current", {})
    daily = w_data.get("daily", {})
    temp = current.get("temperature_2m", 25)
    feels_like = current.get("apparent_temperature", temp)
    humidity = current.get("relative_humidity_2m", 50)
    precip = current.get("precipitation", 0)
    wind = current.get("wind_speed_10m", 10)
    uv_index = (daily.get("uv_index_max") or [5])[0]

    outfit, fabrics, accessories = [], [], []
    if feels_like >= 32:
        outfit.append("Lightweight linen or breathable cotton short-sleeve shirt and shorts/chinos")
        fabrics.extend(["Linen", "Lightweight Cotton", "Bamboo Rayon"])
    elif feels_like >= 20:
        outfit.append("Standard cotton t-shirt or polo with comfortable trousers/jeans")
        fabrics.extend(["Cotton", "Chambray", "Jersey"])
    elif feels_like >= 12:
        outfit.append("Layered outfit: Long-sleeve shirt under a denim jacket or light sweater")
        fabrics.extend(["Fleece", "Denim", "Light Wool"])
    else:
        outfit.append("Thermal inner layer, heavy wool sweater, and insulated jacket")
        fabrics.extend(["Wool", "Down Insulation", "Thermal Synthetics"])

    if uv_index >= 6:
        accessories.extend(["UV-400 Protection Sunglasses", "Wide-brimmed hat or cap", "Broad-spectrum SPF 50+ Sunscreen"])
    if precip > 0.5:
        accessories.extend(["Waterproof raincoat or windbreaker", "Sturdy umbrella"])
    if wind > 25:
        accessories.append("Wind-resistant outer shell")

    activities = {
        "jogging_running": {"feasible": True, "note": "Great conditions for outdoor workouts."},
        "outdoor_dining": {"feasible": True, "note": "Pleasant outdoor seating weather."},
        "lawn_gardening": {"feasible": True, "note": "Optimal plant watering condition."},
    }
    if feels_like > 35:
        activities["jogging_running"] = {"feasible": False, "note": "High heat index risk. Prefer indoor gym or early morning."}
        activities["outdoor_dining"] = {"feasible": False, "note": "Too hot for unshaded outdoor dining."}
    if precip > 1.0:
        activities["jogging_running"] = {"feasible": False, "note": "Wet roads/slippery conditions due to rain."}
        activities["outdoor_dining"] = {"feasible": False, "note": "Rain expected. Move dining indoors."}
    if wind > 30:
        activities["lawn_gardening"] = {"feasible": False, "note": "Strong winds may disrupt spray or damage delicate plants."}

    return jsonify({
        "status": "success",
        "metrics": {
            "temperature": f"{temp}°C", "feels_like": f"{feels_like}°C",
            "humidity": f"{humidity}%", "uv_index": uv_index,
            "wind_speed": f"{wind} km/h",
        },
        "recommendations": {
            "outfit_suggestion": outfit,
            "recommended_fabrics": fabrics,
            "essential_accessories": accessories,
            "activity_feasibility": activities,
        },
    }), 200
