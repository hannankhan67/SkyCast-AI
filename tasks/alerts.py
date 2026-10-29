"""
Background task definitions for SkyCast AI.

Each task uses the shared Celery app instance from celery_app.py to avoid
circular imports between the web process and the worker process.
"""

import logging
from .celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="tasks.evaluate_alert_rules")
def evaluate_alert_rules_async(telemetry_batch):
    """
    Evaluates alert rules asynchronously to prevent blocking incoming HTTP requests.

    Args:
        telemetry_batch: List of dicts with 'temperature' and 'aqi' keys.

    Returns:
        dict with status and count of triggered alerts.
    """
    triggered_alerts = []

    for record in telemetry_batch:
        temp = record.get('temperature', 0)
        aqi = record.get('aqi', 0)

        if temp >= 45.0 or aqi >= 300:
            triggered_alerts.append({
                "city": record.get("city"),
                "severity": "CRITICAL" if temp >= 47 or aqi >= 350 else "WARNING",
                "condition": f"Temp: {temp}°C, AQI: {aqi}"
            })

    logger.info(f"Evaluated {len(telemetry_batch)} records, {len(triggered_alerts)} alerts triggered.")
    return {"status": "processed", "triggered_count": len(triggered_alerts)}