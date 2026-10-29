"""SkyCast AI - Specialized insights blueprint.

Routes:
  /solar           Solar / renewable energy estimator
  /route           Travel & route weather planner
  /agriculture     Agricultural & soil analytics
"""
import json
import math
import zlib
from datetime import datetime, timedelta, timezone

from flask import Blueprint, g, jsonify, render_template, request

import database
from routes.auth import login_required, premium_required

specialized_bp = Blueprint("specialized", __name__)


def _sim(seed, lo=0.0, hi=1.0):
    """Deterministic pseudo-random float in [lo, hi] from a string seed."""
    h = zlib.crc32(str(seed).encode("utf-8"))
    return lo + (h % 100000) / 100000.0 * (hi - lo)


def _solar_estimate(city_key, day_offset=0, kw_capacity=5.0, panel_efficiency=0.18):
    """Solar / PV output estimate using sun geometry + cloud cover.

    `kw_capacity` and `panel_efficiency` come from user input; the response
    includes an hourly power-output profile for the day.
    """
    from app import CITIES
    c = CITIES.get(city_key)
    if not c:
        return {}
    lat = c["lat"]
    day_of_year = datetime.now().timetuple().tm_yday
    declination = 23.45 * math.sin(math.radians(360 / 365 * (day_of_year - 81)))
    cloud_cover = _sim("%s-%d" % (city_key, day_offset)) * 0.6 + 0.2
    atmosphere_transmission = 0.75  # clear-sky GHI at zenith ≈ 1000 * 0.75

    hourly = []
    total_kwh = 0.0
    for hour in range(5, 20):
        hour_angle = 15 * (hour - 12)
        cos_zenith = (
            math.sin(math.radians(lat)) * math.sin(math.radians(declination)) +
            math.cos(math.radians(lat)) * math.cos(math.radians(declination)) *
            math.cos(math.radians(hour_angle))
        )
        clear_sky_ghi = max(0.0, cos_zenith) * 1000 * atmosphere_transmission * 2
        ghi = clear_sky_ghi * (1 - 0.75 * cloud_cover ** 3.4)
        output_kw = kw_capacity * (ghi / 1000.0) * (panel_efficiency / 0.18) * 0.85
        output_kw = max(0.0, output_kw)
        total_kwh += output_kw
        hourly.append({
            "hour": "%02d:00" % hour,
            "ghi_wm2": round(ghi, 1),
            "output_kw": round(output_kw, 2),
        })

    peak_sun_hours = round(sum(h["output_kw"] for h in hourly) / max(kw_capacity, 0.1), 2)
    daily_kwh = round(total_kwh, 2)
    return {
        "city": c["name"],
        "system_size_kw": kw_capacity,
        "panel_efficiency": panel_efficiency,
        "peak_sun_hours": peak_sun_hours,
        "daily_kwh": daily_kwh,
        "monthly_kwh": round(daily_kwh * 30, 1),
        "co2_saved_kg": round(daily_kwh * 0.92, 2),
        "co2_saved_year_tons": round(daily_kwh * 365 * 0.92 / 1000, 2),
        "cloud_cover_pct": round(cloud_cover * 100, 1),
        "hourly_output": hourly,
        "peak_output_kw": round(max((h["output_kw"] for h in hourly), default=0), 2),
    }


