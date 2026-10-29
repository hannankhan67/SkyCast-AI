"""SkyCast AI - SQLite persistence layer (stdlib only).

Stores user accounts and single-use password-reset codes. The database file
lives in ``data/skycast.db`` and is created automatically on first import.
"""

import os
import secrets
import sqlite3
import json
from datetime import datetime, timedelta, timezone

from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_DIR = os.path.join(BASE_DIR, "data")
# SKYCAST_DB lets smoke tests / deployments redirect the database elsewhere.
DB_PATH = os.environ.get("SKYCAST_DB") or os.path.join(_DIR, "skycast.db")

# Reset codes expire after this many minutes.
RESET_CODE_TTL_MINUTES = 15

# Subscription plans. `free` has no premium access; `premium` unlocks the
# Premium page groups (see routes/auth.PREMIUM_PAGE_GROUPS).
# Keep in sync with app._is_premium / routes.auth._user_is_premium and the
# admin console plan selector.
USER_PLANS = ("free", "premium")
PREMIUM_PLANS = ("premium",)


def is_premium_plan(plan):
    """True when a stored subscription value grants premium access."""
    return (plan or "free").lower() in PREMIUM_PLANS


def _connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # Allow concurrent readers/writers to *wait* for the lock up to 30s
    # instead of failing fast with "database is locked" under the threaded
    # Flask dev server or burst AJAX traffic.
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def init_db():
    """Create tables if they do not exist yet."""
    os.makedirs(_DIR, exist_ok=True)
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT    NOT NULL,
                email         TEXT    NOT NULL UNIQUE,
                password_hash TEXT    NOT NULL,
                role          TEXT    NOT NULL DEFAULT 'user',
                created_at    TEXT    NOT NULL
            )
            """
        )
        # Migrate existing databases: add role column if missing
        try:
            cols = [row[1] for row in conn.execute("PRAGMA table_info(users)")]
            if "role" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'")
        except Exception:
            pass
        # Migrate existing databases: add subscription column if missing
        try:
            cols = [row[1] for row in conn.execute("PRAGMA table_info(users)")]
            if "subscription" not in cols:
                conn.execute(
                    "ALTER TABLE users ADD COLUMN subscription TEXT NOT NULL DEFAULT 'free'"
                )
            if "phone" not in cols:
                conn.execute(
                    "ALTER TABLE users ADD COLUMN phone TEXT NOT NULL DEFAULT ''"
                )
        except Exception:
            pass
        # Enterprise was retired as a subscription tier; preserve access by
        # folding existing accounts into the remaining premium tier.
        conn.execute("UPDATE users SET subscription = 'premium' WHERE subscription = 'enterprise'")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS password_resets (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                email      TEXT    NOT NULL,
                code_hash  TEXT    NOT NULL,
                expires_at TEXT    NOT NULL,
                used       INTEGER NOT NULL DEFAULT 0,
                created_at TEXT    NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_resets_email ON password_resets(email)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_keys (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER NOT NULL,
                key_hash      TEXT    NOT NULL,
                name          TEXT    NOT NULL,
                created_at    TEXT    NOT NULL,
                last_used_at  TEXT,
                key_prefix    TEXT,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_api_keys_user ON api_keys(user_id)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS weather_alerts (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL,
                city       TEXT    NOT NULL,
                metric     TEXT    NOT NULL,
                threshold  REAL    NOT NULL,
                operator   TEXT    NOT NULL,
                channels   TEXT    NOT NULL,
                created_at TEXT    NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_alerts_user ON weather_alerts(user_id)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS support_tickets (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                subject     TEXT    NOT NULL,
                category    TEXT    NOT NULL DEFAULT 'general',
                priority    TEXT    NOT NULL DEFAULT 'normal',
                status      TEXT    NOT NULL DEFAULT 'open',
                created_at  TEXT    NOT NULL,
                updated_at  TEXT    NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_support_user ON support_tickets(user_id, status)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS support_replies (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id   INTEGER NOT NULL,
                author_id   INTEGER NOT NULL,
                body        TEXT    NOT NULL,
                is_staff    INTEGER NOT NULL DEFAULT 0,
                created_at  TEXT    NOT NULL,
                FOREIGN KEY (ticket_id) REFERENCES support_tickets(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_support_replies_ticket ON support_replies(ticket_id)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_preferences (
                user_id    INTEGER PRIMARY KEY,
                saved_cities TEXT NOT NULL DEFAULT '[]',
                theme      TEXT    NOT NULL DEFAULT 'dark',
                created_at TEXT    NOT NULL,
                updated_at TEXT    NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notification_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL,
                alert_id   INTEGER,
                channel    TEXT    NOT NULL,
                status     TEXT    NOT NULL,
                detail     TEXT,
                sent_at    TEXT    NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id),
                FOREIGN KEY (alert_id) REFERENCES weather_alerts (id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_requests (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                method      TEXT,
                path        TEXT    NOT NULL,
                city        TEXT,
                status      INTEGER,
                live        INTEGER,
                duration_ms REAL,
                created_at  TEXT    NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_api_requests_created ON api_requests(created_at)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS push_subscriptions (
                endpoint       TEXT PRIMARY KEY,
                user_id        INTEGER NOT NULL,
                subscription   TEXT NOT NULL,
                created_at     TEXT NOT NULL,
                updated_at     TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_push_subscriptions_user ON push_subscriptions(user_id)"
        )
        # --- Admin feature flags (key-value) --------------------------------
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS system_feature_flags (
                flag_key   TEXT PRIMARY KEY,
                flag_value INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL
            )
            """
        )
        # --- Broadcast warning alerts --------------------------------------
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS broadcast_alerts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                title       TEXT NOT NULL,
                message     TEXT NOT NULL,
                severity    TEXT NOT NULL DEFAULT 'warning',
                target_city TEXT NOT NULL DEFAULT 'All',
                is_active   INTEGER NOT NULL DEFAULT 1,
                created_at  TEXT NOT NULL
            )
            """
        )
        # --- Lightweight migrations (v2 columns on user_preferences) --------
        for stmt in (
            "ALTER TABLE user_preferences ADD COLUMN home_city TEXT NOT NULL DEFAULT 'karachi'",
            "ALTER TABLE user_preferences ADD COLUMN unit TEXT NOT NULL DEFAULT 'c'",
            "ALTER TABLE user_preferences ADD COLUMN notify_threshold TEXT NOT NULL DEFAULT 'default'",
        ):
            try:
                conn.execute(stmt)
            except Exception:
                pass  # column already exists
        # --- v3: api_keys tier / rate limiting -----------------------------
        for stmt in (
            "ALTER TABLE api_keys ADD COLUMN tier TEXT NOT NULL DEFAULT 'Free'",
            "ALTER TABLE api_keys ADD COLUMN rate_limit_rpm INTEGER NOT NULL DEFAULT 60",
            "ALTER TABLE api_keys ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1",
        ):
            try:
                conn.execute(stmt)
            except Exception:
                pass
        # --- v5: api_keys display prefix -----------------------------------
        # The raw key is only ever shown once at creation (stored hashed), so
        # a short clear-text prefix is kept for identification in the admin
        # tier manager / portal listings.
        try:
            conn.execute("ALTER TABLE api_keys ADD COLUMN key_prefix TEXT")
        except Exception:
            pass

        # --- v4: analyst expansion (annotations · forecast · audit) ---------
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS telemetry_annotations (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp  TEXT    NOT NULL,
                author_id  INTEGER NOT NULL,
                label      TEXT    NOT NULL,
                severity   TEXT    NOT NULL DEFAULT 'info',
                created_at TEXT    NOT NULL,
                FOREIGN KEY (author_id) REFERENCES users (id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_annotations_ts ON telemetry_annotations(timestamp)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS forecast_verification (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                city          TEXT    NOT NULL,
                timestamp     TEXT    NOT NULL,
                predicted_temp REAL   NOT NULL,
                actual_temp    REAL   NOT NULL,
                error_margin   REAL   NOT NULL,
                created_at    TEXT    NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_fv_city_ts ON forecast_verification(city, timestamp)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS weather_observations (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                city        TEXT    NOT NULL,
                timestamp   TEXT    NOT NULL,
                temperature REAL,
                humidity    REAL,
                wind_speed  REAL,
                pressure    REAL,
                aqi         REAL,
                pm25        REAL,
                source      TEXT    NOT NULL DEFAULT 'sensor',
                created_at  TEXT    NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_wo_city_ts "
            "ON weather_observations(city, timestamp)"
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS analyst_audit_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                author_id  INTEGER NOT NULL,
                action     TEXT    NOT NULL,
                detail     TEXT,
                created_at TEXT    NOT NULL,
                FOREIGN KEY (author_id) REFERENCES users (id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_author ON analyst_audit_log(author_id, created_at)"
        )
        # --- v5: analyst alert simulator dry-run log -------------------------- 
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS alert_simulation_log (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                city             TEXT    NOT NULL,
                analyst_id       INTEGER NOT NULL,
                parameters       TEXT    NOT NULL,
                rules_triggered  TEXT    NOT NULL DEFAULT '[]',
                triggered_count  INTEGER NOT NULL DEFAULT 0,
                highest_severity TEXT    NOT NULL DEFAULT 'NONE',
                simulated_channels TEXT   NOT NULL DEFAULT '[]',
                processing_latency_ms REAL NOT NULL DEFAULT 0,
                executed_at      TEXT    NOT NULL,
                FOREIGN KEY (analyst_id) REFERENCES users (id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sim_city ON alert_simulation_log(city, executed_at DESC)"
        )

        # --- v6: Stripe billing ledger ---------------------------------------
        # One row per Stripe Checkout Session. stripe_session_id is UNIQUE so
        # re-delivered webhooks / a refresh on the success URL update the row
        # instead of duplicating it (see database.record_payment).
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS payments (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id              INTEGER,
                stripe_session_id    TEXT    NOT NULL UNIQUE,
                stripe_payment_intent TEXT,
                stripe_customer_id   TEXT,
                amount_cents         INTEGER NOT NULL DEFAULT 0,
                currency             TEXT    NOT NULL DEFAULT 'usd',
                status               TEXT    NOT NULL DEFAULT 'pending',
                plan                 TEXT    NOT NULL DEFAULT 'premium',
                email                TEXT,
                created_at           TEXT    NOT NULL,
                updated_at           TEXT    NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_payments_user "
            "ON payments(user_id, created_at DESC)"
        )
        # Maps a local user to their Stripe customer (Billing Portal / webhooks).
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS billing_customers (
                user_id            INTEGER PRIMARY KEY,
                stripe_customer_id TEXT NOT NULL UNIQUE,
                updated_at         TEXT NOT NULL
            )
            """
        )


