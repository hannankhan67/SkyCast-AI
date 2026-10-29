"""SkyCast AI - Assistant blueprint.

Routes:
  /assistant         AI chat / outfit + NL search interface
  /api/assistant     JSON endpoint for assistant logic
  /api/search        Natural-language weather search parser
"""
import json
import re
from datetime import datetime, timedelta, timezone

from flask import Blueprint, g, jsonify, render_template, request, session, url_for

import database
from routes.auth import login_required, premium_required

assistant_bp = Blueprint("assistant", __name__)

# --- Helpers ----------------------------------------------------------------

_CITY_ALIASES = {
    "khi": "karachi", "lah": "lahore", "isl": "islamabad",
    "dxb": "dubai", "ldn": "london", "nyc": "newyork",
    "karachi": "karachi", "lahore": "lahore", "islamabad": "islamabad",
    "dubai": "dubai", "london": "london", "new york": "newyork",
    "newyork": "newyork",
}

_DAY_ALIASES = {
    "today": 0, "tomorrow": 1,
    "monday": None, "tuesday": None, "wednesday": None,
    "thursday": None, "friday": None, "saturday": None, "sunday": None,
}


def _resolve_city(text):
    low = (text or "").lower()
    for alias, key in _CITY_ALIASES.items():
        if alias in low:
            return key
    return None


def _resolve_day(text):
    low = (text or "").lower()
    for alias, offset in _DAY_ALIASES.items():
        if alias in low:
            if offset is not None:
                return offset
            today = datetime.now()
            target = alias
            current = today.strftime("%A").lower()
            days_ahead = 0
            while current != target:
                days_ahead += 1
                current = (today + timedelta(days=days_ahead)).strftime("%A").lower()
                if days_ahead > 7:
                    return 0
            return days_ahead
    return 0


def _cities_list():
    from app import CITIES
    return sorted(CITIES.keys())


# --- Activity scores (0-10 actionable indices) --------------------------------

def _clamp10(v):
    return int(max(0, min(10, round(v))))


def _activity_scores(ctx):
    """Score outdoor activities from live context: running, cycling,
    stargazing, outdoor drying + UV-protection and hydration flags."""
    temp = float(ctx.get("max") or 0)
    uv = float(ctx.get("uv") or 0)
    wind = float(ctx.get("wind") or 0)
    precip = float(ctx.get("precip_prob") or ctx.get("precip") or 0)
    cond = (ctx.get("condition") or "").lower()
    raining = "rain" in cond or "drizzle" in cond or "storm" in cond

    running = 10
    running -= abs(temp - 18) * 0.45          # 18°C is ideal running temp
    running -= max(0, uv - 6) * 0.8
    running -= max(0, wind - 20) * 0.15
    running -= precip * 0.06
    if raining:
        running -= 4

    cycling = running - max(0, wind - 15) * 0.25 - (2 if raining else 0)

    # Stargazing: clear sky + low moon-less humidity + light wind
    stargazing = 10
    if any(w in cond for w in ("cloud", "overcast")):
        stargazing -= 5
    if raining or "storm" in cond:
        stargazing -= 8
    if "fog" in cond or "haze" in cond:
        stargazing -= 4
    stargazing -= max(0, wind - 12) * 0.2
    stargazing -= max(0, (humidity_proxy(ctx)) - 70) * 0.05

    drying = 10
    drying -= precip * 0.08
    if raining:
        drying -= 7
    drying -= max(0, 75 - humidity_proxy(ctx)) * -0.02 + 0  # humid air dries slower
    drying -= max(0, humidity_proxy(ctx) - 70) * 0.06
    if temp >= 30:
        drying = min(10, drying + 1)

    return {
        "running": {"score": _clamp10(running),
                     "verdict": _verdict(running)},
        "cycling": {"score": _clamp10(cycling),
                     "verdict": _verdict(cycling)},
        "stargazing": {"score": _clamp10(stargazing),
                        "verdict": _verdict(stargazing)},
        "drying_clothes": {"score": _clamp10(drying),
                            "verdict": _verdict(drying)},
        "uv_protection_needed": uv >= 6,
        "uv_index": uv,
        "hydration_liters_day": round(2.5 + max(0, temp - 25) * 0.08, 1),
    }


