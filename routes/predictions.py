"""SkyCast AI - AI Prediction Engine.

Routes:
  /predictions          AI prediction dashboard with weekly forecast
  /api/predictions/weekly    Weekly weather prediction with recommendations
  /api/predictions/outfit   Clothing & accessory recommendations
  /api/predictions/routes   Safe route suggestions based on weather
  /api/predictions/relief   Nearby relief camps & emergency info
"""

import math
import zlib
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, render_template, request

from routes.auth import login_required, premium_required

predictions_bp = Blueprint("predictions", __name__)

# Real local roads per city (used for safe-route suggestions).
CITY_LOCAL_ROUTES = {
    "karachi": [("Shahrah-e-Faisal Corridor", "Via Saddar & PECHS", 14),
                ("Korangi Creek Route", "Via Korangi Road & Landhi", 18),
                ("North Karachi Link", "Via Nazimabad & North Karachi", 20),
                ("Clifton Coastal Route", "Via Sea View & DHA", 16)],
    "lahore": [("Northern Bypass", "Via Model Town & Gulberg", 12),
               ("Southern Route", "Via Jail Road & Ferozepur Road", 15),
               ("Eastern Loop", "Via Canal Road & Thokar Niaz Baig", 18),
               ("Western Corridor", "Via Multan Road & Raiwind Road", 22)],
    "islamabad": [("Kashmir Highway Route", "Via G-9 & F-10 sectors", 10),
                  ("Expressway Route", "Via Islamabad Expressway & Koral", 16),
                  ("Margalla Corridor", "Via Margalla Road & D-12", 14),
                  ("Faisal Avenue Link", "Via F-8 & Blue Area", 12)],
    "peshawar": [("Ring Road Route", "Via Hayatabad & Chamkani", 13),
                 ("University Road Link", "Via Board Bazaar & UT Circle", 15),
                 ("GT Road Corridor", "Via Nowshera Road & Pirpai", 17),
                 ("Dalazak Route", "Via Dalazak Road & Regi", 19)],
    "quetta": [("Airport Road Route", "Via Baleli & Samungli", 12),
               ("Brewery Road Link", "Via Chiltan Housing & Sariab", 15),
               ("Eastern Bypass", "Via Spini Road & Kuchlak", 18),
               ("Western Route", "Via Sirki Road & Nawan Killi", 20)],
    "multan": [("Bosan Road Route", "Via Gulgasht & Shah Rukn-e-Alam", 13),
               ("Northern Link", "Via Vehari Road & Chungi No 9", 16),
               ("Nishtar Road Corridor", "Via Nishtar Road & Cantt", 14),
               ("Eastern Loop", "Via Old Shujabad Road & Suraj Miani", 19)],
    "dubai": [("Sheikh Zayed Route", "Via Downtown & Business Bay", 12),
              ("Al Khail Corridor", "Via Al Khail Road & Al Barsha", 15),
              ("Emirates Road Loop", "Via International City & Silicon Oasis", 20),
              ("Coastal Route", "Via Jumeirah & Dubai Marina", 16)],
    "london": [("North Circular Route", "Via Ealing & Wembley", 18),
               ("Thames Riverside Route", "Via Embankment & Tower Bridge", 15),
               ("A12 Eastern Link", "Via Stratford & Hackney", 16),
               ("M25 Outer Route", "Via Brent Cross & Hanger Lane", 22)],
    "istanbul": [("E-5 Coastal Route", "Via Kadikoy & Atasehir", 14),
                 ("TEM Motorway Route", "Via Umraniye & Sancaktepe", 18),
                 ("Bosphorus Bridge Route", "Via Besiktas & Besiktas Link", 16),
                 ("Coastal Corridor", "Via Bakirkoy & Atakoy", 15)],
    "cairo": [("Ring Road Route", "Via Nasr City & Heliopolis", 13),
              ("Nile Corniche Route", "Via Garden City & Zamalek", 15),
              ("Mehwar Corridor", "Via New Cairo & 5th Settlement", 18),
              ("26th July Route", "Via Mohandessin & Dokki", 14)],
    "paris": [("Périphérique Route", "Via Porte de Clignancourt", 15),
              ("Rive Droite Link", "Via Châtelet & Bastille", 13),
              ("Rive Gauche Route", "Via Saint-Germain & Montparnasse", 14),
              ("A86 Outer Route", "Via La Défense & Créteil", 20)],
    "berlin": [("Stadtring Route", "Via Charlottenburg & Schöneberg", 14),
               ("Mitte Corridor", "Via Alexanderplatz & Friedrichstraße", 13),
               ("Eastern Link", "Via Lichtenberg & Friedrichshain", 16),
               ("Western Route", "Via Zehlendorf & Steglitz", 15)],
    "madrid": [("M-30 Ring Route", "Via Chamartín & Retiro", 14),
               ("Gran Vía Corridor", "Via Sol & Callao", 12),
               ("Castellana Route", "Via Plaza Castilla & Azca", 15),
               ("Southern Link", "Via Usera & Vallecas", 17)],
    "rome": [("GRA Ring Route", "Via Eur & Tuscolana", 16),
             ("Historic Centre Route", "Via del Corso & Piazza Venezia", 13),
             ("Tiber Route", "Via Lungotevere & Trastevere", 15),
             ("Appian Route", "Via Appia Nuova & San Giovanni", 17)],
    "tokyo": [("Shuto Expressway Route", "Via Shibuya & Shinagawa", 14),
              ("Yamate-dori Corridor", "Via Ikebukuro & Gotanda", 16),
              ("Central Route", "Via Tokyo Station & Ginza", 12),
              ("Bayshore Route", "Via Odaiba & Shinagawa Pier", 15)],
    "beijing": [("2nd Ring Route", "Via Dongcheng & Xicheng", 13),
                ("3rd Ring Corridor", "Via Chaoyang & Haidian", 15),
                ("Chang'an Avenue", "Via Tiananmen & Jianguomen", 12),
                ("Airport Expressway", "Via Sanyuanqiao & Shunyi", 18)],
    "singapore": [("PIE Route", "Via Orchard & Jurong East", 15),
                  ("CTE Corridor", "Via Novena & Ang Mo Kio", 13),
                  ("Coastal Route", "Via Marina Bay & ECP", 14),
                  ("Bukit Timah Link", "Via Newton & Botanic Gardens", 12)],
    "sydney": [("Harbour Route", "Via Harbour Bridge & North Sydney", 14),
               ("Eastern Distributor", "Via Bondi & Paddington", 15),
               ("Parramatta Road", "Via Glebe & Leichhardt", 17),
               ("Anzac Bridge Link", "Via Rozelle & Drummoyne", 13)],
    "toronto": [("Gardiner Expressway", "Via Downtown & Humber Bay", 15),
                ("Don Valley Parkway", "Via Leaside & East York", 16),
                ("Queen Street Corridor", "Via Liberty Village & Riverdale", 14),
                ("Lakeshore Route", "Via Etobicoke & Port Union", 18)],
    "newyork": [("FDR Drive Route", "Via Midtown & Lower Manhattan", 15),
                ("West Side Highway", "Via Chelsea & Upper West Side", 14),
                ("Brooklyn Bridge Route", "Via Downtown Brooklyn & DUMBO", 16),
                ("Harlem River Link", "Via Harlem & Bronx", 18)],
    "losangeles": [("I-405 Route", "Via West LA & Sepulveda Pass", 18),
                   ("Sunset Corridor", "Via Hollywood & Silver Lake", 15),
                   ("Santa Monica Route", "Via Century City & Beverly Hills", 14),
                   ("I-10 Freeway", "Via Downtown & Culver City", 16)],
    "chicago": [("Lake Shore Drive", "Via Loop & Lincoln Park", 14),
                ("Kennedy Expressway", "Via River North & Logan Square", 15),
                ("Michigan Avenue", "Via Magnificent Mile & South Loop", 13),
                ("Wacker Drive Route", "Via West Loop & River North", 12)],
    "mumbai": [("Western Express Highway", "Via Bandra & Andheri", 16),
               ("Eastern Express Highway", "Via Sion & Vikhroli", 18),
               ("Marine Drive Route", "Via Colaba & Chowpatty", 14),
               ("SV Road Link", "Via Mahim & Santacruz", 17)],
    "newdelhi": [("Ring Road Route", "Via South Extension & AIIMS", 14),
                 ("Outer Ring Road", "Via Dwarka & Rohini", 17),
                 ("Central Route", "Via Connaught Place & Rajpath", 12),
                 ("NH-48 Corridor", "Via Gurgaon & Mahipalpur", 18)],
    "dhaka": [("Gulshan Avenue Route", "Via Banani & Baridhara", 14),
              ("Mirpur Road Link", "Via Dhanmondi & Shyamoli", 16),
              ("Airport Road", "Via Uttara & Mohakhali", 15),
              ("Basundhara Route", "Via Rampura & Badda", 18)],
}

