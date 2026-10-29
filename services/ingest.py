"""SkyCast AI — Climate data ingestion service.

Accepts uploaded sensor/station/satellite-derived observation files
(JSON array, JSON Lines, or CSV), validates and normalises every row,
then persists to three layers:

  1. SQLite ``weather_observations`` (authoritative queryable store)
  2. ``services.data_lake`` — Hive-partitioned JSONL on the filesystem
     (``SKYCAST_LAKE_ROOT`` may point at a mounted HDFS/S3 volume)
  3. Optional MongoDB ``weather_logs`` mirror (silently skipped offline)

Handles both historical (file upload) and real-time (single-record API)
ingestion through the same validation core. Corrupt rows are skipped and
counted — never abort the batch.
"""

from __future__ import annotations

import csv as _csv
import io
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import database
from services import data_lake

logger = logging.getLogger(__name__)

#: Columns persisted to SQLite; anything else in a row is dropped.
COLUMNS = ("city", "timestamp", "temperature", "humidity", "wind_speed",
           "pressure", "aqi", "pm25", "source")

_FLOAT_FIELDS = ("temperature", "humidity", "wind_speed", "pressure",
                 "aqi", "pm25")
_MAX_ROWS = 50000
_MAX_BYTES = 20 * 1024 * 1024  # 20 MB upload cap


class IngestError(ValueError):
    """Raised for structurally invalid payloads (bad JSON/CSV, too large)."""


# ---------------------------------------------------------------------------
# Parsing — JSON array / JSON object / JSON Lines / CSV
# ---------------------------------------------------------------------------

def parse_payload(raw: bytes) -> List[dict]:
    """Parse an uploaded file body into raw row dicts.

    Supported formats (sniffed from the first byte, then validated):
      * JSON array of objects:  ``[{...}, {...}]``
      * JSON object with a list under ``records`` / ``data`` / ``observations``
      * JSON Lines (one object per line)
      * CSV with a header row

    Raises:
        IngestError: on size limits, undecodable content, or unusable
            structure. Row-level problems do NOT raise — they are skipped
            and reported by :func:`ingest_rows`.
    """
    if len(raw) > _MAX_BYTES:
        raise IngestError("payload exceeds the 20 MB upload limit")
    text = raw.decode("utf-8-sig", errors="replace").strip()
    if not text:
        raise IngestError("empty payload")

    first = text[0]
    if first in "[{":
        return _parse_json_payload(text)
    if "," in text.splitlines()[0]:
        return _parse_csv_payload(text)
    return _parse_jsonl_payload(text)


def _parse_json_payload(text: str) -> List[dict]:
    """Strict JSON parse; supports array or wrapper-object shapes."""
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise IngestError("invalid JSON: %s" % exc) from exc
    if isinstance(parsed, dict):
        for key in ("records", "data", "observations"):
            if isinstance(parsed.get(key), list):
                parsed = parsed[key]
                break
    if not isinstance(parsed, list):
        raise IngestError("JSON payload must be an array of objects")
    return [row for row in parsed if isinstance(row, dict)]