# ---------------------------------------------------------------------------
# Alert simulator rule engine (dry-run, never fires real notifications)
# ---------------------------------------------------------------------------
import time as _sim_time


def _json(obj):
    """Serialize a value to a compact JSON string for SQLite storage."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _loads(raw):
    """Parse a JSON string, tolerating None/empty input."""
    if not raw:
        return None
    return json.loads(raw)


SYSTEM_ALERT_RULES = [
    {
        "rule_id": "RULE_HEATWAVE_EXTREME",
        "name": "Extreme Heatwave Warning",
        "category": "temperature",
        "severity": "CRITICAL",
        "condition": lambda p: p.get("temperature", 0) >= 45.0,
        "message": "Temperature exceeded critical 45°C threshold.",
    },
    {
        "rule_id": "RULE_HEATWAVE_HIGH",
        "name": "High Temperature Advisory",
        "category": "temperature",
        "severity": "WARNING",
        "condition": lambda p: 40.0 <= p.get("temperature", 0) < 45.0,
        "message": "Temperature in warning zone (40°C - 44.9°C).",
    },
    {
        "rule_id": "RULE_AQI_HAZARDOUS",
        "name": "Hazardous Air Quality Alert",
        "category": "aqi",
        "severity": "CRITICAL",
        "condition": lambda p: p.get("aqi", 0) >= 300,
        "message": "AQI reached hazardous levels (>= 300).",
    },
    {
        "rule_id": "RULE_AQI_UNHEALTHY",
        "name": "Unhealthy Air Quality Advisory",
        "category": "aqi",
        "severity": "WARNING",
        "condition": lambda p: 151 <= p.get("aqi", 0) < 300,
        "message": "AQI elevated to unhealthy levels (151 - 299).",
    },
    {
        "rule_id": "RULE_STORM_WIND",
        "name": "Severe Windstorm Warning",
        "category": "wind",
        "severity": "HIGH",
        "condition": lambda p: p.get("wind_speed", 0) >= 80.0,
        "message": "Sustained wind speed exceeded 80 km/h.",
    },
]

_SEVERITY_RANK = {"CRITICAL": 3, "HIGH": 2, "WARNING": 1}


def run_alert_simulation(city, parameters, analyst_id):
    """Evaluate weather parameters against SYSTEM_ALERT_RULES and log the dry-run.

    Returns the full simulation audit document (with _id as a string and an
    ISO executed_at) so it can be returned directly to the frontend.
    """
    t0 = _sim_time.perf_counter()
    triggered = []
    for rule in SYSTEM_ALERT_RULES:
        try:
            if rule["condition"](parameters):
                triggered.append({
                    "rule_id": rule["rule_id"],
                    "name": rule["name"],
                    "category": rule["category"],
                    "severity": rule["severity"],
                    "message": rule["message"],
                })
        except Exception as err:
            # Never let one misbehaving rule break the whole simulation.
            print(f"[SIMULATOR ERROR] rule {rule['rule_id']}: {err}")

    latency_ms = round((_sim_time.perf_counter() - t0) * 1000, 2)
    highest = max(
        (r["severity"] for r in triggered),
        key=lambda s: _SEVERITY_RANK.get(s, 0),
        default="NONE",
    )

    with _connect() as conn:
        conn.execute(
            """INSERT INTO alert_simulation_log
               (city, analyst_id, parameters, rules_triggered, triggered_count,
                highest_severity, simulated_channels, processing_latency_ms, executed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(city).strip().lower(),
                int(analyst_id),
                _json(parameters),
                _json([r for r in triggered]),
                len(triggered),
                str(highest),
                _json(["in_app", "email", "sms"]),
                latency_ms,
                _now_iso(),
            ),
        )
        row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    doc = {
        "id": row_id,
        "city": str(city).strip().lower(),
        "analyst_id": int(analyst_id),
        "parameters": parameters,
        "rules_triggered": triggered,
        "triggered_count": len(triggered),
        "highest_severity": highest,
        "simulated_channels": ["in_app", "email", "sms"],
        "processing_latency_ms": latency_ms,
        "executed_at": _now_iso(),
    }
    doc["_id"] = str(doc["id"])
    return doc