def _soil_moisture(city_key):
    """Soil analytics with FAO-style ET0 (Hargreaves) + irrigation schedule."""
    from app import CITIES, _live_forecast, _live_payload, _simulated_payload

    c = CITIES.get(city_key)
    if not c:
        return {}
    lat = c["lat"]

    # Live temperature context for the ET0 calculation (fallback: seasonal).
    try:
        w = _live_payload(city_key, _live_forecast(c["lat"], c["lon"]))
        tmax, tmin, rain_mm = float(w["temp"]) + 3, float(w["temp"]) - 4, 0.0
    except Exception:
        tmax, tmin, rain_mm = 34.0, 24.0, 0.0

    # --- Hargreaves-Samani ET0 (FAO-56) -----------------------------------
    doy = datetime.now().timetuple().tm_yday
    dr = 1 + 0.033 * math.cos(2 * math.pi * doy / 365)          # earth-sun distance
    decl = 0.409 * math.sin(2 * math.pi * doy / 365 - 1.39)     # solar declination
    x = max(-1.0, min(1.0, -math.tan(math.radians(lat)) * math.tan(decl)))
    ws = math.acos(x)                                           # sunset hour angle
    ra = (24 * 60 / math.pi) * 0.0820 * dr * (
        ws * math.sin(math.radians(lat)) * math.sin(decl) +
        math.cos(math.radians(lat)) * math.cos(decl) * math.sin(ws)
    )                                                            # MJ/m²/day
    et0 = max(0.0, 0.0023 * ((tmax + tmin) / 2) * ((tmax - tmin) ** 0.5) * ra * 0.408)

    moisture = max(0.0, min(1.0, 0.6 - et0 * 0.06 + _sim("%s-soil" % city_key, -0.1, 0.1)))
    net_irrigation = max(0.0, et0 * 1.0 - rain_mm)              # Kc ≈ 1.0 mixed crop

    if moisture < 0.35:
        advice = ("Irrigate now — apply %.1f mm (%.0f L/m²) early morning "
                  "(5:00-7:00 AM) to minimize evaporation." % (net_irrigation, net_irrigation * 10))
        urgency = "high"
    elif moisture < 0.55:
        advice = ("Light irrigation of %.1f mm (%.0f L/m²) recommended tomorrow "
                  "morning; moisture trending down." % (net_irrigation, net_irrigation * 10))
        urgency = "medium"
    else:
        advice = "Moisture adequate — no irrigation needed for ~2 days."
        urgency = "low"

    return {
        "city": c["name"],
        "soil_moisture_pct": round(moisture * 100, 1),
        "et0_mm_day": round(et0, 2),
        "et0_method": "Hargreaves-Samani (FAO-56)",
        "reference_ra_mj_m2": round(ra, 2),
        "effective_rainfall_mm": rain_mm,
        "net_irrigation_mm": round(net_irrigation, 2),
        "net_irrigation_l_m2": round(net_irrigation * 10, 1),
        "irrigation_urgency": urgency,
        "irrigation_advice": advice,
        "water_saving_tip": ("Drip irrigation at dawn cuts evaporation losses "
                             "by up to 30% versus midday watering."),
        "evapotranspiration_mm": round(et0, 2),
        "frost_risk": "Low" if lat < 30 else "Moderate",
    }


def _route_weather(start, end):
    """Route weather with per-waypoint driving-risk flags."""
    from app import CITIES, _sim

    sc = CITIES.get(start)
    ec = CITIES.get(end)
    if not sc or not ec:
        return {"error": "Unknown city"}
    hours = 4
    points = []
    risks = []
    for i in range(hours + 1):
        frac = i / hours
        lat = sc["lat"] + (ec["lat"] - sc["lat"]) * frac
        lon = sc["lon"] + (ec["lon"] - sc["lon"]) * frac
        temp = round(20 + 10 * math.sin(frac * math.pi) + _sim("%s-%d" % (start, i), -2, 2))
        wind = round(_sim("%s-wind-%d" % (start, i), 6, 42))
        rain = _sim("%s-rain-%d" % (start, i), 0, 1) > 0.62
        fog = _sim("%s-fog-%d" % (start, i), 0, 1) > 0.8
        condition = "Clear Sky"
        if rain:
            condition = "Rain Showers"
        elif fog:
            condition = "Foggy"

        point_risks = []
        if fog:
            point_risks.append("fog")
        if rain:
            point_risks.append("heavy rain")
        if wind >= 35:
            point_risks.append("high crosswind")
        if temp >= 40:
            point_risks.append("extreme heat")
        severity = ("severe" if (fog or (rain and wind >= 35))
                    else ("caution" if point_risks else "clear"))

        points.append({
            "hour": (datetime.now() + timedelta(hours=i)).strftime("%H:%M"),
            "lat": round(lat, 2),
            "lon": round(lon, 2),
            "temp": temp,
            "wind": wind,
            "condition": condition,
            "risks": point_risks,
            "severity": severity,
        })
        if point_risks:
            risks.append({
                "hour": points[-1]["hour"],
                "lat": points[-1]["lat"],
                "lon": points[-1]["lon"],
                "risks": point_risks,
                "severity": severity,
                "advice": (
                    "Slow down and use fog lights." if fog else
                    "Reduce speed, headlights on, beware of aquaplaning." if rain else
                    "Grip the wheel — strong lateral gusts." if wind >= 35 else
                    "Run A/C, carry water for the stretch."
                ),
            })

    overall = ("severe" if any(p["severity"] == "severe" for p in points)
               else ("caution" if any(p["severity"] == "caution" for p in points) else "clear"))
    return {
        "start": sc["name"],
        "end": ec["name"],
        "duration_hours": hours,
        "overall_risk": overall,
        "risk_summary": (
            "Trip looks safe — clear conditions along the whole route." if overall == "clear"
            else "%d checkpoint(s) with hazards — review advisories before departure." % len(risks)
        ),
        "points": points,
        "risks": risks,
    }


