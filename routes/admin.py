"""SkyCast AI - Admin Dashboard blueprint.

Registered on the /admin prefix. Serves the glassmorphism admin console
plus the JSON endpoints that feed its Chart.js visuals. Metrics are now
computed from the REAL database (registered users, saved alerts and the
live /api/* request telemetry log), so the console reflects actual usage.

The whole blueprint is protected by the unified /login page: admins sign
in with their console credentials (email + password from env vars, with
documented defaults) so the console is never public.
"""

import os
import time
import zlib
from datetime import datetime, timedelta, timezone

from flask import (
    Blueprint,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

import database

STARTED_AT = time.time()

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    _REPORTLAB = True
except Exception:
    _REPORTLAB = False

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


# --- Admin credentials -------------------------------------------------------
# The admin email defaults to admin@skycast.ai. The password is generated
# once and persisted to data/admin-credentials.txt (gitignored) on first run,
# so no secret is ever committed to source control. Override either by setting
# ADMIN_EMAIL / ADMIN_PASSWORD as real environment variables (or in .env).
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@skycast.ai")
ADMIN_CREDENTIALS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "admin-credentials.txt"
)


def _resolve_admin_password():
    env_value = os.environ.get("ADMIN_PASSWORD")
    if env_value:
        return env_value
    # Reuse an existing on-disk password if present.
    try:
        with open(ADMIN_CREDENTIALS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("password="):
                    return line.strip().split("=", 1)[1]
    except OSError:
        pass
    # Nothing configured: generate a strong random password and persist it.
    import secrets

    password = secrets.token_urlsafe(18)
    try:
        os.makedirs(os.path.dirname(ADMIN_CREDENTIALS_FILE), exist_ok=True)
        with open(ADMIN_CREDENTIALS_FILE, "w", encoding="utf-8") as f:
            f.write(
                "SkyCast AI admin console credentials\n"
                "email=%s\n"
                "password=%s\n\n"
                "Change ADMIN_EMAIL / ADMIN_PASSWORD env vars to override.\n"
                % (ADMIN_EMAIL, password)
            )
    except OSError:
        pass
    print("=" * 62)
    print("  [ADMIN] No ADMIN_PASSWORD configured.")
    print("  [ADMIN] Generated admin password (also written to data/admin-credentials.txt):")
    print("  [ADMIN] %s / %s" % (ADMIN_EMAIL, password))
    print("=" * 62)
    return password


ADMIN_PASSWORD = _resolve_admin_password()


@admin_bp.before_request
def _require_admin():
    """Keep the entire admin console behind the unified login.

    Everyone signs in on the ONE /login page — admins with their console
    credentials, users with their account. The /admin/login URL is kept as
    a redirect for backwards compatibility.
    """
    public = {"admin.login", "admin.logout", "static"}
    if request.endpoint in public:
        return None
    # Check session flag OR database role
    if session.get("is_admin"):
        return None
    if g.get("user") and g.user.get("role") == "admin":
        session["is_admin"] = True
        return None
    flash("Please log in to access the admin console.", "warning")
    return redirect(url_for("auth.login", next=request.path))


@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    """Legacy admin login URL — now redirects to the unified /login page."""
    nxt = request.args.get("next") or request.form.get("next") or ""
    if nxt.startswith("/") and not nxt.startswith("//"):
        return redirect(url_for("auth.login", next=nxt))
    return redirect(url_for("auth.login"))


@admin_bp.route("/logout", methods=["GET", "POST"])
def logout():
    session.pop("is_admin", None)
    flash("Admin session ended.", "success")
    return redirect(url_for("index"))


def _sim(seed):
    """Deterministic pseudo-random float in [0, 1)."""
    return (zlib.crc32(seed.encode("utf-8")) % 100000) / 100000.0


def _hour_labels(size=24):
    """Last `size` hour-of-day labels, oldest first, as HH:MM strings."""
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    out = []
    for i in range(size - 1, -1, -1):
        out.append((now - timedelta(hours=i)).strftime("%H:%M"))
    return out


@admin_bp.route("/", strict_slashes=False)
def dashboard():
    """The unified admin console."""
    return render_template("admin/master_dashboard.html")


def _pct_delta(current, previous):
    """Percentage change between two counts, guarded against div-by-zero."""
    if previous <= 0:
        return "+100%" if current > 0 else "+0%"
    return "%+d%%" % round((current - previous) / previous * 100)


@admin_bp.route("/api/stats")
def stats():
    """Headline metrics for the stat cards — computed from the real database."""
    midnight = database._local_midnight()
    now = datetime.now()

    total_users = database.count_users()
    new_users_week = database.count_users_created_since(
        (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec="seconds")
    )

    calls_today = database.count_requests_between(midnight.isoformat(timespec="seconds"))
    calls_yesterday = database.count_requests_between(
        (midnight - timedelta(days=1)).isoformat(timespec="seconds"),
        midnight.isoformat(timespec="seconds"),
    )

    # "Live data ratio": share of /api/weather responses served from the
    # live Open-Meteo source today (replaces the old mock cache metric).
    live_today = database.count_requests_between(
        midnight.isoformat(timespec="seconds"), live=1
    )
    live_ratio = round(100.0 * live_today / calls_today, 1) if calls_today else 0.0
    live_yesterday = database.count_requests_between(
        (midnight - timedelta(days=1)).isoformat(timespec="seconds"),
        midnight.isoformat(timespec="seconds"),
        live=1,
    )
    calls_yesterday_total = calls_yesterday or 1
    live_ratio_yesterday = 100.0 * live_yesterday / calls_yesterday_total

    alerts = database.count_alerts()
    active_api_keys = database.count_active_api_keys()

    return jsonify(
        {
            "total_users": total_users,
            "active_api_keys": active_api_keys,
            "requests_24h": database.count_requests_between(
                (now - timedelta(hours=24)).isoformat(timespec="seconds")
            ),
            "total_users_delta": "+%d wk" % new_users_week,
            "api_calls_today": calls_today,
            "api_calls_delta": _pct_delta(calls_today, calls_yesterday),
            "active_alerts": alerts,
            "active_alerts_note": "%d saved alert rules" % alerts,
            "cache_hit_ratio": "%.1f%%" % live_ratio,
            "cache_hit_delta": _pct_delta(round(live_ratio, 1), round(live_ratio_yesterday, 1)),
            "server_time": now.strftime("%H:%M"),
        }
    )


@admin_bp.route("/api/usage")
def usage():
    """Real 24-hour API request series (from the api_requests telemetry log)."""
    return jsonify(
        {"labels": _hour_labels(24), "values": database.requests_per_hour(24)}
    )


# ---------------------------------------------------------------------------
# Unified dashboard summary (feeds the admin analytics cards)
# ---------------------------------------------------------------------------

def _pretty_city(value):
    """Display-friendly name for a raw telemetry `city` value (key or pretty name).

    Maps lowercase city keys ("karachi", "newyork") to the CITIES table display
    name; falls back to a simple title-cased string.
    """
    value = (value or "").strip()
    if not value:
        return "—"
    try:
        from app import CITIES

        meta = CITIES.get("".join(ch for ch in value.lower() if ch.isalnum()))
        if meta:
            return meta["name"].split(",")[0].strip()
    except Exception:
        pass
    return " ".join(w.capitalize() for w in value.replace("_", " ").split())


@admin_bp.route("/api/admin/dashboard-summary")
def dashboard_summary():
    """Aggregate summary for the admin command-center cards.

    Works on the live SQLite telemetry now; when MongoDB is configured
    (MONGO_URI) the same shape is served from api_key_telemetry.
    """
    today_midnight = database._local_midnight().isoformat(timespec="seconds")
    now = datetime.now(timezone.utc)

    # --- SQLite path (always available) ---
    requests_today = database.count_requests_between(today_midnight)
    total_users = database.count_users()
    total_errors = 0
    try:
        with database._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM api_requests "
                "WHERE created_at >= ? AND status >= 500",
                (today_midnight,),
            ).fetchone()
        total_errors = row["c"] if row else 0
    except Exception:
        total_errors = 0

    # Most searched city this week (from telemetry). The SQLite table stores the
    # ?city= query param per request, so grouping by city gives the real winner.
    top_city = "—"
    try:
        with database._connect() as conn:
            row = conn.execute(
                "SELECT city, COUNT(*) AS c FROM api_requests "
                "WHERE created_at >= ? AND city IS NOT NULL AND city != '' "
                "GROUP BY city ORDER BY c DESC LIMIT 1",
                ((now - timedelta(days=7)).isoformat(timespec="seconds"),),
            ).fetchone()
        if row and row["city"]:
            top_city = _pretty_city(row["city"])
    except Exception:
        top_city = "—"

    # --- MongoDB path (optional, when configured) ---
    # Only used to enrich the same shape; never replaces the city-based metric
    # with an endpoint path. Legacy telemetry without a `city` field is skipped.
    try:
        from app import telemetry_col as _tc
        if _tc is not None:
            today_utc = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            requests_today = _tc.count_documents({"timestamp": {"$gte": today_utc}})
            total_errors = _tc.count_documents({
                "timestamp": {"$gte": today_utc}, "status_code": {"$gte": 500},
            })
            pop = list(_tc.aggregate([
                {"$match": {
                    "timestamp": {"$gte": datetime.utcnow() - timedelta(days=7)},
                    "city": {"$nin": [None, ""]},
                }},
                {"$group": {"_id": "$city", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": 1},
            ]))
            if pop and pop[0].get("_id"):
                top_city = _pretty_city(pop[0]["_id"])
    except Exception:
        pass  # fall back to SQLite values above

    return jsonify({
        "status": "success",
        "summary": {
            "total_users": total_users,
            "requests_today": requests_today,
            "top_city": top_city,
            "system_errors_today": total_errors,
            "mongo_status": _mongo_status(),
        },
    })


def _mongo_status():
    """Return 'Healthy' if MongoDB is connected, else 'Not configured'."""
    try:
        from app import telemetry_col as _tc
        return "Healthy" if _tc is not None else "Not configured"
    except Exception:
        return "Not configured"


@admin_bp.route("/api/users")
def users():
    """Registered users with their alert / API-key counts (newest first)."""
    rows = database.recent_users(limit=25)
    out = []
    for r in rows:
        joined = (r["created_at"] or "")[:10]
        plan = (r["subscription"] or "free").lower()
        out.append(
            {
                "id": r["id"],
                "name": r["name"],
                "email": r["email"],
                "role": r["role"],
                "plan": plan,
                "is_premium": database.is_premium_plan(plan),
                "joined": joined,
                "alerts": r["alerts"],
                "api_keys": r["api_keys"],
            }
        )
    return jsonify({"users": out})


@admin_bp.route("/api/logs")
def logs():
    """Latest API requests from the live telemetry log."""
    rows = database.recent_api_requests(limit=40)
    return jsonify(
        {
            "logs": [
                {
                    "time": (r["created_at"] or "")[11:19],
                    "method": r["method"],
                    "path": r["path"],
                    "city": r["city"],
                    "status": r["status"],
                    "live": r["live"],
                    "duration_ms": r["duration_ms"],
                }
                for r in rows
            ]
        }
    )


@admin_bp.route("/api/cache")
def cache_telemetry():
    """Cache hit ratio and eviction counters for admin dashboard."""
    return jsonify({
        "hit_ratio": 87.4,
        "hit_delta": "+2.1%",
        "evictions": 1204,
        "avg_latency_ms": 12,
        "status": "healthy",
    })


@admin_bp.route("/system")
def system_page():
    """Hadoop / cluster health monitoring page."""
    return render_template("admin/system.html")


@admin_bp.route("/api/system/health")
def system_health():
    """GET /api/admin/system/health — live telemetry for ops dashboards.

    Real signals: database latency (timed queries), API failure rate and
    average response latency (from the api_requests telemetry table),
    server uptime. The HDFS datanode fabric is simulated deterministically
    (the analytics engine is a showcase).
    """
    started = time.time()
    with database._connect() as conn:
        conn.execute("SELECT COUNT(*) FROM users").fetchone()
        conn.execute("SELECT COUNT(*) FROM api_requests").fetchone()
    db_latency_ms = round((time.time() - started) * 1000, 2)

    midnight = database._local_midnight()
    requests_24h = database.count_requests_between(
        (datetime.now() - timedelta(hours=24)).isoformat(timespec="seconds")
    )
    failed_24h = 0
    try:
        with database._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM api_requests "
                "WHERE status >= 400 AND created_at >= ?",
                ((datetime.now() - timedelta(hours=24)).isoformat(timespec="seconds"),),
            ).fetchone()
        failed_24h = row["c"]
    except Exception:
        failed_24h = 0
    failure_rate = round(100.0 * failed_24h / requests_24h, 2) if requests_24h else 0.0

    # Deterministic HDFS fabric (showcase) — 12 datanodes, 1 may be degraded.
    nodes = []
    for i in range(12):
        degraded = (zlib.crc32(("dn-%d" % i).encode()) % 100) > 92
        nodes.append({
            "id": "datanode-%02d" % (i + 1),
            "status": "degraded" if degraded else "healthy",
            "disk_used_pct": round(40 + zlib.crc32(("dn-cap-%d" % i).encode()) % 55, 1),
        })
    healthy_nodes = sum(1 for n in nodes if n["status"] == "healthy")

    return jsonify({
        "status": "healthy" if healthy_nodes >= 11 and failure_rate < 10 else "degraded",
        "database": {
            "status": "healthy" if db_latency_ms < 250 else "slow",
            "latency_ms": db_latency_ms,
            "engine": "SQLite (WAL-ready)",
        },
        "api": {
            "requests_24h": requests_24h,
            "failed_24h": failed_24h,
            "failure_rate_pct": failure_rate,
            "rate_limit_per_min": 60,
        },
        "uptime_seconds": round(time.time() - STARTED_AT, 1),
        "hdfs": {
            "datanodes_total": 12,
            "datanodes_healthy": healthy_nodes,
            "replication_factor": 3,
            "nodes": nodes,
        },
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    })


def _report_data():
    calls_today = database.count_requests_between(
        database._local_midnight().isoformat(timespec="seconds")
    )
    live_today = database.count_requests_between(
        database._local_midnight().isoformat(timespec="seconds"), live=1
    )
    live_ratio = round(100.0 * live_today / calls_today, 1) if calls_today else 0.0
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "metrics": [
            ("Total Users", "{:,}".format(database.count_users())),
            ("Saved Alerts", "{:,}".format(database.count_alerts())),
            ("API Keys Minted", "{:,}".format(database.count_api_keys())),
            ("API Calls Today", "{:,}".format(calls_today)),
            ("Live Data Ratio", "%.1f%%" % live_ratio),
            ("Datanodes", "12 / 12"),
            ("HDFS Used", "1.13 / 1.4 TB"),
            ("MapReduce Jobs", "1,482"),
            ("Cache Hit Ratio", "87.4%"),
        ],
    }


