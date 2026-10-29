"""
seed_api_keys.py — populates the SQLite api_keys table with realistic
developer keys so the admin command-center "API Key Tier Manager" panel and
the /developers portal render with live data instead of the empty state.

Deterministic (same keys every run) and idempotent: it clears the api_keys
table first, creates the demo developer accounts if missing, then mints one
key per tier — including a revoked one — with believable last-used stamps.

NOTE: This seeds SQLite (database.api_keys), NOT MongoDB. Like
seed_drift_data.py it targets the dev database directly, and it mints keys
through database.create_api_key() so every seeded key really authenticates
against /api/v1/* (hashes go through werkzeug, never faked).

Usage:
    python seed_api_keys.py
"""
import random
from datetime import datetime, timedelta, timezone

import database

# Tier -> requests/minute. Must stay in sync with
# routes/admin_features._TIER_LIMITS (Free 60 / Pro 500 / Enterprise 5000).
TIER_LIMITS = {"Free": 60, "Pro": 500, "Enterprise": 5000}

# (owner name, owner email, key label, tier, is_active)
DEMO_KEYS = [
    ("Ayesha Khan", "ayesha.dev@skycast.ai", "Mobile app (prod)", "Pro", True),
    ("Ayesha Khan", "ayesha.dev@skycast.ai", "Staging sandbox", "Free", True),
    ("Bilal Ahmed", "bilal.api@skycast.ai", "Partner integration", "Enterprise", True),
    ("Hina Raza", "hina.data@skycast.ai", "Hackathon prototype", "Free", False),
]

DEMO_PASSWORD = "DemoKey123!"  # demo accounts only — never used in production


def seed(clear_first=True):
    rng = random.Random(20260918)  # deterministic — same data every run
    now = datetime.now(timezone.utc)

    if clear_first:
        with database._connect() as conn:
            conn.execute("DELETE FROM api_keys")
            conn.commit()
        print("Cleared existing api_keys rows.")

    minted = []
    for owner, email, label, tier, active in DEMO_KEYS:
        user = database.get_user_by_email(email)
        if user is None:
            uid = database.create_user(owner, email, DEMO_PASSWORD, role="user")
        else:
            uid = user["id"]

        key_id, raw = database.create_api_key(uid, label)

        # Active keys look recently used; revoked ones keep their old stamp.
        last_used = (
            (now - timedelta(minutes=rng.randint(2, 2880))).isoformat(timespec="seconds")
            if active
            else (now - timedelta(days=rng.randint(9, 21))).isoformat(timespec="seconds")
        )
        with database._connect() as conn:
            conn.execute(
                "UPDATE api_keys SET tier = ?, rate_limit_rpm = ?, is_active = ?, "
                "last_used_at = ? WHERE id = ?",
                (tier, TIER_LIMITS[tier], 1 if active else 0, last_used, key_id),
            )
            conn.commit()

        minted.append((key_id, email, label, tier, active, raw))

    print(f"Seeded {len(minted)} API keys across "
          f"{len({row[1] for row in minted})} developer accounts:\n")
    print(f"{'ID':>3}  {'OWNER':<28} {'TIER':<11} {'RPM':>5}  {'STATUS':<8} KEY")
    print("-" * 96)
    for key_id, email, label, tier, active, raw in minted:
        print(f"{key_id:>3}  {email:<28} {tier:<11} {TIER_LIMITS[tier]:>5}  "
              f"{'active' if active else 'revoked':<8} {raw}")
    print("\nThe raw keys above are shown only here — the database stores hashes.")
    print("Try one with:  curl -H \"X-API-Key: <key>\" "
          "http://127.0.0.1:5000/api/v1/weather?city=karachi")
    return minted


if __name__ == "__main__":
    seed()