def _parse_jsonl_payload(text: str) -> List[dict]:
    """One JSON object per line; blank and unparseable lines are skipped."""
    rows: List[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
        except json.JSONDecodeError:
            continue
    if not rows:
        raise IngestError("no valid JSON Lines records found")
    return rows


def _parse_csv_payload(text: str) -> List[dict]:
    """Header-row CSV; structurally broken rows are skipped by DictReader."""
    reader = _csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise IngestError("CSV payload has no header row")
    rows = [dict(row) for row in reader if row]
    if not rows:
        raise IngestError("no data rows found in CSV payload")
    return rows


# ---------------------------------------------------------------------------
# Validation / normalisation
# ---------------------------------------------------------------------------

def _coerce_float(value: Any) -> Optional[float]:
    """Best-effort float coercion; None when the value is unusable."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


#: Physical plausibility bounds — values outside are treated as missing
#: (sensor glitch defence) rather than trusted.
_BOUNDS = {
    "temperature": (-90.0, 60.0),
    "humidity": (0.0, 100.0),
    "wind_speed": (0.0, 250.0),
    "pressure": (800.0, 1200.0),
    "aqi": (0.0, 1000.0),
    "pm25": (0.0, 1000.0),
}


def normalise_row(row: Dict[str, Any]) -> Optional[dict]:
    """Validate one raw row into the canonical observation shape.

    Returns None for rows that cannot be salvaged (missing city or
    timestamp, or no numeric measurement at all). Out-of-bounds numeric
    values are nulled rather than trusted.

    Raises:
        IngestError: never — returns None; batch-level callers count it.
    """
    city = str(row.get("city") or row.get("location") or "").strip()
    if not city:
        return None
    raw_ts = row.get("timestamp") or row.get("time") or row.get("datetime")
    try:
        ts = datetime.fromisoformat(str(raw_ts)[:19])
    except (ValueError, TypeError):
        return None

    rec: Dict[str, Any] = {
        "city": city,
        "timestamp": ts.isoformat(timespec="seconds"),
    }
    for field in _FLOAT_FIELDS:
        value = _coerce_float(row.get(field))
        if value is not None:
            low, high = _BOUNDS[field]
            if not low <= value <= high:
                value = None
        rec[field] = value

    if all(rec[field] is None for field in _FLOAT_FIELDS):
        return None  # a row with no measurement at all is not an observation

    rec["source"] = str(row.get("source") or "sensor").strip() or "sensor"
    return rec


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _sqlite_insert(rows: List[dict]) -> int:
    """Batch-insert rows into weather_observations; returns write count."""
    if not rows:
        return 0
    now = datetime.now().isoformat(timespec="seconds")
    try:
        with database._connect() as conn:
            conn.executemany(
                """
                INSERT INTO weather_observations
                    (city, timestamp, temperature, humidity, wind_speed,
                     pressure, aqi, pm25, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        r["city"], r["timestamp"], r["temperature"],
                        r["humidity"], r["wind_speed"], r["pressure"],
                        r["aqi"], r["pm25"], r["source"], now,
                    )
                    for r in rows
                ],
            )
        return len(rows)
    except Exception as exc:  # noqa: BLE001
        logger.warning("SQLite observation insert failed: %s", exc)
        return 0


def ingest_rows(rows: List[dict], dataset: str = "climate") -> dict:
    """Validate, persist and report on a batch of raw rows.

    Returns a summary with accepted/skipped counts, per-layer write counts
    (SQLite, partitioned lake files, optional Mongo mirror). Never raises
    for row-level problems — only structural failures from
    ``parse_payload`` propagate.
    """
    accepted: List[dict] = []
    skipped = 0
    for row in rows[:_MAX_ROWS]:
        rec = normalise_row(row)
        if rec is None:
            skipped += 1
        else:
            accepted.append(rec)
    if len(rows) > _MAX_ROWS:
        skipped += len(rows) - _MAX_ROWS

    sqlite_written = _sqlite_insert(accepted)
    lake_files = data_lake.write_partition(dataset, accepted)
    mirrored = data_lake.optional_mongo_mirror(accepted, "weather_logs")

    return {
        "received": len(rows),
        "accepted": len(accepted),
        "skipped": skipped,
        "sqlite_written": sqlite_written,
        "lake_files": len(lake_files),
        "mongo_mirrored": mirrored,
    }


def ingest_upload(raw: bytes, dataset: str = "climate") -> dict:
    """Full pipeline for an uploaded file: parse -> validate -> persist."""
    rows = parse_payload(raw)
    return ingest_rows(rows, dataset=dataset)


def load_observations(city: Optional[str] = None, days: int = 30) -> List[dict]:
    """Recent observations from SQLite in the canonical record shape.

    Used as the input to the MapReduce correlation/trend jobs and the
    trend-forecast trainer. Returns rows oldest-first.
    """
    cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    query = ("SELECT city, timestamp, temperature, humidity, wind_speed, "
             "pressure, aqi, pm25 FROM weather_observations WHERE timestamp >= ?")
    params: List[Any] = [cutoff]
    if city:
        query += " AND city = ?"
        params.append(city)
    query += " ORDER BY timestamp ASC LIMIT 50000"
    try:
        with database._connect() as conn:
            return [dict(r) for r in conn.execute(query, params).fetchall()]
    except Exception as exc:  # noqa: BLE001
        logger.warning("loading observations failed: %s", exc)
        return []