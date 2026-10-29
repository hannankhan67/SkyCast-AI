"""SkyCast AI - AI Insights blueprint.

Competition-grade smart insights layer:

    GET /api/summary?city=     Extreme-weather AI summarizer
                               (2-sentence banner for /weather)
    GET /api/banners           Global severe-condition toasts
                               (AQI > 200, heatwave, storms)
    GET /api/v1/aqi/forecast   24-hour air-quality breakdown
                               (PM2.5 / PM10 / O3 / NO2) with live
                               Open-Meteo Air-Quality API + offline
                               deterministic fallback
"""
import json
import math
import urllib.parse
import urllib.request
import zlib
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, render_template, request

insights_bp = Blueprint("insights", __name__)


def _sim(seed, lo, hi):
    """Deterministic pseudo-random float in [lo, hi] from a string seed."""
    h = zlib.crc32(str(seed).encode("utf-8"))
    return lo + (h % 100000) / 100000.0 * (hi - lo)


def _load_weather(city_key):
    """Shared live-weather loader with graceful offline fallback."""
    from app import CITIES, _live_forecast, _live_payload, _simulated_payload

    c = CITIES.get(city_key)
    if not c:
        return None
    try:
        return _live_payload(city_key, _live_forecast(c["lat"], c["lon"]))
    except Exception:
        return _simulated_payload(city_key)


def _hour_int(label):
    """'5:42 AM' -> 5, '2:00 PM' -> 14 (best effort)."""
    try:
        low = label.lower().strip()
        time_part, mer = low.split(" ")
        h = int(time_part.split(":")[0])
        if mer == "pm" and h != 12:
            h += 12
        if mer == "am" and h == 12:
            h = 0
        return h
    except (ValueError, AttributeError):
        return 12


# ---------------------------------------------------------------------------
# Extreme Weather AI Summarizer
# ---------------------------------------------------------------------------

