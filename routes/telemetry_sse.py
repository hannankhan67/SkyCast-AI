"""SkyCast AI — Server-Sent Events live telemetry stream.

Streams REAL performance metrics computed from the SQLite ``api_requests``
table (p50/p95/p99 latency, 5xx error rate, requests/second over a rolling
5-minute window) — satisfying the real-time processing requirement with
live data instead of placeholders. Gated by the ``ANALYST_METRICS``
permission bit: analysts and admins only (401/403 otherwise).
"""

import json
import logging
import time
from datetime import datetime, timedelta
from typing import List

from flask import Blueprint, Response

import database
from security.permissions import require_permission, Permission

logger = logging.getLogger(__name__)

sse_bp = Blueprint('sse_telemetry', __name__)

WINDOW_MINUTES = 5
STREAM_INTERVAL_SECONDS = 2


def _percentile(sorted_values: List[float], q: float) -> float:
    """q-quantile (0..1) of an ascending list; 0.0 when empty."""
    if not sorted_values:
        return 0.0
    idx = min(len(sorted_values) - 1,
              max(0, int(round(q * (len(sorted_values) - 1)))))
    return sorted_values[idx]


def compute_live_metrics() -> dict:
    """Compute live latency/error metrics from the api_requests table.

    Returns a JSON-ready dict with p50/p95/p99 latency (ms), 5xx error
    rate and requests/second over the rolling window. Any failure logs
    and returns the zeroed payload — telemetry must never break a stream.
    """
    payload = {
        "timestamp": time.time(),
        "window_minutes": WINDOW_MINUTES,
        "latency": {"p50": 0.0, "p95": 0.0, "p99": 0.0},
        "error_rate_5xx": 0.0,
        "requests_per_sec": 0.0,
        "samples": 0,
    }
    try:
        cutoff = (datetime.now() - timedelta(minutes=WINDOW_MINUTES)
                  ).isoformat(timespec="seconds")
        with database._connect() as conn:
            rows = conn.execute(
                "SELECT duration_ms, status FROM api_requests "
                "WHERE created_at >= ? ORDER BY id DESC LIMIT 5000",
                (cutoff,),
            ).fetchall()
        durations = sorted(
            float(r["duration_ms"]) for r in rows
            if r["duration_ms"] is not None
        )
        n = len(rows)
        payload["samples"] = n
        payload["latency"] = {
            "p50": round(_percentile(durations, 0.50), 2),
            "p95": round(_percentile(durations, 0.95), 2),
            "p99": round(_percentile(durations, 0.99), 2),
        }
        errors = sum(1 for r in rows
                     if r["status"] is not None and r["status"] >= 500)
        payload["error_rate_5xx"] = round(errors / n, 4) if n else 0.0
        payload["requests_per_sec"] = round(n / (WINDOW_MINUTES * 60.0), 3) if n else 0.0
    except Exception as exc:  # noqa: BLE001
        logger.warning("live metrics computation failed: %s", exc)
    return payload


def generate_telemetry_stream():
    """Yield an SSE frame with freshly computed metrics every tick."""
    while True:
        try:
            yield "data: %s\n\n" % json.dumps(compute_live_metrics())
        except Exception as exc:  # noqa: BLE001
            logger.warning("SSE frame failed: %s", exc)
            yield "event: ping\ndata: {}\n\n"
        time.sleep(STREAM_INTERVAL_SECONDS)

@sse_bp.route('/api/analyst/telemetry/stream', methods=['GET'])
@require_permission(Permission.ANALYST_METRICS)
def stream_telemetry():
    """GET /api/analyst/telemetry/stream — live SSE telemetry (analyst+)."""
    return Response(
        generate_telemetry_stream(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no'
        }
    )