"""SkyCast AI - public pages blueprint.

Routes for the multi-page site:
  /weather      Live weather + hourly + 7-day
  /maps         Radar & layer maps
  /analytics    Climate Analytics Engine (Hadoop/HDFS showcase)
  /dashboard    Personal user dashboard (login required)
  /about        About the project + tech stack
  /health       Health & Symptom Weather Index
  /planner      Event & Outdoor Activity Planner
"""

import json
import math
import zlib
from datetime import datetime, timedelta

from flask import Blueprint, g, jsonify, render_template, request, session, url_for

from routes.auth import (
    PREMIUM_PAGE_GROUPS,
    PREMIUM_PAGE_PREFIXES,
    login_required,
    premium_group_for_path,
    premium_required,
)


def _sim(seed, lo, hi):
    h = zlib.crc32(str(seed).encode("utf-8"))
    return lo + (h % 100000) / 100000.0 * (hi - lo)


def _weather_payload(city_key):
    """Live weather payload with deterministic offline fallback."""
    from app import CITIES, _live_forecast, _live_payload, _simulated_payload

    c = CITIES.get(city_key)
    if not c:
        return None
    try:
        return _live_payload(city_key, _live_forecast(c["lat"], c["lon"]))
    except Exception:
        return _simulated_payload(city_key)


# --- A. Health & Symptom Weather Index --------------------------------------

_ALLERGEN_SEASON = {2: "High (pollen)", 3: "High (pollen)", 4: "High (pollen)",
                    5: "Moderate (pollen)", 9: "Moderate (spore)", 10: "Moderate (spore)"}


def _risk_band(score, lo, hi, low_lbl="Low", mod_lbl="Moderate", high_lbl="High"):
    if score >= hi:
        return high_lbl
    if score >= lo:
        return mod_lbl
    return low_lbl


def _health_index(city_key):
    w = _weather_payload(city_key)
    if not w:
        return None
    temp = float(w.get("temp") or 0)
    humidity = float(w.get("humidity") or 0)
    wind = float(w.get("wind") or 0)
    uv = float(w.get("uv") or 0)
    pressure = float(w.get("pressure") or 1012)
    aqi = float(w.get("aqi") or 60)
    cond = (w.get("condition") or "").lower()

    # --- Barometric pressure trend (3h window) ------------------------------
    p3 = round(pressure + _sim("%s-hp3" % city_key, -5, 5), 1)
    drop = round(pressure - p3, 1)
    migraine_score = 0
    if drop <= -3:
        migraine_score, migraine = 3, "High"
    elif drop <= -1.5:
        migraine_score, migraine = 2, "Moderate"
    else:
        migraine_score, migraine = 1, "Low"

    # --- Air quality / asthma ------------------------------------------------
    pm25 = round(aqi * 0.5, 0)
    pm10 = round(pm25 * 1.6, 0)
    if aqi >= 150:
        asthma_score, asthma = 3, "High"
    elif aqi >= 100:
        asthma_score, asthma = 2, "Moderate"
    else:
        asthma_score, asthma = 1, "Low"

    # --- Joint pain (humidity + low pressure) -------------------------------
    if humidity >= 80 and pressure < 1008:
        joint_score, joint = 3, "High"
    elif humidity >= 75 or pressure < 1005:
        joint_score, joint = 2, "Moderate"
    else:
        joint_score, joint = 1, "Low"

    # --- UV / skin -----------------------------------------------------------
    if uv >= 8:
        uv_band, uv_advice = "High", "Avoid direct sun 11:00-16:00; SPF 50+ and protective clothing."
    elif uv >= 6:
        uv_band, uv_advice = "Moderate", "Wear sunscreen (SPF 30+) and a hat for extended outdoor time."
    else:
        uv_band, uv_advice = "Low", "Minimal burn risk; basic sun protection is enough."

    # --- Pollen --------------------------------------------------------------
    month = datetime.now().month
    pollen_base = _ALLERGEN_SEASON.get(month, "Low")
    pollen_index = round(_sim("%s-pollen" % city_key, 1, 10), 0)
    if any(k in cond for k in ("rain", "drizzle", "shower")):
        pollen_index = max(0, pollen_index - 4)
    pollen_band = _risk_band(pollen_index, 4, 7)

    overall = _risk_band((migraine_score + asthma_score + joint_score) / 3.0 * 3, 2.2, 2.8)
    # map to Low/Moderate/High using averaged 1-3
    avg = (migraine_score + asthma_score + joint_score) / 3.0
    overall_band = "High" if avg >= 2.6 else ("Moderate" if avg >= 1.8 else "Low")

    return {
        "city": w.get("city"),
        "city_key": city_key,
        "temp": temp, "humidity": humidity, "wind": wind, "uv": uv,
        "pressure": round(pressure, 1),
        "pressure_3h_ago": p3,
        "pressure_drop_hpa": drop,
        "aqi": round(aqi, 0), "pm25": pm25, "pm10": pm10,
        "migraine": {"level": migraine, "drop_hpa": drop},
        "asthma": {"level": asthma, "aqi": round(aqi, 0), "pm25": pm25, "pm10": pm10},
        "joint_pain": {"level": joint, "humidity": humidity},
        "uv": {"level": uv_band, "index": uv, "advice": uv_advice},
        "pollen": {"level": pollen_band, "index": pollen_index, "season": pollen_base},
        "overall": overall_band,
    }