def get_simulation_history(limit=10):
    """Return the most recent simulation runs from SQLite."""
    limit = max(1, min(int(limit), 50))
    with _connect() as conn:
        rows = conn.execute(
            """SELECT id, city, analyst_id, parameters, rules_triggered,
                      triggered_count, highest_severity, simulated_channels,
                      processing_latency_ms, executed_at
               FROM alert_simulation_log
               ORDER BY executed_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
    out = []
    for r in rows:
        try:
            params = _loads(r["parameters"])
            if not isinstance(params, dict):
                params = {}
        except Exception:
            params = {}
        try:
            rules = _loads(r["rules_triggered"])
        except Exception:
            rules = []
        try:
            channels = _loads(r["simulated_channels"])
        except Exception:
            channels = []
        out.append({
            "id": r["id"],
            "_id": str(r["id"]),
            "city": r["city"],
            "analyst_id": r["analyst_id"],
            "parameters": params,
            "rules_triggered": rules,
            "triggered_count": r["triggered_count"],
            "highest_severity": r["highest_severity"],
            "simulated_channels": channels,
            "processing_latency_ms": r["processing_latency_ms"],
            "executed_at": r["executed_at"],
        })
    return out


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def get_user_by_id(user_id):
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        return dict(row) if row else None


def get_user_by_email(email):
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ?", ((email or "").strip().lower(),)
        ).fetchone()
        return dict(row) if row else None


def email_taken(email):
    return get_user_by_email(email) is not None


def create_user(name, email, password, role="user"):
    """Insert a new user. Returns the new row id, or None if email exists."""
    email = (email or "").strip().lower()
    if email_taken(email):
        return None
    if role not in ("user", "analyst", "admin"):
        role = "user"
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO users (name, email, password_hash, role, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                (name or "").strip(),
                email,
                generate_password_hash(password),
                role,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
        )
        return cur.lastrowid


def set_user_role(user_id, role):
    """Set a user's role. Returns True if a row was updated."""
    if role not in ("user", "analyst", "admin"):
        return False
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE users SET role = ? WHERE id = ?",
            (role, int(user_id)),
        )
        return cur.rowcount > 0


def set_user_subscription(user_id, plan):
    """Set a user's subscription plan ('free', 'premium' or 'enterprise')."""
    if plan not in USER_PLANS:
        plan = "free"
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE users SET subscription = ? WHERE id = ?",
            (plan, int(user_id)),
        )
        return cur.rowcount > 0