def humidity_proxy(ctx):
    """Assistant context has no humidity — proxy from temperature (hotter
    cities in this dataset are also more humid)."""
    temp = float(ctx.get("max") or 0)
    return max(35, min(90, 40 + (temp - 15) * 1.4))


def _verdict(score):
    s = _clamp10(score)
    if s >= 8:
        return "Excellent"
    if s >= 6:
        return "Good"
    if s >= 4:
        return "Fair"
    if s >= 2:
        return "Poor"
    return "Not recommended"


def _intent_reply(q, ctx, scores):
    """Hyper-localized answers for common practical questions."""
    low = (q or "").lower()
    city = ctx.get("city", "your city").title()
    temp = float(ctx.get("max") or 0)
    cond = (ctx.get("condition") or "").lower()
    raining = "rain" in cond or "drizzle" in cond or "storm" in cond

    if "dry" in low and ("cloth" in low or "laundry" in low or "wash" in low):
        d = scores["drying_clothes"]
        tip = ("Yes — great drying day." if d["score"] >= 6 else
               "Risky — clothes may stay damp." if d["score"] >= 4 else
               "No — keep the laundry indoors today.")
        return {"type": "drying", "answer": "%s: %s (Drying Index %d/10). "
                "Best window: 10:00 AM – 4:00 PM." % (city, tip, d["score"])}

    if "pack" in low or "flight" in low or "trip" in low or "travel" in low:
        items = ["light cotton layers" if temp >= 28 else "warm jacket + layers"]
        if raining:
            items.append("compact umbrella / rain jacket")
        if float(ctx.get("uv") or 0) >= 6:
            items.append("sunscreen SPF 50+ and sunglasses")
        if float(ctx.get("wind") or 0) >= 25:
            items.append("windcheater")
        return {"type": "packing", "answer": "Packing for %s (%s, ~%d°C): bring %s."
                % (city, cond, temp, ", ".join(items))}

    if "star" in low or "sky" in low or "telescope" in low:
        s = scores["stargazing"]
        return {"type": "stargazing", "answer": "Stargazing in %s tonight: %s "
                "(%d/10). %s" % (city, s["verdict"], s["score"],
                                 "Clear skies expected — look after 8 PM."
                                 if s["score"] >= 6 else "Clouds/haze will spoil the view.")}

    if "run" in low or "jog" in low or "gym" in low or "workout" in low:
        r = scores["running"]
        return {"type": "running", "answer": "Running in %s: %s (%d/10). "
                "%s" % (city, r["verdict"], r["score"],
                        "Best slot: early morning before 7 AM."
                        if temp >= 30 else "Any time of day works.")}

    if "umbrella" in low or "rain" in low:
        prob = float(ctx.get("precip_prob") or ctx.get("precip") or 0)
        return {"type": "precipitation",
                "answer": "Rain probability in %s is about %d%% — %s."
                % (city, round(prob), "take an umbrella" if prob > 50 else "you can leave it home")}

    return None


# --- Outfit / activity logic -------------------------------------------------