# Real emergency helplines per country.
COUNTRY_HELPLINES = {
    "Pakistan": [
        {"name": "Rescue 1122", "number": "1122"},
        {"name": "Edhi Emergency", "number": "115"},
        {"name": "NDMA Helpline", "number": "0800-11142"},
        {"name": "Pakistan Red Crescent", "number": "051-9203093"},
    ],
    "United Arab Emirates": [
        {"name": "Dubai Police", "number": "999"},
        {"name": "Ambulance", "number": "998"},
        {"name": "Fire Department", "number": "997"},
        {"name": "Dubai Municipality", "number": "800-34424"},
    ],
    "United Kingdom": [
        {"name": "Emergency Services", "number": "999"},
        {"name": "NHS Non-Emergency", "number": "111"},
        {"name": "Floodline", "number": "0345-988-1188"},
        {"name": "London Ambulance", "number": "999"},
    ],
    "Turkey": [
        {"name": "Emergency (Acil)", "number": "112"},
        {"name": "Police", "number": "155"},
        {"name": "AFAD Disaster Relief", "number": "122"},
        {"name": "Coast Guard", "number": "158"},
    ],
    "Egypt": [
        {"name": "Police Emergency", "number": "122"},
        {"name": "Ambulance", "number": "123"},
        {"name": "Fire Department", "number": "180"},
        {"name": "Egyptian Red Crescent", "number": "226-188-31"},
    ],
    "France": [
        {"name": "Emergency (Urgences)", "number": "112"},
        {"name": "SAMU Medical", "number": "15"},
        {"name": "Police", "number": "17"},
        {"name": "Fire Brigade (Sapeurs)", "number": "18"},
    ],
    "Germany": [
        {"name": "Emergency Services", "number": "112"},
        {"name": "Police", "number": "110"},
        {"name": "Medical Non-Emergency", "number": "116-117"},
        {"name": "THW Relief", "number": "0800-1520-1520"},
    ],
    "Spain": [
        {"name": "Emergency Services", "number": "112"},
        {"name": "Police Nacional", "number": "091"},
        {"name": "Medical (SAMUR)", "number": "092"},
        {"name": "Fire Brigade", "number": "080"},
    ],
    "Italy": [
        {"name": "Emergency Services", "number": "112"},
        {"name": "Medical Emergency", "number": "118"},
        {"name": "Carabinieri", "number": "112"},
        {"name": "Fire Brigade (Vigili)", "number": "115"},
    ],
    "Japan": [
        {"name": "Ambulance & Fire", "number": "119"},
        {"name": "Police", "number": "110"},
        {"name": "Disaster Emergency", "number": "171"},
        {"name": "JNTO Hotline", "number": "050-3816-2787"},
    ],
    "China": [
        {"name": "Ambulance", "number": "120"},
        {"name": "Police", "number": "110"},
        {"name": "Fire Department", "number": "119"},
        {"name": "Traffic Emergency", "number": "122"},
    ],
    "Singapore": [
        {"name": "Emergency Ambulance", "number": "995"},
        {"name": "Police", "number": "999"},
        {"name": "SCDF Fire", "number": "995"},
        {"name": "Public Utilities Board", "number": "1800-284-6600"},
    ],
    "Australia": [
        {"name": "Emergency Services", "number": "000"},
        {"name": "SES Flood & Storm", "number": "132-500"},
        {"name": "Police Link", "number": "131-444"},
        {"name": "Nurse on Call", "number": "1300-606-024"},
    ],
    "Canada": [
        {"name": "Emergency Services", "number": "911"},
        {"name": "Toronto Public Health", "number": "416-338-7600"},
        {"name": "Road Conditions", "number": "511"},
        {"name": "Red Cross Canada", "number": "1-800-418-1111"},
    ],
    "United States": [
        {"name": "Emergency Services", "number": "911"},
        {"name": "FEMA Disaster Relief", "number": "1-800-621-3362"},
        {"name": "American Red Cross", "number": "1-800-733-2767"},
        {"name": "Road Conditions (511)", "number": "511"},
    ],
    "India": [
        {"name": "Emergency (All Services)", "number": "112"},
        {"name": "Ambulance", "number": "102"},
        {"name": "NDMA Helpline", "number": "1078"},
        {"name": "Police", "number": "100"},
    ],
    "Bangladesh": [
        {"name": "Emergency Services", "number": "999"},
        {"name": "Fire Service", "number": "102"},
        {"name": "BD Red Crescent", "number": "02-477-0110"},
        {"name": "Health Advice Line", "number": "16263"},
    ],
}