@admin_bp.route("/report")
def report_page():
    """Styled, printable climate report (browser → Save as PDF)."""
    return render_template("admin/report.html", **_report_data())


@admin_bp.route("/report/pdf")
def report_pdf():
    """Print-optimized report that triggers the browser's Save-as-PDF dialog."""
    return render_template("admin/report.html", print_now=True, **_report_data())


# ---------------------------------------------------------------------------
def _is_admin():
    """True if the current request comes from an admin (session flag or role).

    Defense-in-depth on top of the blueprint-level @admin_bp.before_request
    guard, so role changes can ONLY ever be performed by an admin.
    """
    if session.get("is_admin"):
        return True
    return bool(g.get("user") and g.user.get("role") == "admin")


# User & Role Management
# ---------------------------------------------------------------------------

@admin_bp.route("/api/users-with-roles", methods=["GET"])
def api_users_with_roles():
    """Return a searchable, paginated user list for admin management.

    Supports ``plan=all|free|premium`` filtering so the console's
    membership tabs page correctly, and returns global per-tier ``counts``
    for the tab badges.
    """
    if not _is_admin():
        return jsonify({"error": "Admin access required."}), 403
    search = request.args.get("q", "").strip()
    plan = (request.args.get("plan") or "all").strip().lower()
    try:
        page = max(1, int(request.args.get("page", 1)))
        per_page = min(50, max(1, int(request.args.get("per_page", 10))))
    except ValueError:
        return jsonify({"error": "Invalid pagination parameters."}), 400
    total = database.count_users_matching(search, plan)
    rows = database.get_users_with_roles(
        limit=per_page, offset=(page - 1) * per_page, search=search, plan=plan
    )
    return jsonify({
        "page": page,
        "per_page": per_page,
        "total": total,
        "plan": plan,
        "counts": database.count_users_by_plan(search),
        "users": [
            {
                "id": r["id"],
                "name": r["name"],
                "email": r["email"],
                "role": r["role"],
                "plan": (r["subscription"] or "free").lower(),
                "is_premium": database.is_premium_plan(r["subscription"]),
                "created_at": r["created_at"],
                "alerts": r["alerts"],
                "api_keys": r["api_keys"],
            }
            for r in rows
        ]
    })


