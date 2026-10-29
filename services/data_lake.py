"""SkyCast AI — Partitioned climate data lake.

Writes ingested observations to an HDFS-compatible Hive-partitioned layout
on the filesystem::

    <lake_root>/<dataset>/city=<city>/dt=<YYYY-MM-DD>/part-<ts>-<n>.jsonl

``SKYCAST_LAKE_ROOT`` may point at any mounted distributed filesystem
(HDFS via fuse/wheel, S3FS, NFS) — the code only does plain file I/O, so
the layout ports to a real HDFS cluster without changes. JSONL lines are
newline-delimited JSON, a format every Hadoop/Spark ingest tool reads.

All functions degrade gracefully: any filesystem failure is logged and
returns an empty result — the lake is an ingest mirror, never a hot path.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#: Root of the partitioned lake; override to target a mounted HDFS/S3 path.
LAKE_ROOT = os.environ.get("SKYCAST_LAKE_ROOT") or os.path.join(_BASE_DIR, "data", "lake")


def _partition_dirs(dataset: str, city: str, day: str) -> str:
    """Hive-style directory for (dataset, city, day), path-safe."""
    safe_city = "".join(ch for ch in (city or "unknown").lower() if ch.isalnum())
    if not safe_city:
        safe_city = "unknown"
    return os.path.join(LAKE_ROOT, dataset, "city=%s" % safe_city, "dt=%s" % day)


def write_partition(dataset: str, records: List[dict]) -> List[str]:
    """Append records to per-(city, day) partitions; returns file paths.

    Records must carry ``city``; the partition day comes from the record's
    ``timestamp`` (ISO string or datetime), defaulting to today. Each call
    writes one new ``part-<stamp>.jsonl`` file per touched partition.
    """
    if not records:
        return []
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S%f")[:-3]
    buckets: Dict[str, List[dict]] = {}
    for rec in records:
        try:
            ts = rec.get("timestamp")
            day = (
                datetime.fromisoformat(str(ts)[:10]).date().isoformat()
                if ts else datetime.now().date().isoformat()
            )
        except (ValueError, TypeError):
            day = datetime.now().date().isoformat()
        key = _partition_dirs(dataset, str(rec.get("city") or "unknown"), day)
        buckets.setdefault(key, []).append(rec)

    written: List[str] = []
    for path, rows in buckets.items():
        try:
            os.makedirs(path, exist_ok=True)
            file_path = os.path.join(path, "part-%s.jsonl" % stamp)
            with open(file_path, "a", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row, default=str) + "\n")
            written.append(file_path)
        except OSError as exc:
            logger.warning("lake write failed for %s: %s", path, exc)
    return written


def read_partition(dataset: str, city: str, day: str) -> List[dict]:
    """Read every record from one (city, day) partition ([] on any error)."""
    directory = _partition_dirs(dataset, city, day)
    out: List[dict] = []
    try:
        if not os.path.isdir(directory):
            return out
        for name in sorted(os.listdir(directory)):
            if not name.endswith(".jsonl"):
                continue
            with open(os.path.join(directory, name), "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if line:
                        try:
                            out.append(json.loads(line))
                        except json.JSONDecodeError:
                            logger.warning("skipping corrupt lake line in %s", name)
    except OSError as exc:
        logger.warning("lake read failed for %s: %s", directory, exc)
    return out


def lake_stats() -> dict:
    """Rough inventory of the lake for the admin console."""
    stats: Dict[str, dict] = {}
    try:
        if not os.path.isdir(LAKE_ROOT):
            return {"root": LAKE_ROOT, "datasets": {}}
        for dataset in sorted(os.listdir(LAKE_ROOT)):
            dpath = os.path.join(LAKE_ROOT, dataset)
            if not os.path.isdir(dpath):
                continue
            files = 0
            total_bytes = 0
            for root, _dirs, names in os.walk(dpath):
                for name in names:
                    fpath = os.path.join(root, name)
                    try:
                        files += 1
                        total_bytes += os.path.getsize(fpath)
                    except OSError:
                        continue
            stats[dataset] = {"files": files, "bytes": total_bytes}
    except OSError as exc:
        logger.warning("lake stats failed: %s", exc)
    return {"root": LAKE_ROOT, "datasets": stats}


def optional_mongo_mirror(records: List[dict], collection: str = "weather_logs") -> int:
    """Best-effort mirror of ingested rows into a Mongo collection (0 offline)."""
    if not records:
        return 0
    try:
        from services.drift_engine import get_mongo_db

        db = get_mongo_db()
        if db is None:
            return 0
        db[collection].insert_many([dict(r) for r in records], ordered=False)
        return len(records)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Mongo mirror for %s skipped: %s", collection, exc)
        return 0