"""SkyCast AI — Climate trend prediction (regression model).

Trains a per-city linear trend model over the trailing 30 days of ingested
observations (``weather_observations``) and forecasts the temperature
``horizon`` hours ahead. Uses scikit-learn's ``LinearRegression`` when the
library is importable (same optional-import pattern as ``ml_model.py``)
and falls back to the closed-form least-squares solver in
``services.mapreduce`` otherwise, so the feature never hard-depends on a
native wheel.

Model refresh policy: models are stateless and retrained on every request
from the freshest stored observations — "regularly updated from the latest
available data" by construction. With <= 30 days of history this is a
few-thousand-row fit that runs in milliseconds; swap to a cached/
incremental trainer if datasets grow beyond that.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from services.ingest import load_observations
from services.mapreduce import linear_trend

logger = logging.getLogger(__name__)

try:  # optional dependency, same pattern as ml_model.py
    from sklearn.linear_model import LinearRegression  # type: ignore

    _SKLEARN = True
except Exception:  # pragma: no cover - fallback path
    _SKLEARN = False

_MIN_TRAINING_POINTS = 4


def _series(
    records: List[dict], city: Optional[str] = None
) -> List[Tuple[datetime, float]]:
    """Extract sorted (timestamp, temperature) pairs; None values dropped."""
    points: List[Tuple[datetime, float]] = []
    for rec in records:
        if city and rec.get("city") != city:
            continue
        temp = rec.get("temperature")
        if temp is None:
            continue
        try:
            ts = datetime.fromisoformat(str(rec["timestamp"])[:19])
        except (ValueError, TypeError, KeyError):
            continue
        points.append((ts, float(temp)))
    points.sort(key=lambda pair: pair[0])
    return points


def _fit_sklearn(xs: List[float], ys: List[float]) -> Tuple[float, float, float]:
    """Fit via scikit-learn; returns (slope_per_day, intercept, r_squared)."""
    model = LinearRegression()
    model.fit([[x] for x in xs], ys)
    slope = float(model.coef_[0])
    intercept = float(model.intercept_)
    preds = [slope * x + intercept for x in xs]
    my = sum(ys) / len(ys)
    ss_res = sum((y - p) ** 2 for y, p in zip(ys, preds))
    ss_tot = sum((y - my) ** 2 for y in ys)
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0
    return slope, intercept, max(0.0, min(1.0, r_squared))


def _fit_closed_form(xs: List[float], ys: List[float]) -> Tuple[float, float, float]:
    """Closed-form least squares fallback; same return contract.

    Raises:
        ValueError: when the series is degenerate (no definable trend).
    """
    fit = linear_trend(xs, ys)
    if fit is None:
        raise ValueError("degenerate series: no definable trend")
    slope, intercept = fit
    preds = [slope * x + intercept for x in xs]
    my = sum(ys) / len(ys)
    ss_res = sum((y - p) ** 2 for y, p in zip(ys, preds))
    ss_tot = sum((y - my) ** 2 for y in ys)
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0
    return slope, intercept, max(0.0, min(1.0, r_squared))


def forecast_trend(
    city: str,
    horizon_hours: int = 24,
    days: int = 30,
    fallback_records: Optional[List[dict]] = None,
) -> dict:
    """Train a per-city trend model and forecast the temperature horizon.

    Args:
        city: City slug to model (required).
        horizon_hours: Hours ahead to forecast (1..168).
        days: Training window length in days (default 30).
        fallback_records: Optional pre-loaded records — bypasses the
            database entirely (used by the test suite).

    Returns:
        ``{city, algorithm, trained_points, window_days, slope_per_day,
        r_squared, baseline_temp, baseline_timestamp, horizon_hours,
        forecast: [{timestamp, temp_c}, ...]}`` — or ``{"error": ...}``
        when training is impossible.
    """
    city = (city or "").strip()
    horizon_hours = max(1, min(int(horizon_hours), 168))
    if not city:
        return {"error": "city parameter is required"}

    try:
        records = fallback_records if fallback_records is not None \
            else load_observations(city=city, days=days)
        points = _series(records)
        if len(points) < _MIN_TRAINING_POINTS:
            return {
                "error": "insufficient training data for %s (%d points, need %d)"
                         % (city, len(points), _MIN_TRAINING_POINTS),
            }

        t0 = points[0][0]
        xs = [(ts - t0).total_seconds() / 86400.0 for ts, _ in points]
        ys = [temp for _, temp in points]

        if _SKLEARN:
            try:
                slope, intercept, r_squared = _fit_sklearn(xs, ys)
                algorithm = "sklearn.LinearRegression"
            except Exception as exc:  # noqa: BLE001
                logger.warning("sklearn fit failed (%s) — closed-form fallback", exc)
                slope, intercept, r_squared = _fit_closed_form(xs, ys)
                algorithm = "closed-form-least-squares"
        else:
            slope, intercept, r_squared = _fit_closed_form(xs, ys)
            algorithm = "closed-form-least-squares"

        last_ts, last_temp = points[-1]
        forecast = []
        for step in range(1, horizon_hours + 1):
            future_x = xs[-1] + step / 24.0
            temp = slope * future_x + intercept
            temp = max(-90.0, min(60.0, temp))  # physical clamp
            forecast.append({
                "timestamp": (last_ts + timedelta(hours=step)).isoformat(
                    timespec="seconds"),
                "temp_c": round(temp, 2),
            })

        return {
            "city": city,
            "algorithm": algorithm,
            "trained_points": len(points),
            "window_days": days,
            "slope_per_day": round(slope, 6),
            "r_squared": round(r_squared, 4),
            "baseline_temp": round(last_temp, 2),
            "baseline_timestamp": last_ts.isoformat(timespec="seconds"),
            "horizon_hours": horizon_hours,
            "forecast": forecast,
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("trend forecast failed for %s", city)
        return {"error": str(exc)}