def _build_summary(city_key, weather):
    """Rule-based 2-sentence hyper-local summary from the live payload.

    Looks ahead through the hourly block to time rain / heat / wind, so the
    banner reads like an AI bulletin:  "Monsoon rains expected to peak around
    4:00 PM ... High risk of localized street flooding."
    """
    hourly = weather.get("hourly") or []
    temp = float(weather.get("temp") or 0)
    wind = float(weather.get("wind") or 0)
    cond = (weather.get("condition") or "").lower()

    # --- Sentence 1: rain timing / dominant condition --------------------
    peak = max(hourly, key=lambda h: h.get("precip", 0)) if hourly else None
    peak_prob = (peak or {}).get("precip", 0)
    if peak and peak_prob >= 55:
        s1 = ("Rainfall expected to peak around %s (%d%% probability) in "
              "%s." % (peak["time"], peak_prob, weather.get("city", city_key.title())))
    elif temp >= 40:
        s1 = ("Severe heatwave conditions gripping %s, with a daytime high "
              "near %d°C." % (weather.get("city", city_key.title()), temp))
    elif wind >= 35:
        s1 = ("Strong winds of %d km/h sweeping across %s."
              % (wind, weather.get("city", city_key.title())))
    elif "fog" in cond or "haze" in cond:
        s1 = ("Reduced visibility across %s due to %s."
              % (weather.get("city", city_key.title()),
                 weather.get("condition", "haze").lower()))
    else:
        s1 = ("%s sits under %s at %d°C right now."
              % (weather.get("city", city_key.title()),
                 weather.get("condition", "clear skies").lower(), temp))

    # --- Sentence 2: impact statement ------------------------------------
    impacts = []
    if peak_prob >= 75:
        impacts.append("high risk of localized street flooding and traffic disruption")
    elif peak_prob >= 55:
        impacts.append("carry an umbrella — wet commutes likely")
    if temp >= 40:
        impacts.append("avoid outdoor exertion between 12:00 and 16:00")
    elif temp >= 36:
        impacts.append("stay hydrated and limit midday sun exposure")
    if wind >= 35:
        impacts.append("secure loose objects; difficult for two-wheelers")
    if "storm" in cond or "thunder" in cond:
        impacts.append("avoid open fields and power lines")
    if not impacts:
        if temp <= 10:
            impacts.append("layer up — chilly air all day")
        else:
            impacts.append("great conditions for outdoor plans")

    return {
        "summary": s1 + " " + impacts[0].capitalize() + ".",
        "impact": impacts[0],
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


@insights_bp.route("/api/summary")
def summary():
    from app import CITIES

    city = (request.args.get("city") or "karachi").lower()
    city = "".join(ch for ch in city if ch.isalnum())
    if city not in CITIES:
        return jsonify({"error": "Unknown city"}), 404
    weather = _load_weather(city)
    if weather is None:
        return jsonify({"error": "Could not load weather"}), 404
    out = _build_summary(city, weather)
    out["city"] = CITIES[city]["name"]
    return jsonify(out)


# ---------------------------------------------------------------------------
# Global severe-condition banners (toast system)
# ---------------------------------------------------------------------------

def _aqi_category(aqi):
    if aqi <= 50:
        return "Good"
    if aqi <= 100:
        return "Moderate"
    if aqi <= 150:
        return "Unhealthy for Sensitive Groups"
    if aqi <= 200:
        return "Unhealthy"
    if aqi <= 300:
        return "Very Unhealthy"
    return "Hazardous"


@insights_bp.route("/api/banners")
def banners():
    """Severe-condition toasts shown app-wide (AQI / heatwave / storms)."""
    from app import CITIES

    out = []
    for key, meta in CITIES.items():
        weather = _load_weather(key)
        if weather is None:
            continue
        temp = float(weather.get("temp") or 0)
        cond = (weather.get("condition") or "").lower()
        try:
            data = _aqi_forecast_data(key)
            aqi = int(data.get("current_aqi") or 0) if data else 0
        except Exception:
            aqi = 0

        if aqi >= 200:
            out.append({"level": "severe", "city": meta["name"], "kind": "air",
                        "title": "Severe Air Pollution — %s" % meta["name"].split(",")[0],
                        "message": "AQI at %d (hazardous). Limit outdoor activity, "
                                   "wear an N95 mask outdoors." % aqi})
        if temp >= 40:
            out.append({"level": "severe", "city": meta["name"], "kind": "heat",
                        "title": "Heatwave Warning — %s" % meta["name"].split(",")[0],
                        "message": "Temperature at %d°C. Stay indoors between "
                                   "12:00-16:00 and hydrate frequently." % int(temp)})
        if "storm" in cond or "thunder" in cond:
            out.append({"level": "severe", "city": meta["name"], "kind": "storm",
                        "title": "Thunderstorm Alert — %s" % meta["name"].split(",")[0],
                        "message": "Thunderstorms moving through the area — avoid "
                                   "open fields, tall trees and power lines."})
    return jsonify({"banners": out, "checked": len(CITIES),
                    "generated_at": datetime.now().isoformat(timespec="seconds")})


# ---------------------------------------------------------------------------
# 24-hour AQI forecast (live Open-Meteo Air-Quality API, offline fallback)
# ---------------------------------------------------------------------------

def _aqi_forecast_data(city_key):
    """24h AQI data — live from Open-Meteo Air-Quality API when possible.

    The API returns the city's whole current day starting at local 00:00
    (with `utc_offset_seconds`), so we rebase every timestamp and keep only
    the current hour and the following ones — a clean forward-looking 24h
    window with no duplicates, no server-timezone assumptions, and no
    dependence on the local hour slicing a foreign city's clock.
    """
    from app import CITIES, _sim

    c = CITIES.get(city_key)
    if not c:
        return None
    params = {
        "latitude": c["lat"],
        "longitude": c["lon"],
        "hourly": "pm2_5,pm10,ozone,nitrogen_dioxide,us_aqi",
        "forecast_days": "2",  # ensure >= 24 future hours even late in the day
        "timezone": "auto",
    }
    url = ("https://air-quality-api.open-meteo.com/v1/air-quality?"
           + urllib.parse.urlencode(params))
    try:
        with urllib.request.urlopen(url, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        hourly = data.get("hourly") or {}
        times = hourly.get("time") or []
        n = len(times)
        offset = int(data.get("utc_offset_seconds") or 0)
        pm25 = hourly.get("pm2_5") or [0] * n
        pm10 = hourly.get("pm10") or [0] * n
        o3 = hourly.get("ozone") or [0] * n
        no2 = hourly.get("nitrogen_dioxide") or [0] * n
        usa = hourly.get("us_aqi") or [0] * n

        # Start of the current hour as a UTC instant (same boundary everywhere).
        now_utc = datetime.now(timezone.utc).timestamp()
        hour_start = now_utc - now_utc % 3600

        def _row(i):
            return {
                "time": times[i][11:16],
                "pm2_5": round(pm25[i] or 0, 1),
                "pm10": round(pm10[i] or 0, 1),
                "o3": round(o3[i] or 0, 1),
                "no2": round(no2[i] or 0, 1),
                "us_aqi": int(usa[i] or 0),
            }

        points = []
        for i in range(n):
            if len(points) >= 24:
                break
            t = times[i]
            try:
                dt = datetime.strptime(t[:16], "%Y-%m-%dT%H:%M")
                # naive city-local time -> UTC instant minus the city's offset
                if dt.replace(tzinfo=timezone.utc).timestamp() - offset < hour_start:
                    continue  # past hour - skip
            except (ValueError, TypeError):
                continue
            points.append(_row(i))

        # Safety net: if nothing survives (clock edge case), show the first 24.
        if not points:
            points = [_row(i) for i in range(min(24, n))]

        current = points[0]["us_aqi"] if points else 0
        return {
            "live": True,
            "source": "Open-Meteo Air Quality",
            "points": points,
            "current_aqi": current,
            "peak_aqi": max((p["us_aqi"] for p in points), default=0),
            "category": _aqi_category(current),
        }
    except Exception:
        return _simulated_aqi(city_key)


def _simulated_aqi(city_key):
    """Deterministic offline fallback — realistic diurnal AQI curve."""
    from app import _sim

    now = datetime.now()
    points = []
    for i in range(24):
        hour = (now.hour + i) % 24
        diurnal = 30 * math.cos((hour - 9) * math.pi / 12)  # peak ~9 AM
        base = _sim("%s-aqi" % city_key, 55, 165)
        aqi = int(max(15, min(320, base + diurnal + _sim("%s-h%d" % (city_key, i), -12, 12))))
        pm25 = round(aqi * _sim("%s-r1" % city_key, 0.35, 0.6), 1)
        points.append({
            "time": "%02d:00" % hour,
            "pm2_5": pm25,
            "pm10": round(pm25 * _sim("%s-r2" % city_key, 1.6, 2.4), 1),
            "o3": round(_sim("%s-o3-%d" % (city_key, hour), 15, 60), 1),
            "no2": round(_sim("%s-no2-%d" % (city_key, hour), 8, 45), 1),
            "us_aqi": aqi,
        })
    current = points[0]["us_aqi"]
    return {
        "live": False,
        "source": "SkyCast deterministic simulator",
        "points": points,
        "current_aqi": current,
        "peak_aqi": max(p["us_aqi"] for p in points),
        "category": _aqi_category(current),
    }


@insights_bp.route("/api/v1/aqi/forecast")
def aqi_forecast():
    """GET /api/v1/aqi/forecast?city=karachi — 24h PM2.5/PM10/O3/NO2 + US AQI."""
    from app import CITIES

    city = (request.args.get("city") or "karachi").lower()
    city = "".join(ch for ch in city if ch.isalnum())
    if city not in CITIES:
        return jsonify({"error": "Unknown city"}), 404
    data = _aqi_forecast_data(city)
    if data is None:
        return jsonify({"error": "Could not load air quality"}), 404
    return jsonify({
        "city": CITIES[city]["name"],
        "city_key": city,
        "live": data["live"],
        "source": data["source"],
        "current_aqi": data["current_aqi"],
        "peak_aqi": data["peak_aqi"],
        "category": data["category"],
        "hourly": data["points"],
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    })


@insights_bp.route("/aqi")
def aqi_dashboard():
    """Full air-quality dashboard: current AQI, 24h PM2.5 / O3 / NO2 breakdown."""
    from app import CITIES

    return render_template(
        "aqi.html", active="aqi", cities=sorted(CITIES.keys())
    )
