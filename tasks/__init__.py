"""
SkyCast AI — Celery tasks package.

Exposes the Celery app and registered tasks so both the web process and
the worker process can import them.
"""

from .celery_app import celery_app
from .alerts import evaluate_alert_rules_async

__all__ = ['celery_app', 'evaluate_alert_rules_async']