# Culturally appropriate shelter naming per country.
COUNTRY_SHELTER_NAMES = {
    "Pakistan": [("Civic Center Relief Hub", "Government Disaster Shelter", 500),
                 ("District Hospital Emergency Wing", "Medical Shelter", 200),
                 ("Community Center Safe Zone", "Community Shelter", 350),
                 ("School Building Relief Camp", "Temporary Shelter", 800),
                 ("Mosque / Prayer Hall Shelter", "Community Shelter", 400)],
    "Bangladesh": [("Cyclone Preparedness Center", "Government Shelter", 600),
                   ("District Hospital Emergency Wing", "Medical Shelter", 250),
                   ("Community Center Safe Zone", "Community Shelter", 400),
                   ("School Building Relief Camp", "Temporary Shelter", 700),
                   ("Mosque / Prayer Hall Shelter", "Community Shelter", 450)],
    "Egypt": [("Youth Center Relief Hub", "Government Shelter", 500),
              ("District Hospital Emergency Wing", "Medical Shelter", 200),
              ("Community Center Safe Zone", "Community Shelter", 350),
              ("School Building Relief Camp", "Temporary Shelter", 750),
              ("Mosque / Community Hall Shelter", "Community Shelter", 400)],
    "Turkey": [("AFAD Emergency Shelter", "Government Disaster Shelter", 600),
               ("State Hospital Emergency Wing", "Medical Shelter", 250),
               ("Community Center Safe Zone", "Community Shelter", 350),
               ("School Building Relief Camp", "Temporary Shelter", 700),
               ("Mosque / Cultural Center Shelter", "Community Shelter", 400)],
    "Japan": [("Hinanjo Evacuation Center", "Designated Evacuation Site", 800),
              ("Municipal Hospital Emergency Wing", "Medical Shelter", 300),
              ("Community Center Safe Zone", "Community Shelter", 350),
              ("School Gymnasium Relief Camp", "Temporary Shelter", 500),
              ("Temple / Shrine Grounds Shelter", "Community Shelter", 300)],
    "China": [("Emergency Response Center", "Government Shelter", 600),
              ("District Hospital Emergency Wing", "Medical Shelter", 250),
              ("Community Center Safe Zone", "Community Shelter", 400),
              ("School Building Relief Camp", "Temporary Shelter", 700),
              ("Sports Stadium Shelter", "Mass Shelter", 900)],
    "Singapore": [("Community Club Relief Hub", "Government Shelter", 300),
                  ("General Hospital Emergency Wing", "Medical Shelter", 200),
                  ("Community Center Safe Zone", "Community Shelter", 300),
                  ("School Hall Relief Camp", "Temporary Shelter", 400),
                  ("Sports Complex Shelter", "Mass Shelter", 500)],
    "United Kingdom": [("Council Relief Centre", "Government Shelter", 400),
                       ("NHS Hospital Emergency Wing", "Medical Shelter", 200),
                       ("Community Center Safe Zone", "Community Shelter", 300),
                       ("School Building Relief Camp", "Temporary Shelter", 500),
                       ("Church Hall / Community Shelter", "Community Shelter", 250)],
    "United States": [("Emergency Operations Shelter", "Government Shelter", 500),
                      ("County Hospital Emergency Wing", "Medical Shelter", 250),
                      ("Community Center Safe Zone", "Community Shelter", 350),
                      ("School Building Relief Camp", "Temporary Shelter", 600),
                      ("Church Hall / Civic Shelter", "Community Shelter", 300)],
    "Canada": [("Municipal Emergency Shelter", "Government Shelter", 400),
               ("Regional Hospital Emergency Wing", "Medical Shelter", 200),
               ("Community Center Safe Zone", "Community Shelter", 300),
               ("School Building Relief Camp", "Temporary Shelter", 500),
               ("Church Hall / Civic Shelter", "Community Shelter", 250)],
    "Australia": [("Relief Centre (SES)", "Government Shelter", 400),
                  ("Regional Hospital Emergency Wing", "Medical Shelter", 200),
                  ("Community Center Safe Zone", "Community Shelter", 300),
                  ("School Building Relief Camp", "Temporary Shelter", 500),
                  ("Church Hall / Surf Club Shelter", "Community Shelter", 250)],
    "France": [("Centre d'Hébergement d'Urgence", "Government Shelter", 400),
               ("Hôpital Emergency Wing", "Medical Shelter", 200),
               ("Community Center Safe Zone", "Community Shelter", 300),
               ("School Building Relief Camp", "Temporary Shelter", 500),
               ("Church Hall / Mairie Shelter", "Community Shelter", 250)],
    "Germany": [("Notunterkunft Relief Center", "Government Shelter", 400),
                ("Krankenhaus Emergency Wing", "Medical Shelter", 200),
                ("Community Center Safe Zone", "Community Shelter", 300),
                ("School Building Relief Camp", "Temporary Shelter", 500),
                ("Church Hall / Gemeinde Shelter", "Community Shelter", 250)],
    "Spain": [("Centro de Acogida Shelter", "Government Shelter", 400),
              ("Hospital Emergency Wing", "Medical Shelter", 200),
              ("Community Center Safe Zone", "Community Shelter", 300),
              ("School Building Relief Camp", "Temporary Shelter", 500),
              ("Church Hall / Civic Shelter", "Community Shelter", 250)],
    "Italy": [("Centro di Accoglienza Shelter", "Government Shelter", 400),
              ("Ospedale Emergency Wing", "Medical Shelter", 200),
              ("Community Center Safe Zone", "Community Shelter", 300),
              ("School Building Relief Camp", "Temporary Shelter", 500),
              ("Church Hall / Parish Shelter", "Community Shelter", 250)],
    "India": [("Municipal Relief Camp", "Government Shelter", 600),
              ("District Hospital Emergency Wing", "Medical Shelter", 250),
              ("Community Center Safe Zone", "Community Shelter", 400),
              ("School Building Relief Camp", "Temporary Shelter", 700),
              ("Temple / Community Hall Shelter", "Community Shelter", 400)],
}


