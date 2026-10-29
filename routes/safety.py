"""SkyCast AI — Emergency Safety & Shelter API.

Context-aware hazard protocols, emergency helplines (Pakistan),
and shelter geolocation lookup with Haversine distance sorting.
"""

import math

from flask import Blueprint, jsonify, request

safety_bp = Blueprint("safety", __name__)

# ──────────────────────────────────────────────────────────────────
# Emergency Helpline Directory (Pakistan)
# ──────────────────────────────────────────────────────────────────
EMERGENCY_HELPLINES = [
    {"name": "Rescue 1122", "number": "1122", "type": "Medical & Disaster Response"},
    {"name": "Edhi Foundation", "number": "115", "type": "Ambulance & Emergency"},
    {"name": "Chhipa Emergency", "number": "1020", "type": "Ambulance & Relief"},
    {"name": "PDMA Sindh", "number": "1736", "type": "Disaster Management Authority"},
    {"name": "National Emergency", "number": "1124", "type": "National Response Helpline"},
]

# ──────────────────────────────────────────────────────────────────
# Designated Safe Zones / Emergency Shelters
# ──────────────────────────────────────────────────────────────────
SHELTERS = [
    {"id": 1, "name": "Karachi Civic Center Relief Hub", "type": "Government Disaster Shelter",
     "lat": 24.8934, "lng": 67.0754, "capacity": 500, "status": "Open",
     "address": "Gulshan-e-Iqbal, Block 14, Karachi"},
    {"id": 2, "name": "Nishtar Park High-Ground Shelter", "type": "Elevated Safe Zone",
     "lat": 24.8715, "lng": 67.0312, "capacity": 300, "status": "Open",
     "address": "Soldier Bazar, Karachi"},
    {"id": 3, "name": "National Stadium Relief Camp", "type": "Mass Evacuation Shelter",
     "lat": 24.8953, "lng": 67.0784, "capacity": 2000, "status": "Open",
     "address": "Stadium Road, Karachi"},
    {"id": 4, "name": "Malir Cantonment High-Ground Hub", "type": "Military Relief Hub",
     "lat": 24.9125, "lng": 67.1956, "capacity": 1500, "status": "Open",
     "address": "Malir Cantt, Karachi"},
    {"id": 5, "name": "Lahore Expo Centre Shelter", "type": "Mass Evacuation Shelter",
     "lat": 31.4697, "lng": 74.2728, "capacity": 3000, "status": "Open",
     "address": "Johar Town, Lahore"},
    {"id": 6, "name": "Islamabad Sports Complex Hub", "type": "Government Disaster Shelter",
     "lat": 33.7200, "lng": 73.1200, "capacity": 1000, "status": "Open",
     "address": "Sector F-6, Islamabad"},
]

# ──────────────────────────────────────────────────────────────────
# Action Protocols (keyed by condition keyword)
# ──────────────────────────────────────────────────────────────────
SAFETY_PROTOCOLS = {
    "thunderstorm": {
        "hazard": "Severe Thunderstorm & Lightning",
        "severity": "HIGH",
        "action_title": "Immediate Lightning & Wind Safeguards",
        "do_list": [
            "Seek shelter inside a sturdy building or enclosed metal vehicle immediately.",
            "Stay clear of windows, exterior doors, and metal plumbing fixtures.",
            "Unplug expensive electronic appliances to prevent surge damage.",
            "Wait at least 30 minutes after the last thunderclap before stepping outside.",
        ],
        "dont_list": [
            "Do NOT shelter under tall, isolated trees or open metallic shade structures.",
            "Avoid standing near high ground, open fields, or electrical poles.",
            "Do NOT touch corded electrical devices or plugged-in hardware during strikes.",
        ],
    },
    "flood": {
        "hazard": "Flash Flood & Urban Inundation",
        "severity": "CRITICAL",
        "action_title": "Turn Around, Don't Drown Protocol",
        "do_list": [
            "Move immediately to upper floors, elevated ground, or designated concrete safe zones.",
            "Switch off main electricity breakers and gas valves if water begins entering.",
            "Keep emergency rescue contact numbers saved and ready to dial.",
            "Carry an emergency Go-Bag with freshwater, basic first aid, and power banks.",
        ],
        "dont_list": [
            "NEVER walk, swim, or drive through moving floodwaters (6 inches can knock an adult down).",
            "Do NOT drive across flooded underpasses or low-lying road bridges.",
            "Avoid basements, underground parking structures, or submerged elevator shafts.",
        ],
    },
    "heatwave": {
        "hazard": "Extreme Heatwave & Sunstroke",
        "severity": "HIGH",
        "action_title": "Heatstroke Prevention Protocol",
        "do_list": [
            "Stay hydrated — drink water every 15–20 minutes even if not thirsty.",
            "Remain indoors or in shaded areas between 11:00 AM and 4:00 PM.",
            "Wear light-coloured, loose-fitting clothing and a wide-brimmed hat.",
            "Check on elderly neighbours and young children frequently.",
        ],
        "dont_list": [
            "Do NOT leave children or pets parked in closed vehicles.",
            "Avoid caffeinated or alcoholic drinks — they accelerate dehydration.",
            "Do NOT engage in strenuous outdoor activity during peak heat hours.",
        ],
    },
}


def _haversine(lat1, lon1, lat2, lon2):
    """Distance in km between two coordinates."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    return round(R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)), 2)


# ──────────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────────

@safety_bp.route("/api/v1/safety/helplines")
def helplines():
    return jsonify({"status": "success", "helplines": EMERGENCY_HELPLINES}), 200


@safety_bp.route("/api/v1/safety/advisory")
def advisory():
    condition = request.args.get("condition", "thunderstorm").lower()
    proto = SAFETY_PROTOCOLS.get(condition, SAFETY_PROTOCOLS["thunderstorm"])
    return jsonify({"status": "success", "advisory": proto}), 200


@safety_bp.route("/api/v1/safety/shelters")
def shelters():
    try:
        lat = float(request.args.get("lat", 24.8607))
        lng = float(request.args.get("lng", 67.0011))
    except (ValueError, TypeError):
        lat, lng = 24.8607, 67.0011

    out = []
    for s in SHELTERS:
        entry = dict(s)
        entry["distance_km"] = _haversine(lat, lng, s["lat"], s["lng"])
        out.append(entry)
    out.sort(key=lambda x: x["distance_km"])

    return jsonify({
        "status": "success",
        "user_coordinates": {"lat": lat, "lng": lng},
        "total_shelters": len(out),
        "shelters": out,
    }), 200