# --- D. Event & Outdoor Activity Planner ------------------------------------

_EVENT_PROFILES = {
    "wedding":   {"label": "Outdoor Wedding", "rain": 4.0, "wind": 1.2, "heat": 1.0, "cold": 1.0, "cloud": 0.4},
    "cricket":   {"label": "Cricket Match",   "rain": 5.0, "wind": 1.5, "heat": 0.8, "cold": 1.2, "cloud": 0.3},
    "drone":     {"label": "Drone Flying",    "rain": 4.5, "wind": 3.5, "heat": 0.4, "cold": 0.6, "cloud": 0.8},
    "camping":   {"label": "Camping",         "rain": 4.0, "wind": 1.5, "heat": 0.6, "cold": 2.0, "cloud": 0.5},
    "marathon":  {"label": "Marathon / Run",  "rain": 3.5, "wind": 1.0, "heat": 2.2, "cold": 1.0, "cloud": 0.3},
    "hiking":    {"label": "Hiking",          "rain": 3.5, "wind": 1.2, "heat": 1.4, "cold": 1.4, "cloud": 0.4},
}


def _event_feasibility(event, ctx):
    p = _EVENT_PROFILES.get(event, _EVENT_PROFILES["cricket"])
    max_t = float(ctx.get("max") or 25)
    min_t = float(ctx.get("min") or 15)
    precip = float(ctx.get("precip_prob") or 0)
    wind = float(ctx.get("wind") or 0)
    cond = (ctx.get("condition") or "").lower()
    cloud = 1.0 if any(k in cond for k in ("cloud", "overcast", "fog")) else 0.0

    # Heat index (simple apparent-temperature proxy)
    heat = max_t + (humidity_factor(ctx) if False else 0)
    penalty = 0.0
    penalty += p["rain"] * (precip / 100.0) * 2.0
    penalty += p["wind"] * max(0.0, wind - 18) / 10.0
    penalty += p["heat"] * max(0.0, max_t - 32) / 6.0
    penalty += p["cold"] * max(0.0, 12 - min_t) / 6.0
    penalty += p["cloud"] * cloud

    score = max(1.0, min(10.0, 10.0 - penalty))
    verdict = ("Excellent" if score >= 8 else "Good" if score >= 6.5
               else "Marginal" if score >= 4.5 else "Poor")
    return round(score, 1), verdict


def humidity_factor(ctx):
    return 0.0


def _planner(city_key, event, days):
    from routes.assistant import _build_weather_context

    results = []
    for off in range(days):
        ctx = _build_weather_context(city_key, off)
        if not ctx:
            continue
        score, verdict = _event_feasibility(event, ctx)
        results.append({
            "day_offset": off,
            "day": ctx.get("day"),
            "date": (datetime.now() + timedelta(days=off)).strftime("%b %d"),
            "max": ctx.get("max"), "min": ctx.get("min"),
            "precip_prob": ctx.get("precip_prob"), "wind": ctx.get("wind"),
            "condition": ctx.get("condition"),
            "score": score, "verdict": verdict,
        })
    best = max(results, key=lambda r: r["score"]) if results else None
    return {"event": _EVENT_PROFILES.get(event, {}).get("label", event),
            "city": city_key, "days": results, "best": best}


