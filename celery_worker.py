#!/usr/bin/env python3
"""
SkyCast AI — Celery worker entry point.

Usage:
    python celery_worker.py
or with Celery CLI directly:
    celery -A tasks worker --loglevel=info
"""

import os
import sys

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tasks import celery_app


if __name__ == '__main__':
    celery_app.worker_main(['worker', '--loglevel=info'])