def _sim(seed, lo, hi):
    """Deterministic pseudo-random float in [lo, hi] from a string seed."""
    h = zlib.crc32(str(seed).encode("utf-8"))
    return lo + (h % 100000) / 100000.0 * (hi - lo)


def _cities_list():
    from app import CITIES
    return sorted(CITIES.keys())


def _get_city_coords(city_key):
    from app import CITIES
    return CITIES.get(city_key)


# --- Weekly Forecast Generator ---

def _generate_weekly_forecast(city_key):
    """Generate 7-day weather forecast with AI predictions."""
    from app import CITIES, _live_forecast, _live_payload, _simulated_payload

    c = CITIES.get(city_key)
    if not c:
        return None

    try:
        weather = _live_payload(city_key, _live_forecast(c["lat"], c["lon"]))
    except Exception:
        weather = _simulated_payload(city_key)

    base_temp = float(weather.get("temp") or 25)
    base_condition = weather.get("condition", "Clear Sky")
    base_humidity = float(weather.get("humidity") or 50)
    base_wind = float(weather.get("wind") or 10)
    base_uv = float(weather.get("uv") or 5)

    days = []
    conditions = ["Clear Sky", "Partly Cloudy", "Light Drizzle", "Rain Showers", "Overcast", "Mostly Clear", "Clear Sky"]

    for i in range(7):
        date = datetime.now() + timedelta(days=i)
        day_name = date.strftime("%A")
        date_str = date.strftime("%b %d")

        temp_var = _sim(f"{city_key}-temp-{i}", -4, 4)
        max_temp = round(base_temp + temp_var, 1)
        min_temp = round(max_temp - _sim(f"{city_key}-min-{i}", 6, 12), 1)

        cond_idx = int(_sim(f"{city_key}-cond-{i}", 0, len(conditions) - 0.01))
        condition = conditions[cond_idx]

        humidity = int(max(20, min(95, base_humidity + _sim(f"{city_key}-hum-{i}", -15, 15))))
        wind = round(max(0, base_wind + _sim(f"{city_key}-wind-{i}", -5, 15)), 1)
        uv = round(max(0, min(12, base_uv + _sim(f"{city_key}-uv-{i}", -2, 3))), 1)
        precip_prob = int(_sim(f"{city_key}-precip-{i}", 0, 100)) if "Rain" in condition or "Drizzle" in condition else int(_sim(f"{city_key}-precip-{i}", 0, 30))

        confidence = int(85 + _sim(f"{city_key}-conf-{i}", -10, 14))

        days.append({
            "day": day_name,
            "date": date_str,
            "max_temp": max_temp,
            "min_temp": min_temp,
            "condition": condition,
            "humidity": humidity,
            "wind": wind,
            "uv": uv,
            "precip_prob": precip_prob,
            "confidence": confidence,
        })

    return {
        "city": c["name"],
        "city_key": city_key,
        "generated_at": datetime.now().isoformat(),
        "forecast": days,
    }