# --- Routes ------------------------------------------------------------------

@specialized_bp.route("/solar", endpoint="solar")
@premium_required
@login_required
def solar_page():
    from app import CITIES
    return render_template("solar.html", active="solar", cities=sorted(CITIES.keys()))


@specialized_bp.route("/api/solar")
def solar_api():
    from app import CITIES
    city = (request.args.get("city") or "karachi").lower()
    city = "".join(ch for ch in city if ch.isalnum())
    if city not in CITIES:
        return jsonify({"error": "Unknown city"}), 404
    day = int(request.args.get("day") or 0)
    try:
        kw = float(request.args.get("size") or request.args.get("kw") or 5.0)
    except (TypeError, ValueError):
        kw = 5.0
    kw = max(0.5, min(kw, 100.0))
    try:
        eff = float(request.args.get("eff") or 0.18)
    except (TypeError, ValueError):
        eff = 0.18
    eff = max(0.08, min(eff, 0.45))
    return jsonify(_solar_estimate(city, day, kw, eff))


@specialized_bp.route("/api/v1/solar/calculate")
def v1_solar_calculate():
    """GET /api/v1/solar/calculate?lat=&lon=&kw_capacity=

    Projected hourly power output for an arbitrary coordinate (falls back to
    the nearest covered city for climate realism).
    """
    from app import CITIES

    try:
        lat = float(request.args.get("lat"))
        lon = float(request.args.get("lon"))
    except (TypeError, ValueError):
        return jsonify({"error": "lat and lon query params are required numbers"}), 400
    try:
        kw = float(request.args.get("kw_capacity") or 5.0)
    except (TypeError, ValueError):
        kw = 5.0
    kw = max(0.5, min(kw, 100.0))

    # Snap to the nearest known city so the cloud-cover simulation is sane.
    nearest_key, nearest_d = None, None
    for key, c in CITIES.items():
        d = (c["lat"] - lat) ** 2 + (c["lon"] - lon) ** 2
        if nearest_d is None or d < nearest_d:
            nearest_key, nearest_d = key, d
    est = _solar_estimate(nearest_key, 0, kw, 0.18)
    est.update({
        "requested_lat": lat,
        "requested_lon": lon,
        "nearest_city": est.get("city"),
        "kw_capacity": kw,
        "api_version": "v1",
    })
    return jsonify(est)


@specialized_bp.route("/agriculture", endpoint="agriculture")
@premium_required
@login_required
def agriculture_page():
    from app import CITIES
    return render_template("agriculture.html", active="agriculture", cities=sorted(CITIES.keys()))


@specialized_bp.route("/api/agriculture")
def agriculture_api():
    from app import CITIES
    city = (request.args.get("city") or "karachi").lower()
    city = "".join(ch for ch in city if ch.isalnum())
    if city not in CITIES:
        return jsonify({"error": "Unknown city"}), 404
    return jsonify(_soil_moisture(city))


@specialized_bp.route("/route", endpoint="route")
@login_required
def route_page():
    from app import CITIES
    return render_template("route.html", active="route", cities=sorted(CITIES.keys()))


@specialized_bp.route("/api/route")
def route_api():
    start = (request.args.get("start") or "").lower().strip()
    end = (request.args.get("end") or "").lower().strip()
    start = "".join(ch for ch in start if ch.isalnum())
    end = "".join(ch for ch in end if ch.isalnum())
    from app import CITIES
    if start not in CITIES or end not in CITIES:
        return jsonify({"error": "Unknown city"}), 404
    return jsonify(_route_weather(start, end))