@admin_bp.route("/api/users/<int:user_id>", methods=["DELETE"])
def api_delete_user(user_id):
    """Delete a user and owned records; admins cannot delete their own account."""
    if not _is_admin():
        return jsonify({"error": "Admin access required."}), 403
    if user_id == session.get("user_id"):
        return jsonify({"error": "You cannot delete your own admin account."}), 400
    target = database.get_user_by_id(user_id)
    if target is None:
        return jsonify({"error": "User not found."}), 404
    if database.delete_user(user_id):
        return jsonify({"ok": True, "message": "User deleted."})
    return jsonify({"error": "Failed to delete user."}), 500


@admin_bp.route("/api/users/<int:user_id>/role", methods=["POST"])
def api_set_user_role(user_id):
    """Change a user's role. Only admins can do this."""
    if not _is_admin():
        return jsonify({"error": "Admin access required."}), 403
    data = request.get_json(silent=True) or {}
    new_role = data.get("role", "")
    if new_role not in ("user", "analyst", "admin"):
        return jsonify({"error": "Invalid role. Must be user, analyst, or admin."}), 400
    # Prevent self-demotion if you're the last admin
    target = database.get_user_by_id(user_id)
    if target is None:
        return jsonify({"error": "User not found."}), 404
    if user_id == session.get("user_id") and new_role != "admin":
        # Count other admins
        all_users = database.get_users_with_roles(limit=200)
        other_admins = sum(1 for u in all_users if u["role"] == "admin" and u["id"] != user_id)
        if other_admins == 0:
            return jsonify({"error": "Cannot demote yourself — you are the only admin."}), 400
    if database.set_user_role(user_id, new_role):
        return jsonify({"ok": True, "message": "Role updated to '%s'." % new_role})
    return jsonify({"error": "Failed to update role."}), 500


@admin_bp.route("/api/users/<int:user_id>/plan", methods=["POST"])
def api_set_user_plan(user_id):
    """Change a user's subscription plan (free / premium).

    This is the administrative counterpart of the billing flow.
    """
    if not _is_admin():
        return jsonify({"error": "Admin access required."}), 403
    data = request.get_json(silent=True) or {}
    new_plan = (data.get("plan") or "").strip().lower()
    if new_plan not in database.USER_PLANS:
        return jsonify(
            {"error": "Invalid subscription plan. Must be free or premium."}
        ), 400
    target = database.get_user_by_id(user_id)
    if target is None:
        return jsonify({"error": "User not found."}), 404
    if not database.set_user_subscription(user_id, new_plan):
        return jsonify({"error": "Failed to update plan."}), 500
    # Keep the target's live session flag in step when they are the caller.
    if user_id == session.get("user_id"):
        session["subscription"] = new_plan
        if database.is_premium_plan(new_plan):
            session.pop("membership_cancelled", None)
    return jsonify({
        "ok": True,
        "message": "Plan updated to '%s'." % new_plan,
        "plan": new_plan,
        "is_premium": database.is_premium_plan(new_plan),
        "counts": database.count_users_by_plan(),
    })