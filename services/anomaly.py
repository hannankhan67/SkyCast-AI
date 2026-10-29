"""SkyCast AI — Z-score microclimate anomaly detector.

For every city, computes the population mean (μ) and standard deviation
(σ) of the trailing 30 days of observed temperature and AQI, then flags
any observation whose Z-score

    Z = (x − μ) / σ

satisfies |Z| ≥ 2.5 (about 1.2% of a normal distribution — rare enough to
be interesting, common enough to survive small samples). Flagged records
are upserted into the MongoDB ``climate_anomalies`` collection.

`zscore` and `mean_std` are pure functions, unit-tested in
verify_drift_engine.py without any database.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

from services.drift_engine import _load_with_source, get_mongo_db

logger = logging.getLogger(__name__)

#: |Z| at or above this value is flagged (spec default).
DEFAULT_THRESHOLD = 2.5
#: |Z| at or above this is additionally marked "extreme".
EXTREME_THRESHOLD = 3.0


# ---------------------------------------------------------------------------
# Pure math helpers
# ---------------------------------------------------------------------------

def mean_std(values: Sequence[float]) -> Tuple[float, float]:
    """Population mean μ and standard deviation σ = sqrt((1/n) Σ (x−μ)²).

    Args:
        values: Observations in the rolling window.

    Returns:
        ``(mu, sigma)`` as floats.

    Raises:
        ValueError: when ``values`` is empty.
    """
    n = len(values)
    if n == 0:
        raise ValueError("at least one value is required")
    mu = sum(values) / n
    variance = sum((v - mu) ** 2 for v in values) / n
    return mu, variance ** 0.5


def zscore(value: float, mean: float, std: float) -> float:
    """Standard score Z = (x − μ) / σ.

    Returns 0.0 for flat series (σ ≈ 0) so a constant climate can never
    produce a division-by-zero or a spurious anomaly.
    """
    if std <= 1e-12:
        return 0.0
    return (value - mean) / std


# ---------------------------------------------------------------------------
# Detection + persistence
# ---------------------------------------------------------------------------

def detect_anomalies(
    days: int = 30,
    threshold: float = DEFAULT_THRESHOLD,
    records: Optional[List[dict]] = None,
) -> List[dict]:
    """Flag observations whose |Z| ≥ ``threshold`` per city and metric.

    Args:
        days: Rolling window length in days (default 30).
        threshold: Absolute Z-score cutoff (default 2.5).
        records: Optional pre-loaded records — skips the source resolver
            entirely (used by the test suite with synthetic data).

    Returns:
        Anomaly dicts carrying city, metric, value, window statistics and
        the computed Z-score.
    """
    if records is None:
        records, _source = _load_with_source(hours=days * 24)

    by_city: Dict[str, List[dict]] = {}
    for rec in records:
        by_city.setdefault(rec["city"], []).append(rec)

    now_iso = datetime.now().isoformat(timespec="seconds")
    flagged: List[dict] = []

    for city, recs in by_city.items():
        series = {
            "temperature": [
                (r["timestamp"], float(r["actual_temp"]))
                for r in recs
                if r["actual_temp"] is not None
            ],
            "air_quality": [
                (r["timestamp"], float(r["actual_aqi"]))
                for r in recs
                if r["actual_aqi"] is not None
            ],
        }
        for metric, points in series.items():
            if len(points) < 2:
                continue  # σ of a single sample is meaningless
            values = [v for _, v in points]
            mu, sigma = mean_std(values)
            for ts, value in points:
                z = zscore(value, mu, sigma)
                if abs(z) < threshold:
                    continue
                flagged.append({
                    "city": city,
                    "metric": metric,
                    "timestamp": ts.isoformat(timespec="seconds"),
                    "value": round(value, 2),
                    "mean": round(mu, 2),
                    "std": round(sigma, 2),
                    "z_score": round(z, 3),
                    "severity": "extreme" if abs(z) >= EXTREME_THRESHOLD else "high",
                    "detected_at": now_iso,
                })
    return flagged


def store_anomalies(anomalies: List[dict]) -> int:
    """Upsert anomalies into Mongo ``climate_anomalies``.

    Deduplicates on (city, timestamp, metric) so re-running detection over
    an overlapping window never creates duplicate documents. Returns the
    write count (0 when Mongo is unavailable).
    """
    if not anomalies:
        return 0
    db = get_mongo_db()
    if db is None:
        logger.info("Mongo unavailable — %d anomalies not persisted", len(anomalies))
        return 0
    written = 0
    try:
        coll = db["climate_anomalies"]
        coll.create_index(
            [("city", 1), ("timestamp", 1), ("metric", 1)], unique=True
        )
        for item in anomalies:
            key = {
                "city": item["city"],
                "timestamp": item["timestamp"],
                "metric": item["metric"],
            }
            coll.update_one(key, {"$set": dict(item)}, upsert=True)
            written += 1
    except Exception as exc:  # noqa: BLE001
        logger.warning("storing anomalies failed: %s", exc)
    return written


def recent_anomalies(
    city: Optional[str] = None,
    days: int = 7,
    limit: int = 50,
) -> List[dict]:
    """Most recent stored anomalies, newest observation first."""
    db = get_mongo_db()
    if db is None:
        return []
    cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    query: Dict[str, dict] = {"timestamp": {"$gte": cutoff}}
    if city:
        query["city"] = city
    try:
        cursor = (
            db["climate_anomalies"]
            .find(query, {"_id": 0})
            .sort("timestamp", -1)
            .limit(int(limit))
        )
        return list(cursor)
    except Exception as exc:  # noqa: BLE001
        logger.warning("reading anomalies failed: %s", exc)
        return []