# --- F. Live Lightning & Storm Cell Tracker ---------------------------------

def _lightning(city_key):
    from app import CITIES

    c = CITIES.get(city_key)
    if not c:
        return None
    strikes = []
    for i in range(18):
        dlat = _sim("%s-lat%d" % (city_key, i), -1.6, 1.6)
        dlon = _sim("%s-lon%d" % (city_key, i), -1.6, 1.6)
        strikes.append({
            "lat": round(c["lat"] + dlat, 4),
            "lon": round(c["lon"] + dlon, 4),
            "intensity": round(_sim("%s-int%d" % (city_key, i), 5, 95)),
            "age_s": round(_sim("%s-age%d" % (city_key, i), 0, 90)),
        })
    # Storm cell vector derived from wind direction (deterministic).
    wind_dir = round(_sim("%s-wdir" % city_key, 0, 360))
    wind_spd = round(_sim("%s-wspd" % city_key, 10, 45))
    return {
        "city": c["name"], "city_key": city_key,
        "center": [c["lat"], c["lon"]],
        "strikes": strikes,
        "cell": {"direction_deg": wind_dir, "speed_kmh": wind_spd},
        "generated_at": datetime.now().strftime("%H:%M:%S"),
    }

import database

pages_bp = Blueprint("pages", __name__)


@pages_bp.route("/weather")
def weather():
    return render_template("weather.html", active="weather")


@pages_bp.route("/maps")
def maps():
    return render_template("maps.html", active="maps")


@pages_bp.route("/analytics")
def analytics():
    return render_template("analytics.html", active="analytics")


@pages_bp.route("/dashboard")
@login_required
def dashboard():
    telemetry = None
    # Only analysts and admins pay the cost of the live telemetry aggregation.
    if g.user.get("role") in ("analyst", "admin"):
        telemetry = database.analyst_dashboard_telemetry()
        # Alt+M mode override: force the "Simulated Data" badge presentation.
        if telemetry and session.get("telemetry_mode") == "simulated":
            telemetry["is_simulated"] = True
    return render_template(
        "dashboard.html", active="dashboard", telemetry=telemetry
    )


@pages_bp.route("/about")
def about():
    return render_template("about.html", active="about")


# ---------------------------------------------------------------------------
# User settings / preferences
# ---------------------------------------------------------------------------

@pages_bp.route("/settings")
@login_required
def settings():
    from app import CITIES

    prefs = database.get_preferences(g.user["id"])
    return render_template(
        "settings.html",
        active="settings",
        cities=sorted(CITIES.keys()),
        prefs=prefs,
    )


@pages_bp.route("/api/user/preferences", methods=["POST"])
@login_required
def save_preferences():
    """POST /api/user/preferences

    Body (JSON): home_city, unit ("c"|"f"), notify_threshold
    ("default" | "sensitive" | "strict").
    """
    from app import CITIES

    data = request.get_json(silent=True) or {}

    home_city = data.get("home_city")
    unit = data.get("unit")
    threshold = data.get("notify_threshold")

    if home_city is not None:
        home_city = "".join(ch for ch in str(home_city).lower() if ch.isalnum())
        if home_city not in CITIES:
            return jsonify({"error": "Unknown home city"}), 400
    if unit is not None and unit not in ("c", "f"):
        return jsonify({"error": "unit must be 'c' or 'f'"}), 400
    if threshold is not None and threshold not in ("default", "sensitive", "strict"):
        return jsonify({"error": "notify_threshold must be default, sensitive or strict"}), 400

    # Optional WhatsApp number (used by the forgot-password WhatsApp channel).
    phone = data.get("phone")
    if phone is not None:
        if not database.update_user_phone(g.user["id"], str(phone)):
            return jsonify({"error": "Invalid phone number"}), 400

    database.update_preferences(
        g.user["id"], home_city=home_city, unit=unit, notify_threshold=threshold
    )
    prefs = database.get_preferences(g.user["id"])
    user = database.get_user_by_id(g.user["id"]) or {}
    prefs["phone"] = user.get("phone", "")
    return jsonify({"ok": True, "preferences": prefs})


# ---------------------------------------------------------------------------
# Dashboard saved cities (per-user city list management)
# ---------------------------------------------------------------------------

