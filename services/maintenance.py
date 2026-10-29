"""SkyCast AI — Maintenance services: database backup & vacuum.

Implements the reliability requirements:
  * ``create_backup``  — online SQLite backup (``Connection.backup`` API,
    safe to run while the app is live), gzip-compressed, with retention
    pruning so disk usage stays bounded.
  * ``list_backups``   — inventory for the admin console / cron monitoring.
  * ``vacuum_database``— reclaims free pages and defragments.

Backups live in ``<project>/data/backups`` (the ``data/`` directory is
gitignored). Run ``scripts/backup_database.py`` from cron / Task Scheduler
for the scheduled-automated-backup requirement; the admin API exposes the
same operations on demand.
"""

from __future__ import annotations

import gzip
import logging
import os
import shutil
import sqlite3
from datetime import datetime
from typing import Dict, List

import database

logger = logging.getLogger(__name__)

_BACKUP_DIR = os.path.join(os.path.dirname(database.DB_PATH), "backups")
_DEFAULT_KEEP = 14
_VACUUM_BATCH_BYTES = 0  # sqlite3 total_changes not needed; simple VACUUM


def create_backup(keep: int = _DEFAULT_KEEP) -> Dict[str, object]:
    """Create a gzip-compressed online backup of the SQLite database.

    Uses the SQLite online-backup API, which copies a consistent snapshot
    even while other connections are writing. Older archives beyond
    ``keep`` are pruned (oldest first).

    Returns:
        ``{"ok": True, "path": ..., "size_bytes": ..., "created_at": ...}``
        or ``{"ok": False, "error": ...}``.
    """
    keep = max(1, int(keep))
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    os.makedirs(_BACKUP_DIR, exist_ok=True)
    plain_path = os.path.join(_BACKUP_DIR, "skycast-%s.db" % stamp)
    gz_path = plain_path + ".gz"
    try:
        source = sqlite3.connect(database.DB_PATH)
        try:
            destination = sqlite3.connect(plain_path)
            try:
                source.backup(destination)  # online-safe page copy
            finally:
                destination.close()
        finally:
            source.close()

        with open(plain_path, "rb") as src, gzip.open(gz_path, "wb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
        os.remove(plain_path)

        size = os.path.getsize(gz_path)
        _prune_old_backups(keep)
        logger.info("database backup written: %s (%d bytes)", gz_path, size)
        return {
            "ok": True,
            "path": gz_path,
            "size_bytes": size,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("backup failed")
        return {"ok": False, "error": str(exc)}


def _prune_old_backups(keep: int) -> int:
    """Delete the oldest archives beyond ``keep``; returns removed count."""
    try:
        archives = sorted(
            f for f in os.listdir(_BACKUP_DIR) if f.endswith(".db.gz")
        )
        removed = 0
        for name in archives[:-keep] if len(archives) > keep else []:
            try:
                os.remove(os.path.join(_BACKUP_DIR, name))
                removed += 1
            except OSError:
                continue
        return removed
    except OSError:
        return 0


def list_backups() -> List[Dict[str, object]]:
    """Inventory of stored backup archives (newest first)."""
    out: List[Dict[str, object]] = []
    try:
        if not os.path.isdir(_BACKUP_DIR):
            return out
        for name in sorted(os.listdir(_BACKUP_DIR), reverse=True):
            if not name.endswith(".db.gz"):
                continue
            path = os.path.join(_BACKUP_DIR, name)
            try:
                out.append({
                    "name": name,
                    "size_bytes": os.path.getsize(path),
                    "modified_at": datetime.fromtimestamp(
                        os.path.getmtime(path)).isoformat(timespec="seconds"),
                })
            except OSError:
                continue
    except OSError as exc:
        logger.warning("listing backups failed: %s", exc)
    return out


def vacuum_database() -> Dict[str, object]:
    """VACUUM the SQLite database; returns status and freed-page info."""
    try:
        with database._connect() as conn:
            before = conn.execute("PRAGMA page_count").fetchone()[0]
            conn.execute("VACUUM")
            after = conn.execute("PRAGMA page_count").fetchone()[0]
        freed_kb = max(0, before - after) * 4  # 4 KiB pages (default)
        return {"ok": True, "pages_before": before, "pages_after": after,
                "freed_kb": freed_kb}
    except Exception as exc:  # noqa: BLE001
        logger.exception("vacuum failed")
        return {"ok": False, "error": str(exc)}