def _outfit_advice(temp, condition, uv, wind, humidity):
    items = []
    activities = []
    if temp >= 30:
        items.extend(["light cotton shirt", "shorts", "sunglasses", "sunscreen"])
        activities.extend(["swimming", "early morning jog", "indoor sports during peak heat"])
    elif temp >= 22:
        items.extend(["t-shirt", "light jacket optional"])
        activities.extend(["cricket", "cycling", "outdoor dining"])
    elif temp >= 15:
        items.extend(["long sleeves", "light sweater"])
        activities.extend(["hiking", "football", "sightseeing"])
    elif temp >= 5:
        items.extend(["coat", "scarf", "gloves"])
        activities.extend(["hot chocolate tour", "museum visits", "cozy cafes"])
    else:
        items.extend(["heavy winter coat", "thermal layers", "wool hat"])
        activities.extend(["indoor climbing", "skating rink", "board games"])

    if "rain" in (condition or "").lower() or "drizzle" in (condition or "").lower():
        items.append("umbrella / raincoat")
        activities = [a for a in activities if "indoor" in a or "cafe" in a or "museum" in a]
    if uv >= 8:
        items.append("high-SPF sunscreen")
    if wind >= 25:
        items.append("windbreaker")
    if humidity >= 80:
        items.append("moisture-wicking fabrics")
    return items, activities


def _activity_recommendations(ctx):
    """Recommend outdoor activities (running, sports, stargazing) using
    temperature, UV index and precipitation probability."""
    temp = ctx["max"]
    uv = ctx["uv"]
    p = ctx["precip_prob"]            # precipitation probability, %
    wind = ctx["wind"]
    cond = (ctx["condition"] or "").lower()
    cloudy = any(k in cond for k in ["overcast", "cloud", "fog", "rain", "storm", "drizzle"])
    clear = ("clear" in cond) or ("partly" in cond)

    recs = []

    # --- Running -------------------------------------------------------------
    if p >= 60:
        run = ("Not recommended", "High chance of rain (%d%%)." % p)
    elif temp > 32:
        run = ("Not recommended", "Too hot (%d\u00b0); risk of heat exhaustion." % temp)
    elif temp < 4:
        run = ("Not recommended", "Too cold (%d\u00b0); icy and unsafe." % temp)
    elif uv >= 8 and temp >= 28:
        run = ("Caution", "Very high UV (%s); run early morning or evening." % uv)
    elif 10 <= temp <= 28:
        run = ("Great", "Ideal running weather (%d\u00b0, UV %s)." % (temp, uv))
    else:
        run = ("Okay", "Manageable at %d\u00b0; dress for the conditions." % temp)
    recs.append({"name": "Running", "verdict": run[0], "reason": run[1]})

    # --- Outdoor sports ------------------------------------------------------
    if p >= 60:
        sport = ("Not recommended", "Rain likely (%d%%)." % p)
    elif wind >= 35:
        sport = ("Not recommended", "Strong winds (%d km/h)." % wind)
    elif temp > 34:
        sport = ("Not recommended", "Too hot (%d\u00b0) for outdoor sports." % temp)
    elif 12 <= temp <= 32:
        sport = ("Great", "Good conditions for outdoor sports.")
    else:
        sport = ("Okay", "Playable at %d\u00b0; take breaks if needed." % temp)
    recs.append({"name": "Outdoor Sports", "verdict": sport[0], "reason": sport[1]})

    # --- Stargazing ----------------------------------------------------------
    if p >= 40 or cloudy:
        star = ("Not recommended", "Skies not clear (%s, %d%% precip)." % (ctx["condition"], p))
    elif wind >= 25:
        star = ("Caution", "Breezy (%d km/h); bring warm layers." % wind)
    elif clear:
        star = ("Great", "Clear skies — excellent viewing conditions.")
    else:
        star = ("Okay", "Decent skies; some viewing possible.")
    recs.append({"name": "Stargazing", "verdict": star[0], "reason": star[1]})

    return recs