def get_user_subscription(user_id):
    """Return the user's stored plan, or None when the user does not exist."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT subscription FROM users WHERE id = ?", (int(user_id),)
        ).fetchone()
    if row is None:
        return None
    return (row["subscription"] or "free").lower()


# ---------------------------------------------------------------------------
# Stripe billing ledger
# ---------------------------------------------------------------------------

def record_payment(
    user_id,
    stripe_session_id,
    amount_cents=0,
    currency="usd",
    status="pending",
    plan="premium",
    email=None,
    payment_intent=None,
    customer_id=None,
):
    """Insert or refresh a Stripe payment row. Returns True when stored.

    Idempotent on ``stripe_session_id``: a re-delivered webhook or a browser
    refresh on the success URL updates the existing ledger row rather than
    creating a duplicate charge record.
    """
    session_id = (stripe_session_id or "").strip()
    if not session_id:
        return False
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        with _connect() as conn:
            conn.execute(
                """
                INSERT INTO payments (
                    user_id, stripe_session_id, stripe_payment_intent,
                    stripe_customer_id, amount_cents, currency, status,
                    plan, email, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(stripe_session_id) DO UPDATE SET
                    status                = excluded.status,
                    amount_cents          = excluded.amount_cents,
                    currency              = excluded.currency,
                    stripe_payment_intent = excluded.stripe_payment_intent,
                    stripe_customer_id    = excluded.stripe_customer_id,
                    updated_at            = excluded.updated_at
                """,
                (
                    int(user_id) if user_id else None,
                    session_id,
                    payment_intent,
                    customer_id,
                    int(amount_cents or 0),
                    (currency or "usd").lower(),
                    status or "pending",
                    plan or "premium",
                    email,
                    now,
                    now,
                ),
            )
        return True
    except Exception:
        return False


def get_payment(stripe_session_id):
    """Return the ledger row for a Checkout Session id, else None."""
    try:
        with _connect() as conn:
            return conn.execute(
                "SELECT * FROM payments WHERE stripe_session_id = ?",
                ((stripe_session_id or "").strip(),),
            ).fetchone()
    except Exception:
        return None


def list_payments(user_id=None, limit=50):
    """Most-recent payments first, optionally scoped to a single user."""
    try:
        with _connect() as conn:
            if user_id is None:
                return conn.execute(
                    "SELECT * FROM payments ORDER BY id DESC LIMIT ?",
                    (int(limit),),
                ).fetchall()
            return conn.execute(
                "SELECT * FROM payments WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (int(user_id), int(limit)),
            ).fetchall()
    except Exception:
        return []


def set_stripe_customer(user_id, customer_id):
    """Remember a user's Stripe customer id (Billing Portal + webhooks)."""
    if not user_id or not customer_id:
        return False
    try:
        with _connect() as conn:
            conn.execute(
                """
                INSERT INTO billing_customers (user_id, stripe_customer_id, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    stripe_customer_id = excluded.stripe_customer_id,
                    updated_at         = excluded.updated_at
                """,
                (
                    int(user_id),
                    str(customer_id),
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                ),
            )
        return True
    except Exception:
        return False


def get_stripe_customer_id(user_id):
    """Stripe customer id for a local user, or None."""
    try:
        with _connect() as conn:
            row = conn.execute(
                "SELECT stripe_customer_id FROM billing_customers WHERE user_id = ?",
                (int(user_id),),
            ).fetchone()
        return row["stripe_customer_id"] if row else None
    except Exception:
        return None


def get_user_id_by_stripe_customer(customer_id):
    """Reverse lookup used by subscription.deleted / payment_failed webhooks."""
    if not customer_id:
        return None
    try:
        with _connect() as conn:
            row = conn.execute(
                "SELECT user_id FROM billing_customers WHERE stripe_customer_id = ?",
                (str(customer_id),),
            ).fetchone()
        return row["user_id"] if row else None
    except Exception:
        return None


def _plan_filter_sql(plan):
    """SQL fragment + params restricting users to a subscription tier.

    ``plan`` accepts 'all'/None (no filter), 'free', 'premium' (which also
    or 'premium'.
    """
    plan = (plan or "all").strip().lower()
    if plan in ("premium", "paid"):
        return "u.subscription = 'premium'", []
    if plan == "free":
        return "(u.subscription IS NULL OR u.subscription = '' OR u.subscription = 'free')", []
    return None, []


def get_users_with_roles(limit=100, offset=0, search="", plan="all"):
    """Return a page of users with optional name/email search and plan filter."""
    search = (search or "").strip()
    plan_sql, plan_params = _plan_filter_sql(plan)
    where = []
    params = []
    if search:
        where.append("(u.name LIKE ? OR u.email LIKE ?)")
        params += ["%" + search + "%", "%" + search + "%"]
    if plan_sql:
        where.append(plan_sql)
        params += plan_params
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    params += [int(limit), int(offset)]
    with _connect() as conn:
        return conn.execute(
            "SELECT u.id, u.name, u.email, u.role, u.subscription, u.created_at, "
            "(SELECT COUNT(*) FROM weather_alerts a WHERE a.user_id = u.id) AS alerts, "
            "(SELECT COUNT(*) FROM api_keys k WHERE k.user_id = u.id) AS api_keys "
            "FROM users u" + clause + " ORDER BY u.id DESC LIMIT ? OFFSET ?",
            params,
        ).fetchall()


def count_users_matching(search="", plan="all"):
    """Count users matching an optional name/email search and plan filter."""
    search = (search or "").strip()
    plan_sql, plan_params = _plan_filter_sql(plan)
    where = []
    params = []
    if search:
        where.append("(u.name LIKE ? OR u.email LIKE ?)")
        params += ["%" + search + "%", "%" + search + "%"]
    if plan_sql:
        where.append(plan_sql)
        params += plan_params
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    with _connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) AS c FROM users u" + clause, params
        ).fetchone()["c"]


def count_users_by_plan(search=""):
    """Global per-tier user counts for the admin console filter tabs.

    Mirrors the same search/plan semantics as the directory list, so the tab
    badges always match what the table would show.
    """
    return {
        "all": count_users_matching(search, "all"),
        "free": count_users_matching(search, "free"),
        "premium": count_users_matching(search, "premium"),
    }


def delete_user(user_id):
    """Delete a user and all records owned by that user in one transaction."""
    user_id = int(user_id)
    with _connect() as conn:
        exists = conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone()
        if not exists:
            return False

        alert_ids = [
            row["id"] for row in conn.execute(
                "SELECT id FROM weather_alerts WHERE user_id = ?", (user_id,)
            ).fetchall()
        ]
        if alert_ids:
            placeholders = ",".join("?" for _ in alert_ids)
            conn.execute(
                "DELETE FROM notification_log WHERE alert_id IN (" + placeholders + ")",
                alert_ids,
            )
        conn.execute("DELETE FROM notification_log WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM support_replies WHERE author_id = ?", (user_id,))
        conn.execute(
            "DELETE FROM support_replies WHERE ticket_id IN "
            "(SELECT id FROM support_tickets WHERE user_id = ?)",
            (user_id,),
        )
        conn.execute("DELETE FROM support_tickets WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM weather_alerts WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM api_keys WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM user_preferences WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM billing_customers WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM payments WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM password_resets WHERE email = (SELECT email FROM users WHERE id = ?)", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return True


def authenticate(email, password):
    """Return the user row when the credentials are valid, else None."""
    user = get_user_by_email(email)
    if user and check_password_hash(user["password_hash"], password or ""):
        return user
    return None


# ---------------------------------------------------------------------------
# WhatsApp / phone (password-reset delivery channel)
# ---------------------------------------------------------------------------

def normalize_phone(raw):
    """Normalise a phone number to digits with an optional leading '+'.

    Accepts '+92 300 1234567', '0300-1234567', '923001234567' etc.
    Returns None when the value is unusable (fewer than 10 / more than 15
    digits). An empty/whitespace input returns '' so callers can clear a
    stored number.
    """
    raw = (raw or "").strip()
    if not raw:
        return ""
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not 10 <= len(digits) <= 15:
        return None
    return ("+" if raw.startswith("+") else "") + digits


def phones_match(stored, given):
    """Tolerant phone comparison for the WhatsApp ownership check.

    Matches when the normalised values are equal OR when their digit
    tails (last 9 digits) agree, so '+92 300 1234567' matches a stored
    '03001234567'.
    """
    a, b = normalize_phone(stored), normalize_phone(given)
    if not a or not b:
        return False
    a_digits, b_digits = a.lstrip("+"), b.lstrip("+")
    if a_digits == b_digits:
        return True
    tail_a, tail_b = a_digits[-9:], b_digits[-9:]
    return len(tail_a) == 9 and tail_a == tail_b


def get_user_by_phone(phone):
    """Return the user row whose stored phone matches (tail-tolerant)."""
    target = normalize_phone(phone)
    if not target:
        return None
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM users WHERE phone != ''").fetchall()
    for row in rows:
        if phones_match(row["phone"], target):
            return row
    return None


def update_user_phone(user_id, phone):
    """Store a normalised phone on the users row ('' clears it).

    Returns True on success, False when the number is invalid.
    """
    normalized = normalize_phone(phone)
    if normalized is None:
        return False
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE users SET phone = ? WHERE id = ?",
            (normalized, int(user_id)),
        )
        return cur.rowcount > 0