@specialized_bp.route("/api/v1/route/weather")
def v1_route_weather():
    """GET /api/v1/route/weather?origin=karachi&destination=lahore

    Polyline waypoints with per-checkpoint weather risks for drivers.
    """
    origin = (request.args.get("origin") or "").lower().strip()
    destination = (request.args.get("destination") or "").lower().strip()
    origin = "".join(ch for ch in origin if ch.isalnum())
    destination = "".join(ch for ch in destination if ch.isalnum())
    from app import CITIES
    if origin not in CITIES or destination not in CITIES:
        return jsonify({"error": "origin and destination must be covered cities"}), 404
    out = _route_weather(origin, destination)
    out["api_version"] = "v1"
    return jsonify(out)


@specialized_bp.route("/historical", endpoint="historical")
@premium_required
@login_required
def historical_page():
    return render_template("historical.html", active="historical")


def _historical_baselines(city_key):
    """Past-year comparison: 12 months of current temps vs 10/20/30-yr baselines.

    Returns 12 monthly points (oldest -> newest) for the trailing year,
    where each point is that month's average temperature against the
    long-term climate baseline for the same month. A deterministic warming
    trend keeps older baselines cooler than the current series, mirroring
    a real climate anomaly.
    """
    from app import CITIES, _sim

    c = CITIES.get(city_key)
    if not c:
        return None

    today = datetime.now()
    MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    labels, current, b10, b20, b30 = [], [], [], [], []

    for offset in range(11, -1, -1):  # 11 months ago -> current month
        m = today.month - offset
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        labels.append("%s %d" % (MONTHS[m - 1], y))

        # seasonal base for this month
        base = 20 + 10 * math.sin((m / 12) * math.pi)
        cur = round(base + _sim("%s-%d-%d" % (city_key, y, m), -3, 3), 1)
        current.append(cur)
        b10.append(round(cur - _sim("%s-10-%d" % (city_key, m), 0.4, 1.2), 1))
        b20.append(round(cur - _sim("%s-20-%d" % (city_key, m), 0.8, 2.0), 1))
        b30.append(round(cur - _sim("%s-30-%d" % (city_key, m), 1.4, 3.0), 1))

    cur_avg = sum(current) / len(current)
    b30_avg = sum(b30) / len(b30)
    anomaly = round(cur_avg - b30_avg, 1)
    month_name = MONTHS[today.month - 1]

    on_this_day = {
        "date": today.strftime("%b %d"),
        "record_high": round(max(current) + _sim("%s-rh-%d" % (city_key, today.month), 2, 6)),
        "record_low": round(min(current) - _sim("%s-rl-%d" % (city_key, today.month), 2, 6)),
        "events": [
            {"year": today.year - 12, "text": "Record heatwave — %d°C peak" % round(max(current) + 5)},
            {"year": today.year - 21, "text": "Severe thunderstorm & flash flooding"},
            {"year": today.year - 28, "text": "Coldest %s on record — %d°C" % (month_name, round(min(current) - 5))},
        ],
    }

    return {
        "city": c["name"], "city_key": city_key, "month": today.month, "month_name": month_name,
        "labels": labels, "current": current,
        "baseline_10": b10, "baseline_20": b20, "baseline_30": b30,
        "current_avg": round(cur_avg, 1), "baseline_30_avg": round(b30_avg, 1),
        "anomaly_30yr": anomaly,
        "anomaly_label": ("+%.1f°C warmer" % anomaly) if anomaly >= 0 else ("%.1f°C cooler" % anomaly),
        "on_this_day": on_this_day,
    }


@specialized_bp.route("/api/historical")
def historical_api():
    city = (request.args.get("city") or "karachi").lower()
    city = "".join(ch for ch in city if ch.isalnum())
    from app import CITIES
    if city not in CITIES:
        return jsonify({"error": "Unknown city"}), 404
    data = _historical_baselines(city)
    if not data:
        return jsonify({"error": "Could not build history"}), 404
    return jsonify(data)
