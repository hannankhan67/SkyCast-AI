"""SkyCast AI — MapReduce engine for climate analytics.

Implements the classic Map/Shuffle/Reduce programming model over data
shards: the mapper runs in parallel worker processes (``multiprocessing``)
when the workload warrants it, partial results are grouped by key (the
shuffle), and each reducer combines the per-shard partials into a final
aggregate. With one worker — or if the process pool cannot start — the
engine falls back to serial execution so results are always produced.

Sharding strategy: records are split into contiguous chunks of roughly
equal size; every mapper sees a disjoint slice, so per-key sum statistics
compose associatively and the reduced result is shard-count independent.

Concrete jobs shipped here:
  * ``pearson`` / ``linear_trend`` — pure math primitives
  * ``city_pearson_job`` — per-city Pearson correlations between metrics
  * ``city_trend_job``   — per-city temperature trend (°C / day)

The math helpers are pure, typed, and unit-tested in
verify_data_engineering.py without any database.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Callable, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

#: Sufficient statistics for a correlation: n, Σx, Σy, Σxx, Σyy, Σxy.
SumKey = Tuple[float, float, float, float, float, float]


# ---------------------------------------------------------------------------
# Generic MapReduce driver
# ---------------------------------------------------------------------------

def shard_records(records: Sequence[dict], n_shards: int) -> List[List[dict]]:
    """Split records into at most ``n_shards`` contiguous, non-empty chunks."""
    records = list(records)
    if not records:
        return []
    n_shards = max(1, min(int(n_shards), len(records)))
    size = -(-len(records) // n_shards)  # ceil division
    return [records[i:i + size] for i in range(0, len(records), size)]


def _merge_value(existing, incoming):
    """Shuffle merge for one field.

    Tuples (and non-string lists) merge element-wise; bare numbers sum;
    anything else keeps the first value seen. This makes the shuffle
    associative, so the reduced result is shard-count independent.
    """
    if isinstance(incoming, (tuple, list)) and not isinstance(incoming, str):
        if isinstance(existing, (tuple, list)) and not isinstance(existing, str) \
                and len(existing) == len(incoming):
            return tuple(a + b for a, b in zip(existing, incoming))
        return tuple(incoming)
    if isinstance(incoming, (int, float)):
        return existing + incoming
    return existing if existing is not None else incoming


def map_reduce(
    shards: Sequence[List[dict]],
    mapper: Callable[[List[dict]], Dict[str, dict]],
    reducer: Callable[[str, dict], dict],
    workers: int = 1,
) -> Dict[str, dict]:
    """Run mapper over shards, shuffle per-key partials, reduce each key.

    Args:
        shards: Disjoint record slices produced by ``shard_records``.
        mapper: ``shard -> {key: partial_dict}``; partial fields must be
            mergeable per ``_merge_value`` (numbers, sum-tuples, lists).
        reducer: ``(key, merged_partial) -> final_dict``.
        workers: Parallel mapper processes; 1 = serial (also the fallback
            whenever the process pool cannot start).

    Returns:
        ``{key: reduced_dict}`` — identical for any shard count.
    """
    mapped: List[Dict[str, dict]] = []
    if workers <= 1 or len(shards) <= 1:
        mapped = [mapper(s) for s in shards]
    else:
        try:
            import multiprocessing as mp

            ctx = mp.get_context("spawn")
            with ctx.Pool(processes=min(workers, len(shards))) as pool:
                mapped = pool.map(mapper, shards)
        except Exception as exc:  # noqa: BLE001 - never fail for parallelism
            logger.warning("parallel map unavailable (%s) — running serial", exc)
            mapped = [mapper(s) for s in shards]

    merged: Dict[str, dict] = {}
    for partial in mapped:
        for key, values in (partial or {}).items():
            slot = merged.setdefault(key, {})
            for name, value in (values or {}).items():
                slot[name] = _merge_value(slot.get(name), value)
    return {key: reducer(key, slot) for key, slot in merged.items()}


# ---------------------------------------------------------------------------
# Pure math primitives
# ---------------------------------------------------------------------------

def pearson(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    """Pearson correlation coefficient r ∈ [-1, 1]; None when undefined.

    r = Σ(x−x̄)(y−ȳ) / sqrt(Σ(x−x̄)² · Σ(y−ȳ)²)

    Returns None when fewer than 2 paired samples exist or either series
    has zero variance (r is mathematically undefined there).

    Raises:
        ValueError: when the series lengths differ.
    """
    if len(xs) != len(ys):
        raise ValueError("xs and ys must have the same length")
    n = len(xs)
    if n < 2:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    var_x = sum((x - mx) ** 2 for x in xs)
    var_y = sum((y - my) ** 2 for y in ys)
    denom = math.sqrt(var_x * var_y)
    if denom <= 1e-12:
        return None
    return max(-1.0, min(1.0, cov / denom))


def linear_trend(
    xs: Sequence[float], ys: Sequence[float]
) -> Optional[Tuple[float, float]]:
    """Ordinary least-squares fit ``y = slope·x + intercept``.

    Returns:
        ``(slope, intercept)`` or None when degenerate (n < 2 or constant x).

    Raises:
        ValueError: when the series lengths differ.
    """
    if len(xs) != len(ys):
        raise ValueError("xs and ys must have the same length")
    n = len(xs)
    if n < 2:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 1e-12:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx
    return slope, my - slope * mx


def _pair_sums(pairs: Sequence[Tuple[float, float]]) -> SumKey:
    """Composable sufficient statistics for Pearson's r."""
    n = float(len(pairs))
    sx = sum(x for x, _ in pairs)
    sy = sum(y for _, y in pairs)
    sxx = sum(x * x for x, _ in pairs)
    syy = sum(y * y for _, y in pairs)
    sxy = sum(x * y for x, y in pairs)
    return (n, sx, sy, sxx, syy, sxy)