def update_password(email, new_password):
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE users SET password_hash = ? WHERE email = ?",
            (generate_password_hash(new_password), (email or "").strip().lower()),
        )
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Password reset codes
# ---------------------------------------------------------------------------

def store_reset_code(email, code):
    """Persist a hashed 6-digit code and invalidate any previous ones."""
    email = (email or "").strip().lower()
    now = datetime.now(timezone.utc)
    with _connect() as conn:
        # Invalidate outstanding codes so only the newest one works.
        conn.execute(
            "UPDATE password_resets SET used = 1 WHERE email = ? AND used = 0",
            (email,),
        )
        conn.execute(
            "INSERT INTO password_resets (email, code_hash, expires_at, created_at) "
            "VALUES (?, ?, ?, ?)",
            (
                email,
                generate_password_hash(code),
                (now + timedelta(minutes=RESET_CODE_TTL_MINUTES)).isoformat(
                    timespec="seconds"
                ),
                now.isoformat(timespec="seconds"),
            ),
        )


def verify_reset_code(email, code):
    """Check a reset code without consuming it."""
    row = _latest_reset(email)
    if row is None:
        return False
    return check_password_hash(row["code_hash"], (code or "").strip())


def consume_reset_code(email, code):
    """Atomically verify AND burn a reset code (single use)."""
    email = (email or "").strip().lower()
    row = _latest_reset(email)
    if row is None or not check_password_hash(row["code_hash"], (code or "").strip()):
        return False
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE password_resets SET used = 1 WHERE id = ? AND used = 0",
            (row["id"],),
        )
        return cur.rowcount > 0


def _latest_reset(email):
    """The newest unused, unexpired reset row for this email (or None)."""
    email = (email or "").strip().lower()
    cutoff = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect() as conn:
        return conn.execute(
            "SELECT * FROM password_resets "
            "WHERE email = ? AND used = 0 AND expires_at >= ? "
            "ORDER BY id DESC LIMIT 1",
            (email, cutoff),
        ).fetchone()


def generate_reset_code():
    """Cryptographically random 6-digit code, e.g. '048213'."""
    return "%06d" % secrets.randbelow(1000000)


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------

def create_api_key(user_id, name):
    user_id = int(user_id)
    raw = secrets.token_urlsafe(32)
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO api_keys (user_id, key_hash, name, created_at, key_prefix) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                user_id,
                generate_password_hash(raw),
                (name or "").strip() or "Default",
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                raw[:8],
            ),
        )
        return cur.lastrowid, raw


def get_api_keys_by_user(user_id):
    with _connect() as conn:
        return conn.execute(
            "SELECT id, name, created_at, last_used_at FROM api_keys WHERE user_id = ? ORDER BY id DESC",
            (int(user_id),),
        ).fetchall()


def verify_api_key(raw):
    with _connect() as conn:
        rows = conn.execute("SELECT id, user_id, key_hash FROM api_keys").fetchall()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for row in rows:
        if check_password_hash(row["key_hash"], raw or ""):
            # Commit + close promptly so the write lock is released before the
            # next request touches the database (threaded Flask dev server).
            with _connect() as conn:
                conn.execute(
                    "UPDATE api_keys SET last_used_at = ? WHERE id = ?",
                    (now, row["id"]),
                )
            return row["user_id"]
    return None


def delete_api_key(key_id, user_id):
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM api_keys WHERE id = ? AND user_id = ?",
            (int(key_id), int(user_id)),
        )
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Weather alerts
# ---------------------------------------------------------------------------

def create_alert(user_id, city, metric, threshold, operator, channels):
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO weather_alerts (user_id, city, metric, threshold, operator, channels, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                int(user_id),
                (city or "").strip(),
                (metric or "").strip(),
                float(threshold),
                (operator or "").strip(),
                (channels or "").strip(),
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
        )
        return cur.lastrowid


def get_alerts_by_user(user_id):
    with _connect() as conn:
        return conn.execute(
            "SELECT * FROM weather_alerts WHERE user_id = ? ORDER BY id DESC",
            (int(user_id),),
        ).fetchall()


def delete_alert(alert_id, user_id):
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM weather_alerts WHERE id = ? AND user_id = ?",
            (int(alert_id), int(user_id)),
        )
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Support tickets & replies
# ---------------------------------------------------------------------------

def create_support_ticket(user_id, subject, category="general", priority="normal"):
    """Create a new support ticket. Returns the new ticket id."""
    if category not in ("general", "bug", "feature", "billing", "other"):
        category = "general"
    if priority not in ("low", "normal", "high", "urgent"):
        priority = "normal"
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO support_tickets
               (user_id, subject, category, priority, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'open', ?, ?)""",
            (int(user_id), (subject or "").strip(), category, priority, now, now),
        )
        return cur.lastrowid


def get_support_tickets_for_user(user_id):
    """Return a user's tickets, newest first."""
    with _connect() as conn:
        return conn.execute(
            """SELECT t.*, u.name AS user_name
               FROM support_tickets t
               JOIN users u ON u.id = t.user_id
               WHERE t.user_id = ?
               ORDER BY t.updated_at DESC""",
            (int(user_id),),
        ).fetchall()


def get_support_ticket(ticket_id, user_id=None):
    """Return one ticket (optionally scoped to a specific user)."""
    with _connect() as conn:
        if user_id is not None:
            row = conn.execute(
                """SELECT t.*, u.name AS user_name, u.email AS user_email
                   FROM support_tickets t
                   JOIN users u ON u.id = t.user_id
                   WHERE t.id = ? AND t.user_id = ?""",
                (int(ticket_id), int(user_id)),
            ).fetchone()
        else:
            row = conn.execute(
                """SELECT t.*, u.name AS user_name, u.email AS user_email
                   FROM support_tickets t
                   JOIN users u ON u.id = t.user_id
                   WHERE t.id = ?""",
                (int(ticket_id),),
            ).fetchone()
        return dict(row) if row else None