def _build_weather_context(city_key, day_offset=0):
    from app import CITIES, _live_forecast, _live_payload, _simulated_payload, condition as _cond
    c = CITIES.get(city_key)
    if not c:
        return None
    try:
        import urllib.parse, urllib.request, json
        params = {
            "latitude": c["lat"], "longitude": c["lon"],
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,uv_index_max,wind_speed_10m_max",
            "timezone": "auto", "forecast_days": "7",
        }
        url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        day_idx = min(day_offset, len(data.get("daily", {}).get("time", [])) - 1)
        if day_idx < 0:
            day_idx = 0
        d = data["daily"]
        code = d["weather_code"][day_idx]
        label, _ = _cond(code)
        return {
            "city": c["name"], "city_key": city_key,
            "day": (datetime.now() + timedelta(days=day_offset)).strftime("%A"),
            "condition": label,
            "max": round(d["temperature_2m_max"][day_idx]),
            "min": round(d["temperature_2m_min"][day_idx]),
            "precip": round(d["precipitation_sum"][day_idx], 1),
            "precip_prob": round(d["precipitation_probability_max"][day_idx], 0),
            "uv": round(d["uv_index_max"][day_idx], 1),
            "wind": round(d["wind_speed_10m_max"][day_idx], 1),
        }
    except Exception:
        return {
            "city": c["name"], "city_key": city_key,
            "day": (datetime.now() + timedelta(days=day_offset)).strftime("%A"),
            "condition": "Clear Sky", "max": 30, "min": 25,
            "precip": 0.0, "precip_prob": 10.0, "uv": 7.0, "wind": 12.0,
        }


# --- Routes ------------------------------------------------------------------

@assistant_bp.route("/assistant")
@premium_required
@login_required
def assistant_page():
    from app import CITIES
    cities = sorted(CITIES.keys())
    if g.get("user") is None:
        return render_template("assistant.html", active="assistant", guest=True, cities=cities)
    return render_template("assistant.html", active="assistant", guest=False, cities=cities)


@assistant_bp.route("/api/assistant", methods=["POST"])
def assistant_api():
    data = request.get_json(silent=True) or {}
    q = (data.get("message") or "").strip()
    city_key = _resolve_city(q)
    day_offset = _resolve_day(q)
    ctx = _build_weather_context(city_key or "karachi", day_offset)

    items, activities = _outfit_advice(
        ctx["max"], ctx["condition"], ctx["uv"], ctx["wind"], 60
    )
    from app import CITIES as _CITIES
    cities_list = _cities_list()

    scores = _activity_scores(ctx)

    # Hyper-localized intents first (dry clothes, packing, stargazing, running)
    intent = _intent_reply(q, ctx, scores)
    if intent is not None:
        intent["city_key"] = city_key or "karachi"
        intent["scores"] = scores
        intent["suggested_cities"] = cities_list
        return jsonify(intent)

    reply = {
        "type": "outfit",
        "city": ctx["city"],
        "day": ctx["day"],
        "condition": ctx["condition"],
        "max": ctx["max"],
        "min": ctx["min"],
        "uv": ctx["uv"],
        "wind": ctx["wind"],
        "precip": ctx["precip"],
        "outfit": items,
        "activities": activities,
        "scores": scores,
        "suggested_cities": cities_list,
    }

    if any(word in q.lower() for word in ["rain", "umbrella", "precipitation"]):
        reply["type"] = "precipitation"
        reply["precipitation_advice"] = (
            "Carry an umbrella." if ctx["precip"] > 0.5 else "No precipitation expected."
        )

    return jsonify(reply)


@assistant_bp.route("/api/outfit", methods=["POST"])
def outfit_api():
    data = request.get_json(silent=True) or {}
    city_key = (data.get("city") or _resolve_city(data.get("message", "")) or "karachi")
    try:
        day_offset = int(data.get("day_offset", 0) or 0)
    except (TypeError, ValueError):
        day_offset = 0
    day_offset = max(0, min(day_offset, 6))
    ctx = _build_weather_context(city_key, day_offset)

    items, activities = _outfit_advice(
        ctx["max"], ctx["condition"], ctx["uv"], ctx["wind"], 60
    )
    recs = _activity_recommendations(ctx)
    scores = _activity_scores(ctx)

    return jsonify({
        "city": ctx["city"],
        "day": ctx["day"],
        "condition": ctx["condition"],
        "max": ctx["max"],
        "min": ctx["min"],
        "uv": ctx["uv"],
        "wind": ctx["wind"],
        "precip_prob": ctx["precip_prob"],
        "outfit": items,
        "activities": activities,
        "recommendations": recs,
        "scores": scores,
    })


