"""SkyCast AI — Forecast backtesting (drift) engine.

Computes city-level MAE / RMSE for temperature and AQI by comparing stored
forecasts against observed actuals, then persists daily snapshots to the
MongoDB ``model_drift_metrics`` collection (optional at runtime).

Record sources, tried in order (first one with in-window data wins):
  1. MongoDB ``forecast_verification`` — populated hourly by
     scripts/sync_forecast_actuals.py (temperature + AQI pairs).
  2. MongoDB ``weather_logs`` — the generic forecast-log collection; used
     automatically whenever it contains matching documents.
  3. SQLite ``forecast_verification`` — seeded by seed_drift_data.py
     (temperature pairs only; AQI metrics will be null for this source).

The mathematical helpers (``mae`` / ``rmse``) are pure functions with no
database dependency so they can be unit-tested with synthetic data — see
verify_drift_engine.py.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

import database

logger = logging.getLogger(__name__)

#: Fields a normalised forecast record carries.
RECORD_FIELDS = (
    "city", "timestamp", "predicted_temp", "actual_temp",
    "predicted_aqi", "actual_aqi",
)


def get_mongo_db():
    """Return the app-wide Mongo database handle, or None when unavailable.

    Reuses the client Flask bound at boot (``app._mongo_db``) so connection
    settings and credentials stay identical to every other Mongo feature.
    The import is deferred because ``app`` imports this package's routes.
    """
    try:
        from app import _mongo_db  # bound at boot only after a successful ping
        return _mongo_db
    except Exception:  # pragma: no cover - circular import / teardown guard
        return None


# ---------------------------------------------------------------------------
# Pure math helpers
# ---------------------------------------------------------------------------

def mae(actual: Sequence[float], predicted: Sequence[float]) -> float:
    """Mean Absolute Error — MAE = (1/n) * Σ |y_i − ŷ_i|.

    Args:
        actual: Observed values (y_i).
        predicted: Forecast values (ŷ_i), same order and length.

    Returns:
        The mean of absolute errors.

    Raises:
        ValueError: when lengths differ or no observations are given.
    """
    if len(actual) != len(predicted):
        raise ValueError("actual and predicted must have the same length")
    n = len(actual)
    if n == 0:
        raise ValueError("at least one observation is required")
    return sum(abs(a - p) for a, p in zip(actual, predicted)) / n


def rmse(actual: Sequence[float], predicted: Sequence[float]) -> float:
    """Root Mean Square Error — RMSE = sqrt((1/n) * Σ (y_i − ŷ_i)²).

    Penalises large errors more heavily than MAE because the differences
    are squared before averaging.

    Raises:
        ValueError: when lengths differ or no observations are given.
    """
    if len(actual) != len(predicted):
        raise ValueError("actual and predicted must have the same length")
    n = len(actual)
    if n == 0:
        raise ValueError("at least one observation is required")
    return math.sqrt(
        sum((a - p) ** 2 for a, p in zip(actual, predicted)) / n
    )


# ---------------------------------------------------------------------------
# Record loading (Mongo sources first, SQLite fallback)
# ---------------------------------------------------------------------------

def _parse_ts(value: Any) -> Optional[datetime]:
    """Parse 'YYYY-MM-DDTHH:MM[:SS]' style timestamps; None when unusable."""
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    for size in (19, 16):  # with seconds / minutes only
        try:
            return datetime.fromisoformat(text[:size])
        except ValueError:
            continue
    return None


def _norm_record(doc: Any) -> Optional[dict]:
    """Map a Mongo document or SQLite row onto the common record shape."""
    try:
        getter = doc.get if hasattr(doc, "get") else (lambda k, d=None: doc[k])
        rec = {
            "city": str(getter("city") or "").strip(),
            "timestamp": _parse_ts(getter("timestamp")),
            "predicted_temp": getter("predicted_temp"),
            "actual_temp": getter("actual_temp"),
            "predicted_aqi": getter("predicted_aqi"),
            "actual_aqi": getter("actual_aqi"),
        }
    except Exception:
        return None
    if not rec["city"] or rec["timestamp"] is None:
        return None
    if rec["predicted_temp"] is None and rec["actual_temp"] is None:
        return None
    return rec


def _mongo_records(coll_name: str, limit: int) -> List[dict]:
    """Newest ``limit`` records from a Mongo collection ([] when offline)."""
    out: List[dict] = []
    try:
        db = get_mongo_db()
        if db is None:
            return out
        cursor = db[coll_name].find({}, {"_id": 0}).sort("_id", -1).limit(limit)
        out = [r for r in (_norm_record(doc) for doc in cursor) if r]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Mongo source %s unavailable: %s", coll_name, exc)
    return out


def _sqlite_records(limit: int) -> List[dict]:
    """Newest records from the SQLite forecast_verification table."""
    out: List[dict] = []
    try:
        with database._connect() as conn:
            rows = conn.execute(
                "SELECT city, timestamp, predicted_temp, actual_temp "
                "FROM forecast_verification ORDER BY id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        out = [r for r in (_norm_record(dict(row)) for row in rows) if r]
    except Exception as exc:  # noqa: BLE001
        logger.warning("SQLite forecast_verification unavailable: %s", exc)
    return out


def _load_with_source(hours: int = 24) -> Tuple[List[dict], str]:
    """Load recent records; returns ``(records, source_name)``.

    A +3h grace is added to the cutoff because seed/worker timestamps may
    be written in local rather than UTC wall-clock time.
    """
    cutoff = datetime.now() - timedelta(hours=hours + 3)
    for source, records in (
        ("mongo:forecast_verification", _mongo_records("forecast_verification", 5000)),
        ("mongo:weather_logs", _mongo_records("weather_logs", 5000)),
        ("sqlite:forecast_verification", _sqlite_records(5000)),
    ):
        recent = [r for r in records if r["timestamp"] >= cutoff]
        if recent:
            return recent, source
    return [], "none"


def load_recent_records(hours: int = 24) -> List[dict]:
    """Public loader — recent normalised records (empty list when none)."""
    records, _source = _load_with_source(hours=hours)
    return records


# ---------------------------------------------------------------------------
# Backtesting computation + persistence
# ---------------------------------------------------------------------------

def compute_city_metrics(records: List[dict]) -> List[dict]:
    """Per-city MAE / RMSE snapshot from normalised records.

    Temperature and AQI are scored independently — a record without an AQI
    pair still contributes to the temperature metrics. Values are rounded
    to 4 decimals; a metric group with no usable pairs is reported as None.
    """
    now = datetime.now()
    by_city: Dict[str, List[dict]] = {}
    for rec in records:
        by_city.setdefault(rec["city"], []).append(rec)

    metrics: List[dict] = []
    for city, recs in sorted(by_city.items()):
        temp_pairs = [
            (float(r["actual_temp"]), float(r["predicted_temp"]))
            for r in recs
            if r["actual_temp"] is not None and r["predicted_temp"] is not None
        ]
        aqi_pairs = [
            (float(r["actual_aqi"]), float(r["predicted_aqi"]))
            for r in recs
            if r["actual_aqi"] is not None and r["predicted_aqi"] is not None
        ]

        temperature = None
        if temp_pairs:
            actuals = [a for a, _ in temp_pairs]
            preds = [p for _, p in temp_pairs]
            temperature = {
                "mae": round(mae(actuals, preds), 4),
                "rmse": round(rmse(actuals, preds), 4),
            }

        air_quality = None
        if aqi_pairs:
            actuals = [a for a, _ in aqi_pairs]
            preds = [p for _, p in aqi_pairs]
            air_quality = {
                "mae": round(mae(actuals, preds), 4),
                "rmse": round(rmse(actuals, preds), 4),
            }

        metrics.append({
            "city": city,
            "window_date": now.date().isoformat(),
            "window_hours": 24,
            "sample_size_temp": len(temp_pairs),
            "sample_size_aqi": len(aqi_pairs),
            "temperature": temperature,
            "air_quality": air_quality,
            "computed_at": now.isoformat(timespec="seconds"),
        })
    return metrics


def store_metrics(metrics: List[dict]) -> int:
    """Upsert daily snapshots into Mongo ``model_drift_metrics``.

    Deduplicates on (city, window_date) so repeated runs on the same day
    refresh the snapshot rather than duplicate it. Returns the write count
    (0 when Mongo is unavailable).
    """
    if not metrics:
        return 0
    db = get_mongo_db()
    if db is None:
        logger.info("Mongo unavailable — %d snapshots not persisted", len(metrics))
        return 0
    written = 0
    try:
        coll = db["model_drift_metrics"]
        coll.create_index([("city", 1), ("window_date", 1)], unique=True)
        for doc in metrics:
            key = {"city": doc["city"], "window_date": doc["window_date"]}
            coll.update_one(key, {"$set": dict(doc)}, upsert=True)
            written += 1
    except Exception as exc:  # noqa: BLE001
        logger.warning("storing drift metrics failed: %s", exc)
    return written


def backtest(hours: int = 24, store: bool = True) -> dict:
    """One backtest cycle: load records -> compute metrics -> persist."""
    records, source = _load_with_source(hours=hours)
    metrics = compute_city_metrics(records)
    stored = store_metrics(metrics) if store else 0
    return {
        "source": source,
        "window_hours": hours,
        "sample_size": len(records),
        "cities": len(metrics),
        "metrics": metrics,
        "stored": stored,
    }


def recent_metrics(city: Optional[str] = None, days: int = 7) -> List[dict]:
    """Stored daily snapshots for the trailing ``days`` days (oldest first)."""
    db = get_mongo_db()
    if db is None:
        return []
    cutoff = (datetime.now() - timedelta(days=days)).date().isoformat()
    query: Dict[str, dict] = {"window_date": {"$gte": cutoff}}
    if city:
        query["city"] = city
    try:
        cursor = (
            db["model_drift_metrics"]
            .find(query, {"_id": 0})
            .sort("window_date", 1)
            .limit(365)
        )
        return list(cursor)
    except Exception as exc:  # noqa: BLE001
        logger.warning("reading drift metrics failed: %s", exc)
        return []