# Cities shown on first visit, before the user customizes their list.
_DEFAULT_SAVED_CITIES = ["karachi", "lahore", "islamabad", "dubai", "london", "newyork"]


def _saved_city_list(user_id):
    """Parse the user's stored saved_cities JSON into a clean list of keys."""
    prefs = database.get_preferences(user_id)
    try:
        raw = json.loads(prefs.get("saved_cities") or "[]")
        if isinstance(raw, list):
            return [str(c).strip().lower() for c in raw if c]
    except (ValueError, TypeError):
        pass
    return []


def _saved_cities_with_defaults(user_id):
    """Return the saved list, seeding the first-run defaults on first use.

    Seeding on first access keeps behaviour consistent: the defaults are
    persisted, so the very first add/remove does not silently replace them.
    """
    saved = _saved_city_list(user_id)
    if not saved:
        saved = list(_DEFAULT_SAVED_CITIES)
        database.update_preferences(user_id, saved_cities=json.dumps(saved))
    return saved


@pages_bp.route("/api/cities")
def cities_catalog():
    """Full city directory grouped by country — powers the 'add a city' picker."""
    from app import CITIES

    countries = {}
    for key, meta in CITIES.items():
        country = meta.get("country", "Other")
        countries.setdefault(country, []).append(
            {"key": key, "name": meta.get("name", key)}
        )
    catalog = [
        {"country": country, "cities": sorted(cities, key=lambda c: c["name"])}
        for country, cities in sorted(countries.items())
    ]
    return jsonify({"countries": catalog})


@pages_bp.route("/api/user/saved-cities", methods=["GET"])
@login_required
def list_saved_cities():
    from app import CITIES

    saved = _saved_cities_with_defaults(g.user["id"])
    saved = [k for k in saved if k in CITIES]
    return jsonify({"cities": saved})


@pages_bp.route("/api/user/saved-cities", methods=["POST"])
@login_required
def add_saved_city():
    """POST /api/user/saved-cities  body: {"city": "tokyo"}"""
    from app import CITIES

    data = request.get_json(silent=True) or {}
    key = "".join(ch for ch in str(data.get("city", "")).lower() if ch.isalnum())
    if not key or key not in CITIES:
        return jsonify({"error": "Unknown city", "cities": sorted(CITIES)}), 400

    saved = _saved_cities_with_defaults(g.user["id"])
    if key not in saved:
        saved.append(key)
        database.update_preferences(g.user["id"], saved_cities=json.dumps(saved))
    return jsonify({"ok": True, "cities": saved})


@pages_bp.route("/api/user/saved-cities/<city>", methods=["DELETE"])
@login_required
def remove_saved_city(city):
    from app import CITIES

    key = "".join(ch for ch in str(city).lower() if ch.isalnum())
    saved = _saved_cities_with_defaults(g.user["id"])
    if key in saved:
        saved.remove(key)
        database.update_preferences(g.user["id"], saved_cities=json.dumps(saved))
    return jsonify({"ok": True, "cities": [k for k in saved if k in CITIES]})


@pages_bp.route("/api/user/subscription/cancel", methods=["POST"])
@login_required
def cancel_subscription():
    """POST /api/user/subscription/cancel

    Premium users may cancel at any time. The account is downgraded to Free
    immediately and the session subscription flag is refreshed so the
    navigation reactives without a full page reload.

    Instant revocation: `g.user` is re-read from the database on every
    request, so the next page render already sees subscription="free" and
    relocks Specialized / Insights. The `membership_cancelled` session flag
    additionally tells the route guard to EVICT (rather than upsell) anyone
    who lands on a Premium URL after cancelling.
    """
    user = g.user
    if (user.get("subscription") or "free").lower() != "premium":
        return jsonify({"error": "No active Premium subscription to cancel."}), 400

    database.set_user_subscription(user["id"], "free")

    session["subscription"] = "free"
    session["membership_cancelled"] = True

    # If the cancellation was triggered from a Premium page, report which
    # group the client must evict the user out of.
    evicted_from = premium_group_for_path(request.path)

    return jsonify(
        {
            "ok": True,
            "subscription": "free",
            "is_premium": False,
            "premium_groups": sorted(PREMIUM_PAGE_GROUPS.keys()),
            "restricted_paths": list(PREMIUM_PAGE_PREFIXES),
            "evicted_from": evicted_from,
            "redirect": url_for("pages.dashboard"),
            "message": (
                "Your membership has been canceled. "
                "%s is now locked." % (evicted_from or "Premium pages")
            ),
        }
    )