_TRIP_PROFILES = {
    "travel": ["travel documents", "power bank", "reusable water bottle", "compact umbrella"],
    "outdoor": ["daypack", "trail snacks", "refillable water", "insect repellent"],
    "sports": ["sports attire", "extra socks", "water bottle", "towel"],
    "beach": ["swimsuit", "beach towel", "flip-flops", "after-sun lotion"],
    "general": [],
}


def _packing_advice(city_key, day_offset, trip_type):
    """Hourly-aware packing list from forecasted rain, wind chill and UV."""
    ctx = _build_weather_context(city_key, day_offset)
    if not ctx:
        return None
    items, _ = _outfit_advice(ctx["max"], ctx["condition"], ctx["uv"], ctx["wind"], 60)
    packing = list(items)
    packing.extend(_TRIP_PROFILES.get((trip_type or "general").lower(), []))

    wind_chill = round(ctx["max"] - max(0.0, (ctx["wind"] - 10)) * 0.4)
    notes = []
    if ctx["precip_prob"] >= 40:
        notes.append("Rain likely (%d%%) — pack a compact umbrella or rain shell." % ctx["precip_prob"])
    else:
        notes.append("Low rain chance (%d%%) — no rain gear required." % ctx["precip_prob"])
    if ctx["wind"] >= 25:
        notes.append("Wind chill feels near %d\u00b0 — bring a windbreaker." % wind_chill)
    if ctx["uv"] >= 6:
        notes.append("UV index %s — pack SPF 30+, sunglasses and a hat." % ctx["uv"])
    if ctx["max"] >= 33:
        notes.append("Hot (%d\u00b0) — light, breathable fabrics and extra water." % ctx["max"])
    if ctx["min"] <= 12:
        notes.append("Cool night (%d\u00b0 — layer a warm mid-layer." % ctx["min"])

    return {
        "city": ctx["city"], "day": ctx["day"], "condition": ctx["condition"],
        "max": ctx["max"], "min": ctx["min"], "uv": ctx["uv"], "wind": ctx["wind"],
        "precip_prob": ctx["precip_prob"], "wind_chill": wind_chill,
        "outfit": items, "packing": packing, "notes": notes,
    }


@assistant_bp.route("/api/packing", methods=["POST"])
def packing_api():
    data = request.get_json(silent=True) or {}
    city_key = (data.get("city") or _resolve_city(data.get("message", "")) or "karachi")
    try:
        day_offset = int(data.get("day_offset", 0) or 0)
    except (TypeError, ValueError):
        day_offset = 0
    day_offset = max(0, min(day_offset, 6))
    trip = (data.get("trip_type") or "general").lower()
    res = _packing_advice(city_key, day_offset, trip)
    if not res:
        return jsonify({"error": "Unknown city"}), 404
    return jsonify(res)


@assistant_bp.route("/api/search")
def search_api():
    q = (request.args.get("q") or "").strip().lower()
    city_key = _resolve_city(q)
    day_offset = _resolve_day(q)
    ctx = _build_weather_context(city_key or "karachi", day_offset)
    from app import condition as _cond
    from ml_model import will_rain, rain_probability
    rain = will_rain(ctx["max"], 60, ctx["wind"], 1005)
    prob = rain_probability(ctx["max"], 60, ctx["wind"], 1005)

    answer = {
        "query": q,
        "city": ctx["city"],
        "day": ctx["day"],
        "condition": ctx["condition"],
        "max": ctx["max"],
        "min": ctx["min"],
        "will_rain": bool(rain),
        "rain_probability": round(prob * 100, 1),
        "precip_mm": ctx["precip"],
        "uv": ctx["uv"],
        "wind": ctx["wind"],
        "advice": (
            "Expect rain. Carry an umbrella and wear waterproof shoes."
            if rain else "No rain expected. Good day for outdoor plans."
        ),
    }
    return jsonify(answer)