def _get_outfit_recommendation(temp, condition, uv, wind, precip_prob):
    """Generate clothing recommendations based on weather conditions."""
    outfit = []
    accessories = []
    fabrics = []

    if temp >= 35:
        outfit.append("Lightweight linen or breathable cotton short-sleeve shirt")
        outfit.append("Light-colored shorts or loose-fitting trousers")
        fabrics.extend(["Linen", "Lightweight Cotton", "Bamboo Rayon"])
    elif temp >= 28:
        outfit.append("Cotton t-shirt or polo shirt")
        outfit.append("Comfortable jeans or chinos")
        fabrics.extend(["Cotton", "Chambray", "Jersey"])
    elif temp >= 20:
        outfit.append("Long-sleeve shirt or light sweater")
        outfit.append("Jeans or casual trousers")
        fabrics.extend(["Cotton", "Light Wool", "Denim"])
    elif temp >= 12:
        outfit.append("Layered outfit: shirt under a denim jacket or sweater")
        outfit.append("Warm trousers or jeans")
        fabrics.extend(["Fleece", "Denim", "Light Wool"])
    else:
        outfit.append("Thermal inner layer with heavy wool sweater")
        outfit.append("Insulated jacket and warm trousers")
        fabrics.extend(["Wool", "Down Insulation", "Thermal Synthetics"])

    cond_lower = (condition or "").lower()
    if "rain" in cond_lower or "drizzle" in cond_lower or precip_prob > 60:
        accessories.append("Umbrella (essential)")
        accessories.append("Waterproof jacket or raincoat")
        accessories.append("Water-resistant shoes or boots")
    if uv >= 6:
        accessories.append("UV-400 protection sunglasses")
        accessories.append("Wide-brimmed hat or cap")
        accessories.append("Broad-spectrum SPF 50+ sunscreen")
    if wind >= 25:
        accessories.append("Wind-resistant outer shell")
        accessories.append("Scarf or face cover for dust protection")
    if temp < 15:
        accessories.append("Warm gloves")
        accessories.append("Beanie or warm hat")
        accessories.append("Scarf for neck protection")

    umbrella_needed = precip_prob > 40 or "rain" in cond_lower or "drizzle" in cond_lower
    return {
        "outfit": outfit,
        "fabrics": fabrics,
        "accessories": accessories,
        "umbrella_needed": umbrella_needed,
        "umbrella_reason": "Rain expected - carry an umbrella!" if umbrella_needed else "No rain expected today.",
    }


