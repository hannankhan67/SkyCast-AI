"""SkyCast AI — Redis response caching with graceful degradation.

Usage:

    from services.cache import cache_response

    @mypage_bp.route("/api/expensive")
    @cache_response(ttl_seconds=300)
    def expensive_view():
        ...

Only successful (HTTP 200) JSON responses are cached. The cache key hashes
the request method, path, sorted query parameters and JSON body, so two
different queries never collide. When Redis is not installed, not
configured, or unreachable, the decorator silently falls through to the
wrapped view — caching is a pure optimisation here, never a dependency.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from functools import wraps
from typing import Any, Callable, Optional

from flask import jsonify, request

logger = logging.getLogger(__name__)

try:  # redis-py is optional; the decorator degrades to pass-through without it
    import redis  # type: ignore
except ImportError:  # pragma: no cover
    redis = None  # type: ignore

_KEY_PREFIX = "skycast:cache:"
#: When Redis is down, wait this long before probing again (seconds) so a
#: dead Redis cannot add a connection timeout to every request.
_RETRY_INTERVAL_SECONDS = 30.0

_client: Optional[Any] = None
_down_until = 0.0


def _get_redis() -> Optional[Any]:
    """Lazily connect to Redis; returns None while it is unavailable.

    Reads REDIS_URL from the environment with a standard local fallback.
    Connection failures set a retry deadline so repeated requests skip the
    probe until _RETRY_INTERVAL_SECONDS have elapsed.
    """
    global _client, _down_until
    now = time.monotonic()
    if _client is not None:
        return _client
    if now < _down_until:
        return None
    if redis is None:
        logger.warning("redis-py not installed — response caching disabled")
        _down_until = now + _RETRY_INTERVAL_SECONDS
        return None
    url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    try:
        candidate = redis.Redis.from_url(
            url,
            socket_connect_timeout=1,
            socket_timeout=1,
            decode_responses=True,
        )
        candidate.ping()
        _client = candidate
        logger.info("Redis response cache connected: %s", url)
        return _client
    except Exception as exc:  # noqa: BLE001 - any failure disables caching
        logger.warning("Redis unavailable (%s) — caching disabled for %ds", exc,
                       int(_RETRY_INTERVAL_SECONDS))
        _down_until = now + _RETRY_INTERVAL_SECONDS
        return None


def build_cache_key() -> str:
    """Stable SHA-256 cache key for the current request.

    Incorporates the HTTP method, route path, sorted query parameters and
    a hash of the raw JSON body, so identical logical requests share one
    entry while any parameter change produces a distinct key.
    """
    args = sorted((request.args or {}).items(multi=True))
    body = request.get_data(cache=True, as_text=True) or ""
    raw = "|".join([
        request.method,
        request.path,
        json.dumps(args, sort_keys=True, default=str),
        hashlib.sha256(body.encode("utf-8")).hexdigest() if body else "-",
    ])
    return _KEY_PREFIX + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def cache_response(ttl_seconds: int = 300) -> Callable:
    """Cache a JSON view response in Redis for ``ttl_seconds``.

    Behaviour:
      * Redis unavailable (not installed / offline / timeout) -> the view
        always runs; the decorator is a no-op.
      * Cache hit on a stored 200 payload -> returned without calling the
        view.
      * View returns a 200 JSON response -> stored via SETEX.
      * Anything else (non-200, non-JSON) -> never cached.
      * Every Redis error is caught and logged; the live response is
        always returned to the caller regardless.
    """
    def decorator(view: Callable) -> Callable:
        @wraps(view)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            client = _get_redis()
            if client is None:
                return view(*args, **kwargs)

            key = build_cache_key()
            try:
                cached = client.get(key)
                if cached:
                    envelope = json.loads(cached)
                    response = jsonify(envelope.get("body"))
                    response.status_code = int(envelope.get("status", 200))
                    return response
            except Exception as exc:  # noqa: BLE001
                logger.warning("cache read failed for %s: %s", key, exc)

            response = view(*args, **kwargs)

            try:
                if response.status_code == 200:
                    payload = response.get_json(silent=True)
                    if payload is not None:
                        envelope = json.dumps(
                            {"status": response.status_code, "body": payload}
                        )
                        client.setex(key, int(ttl_seconds), envelope)
            except Exception as exc:  # noqa: BLE001
                logger.warning("cache write failed for %s: %s", key, exc)

            return response
        return wrapped
    return decorator