# ---------------------------------------------------------------------------
# A. Health & Symptom Weather Index
# ---------------------------------------------------------------------------

@pages_bp.route("/health")
@login_required
def health_page():
    from app import CITIES

    return render_template("health.html", active="health", cities=sorted(CITIES.keys()))


@pages_bp.route("/api/health")
def health_api():
    from app import CITIES

    city = (request.args.get("city") or "karachi").lower()
    city = "".join(ch for ch in city if ch.isalnum())
    if city not in CITIES:
        return jsonify({"error": "Unknown city"}), 404
    data = _health_index(city)
    if not data:
        return jsonify({"error": "Could not load weather"}), 404
    return jsonify(data)


# ---------------------------------------------------------------------------
# D. Event & Outdoor Activity Planner
# ---------------------------------------------------------------------------

@pages_bp.route("/planner")
@login_required
def planner_page():
    from app import CITIES

    return render_template(
        "planner.html", active="planner", cities=sorted(CITIES.keys()),
        events=list(_EVENT_PROFILES.values()),
    )


@pages_bp.route("/api/planner")
def planner_api():
    from app import CITIES
    from models.mongo_models import EventPlanModel

    city = (request.args.get("city") or "karachi").lower()
    city = "".join(ch for ch in city if ch.isalnum())
    event = (request.args.get("event") or "cricket").lower()
    try:
        days = max(1, min(int(request.args.get("days") or 7), 14))
    except (TypeError, ValueError):
        days = 7
    if city not in CITIES:
        return jsonify({"error": "Unknown city"}), 404
    if event not in _EVENT_PROFILES:
        return jsonify({"error": "Unknown event type"}), 400
    result = _planner(city, event, days)

    # Optional persistence: store the recommended day for logged-in users.
    best = result.get("best")
    if best is not None and g.get("user") is not None:
        try:
            from datetime import datetime as _dt
            EventPlanModel.save(EventPlanModel.create_document(
                user_id=g.user.get("id"), event_type=event, city=CITIES[city]["name"],
                event_date=_dt.now(), score=best["score"], label=best["verdict"],
                weather_data={"temp": best["max"], "rain_prob": best["precip_prob"],
                              "wind_speed": best["wind"], "cloud_cover": 0},
            ))
        except Exception:
            pass  # Mongo optional — never break the response

    return jsonify(result)


# ---------------------------------------------------------------------------
# F. Live Lightning & Storm Cell Tracker
# ---------------------------------------------------------------------------

@pages_bp.route("/api/lightning")
def lightning_api():
    from app import CITIES

    city = (request.args.get("city") or "karachi").lower()
    city = "".join(ch for ch in city if ch.isalnum())
    if city not in CITIES:
        return jsonify({"error": "Unknown city"}), 404
    data = _lightning(city)
    if not data:
        return jsonify({"error": "Could not build storm data"}), 404
    return jsonify(data)


# ---------------------------------------------------------------------------
# G. Subscription / Pricing
# ---------------------------------------------------------------------------

@pages_bp.route("/pricing")
def pricing():
    """Pricing & upgrade landing page (glassmorphic)."""
    return render_template("pages/pricing.html", active="pricing")


@pages_bp.route("/api/account/subscription", methods=["POST"])
@login_required
def update_subscription():
    """Demo endpoint: flip the logged-in user's subscription tier.

    No real billing — sets the `subscription` column to 'free' | 'premium'
    | 'premium' (unlocks Premium pages).
    """
    data = request.get_json(silent=True) or {}
    plan = (data.get("plan") or "").lower()
    if plan not in database.USER_PLANS:
        return jsonify({"error": "plan must be 'free' or 'premium'"}), 400
    database.set_user_subscription(g.user["id"], plan)
    session["subscription"] = plan
    if database.is_premium_plan(plan):
        # Re-subscribing clears the eviction flag so the premium pages are
        # reachable again instead of bouncing the user to the dashboard.
        session.pop("membership_cancelled", None)
    return jsonify({"status": "ok", "plan": plan,
                    "is_premium": database.is_premium_plan(plan)})