def _corr_from_sums(s: SumKey) -> Optional[float]:
    """Rebuild Pearson r from composable sums; None when degenerate."""
    n, sx, sy, sxx, syy, sxy = s
    if n < 2:
        return None
    cov = sxy - sx * sy / n
    var_x = sxx - sx * sx / n
    var_y = syy - sy * sy / n
    denom = math.sqrt(max(var_x, 0.0) * max(var_y, 0.0))
    if denom <= 1e-12:
        return None
    return max(-1.0, min(1.0, cov / denom))


def _add_sums(a: SumKey, b: SumKey) -> SumKey:
    """Element-wise sum of two sufficient-statistic tuples."""
    return tuple(x + y for x, y in zip(a, b))


# ---------------------------------------------------------------------------
# Job 1: per-city Pearson correlations (MapReduce)
# ---------------------------------------------------------------------------

def build_pair_records(records: Sequence[dict]) -> List[dict]:
    """Attach metric-pair tensors to raw observation records for the job.

    Emits one record per input with an ``_values`` dict containing every
    fully observed pair: temp↔aqi, temp↔humidity, wind↔aqi. Records
    missing either member of a pair simply contribute nothing for it —
    the graceful missing-data rule.
    """
    enriched: List[dict] = []
    for rec in records:
        t = rec.get("temperature")
        h = rec.get("humidity")
        w = rec.get("wind_speed")
        a = rec.get("aqi")
        pairs = {
            "temp_aqi": (t, a),
            "temp_humidity": (t, h),
            "wind_aqi": (w, a),
        }
        enriched.append(dict(rec, _values={
            k: v for k, v in pairs.items()
            if v[0] is not None and v[1] is not None
        }))
    return enriched


def _pearson_mapper(shard: List[dict]) -> Dict[str, dict]:
    """Emit per-city partial sums for every metric pair in this shard."""
    partial: Dict[str, dict] = {}
    for rec in shard:
        city = str(rec.get("city") or "unknown")
        for name, (x, y) in (rec.get("_values") or {}).items():
            if x is None or y is None:
                continue
            slot = partial.setdefault(city, {})
            slot[name] = _add_sums(
                slot.get(name, (0.0,) * 6),
                _pair_sums([(float(x), float(y))]),
            )
    return partial


def _corr_reducer(_key: str, sums: dict) -> dict:
    """Shuffle reducer: combine partial sums and derive Pearson r."""
    return {name: _corr_from_sums(total) for name, total in sums.items()}


def city_pearson_job(
    records: Sequence[dict], workers: int = 1
) -> Dict[str, Dict[str, Optional[float]]]:
    """MapReduce job: per-city Pearson correlations between climate metrics.

    Args:
        records: Observation records (see ``build_pair_records``).
        workers: Parallel mapper processes (1 = serial).

    Returns:
        ``{city: {pair_name: r_or_None}}``
    """
    shards = shard_records(records, workers)
    result = map_reduce(shards, _pearson_mapper, _corr_reducer, workers=workers)
    return result


# ---------------------------------------------------------------------------
# Job 2: per-city temperature trend (MapReduce)
# ---------------------------------------------------------------------------

def _to_days(ts) -> Optional[float]:
    """Timestamp -> fractional days since 2000-01-01 (None when unusable)."""
    if isinstance(ts, (int, float)):
        return float(ts)
    try:
        parsed = datetime.fromisoformat(str(ts)[:19])
        return (parsed - datetime(2000, 1, 1)).total_seconds() / 86400.0
    except (ValueError, TypeError):
        return None


def _trend_mapper(shard: List[dict]) -> Dict[str, dict]:
    """Emit per-city partial sums for the temperature-vs-time trend fit."""
    partial: Dict[str, dict] = {}
    for rec in shard:
        if rec.get("temperature") is None:
            continue
        t = _to_days(rec.get("timestamp"))
        if t is None:
            continue
        city = str(rec.get("city") or "unknown")
        y = float(rec["temperature"])
        sums = (1.0, t, y, t * t, y * y, t * y)
        slot = partial.setdefault(city, {})
        slot["trend"] = _add_sums(slot.get("trend", (0.0,) * 6), sums)
    return partial


def _trend_reducer(_key: str, sums: dict) -> dict:
    """Shuffle reducer: combined sums -> slope (°C/day) + r²."""
    n, sx, sy, sxx, syy, sxy = sums.get("trend", (0.0,) * 6)
    if n < 2:
        return {"slope_per_day": None, "r_squared": None, "points": int(n)}
    mx, my = sx / n, sy / n
    sxx_c = max(sxx - n * mx * mx, 0.0)
    syy_c = max(syy - n * my * my, 0.0)
    sxy_c = sxy - n * mx * my
    slope = sxy_c / sxx_c if sxx_c > 1e-12 else None
    denom_r = math.sqrt(sxx_c * syy_c)
    r = max(-1.0, min(1.0, sxy_c / denom_r)) if denom_r > 1e-12 else None
    return {
        "slope_per_day": round(slope, 6) if slope is not None else None,
        "r_squared": round(r * r, 4) if r is not None else None,
        "points": int(n),
    }


def city_trend_job(records: Sequence[dict], workers: int = 1) -> Dict[str, dict]:
    """MapReduce job: per-city least-squares temperature trend (°C/day).

    Args:
        records: Observation records with ``temperature`` + ``timestamp``.
        workers: Parallel mapper processes (1 = serial).

    Returns:
        ``{city: {slope_per_day, r_squared, points}}``
    """
    shards = shard_records(records, workers)
    return map_reduce(shards, _trend_mapper, _trend_reducer, workers=workers)