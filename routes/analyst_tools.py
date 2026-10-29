import os
import math
from flask import Blueprint, request, jsonify
from security.permissions import require_permission, Permission

analyst_bp = Blueprint('analyst_tools', __name__)

@analyst_bp.route('/api/analyst/alerts/dry-run', methods=['POST'])
@require_permission(Permission.ANALYST_METRICS)
def alert_dry_run():
    """
    Evaluates mock weather conditions against user-defined alert thresholds.
    Payload: { "rules": [...], "mock_input": { "temperature": 47, "wind_speed": 90, "aqi": 350 } }
    """
    data = request.get_json() or {}
    rules = data.get('rules', [])
    mock = data.get('mock_input', {})

    triggered = []
    for rule in rules:
        field = rule.get('field')
        operator = rule.get('operator')
        threshold = rule.get('threshold')
        severity = rule.get('severity', 'WARNING')

        val = mock.get(field)
        if val is None:
            continue

        is_match = False
        if operator == '>' and val > threshold:
            is_match = True
        elif operator == '>=' and val >= threshold:
            is_match = True
        elif operator == '<' and val < threshold:
            is_match = True
        elif operator == '<=' and val <= threshold:
            is_match = True
        elif operator == '==' and val == threshold:
            is_match = True

        if is_match:
            triggered.append({
                "rule_name": rule.get('name'),
                "severity": severity,
                "field": field,
                "current_value": val,
                "threshold": threshold
            })

    return jsonify({
        "status": "success",
        "total_evaluated": len(rules),
        "triggered_rules": triggered
    }), 200


@analyst_bp.route('/api/analyst/composite-index/calculate', methods=['POST'])
@require_permission(Permission.ANALYST_METRICS)
def calculate_composite_index():
    """
    Computes custom composite indicators (e.g., Heat Stress Index, Wildfire Danger Rating).
    Payload: { "index_type": "heat_stress", "temperature": 38, "humidity": 65, "wind_speed": 12 }
    """
    data = request.get_json() or {}
    index_type = data.get('index_type')
    T = data.get('temperature', 0)
    RH = data.get('humidity', 0)
    W = data.get('wind_speed', 0)

    result_score = 0
    category = "LOW"

    if index_type == "heat_stress":
        if T <= 273.15 or RH == 0:
            result_score = float(T)
        else:
            e_s = 6.1094 * math.pow(10, (7.625 * T) / (240.925 + T))
            result_score = 1.07 * T - 0.033 * RH * (e_s - 10) + 0.9
        if result_score > 54:
            category = "EXTREME_DANGER"
        elif result_score > 41:
            category = "DANGER"
        elif result_score > 32:
            category = "EXTREME_CAUTION"
        elif result_score > 27:
            category = "CAUTION"

    elif index_type == "wildfire_danger":
        if RH > 0:
            result_score = (T * 0.4) + ((100 - RH) * 0.4) + (W * 0.2)
        else:
            result_score = (T * 0.4) + (W * 0.2)
        category = "HIGH" if result_score > 60 else ("MODERATE" if result_score > 40 else "LOW")

    elif index_type == "crop_thermal_stress":
        result_score = T - (0.05 * RH) + (0.02 * W)
        category = "SEVERE" if result_score > 35 else ("MODERATE" if result_score > 28 else "LOW")

    else:
        return jsonify({"error": f"Unsupported index_type: {index_type}"}), 400

    return jsonify({
        "index_type": index_type,
        "score": round(result_score, 2),
        "category": category
    }), 200


@analyst_bp.route('/api/analyst/export/geojson', methods=['POST'])
@require_permission(Permission.ANALYST_EXPORT)
def export_geojson_bbox():
    """
    Queries spatial logs within a bounding box and returns valid GeoJSON.
    Payload: { "bbox": [min_lon, min_lat, max_lon, max_lat] }
    """
    data = request.get_json() or {}
    bbox = data.get('bbox')

    if not bbox or len(bbox) != 4:
        return jsonify({"error": "Invalid bounding box coordinate format"}), 400

    query = {
        "location": {
            "$geoWithin": {
                "$box": [
                    [bbox[0], bbox[1]],
                    [bbox[2], bbox[3]]
                ]
            }
        }
    }

    try:
        from database import mongo_db
        cursor = mongo_db.weather_logs.find(query, {"_id": 0}).limit(1000)
    except Exception as e:
        return jsonify({"error": "MongoDB unavailable", "detail": str(e)}), 503

    features = []
    for doc in cursor:
        coords = doc.get("location", {}).get("coordinates", [0, 0])
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": coords},
            "properties": {
                "city": doc.get("city"),
                "temperature": doc.get("temperature"),
                "aqi": doc.get("aqi"),
                "timestamp": doc.get("timestamp")
            }
        })

    return jsonify({"type": "FeatureCollection", "features": features}), 200