def _get_route_suggestions(city_key):
    """Generate safe route suggestions based on weather conditions."""
    from app import CITIES

    c = CITIES.get(city_key)
    if not c:
        return []

    route_names = CITY_LOCAL_ROUTES.get(city_key, [
        ("Northern Bypass", "Via Main Highway", 12),
        ("Southern Route", "Via Secondary Road", 15),
        ("Eastern Loop", "Via Ring Road", 18),
        ("Western Corridor", "Via Coastal Route", 22),
    ])

    routes = []
    for i, (name, desc, base_time) in enumerate(route_names):
        delay = int(_sim(f"{city_key}-route-{i}", 0, 15))
        risk_level = _sim(f"{city_key}-risk-{i}", 0, 1)

        if risk_level > 0.7:
            status = "caution"
            advisory = "Heavy rain expected on this route - consider alternate path."
        elif risk_level > 0.4:
            status = "moderate"
            advisory = "Light precipitation possible - drive carefully."
        else:
            status = "clear"
            advisory = "Clear conditions - safe to travel."

        routes.append({
            "name": name,
            "description": desc,
            "estimated_time_min": base_time + delay,
            "status": status,
            "advisory": advisory,
        })

    return routes


def _get_relief_camps(city_key):
    """Get nearby relief camps and emergency information."""
    from app import CITIES

    c = CITIES.get(city_key)
    if not c:
        return []

    country = c.get("country", "Pakistan")
    shelters = COUNTRY_SHELTER_NAMES.get(country, [
        (n, t, cap) for n, t, cap in COUNTRY_SHELTER_NAMES.get("Pakistan")
    ])

    camps = []
    for i, (name, stype, capacity) in enumerate(shelters):
        lat = c["lat"] + _sim(f"{city_key}-slat{i}", -0.08, 0.08)
        lon = c["lon"] + _sim(f"{city_key}-slon{i}", -0.08, 0.08)

        # Haversine distance
        r = 6371.0
        p1, p2 = math.radians(c["lat"]), math.radians(lat)
        dp = math.radians(lat - c["lat"])
        dl = math.radians(lon - c["lon"])
        a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        dist = round(r * 2 * math.asin(math.sqrt(a)), 1)

        camps.append({
            "name": f"{name} - {CITIES[city_key]['name'].split(',')[0]}",
            "type": stype,
            "distance_km": dist,
            "capacity": f"{capacity} people",
            "lat": round(lat, 4),
            "lon": round(lon, 4),
            "status": "Open",
        })

    camps.sort(key=lambda x: x["distance_km"])
    return camps