def get_all_support_tickets(status=None):
    """Return all tickets (admin view), optionally filtered by status."""
    with _connect() as conn:
        if status:
            return conn.execute(
                """SELECT t.*, u.name AS user_name, u.email AS user_email
                   FROM support_tickets t
                   JOIN users u ON u.id = t.user_id
                   WHERE t.status = ?
                   ORDER BY
                     CASE t.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1
                       WHEN 'normal' THEN 2 ELSE 3 END,
                     t.updated_at DESC""",
                (status,),
            ).fetchall()
        return conn.execute(
            """SELECT t.*, u.name AS user_name, u.email AS user_email
               FROM support_tickets t
               JOIN users u ON u.id = t.user_id
               ORDER BY
                 CASE t.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1
                   WHEN 'normal' THEN 2 ELSE 3 END,
                 t.updated_at DESC"""
        ).fetchall()


def add_support_reply(ticket_id, author_id, body, is_staff=False):
    """Append a reply to a ticket and bump its updated_at. Returns reply id."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO support_replies (ticket_id, author_id, body, is_staff, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (int(ticket_id), int(author_id), (body or "").strip(), 1 if is_staff else 0, now),
        )
        conn.execute(
            "UPDATE support_tickets SET updated_at = ? WHERE id = ?",
            (now, int(ticket_id)),
        )
        return cur.lastrowid


def get_support_replies(ticket_id):
    """Return replies for a ticket, oldest first."""
    with _connect() as conn:
        return conn.execute(
            """SELECT r.*, u.name AS author_name
               FROM support_replies r
               JOIN users u ON u.id = r.author_id
               WHERE r.ticket_id = ?
               ORDER BY r.created_at ASC""",
            (int(ticket_id),),
        ).fetchall()


def update_ticket_status(ticket_id, status):
    """Update a ticket's status. Returns True if a row was updated."""
    if status not in ("open", "in_progress", "resolved", "closed"):
        return False
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE support_tickets SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, int(ticket_id)),
        )
        return cur.rowcount > 0


def count_open_tickets():
    """Return the number of open/in-progress tickets (admin badge)."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM support_tickets WHERE status IN ('open','in_progress')"
        ).fetchone()
        return row["c"] if row else 0


# ---------------------------------------------------------------------------
# User preferences
# ---------------------------------------------------------------------------

def get_preferences(user_id):
    with _connect() as conn:
        row = conn.execute(
            "SELECT saved_cities, theme, home_city, unit, notify_threshold "
            "FROM user_preferences WHERE user_id = ?",
            (int(user_id),),
        ).fetchone()
        if row is None:
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            conn.execute(
                "INSERT INTO user_preferences (user_id, created_at, updated_at) VALUES (?, ?, ?)",
                (int(user_id), now, now),
            )
            return {
                "saved_cities": "[]",
                "theme": "dark",
                "home_city": "karachi",
                "unit": "c",
                "notify_threshold": "default",
            }
        return {
            "saved_cities": row["saved_cities"],
            "theme": row["theme"],
            "home_city": row["home_city"] or "karachi",
            "unit": row["unit"] or "c",
            "notify_threshold": row["notify_threshold"] or "default",
        }


def update_preferences(user_id, saved_cities=None, theme=None,
                       home_city=None, unit=None, notify_threshold=None):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect() as conn:
        row = conn.execute(
            "SELECT user_id FROM user_preferences WHERE user_id = ?", (int(user_id),)
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO user_preferences (user_id, saved_cities, theme, home_city, unit, "
                "notify_threshold, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    int(user_id),
                    saved_cities or "[]",
                    theme or "dark",
                    home_city or "karachi",
                    unit or "c",
                    notify_threshold or "default",
                    now,
                    now,
                ),
            )
            return
        sets = ["updated_at = ?"]
        args = [now]
        for column, value in (
            ("saved_cities", saved_cities),
            ("theme", theme),
            ("home_city", home_city),
            ("unit", unit),
            ("notify_threshold", notify_threshold),
        ):
            if value is not None:
                sets.append("%s = ?" % column)
                args.append(value)
        args.append(int(user_id))
        conn.execute(
            "UPDATE user_preferences SET " + ", ".join(sets) + " WHERE user_id = ?",
            tuple(args),
        )


# ---------------------------------------------------------------------------
# Notification log
# ---------------------------------------------------------------------------

def log_notification(user_id, alert_id, channel, status, detail=None):
    with _connect() as conn:
        conn.execute(
            "INSERT INTO notification_log (user_id, alert_id, channel, status, detail, sent_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                int(user_id),
                int(alert_id) if alert_id else None,
                (channel or "").strip(),
                (status or "").strip(),
                detail,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
        )


def get_notification_log(user_id, limit=50):
    with _connect() as conn:
        return conn.execute(
            "SELECT * FROM notification_log WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (int(user_id), int(limit)),
        ).fetchall()


def save_push_subscription(user_id, subscription):
    endpoint = (subscription.get("endpoint") or "").strip()
    if not endpoint:
        raise ValueError("Push subscription endpoint is required")
    payload = json.dumps(subscription, separators=(",", ":"), sort_keys=True)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO push_subscriptions (endpoint, user_id, subscription, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(endpoint) DO UPDATE SET
                user_id = excluded.user_id,
                subscription = excluded.subscription,
                updated_at = excluded.updated_at
            """,
            (endpoint, int(user_id), payload, now, now),
        )


def delete_push_subscription(endpoint):
    with _connect() as conn:
        conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))


def get_push_subscriptions(user_id=None):
    with _connect() as conn:
        if user_id is None:
            rows = conn.execute(
                "SELECT user_id, endpoint, subscription FROM push_subscriptions"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT user_id, endpoint, subscription FROM push_subscriptions WHERE user_id = ?",
                (int(user_id),),
            ).fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# API request telemetry (powers the live admin dashboard)
# ---------------------------------------------------------------------------

def log_api_request(method, path, city=None, status=None, live=None, duration_ms=None):
    """Record one API request. `created_at` is stored in LOCAL time so the
    admin 'today' / hourly-bucket queries line up with the chart labels."""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO api_requests (method, path, city, status, live, duration_ms, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                (method or "").strip(),
                (path or "").strip(),
                city,
                status,
                live,
                duration_ms,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )


def prune_api_requests(days=7):
    """Drop telemetry older than `days` days (keeps the DB small)."""
    cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    with _connect() as conn:
        conn.execute("DELETE FROM api_requests WHERE created_at < ?", (cutoff,))


def _local_midnight():
    return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)


def count_users():
    with _connect() as conn:
        return conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]


def count_users_created_since(cutoff_iso):
    with _connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) AS c FROM users WHERE created_at >= ?", (cutoff_iso,)
        ).fetchone()["c"]


