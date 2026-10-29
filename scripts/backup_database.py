#!/usr/bin/env python3
"""SkyCast AI — scheduled SQLite database backup.

Creates a gzip-compressed online backup of data/skycast.db (safe to run
while the Flask app is live) and prunes old archives beyond the retention
count. Intended for cron / Windows Task Scheduler:

    0 */6 * * *  /path/to/venv/bin/python /path/to/skycast-ai/scripts/backup_database.py --keep 14

Exit codes: 0 = backup created, 1 = failure (alert your monitoring).
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.maintenance import create_backup  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gzip-compressed SQLite backup with retention pruning")
    parser.add_argument(
        "--keep", type=int, default=14,
        help="number of archives to retain (default: 14)")
    args = parser.parse_args()

    result = create_backup(keep=args.keep)
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())