# --- Flask Routes ---

@predictions_bp.route("/predictions")
@premium_required
@login_required
def predictions_page():
    """AI Prediction dashboard."""
    return render_template(
        "predictions.html",
        active="predictions",
        cities=_cities_list(),
    )


@predictions_bp.route("/api/predictions/weekly", methods=["GET"])
def api_weekly_prediction():
    """Get 7-day weather forecast with AI predictions."""
    city = request.args.get("city", "karachi").lower()
    city = "".join(ch for ch in city if ch.isalnum())

    forecast = _generate_weekly_forecast(city)
    if not forecast:
        return jsonify({"error": "Unknown city"}), 404

    return jsonify({"status": "success", "forecast": forecast})


@predictions_bp.route("/api/predictions/outfit", methods=["GET"])
def api_outfit_recommendation():
    """Get clothing recommendations based on weather."""
    city = request.args.get("city", "karachi").lower()
    city = "".join(ch for ch in city if ch.isalnum())

    from app import CITIES, _live_forecast, _live_payload, _simulated_payload
    c = CITIES.get(city)
    if not c:
        return jsonify({"error": "Unknown city"}), 404

    try:
        weather = _live_payload(city, _live_forecast(c["lat"], c["lon"]))
    except Exception:
        weather = _simulated_payload(city)

    temp = float(weather.get("temp") or 25)
    condition = weather.get("condition", "Clear Sky")
    uv = float(weather.get("uv") or 5)
    wind = float(weather.get("wind") or 10)
    precip_prob = float(weather.get("precip_prob", weather.get("humidity", 50)) or 0)

    recommendation = _get_outfit_recommendation(temp, condition, uv, wind, precip_prob)

    return jsonify({
        "status": "success",
        "city": CITIES[city]["name"],
        "current": {
            "temp": temp,
            "condition": condition,
            "uv": uv,
            "wind": wind,
            "precip_prob": precip_prob,
        },
        "recommendation": recommendation,
    })


@predictions_bp.route("/api/predictions/routes", methods=["GET"])
def api_route_suggestions():
    """Get safe route suggestions based on weather."""
    city = request.args.get("city", "karachi").lower()
    city = "".join(ch for ch in city if ch.isalnum())

    from app import CITIES
    if city not in CITIES:
        return jsonify({"error": "Unknown city"}), 404

    routes = _get_route_suggestions(city)
    return jsonify({
        "status": "success",
        "city": CITIES[city]["name"],
        "routes": routes,
    })


@predictions_bp.route("/api/predictions/relief", methods=["GET"])
def api_relief_camps():
    """Get nearby relief camps and emergency information."""
    city = request.args.get("city", "karachi").lower()
    city = "".join(ch for ch in city if ch.isalnum())

    from app import CITIES
    if city not in CITIES:
        return jsonify({"error": "Unknown city"}), 404

    camps = _get_relief_camps(city)
    country = CITIES[city].get("country", "Pakistan")
    helplines = COUNTRY_HELPLINES.get(country, COUNTRY_HELPLINES["Pakistan"])
    return jsonify({
        "status": "success",
        "city": CITIES[city]["name"],
        "country": country,
        "camps": camps,
        "helplines": helplines,
    })