def count_alerts():
    with _connect() as conn:
        return conn.execute("SELECT COUNT(*) AS c FROM weather_alerts").fetchone()["c"]


def count_api_keys():
    with _connect() as conn:
        return conn.execute("SELECT COUNT(*) AS c FROM api_keys").fetchone()["c"]


def count_active_api_keys():
    with _connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) AS c FROM api_keys WHERE is_active = 1"
        ).fetchone()["c"]


def count_requests_between(start_iso, end_iso=None, live=None):
    """Count logged API requests in the [start, end) window (local time)."""
    sql = "SELECT COUNT(*) AS c FROM api_requests WHERE created_at >= ?"
    args = [start_iso]
    if end_iso:
        sql += " AND created_at < ?"
        args.append(end_iso)
    if live is not None:
        sql += " AND live = ?"
        args.append(1 if live else 0)
    with _connect() as conn:
        return conn.execute(sql, tuple(args)).fetchone()["c"]


def requests_per_hour(hours=24):
    """Bucket the last `hours` hours of API requests, oldest first.

    Aligned with admin._hour_labels(): hour-of-day buckets in local time,
    so values[i] matches labels[i] exactly.
    """
    now = datetime.now()
    current_hour = now.replace(minute=0, second=0, microsecond=0)
    cutoff = (current_hour - timedelta(hours=hours - 1)).isoformat(timespec="seconds")
    counts = {i: 0 for i in range(hours)}
    with _connect() as conn:
        rows = conn.execute(
            "SELECT created_at FROM api_requests WHERE created_at >= ?",
            (cutoff,),
        ).fetchall()
    for row in rows:
        try:
            t = datetime.fromisoformat(row["created_at"]).replace(
                minute=0, second=0, microsecond=0
            )
        except (TypeError, ValueError):
            continue
        idx = hours - 1 - int((current_hour - t).total_seconds() // 3600)
        if 0 <= idx < hours:
            counts[idx] += 1
    return [counts[i] for i in range(hours)]


def analyst_dashboard_telemetry(hours=24):
    """Live 24h telemetry aggregation for the Analyst dashboard.

    Single SQLite pass over the api_requests telemetry table producing the
    KPI totals, active API-key count and hour-of-day chart series. The dict
    is shaped to drop straight into {{ telemetry | tojson }} -> Chart.js
    with no extra client-side fetch. Returns None if the table is unreadable.
    """
    now = datetime.now()
    current_hour = now.replace(minute=0, second=0, microsecond=0)
    cutoff = (current_hour - timedelta(hours=hours - 1)).isoformat(timespec="seconds")
    labels = [
        (current_hour - timedelta(hours=i)).strftime("%H:00")
        for i in range(hours - 1, -1, -1)
    ]
    try:
        with _connect() as conn:
            kpi = conn.execute(
                """
                SELECT COUNT(*) AS total_requests,
                       COALESCE(ROUND(AVG(duration_ms), 1), 0)              AS avg_latency,
                       COALESCE(ROUND(100.0 * SUM(CASE WHEN status < 400
                                                      THEN 1 ELSE 0 END)
                                      / NULLIF(COUNT(*), 0), 2), 0.0)        AS success_rate
                FROM api_requests
                WHERE created_at >= ?
                """,
                (cutoff,),
            ).fetchone()
            active_keys = conn.execute(
                "SELECT COUNT(*) AS c FROM api_keys WHERE is_active = 1"
            ).fetchone()["c"]
            rows = conn.execute(
                """
                SELECT substr(created_at, 12, 2) || ':00' AS hour,
                       COUNT(*)                           AS req_count,
                       COALESCE(ROUND(AVG(duration_ms), 1), 0) AS avg_latency
                FROM api_requests
                WHERE created_at >= ?
                GROUP BY substr(created_at, 12, 2)
                ORDER BY MIN(created_at)
                """,
                (cutoff,),
            ).fetchall()
    except Exception:
        return None

    try:
        by_hour = {
            r["hour"]: {"req_count": r["req_count"], "avg_latency": r["avg_latency"]}
            for r in (rows or [])
        }
    except Exception:
        by_hour = {}

    is_simulated = bool(kpi["total_requests"] == 0)
    return {
        "generated_at": now.strftime("%H:%M"),
        "is_simulated": is_simulated,
        "total_requests": int(kpi["total_requests"] or 0),
        "avg_latency": float(kpi["avg_latency"] or 0),
        "success_rate": float(kpi["success_rate"] or 0.0),
        "active_keys": int(active_keys or 0),
        "chart_labels": labels,
        "chart_requests": [
            by_hour[h]["req_count"] if h in by_hour else 0 for h in labels
        ],
        "chart_latencies": [
            by_hour[h]["avg_latency"] if h in by_hour else None for h in labels
        ],
    }


def recent_users(limit=25):
    """Newest registered users with their alert / API-key counts."""
    with _connect() as conn:
        return conn.execute(
            """
            SELECT u.id, u.name, u.email, u.role, u.subscription, u.created_at,
                   (SELECT COUNT(*) FROM weather_alerts a WHERE a.user_id = u.id) AS alerts,
                   (SELECT COUNT(*) FROM api_keys k WHERE k.user_id = u.id)      AS api_keys
            FROM users u
            ORDER BY u.id DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()


# ---------------------------------------------------------------------------
# Analyst expansion: annotations · forecast accuracy · audit log · matrices
# ---------------------------------------------------------------------------

def _now_iso():
    return datetime.now().isoformat(timespec="seconds")


# --- 1.1 Timeline incident annotations --------------------------------------

def list_annotations(limit=100):
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT a.id, a.timestamp, a.label, a.severity, a.created_at,
                   u.name AS author
            FROM telemetry_annotations a
            JOIN users u ON u.id = a.author_id
            ORDER BY a.timestamp DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        return [dict(r) for r in rows]


def add_annotation(timestamp, author_id, label, severity="info"):
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO telemetry_annotations
                (timestamp, author_id, label, severity, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (str(timestamp), int(author_id), str(label), str(severity), _now_iso()),
        )
        return cur.lastrowid


def delete_annotation(annotation_id, author_id):
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM telemetry_annotations WHERE id = ? AND author_id = ?",
            (int(annotation_id), int(author_id)),
        )
        return cur.rowcount > 0


# --- 1.2 Endpoint latency & error heatmap ------------------------------------

def endpoint_matrix(hours=24):
    """24h matrix: per API path → request count, 4xx/5xx, avg latency."""
    cutoff = (datetime.now() - timedelta(hours=hours)).isoformat(timespec="seconds")
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT path,
                   COUNT(*)                                AS requests,
                   COALESCE(ROUND(AVG(duration_ms), 1), 0)  AS avg_latency,
                   SUM(CASE WHEN status BETWEEN 400 AND 499
                            THEN 1 ELSE 0 END)             AS errors_4xx,
                   SUM(CASE WHEN status >= 500
                            THEN 1 ELSE 0 END)             AS errors_5xx
            FROM api_requests
            WHERE created_at >= ?
            GROUP BY path
            ORDER BY requests DESC
            LIMIT 25
            """,
            (cutoff,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["status"] = (
                "red" if d["errors_5xx"] > 0 or d["avg_latency"] > 200
                else "amber" if d["avg_latency"] > 50
                else "teal"
            )
            out.append(d)
        return out


# --- 2.1 Model drift & forecast accuracy (MAE / RMSE) -------------------------

def record_forecast_verification(city, predicted_temp, actual_temp):
    err = abs(float(actual_temp) - float(predicted_temp))
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO forecast_verification
                (city, timestamp, predicted_temp, actual_temp, error_margin, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (str(city), _now_iso(), float(predicted_temp),
             float(actual_temp), round(err, 2), _now_iso()),
        )
    return err


def model_accuracy(city=None, window_hours=168):
    """MAE and RMSE over the verification window, optionally per city."""
    cutoff = (datetime.now() - timedelta(hours=window_hours)).isoformat(timespec="seconds")
    q, params = (
        "SELECT city, predicted_temp, actual_temp, error_margin FROM forecast_verification "
        "WHERE timestamp >= ?",
        (cutoff,),
    )
    if city:
        q += " AND city = ?"
        params = (cutoff, str(city))
    q += " ORDER BY timestamp DESC LIMIT 2000"
    with _connect() as conn:
        rows = conn.execute(q, params).fetchall()

    if not rows:
        return {"count": 0, "mae": None, "rmse": None, "cities": []}

    errs = [float(r["error_margin"]) for r in rows]
    n = len(errs)
    mae = sum(errs) / n
    rmse = (sum(e * e for e in errs) / n) ** 0.5

    by_city = {}
    for r in rows:
        by_city.setdefault(r["city"], []).append(float(r["error_margin"]))
    cities = [
        {
            "city": c,
            "count": len(v),
            "mae": round(sum(v) / len(v), 2),
            "rmse": round((sum(e * e for e in v) / len(v)) ** 0.5, 2),
        }
        for c, v in sorted(by_city.items())
    ]
    return {
        "count": n,
        "mae": round(mae, 2),
        "rmse": round(rmse, 2),
        "window_hours": int(window_hours),
        "cities": cities,
    }

# --- 3.1 Hadoop job runner (in-process simulation, QUEUED→RUNNING→SUCCESS) ----

_HADOOP_JOBS = {}


def hadoop_job_create(job_type, author_id):
    """Simulated MapReduce/Spark climate job. Types: daily_summary,
    aqi_averages, extreme_events."""
    valid = ("daily_summary", "aqi_averages", "extreme_events")
    if job_type not in valid:
        return None
    job_id = "job_%s_%s" % (datetime.now().strftime("%Y%m%d_%H%M%S"),
                            secrets.token_hex(3))
    job = {
        "job_id": job_id,
        "type": job_type,
        "author_id": int(author_id),
        "status": "QUEUED",
        "map_progress": 0,
        "reduce_progress": 0,
        "submitted_at": _now_iso(),
        "finished_at": None,
    }
    _HADOOP_JOBS[job_id] = job
    return dict(job)


def hadoop_job_get(job_id):
    job = _HADOOP_JOBS.get(job_id)
    if job is None:
        return None
    # advance the simulated pipeline deterministically over ~30 seconds
    elapsed = (datetime.now() - datetime.fromisoformat(job["submitted_at"])).total_seconds()
    if elapsed < 3:
        job["status"] = "QUEUED"
    elif elapsed < 20:
        job["status"] = "RUNNING"
        job["map_progress"] = min(100, int(elapsed / 20 * 100))
        job["reduce_progress"] = max(0, min(100, int((elapsed - 10) / 10 * 100)))
    else:
        job["status"] = "SUCCESS"
        job["map_progress"] = 100
        job["reduce_progress"] = 100
        job["finished_at"] = job["finished_at"] or _now_iso()
    return dict(job)


# --- 3.2 Climate data exporter ------------------------------------------------

def export_metrics(range_hours=168):
    """Clean dataset for R / Pandas / Tableau (telemetry + forecast rows)."""
    cutoff = (datetime.now() - timedelta(hours=range_hours)).isoformat(timespec="seconds")
    with _connect() as conn:
        telemetry = [
            dict(r) for r in conn.execute(
                """
                SELECT path, status, duration_ms, live, created_at
                FROM api_requests WHERE created_at >= ?
                ORDER BY created_at DESC LIMIT 5000
                """,
                (cutoff,),
            )
        ]
        forecast = [
            dict(r) for r in conn.execute(
                """
                SELECT city, timestamp, predicted_temp, actual_temp, error_margin
                FROM forecast_verification WHERE timestamp >= ?
                ORDER BY timestamp DESC LIMIT 2000
                """,
                (cutoff,),
            )
        ]
    return {"range_hours": int(range_hours), "telemetry": telemetry,
            "forecast_verification": forecast}


# --- 4.2 Analyst activity audit log -------------------------------------------

def audit_log_action(author_id, action, detail=None):
    with _connect() as conn:
        conn.execute(
            "INSERT INTO analyst_audit_log (author_id, action, detail, created_at) "
            "VALUES (?, ?, ?, ?)",
            (int(author_id), str(action), detail, _now_iso()),
        )


def audit_log_list(limit=100, author_id=None, action=None):
    q = ("SELECT a.id, a.action, a.detail, a.created_at, u.name AS author "
         "FROM analyst_audit_log a JOIN users u ON u.id = a.author_id")
    params = []
    conds = []
    if author_id:
        conds.append("a.author_id = ?")
        params.append(int(author_id))
    if action:
        conds.append("a.action = ?")
        params.append(str(action))
    if conds:
        q += " WHERE " + " AND ".join(conds)
    q += " ORDER BY a.id DESC LIMIT ?"
    params.append(int(limit))
    with _connect() as conn:
        return [dict(r) for r in conn.execute(q, params)]



def recent_api_requests(limit=50):
    with _connect() as conn:
        return conn.execute(
            "SELECT method, path, city, status, live, duration_ms, created_at "
            "FROM api_requests ORDER BY id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()


init_db()
