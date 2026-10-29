"""SkyCast AI — session-based authentication (Flask + stdlib + werkzeug,

which ships with Flask). Routes:

    GET/POST /signup            create an account (auto-login)
    GET/POST /login             ONE unified login for users AND admins:
                                - valid user account  -> user dashboard
                                - valid admin console credentials -> /admin
                                (?next=... supported)
    GET/POST /logout            log out
    GET/POST /forgot-password   request a 6-digit code by email
    GET/POST /reset-password    enter the code + choose a new password
"""

import functools
import re
from datetime import datetime, timedelta

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
import mailer
from routes.admin import ADMIN_EMAIL, ADMIN_PASSWORD

auth_bp = Blueprint("auth", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LEN = 8

# --- Role constants ---
ROLE_USER = "user"
ROLE_ANALYST = "analyst"
ROLE_ADMIN = "admin"
ROLES = (ROLE_USER, ROLE_ANALYST, ROLE_ADMIN)

# Role hierarchy for permission checks
ROLE_HIERARCHY = {ROLE_USER: 0, ROLE_ANALYST: 1, ROLE_ADMIN: 2}


# ---------------------------------------------------------------------------
# Decorators
# ---------------------------------------------------------------------------

def login_required(view):
    """Redirect anonymous users to the login page (remembers destination)."""

    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.get("user") is None:
            flash("Please log in to access that page.", "warning")
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def role_required(*roles):
    """Restrict access to users with one of the given roles."""
    def decorator(view):
        @functools.wraps(view)
        def wrapped(*args, **kwargs):
            if g.get("user") is None:
                flash("Please log in to access that page.", "warning")
                return redirect(url_for("auth.login", next=request.path))
            user_role = g.user.get("role", ROLE_USER)
            if user_role not in roles:
                flash("You do not have permission to access that page.", "error")
                return redirect(url_for("pages.dashboard"))
            return view(*args, **kwargs)
        return wrapped
    return decorator


def admin_required(view):
    """Shortcut: restrict to admin users only."""
    return role_required(ROLE_ADMIN)(view)


def analyst_required(view):
    """Shortcut: restrict to analyst and admin users."""
    return role_required(ROLE_ANALYST, ROLE_ADMIN)(view)


def _user_is_premium(user):
    """Return True if the user dict has an active Premium plan."""
    if not user:
        return False
    return database.is_premium_plan(user.get("subscription"))


# ---------------------------------------------------------------------------
# Premium page groups — the single source of truth shared by the route guard,
# the navigation partial and the client-side eviction helper.
#
# `Specialized` = Solar ROI / Agri-Climate / Historical Data
# `Insights`    = AI Assistant / AI Predictions / Active Alerts / Disaster Safety
#
# `/maps` (Live WeatherRadar) is intentionally NOT listed: it is a public page.
# ---------------------------------------------------------------------------

PREMIUM_PAGE_GROUPS = {
    "Specialized": ("/solar", "/agriculture", "/historical"),
    "Insights": ("/assistant", "/predictions", "/alerts", "/disaster"),
}

PREMIUM_PAGE_PREFIXES = tuple(
    prefix for prefixes in PREMIUM_PAGE_GROUPS.values() for prefix in prefixes
)


def is_premium_path(path):
    """True when `path` belongs to a Premium-only page group."""
    return premium_group_for_path(path) is not None


def premium_group_for_path(path):
    """Return the Premium group ('Specialized' / 'Insights') that owns `path`.

    Matches on path segments so '/solar' and '/solar/' both resolve, while
    an unrelated '/solarium' never would.
    """
    clean = (path or "").split("?")[0].split("#")[0].rstrip("/")
    if not clean:
        return None
    for group, prefixes in PREMIUM_PAGE_GROUPS.items():
        for prefix in prefixes:
            if clean == prefix or clean.startswith(prefix + "/"):
                return group
    return None


def premium_required(view):
    """Restrict access to Premium subscribers.

    - Anonymous users are sent to /login (return URL remembered).
    - Users who just cancelled are INSTANTLY evicted to /dashboard: their
      Premium pages are relocked the moment the session is downgraded.
    - Free-tier users who never subscribed are sent to /pricing to upgrade.
    """
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.get("user") is None:
            flash("Please log in to access that page.", "warning")
            return redirect(url_for("auth.login", next=request.path))
        if not _user_is_premium(g.user):
            group = premium_group_for_path(request.path)
            if session.get("membership_cancelled"):
                # Revoked mid-session: relock and evict, never offer an upsell.
                flash(
                    "Your membership has been canceled. %s is now locked — "
                    "you were returned to your dashboard." % (group or "Premium"),
                    "warning",
                )
                return redirect(url_for("pages.dashboard"))
            flash("Premium access required. Upgrade to unlock this feature.", "warning")
            return redirect(url_for("pages.pricing", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def min_role_required(min_role):
    """Restrict to users with at least the given role level in hierarchy."""
    def decorator(view):
        @functools.wraps(view)
        def wrapped(*args, **kwargs):
            if g.get("user") is None:
                flash("Please log in to access that page.", "warning")
                return redirect(url_for("auth.login", next=request.path))
            user_role = g.user.get("role", ROLE_USER)
            if ROLE_HIERARCHY.get(user_role, 0) < ROLE_HIERARCHY.get(min_role, 0):
                flash("You do not have permission to access that page.", "error")
                return redirect(url_for("pages.dashboard"))
            return view(*args, **kwargs)
        return wrapped
    return decorator


def _valid_email(email):
    return bool(EMAIL_RE.match((email or "").strip()))


def _safe_next():
    """Only allow same-site relative redirect targets."""
    target = request.args.get("next") or request.form.get("next") or ""
    if target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("pages.dashboard")


# ---------------------------------------------------------------------------
# Signup / Login / Logout
# ---------------------------------------------------------------------------

@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if g.get("user"):
        return redirect(url_for("pages.dashboard"))

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm_password") or ""

        errors = []
        if len(name) < 2:
            errors.append("Please enter your full name.")
        if not _valid_email(email):
            errors.append("Please enter a valid email address.")
        if len(password) < MIN_PASSWORD_LEN:
            errors.append(
                "Password must be at least %d characters." % MIN_PASSWORD_LEN
            )
        if password != confirm:
            errors.append("Passwords do not match.")
        if not errors and database.email_taken(email):
            errors.append("An account with this email already exists.")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template(
                "auth/signup.html",
                active="signup",
                form={"name": name, "email": email},
            ), 400

        database.create_user(name, email, password, role="user")
        user = database.authenticate(email, password)
        session.clear()
        session["user_id"] = user["id"]
        flash("Welcome to SkyCast, %s! Your account is ready." % name, "success")
        return redirect(_safe_next())

    return render_template("auth/signup.html", active="signup", form={})


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """ONE login page for everyone.

    Registered users land on their personal dashboard; users with the
    'admin' role land on /admin. The legacy ADMIN_EMAIL / ADMIN_PASSWORD
    console credentials still work for backward compatibility.
    """
    if g.get("user"):
        # Already logged in — send to the right place
        if g.user.get("role") == ROLE_ADMIN:
            return redirect(url_for("admin.dashboard"))
        return redirect(url_for("pages.dashboard"))
    if session.get("is_admin"):
        return redirect(url_for("admin.dashboard"))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        remember = request.form.get("remember") == "on"

        # 1) Regular user account (including role-based admins)?
        user = database.authenticate(email, password)
        if user is not None:
            session.clear()
            session["user_id"] = user["id"]
            if remember:
                session.permanent = True
            flash("Welcome back, %s!" % user["name"].split(" ")[0], "success")
            # Admins go to the admin console; everyone else to their dashboard
            if user.get("role") == ROLE_ADMIN:
                session["is_admin"] = True
                return redirect(url_for("admin.dashboard"))
            return redirect(_safe_next())

        # 2) Legacy admin console credentials? (backward compatibility)
        if email == ADMIN_EMAIL.lower() and password == ADMIN_PASSWORD:
            session.clear()
            session["is_admin"] = True
            # If the admin also has a regular account, grant both sessions.
            account = database.get_user_by_email(email)
            if account:
                session["user_id"] = account["id"]
            if remember:
                session.permanent = True
            flash("Admin session started. Welcome to the console.", "success")
            nxt = request.form.get("next", "")
            if nxt.startswith("/") and not nxt.startswith("//"):
                return redirect(nxt)
            return redirect(url_for("admin.dashboard"))

        flash("Invalid email or password. Please try again.", "error")
        return render_template(
            "auth/login.html",
            active="login",
            form={"email": email},
            next=request.form.get("next", ""),
        ), 401

    return render_template(
        "auth/login.html", active="login", form={}, next=request.args.get("next", "")
    )


@auth_bp.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    flash("You have been logged out. See you soon!", "success")
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Forgot password / Reset password (email verification code)
# ---------------------------------------------------------------------------

@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if g.get("user"):
        return redirect(url_for("pages.dashboard"))

    if request.method == "POST":
        # JSON clients (the AJAX forgot-password wizard) and classic form
        # posts share the same logic; only the response shape differs.
        wants_json = request.is_json
        payload = request.get_json(silent=True) if wants_json else None
        payload = payload if isinstance(payload, dict) else {}

        email = (payload.get("email") or request.form.get("email") or "").strip().lower()
        channel = (payload.get("channel") or request.form.get("channel") or "email").strip().lower()
        phone_input = (payload.get("phone") or request.form.get("phone") or "").strip()

        if not _valid_email(email):
            if wants_json:
                return (
                    jsonify({"success": False, "error": "Please enter a valid email address."}),
                    400,
                )
            flash("Please enter a valid email address.", "error")
            return render_template(
                "auth/forgot_password.html",
                active="login",
                form={"email": email, "phone": phone_input, "channel": channel},
            ), 400

        # Always show the same response so attackers can't probe which
        # emails are registered (no account enumeration).
        user = database.get_user_by_email(email)
        if user:
            code = database.generate_reset_code()
            database.store_reset_code(email, code)

            # WhatsApp ownership check: the number must match the one the
            # user registered in Settings, so codes can't be sprayed to
            # arbitrary WhatsApp numbers.
            number_matched = True
            if channel == "whatsapp":
                # Ownership check: the number must match the one the user
                # registered in Settings, so codes can't be sprayed to
                # arbitrary WhatsApp numbers.
                number_matched = database.phones_match(
                    user.get("phone") or "", phone_input
                )

            if channel == "whatsapp" and not number_matched:
                # Number not on file — never send to a foreign number and
                # never reveal whether the number matched.
                delivered = False
            elif channel == "whatsapp":
                delivered, _detail = mailer.send_reset_code_whatsapp(
                    database.normalize_phone(user["phone"]) or phone_input,
                    code,
                    database.RESET_CODE_TTL_MINUTES,
                )
            else:
                delivered, _detail = mailer.send_reset_code(
                    email, code, database.RESET_CODE_TTL_MINUTES
                )

            if not delivered:
                # SECURITY: the OTP is NEVER returned to the browser in any
                # form — no JSON field, no session, no template variable.
                # When delivery is unavailable (SMTP/WhatsApp unconfigured or
                # broken locally), mailer.py prints the code strictly to the
                # server terminal ([SERVER TERMINAL LOG]) so development can
                # continue without exposing the code through the UI or the
                # HTTP response.
                pass

            if delivered:
                via = "WhatsApp" if channel == "whatsapp" else "email"
                if wants_json:
                    return jsonify({
                        "success": True,
                        "message": "If that email is registered, a 6-digit "
                                   "verification code has been sent to your "
                                   "%s. It expires in %d minutes."
                                   % (via, database.RESET_CODE_TTL_MINUTES),
                    })
                flash(
                    "If that email is registered, a 6-digit verification code "
                    "has been sent to your %s. It expires in %d minutes."
                    % (via, database.RESET_CODE_TTL_MINUTES),
                    "success",
                )
            else:
                # Generic, enumeration-safe response for every non-delivered
                # path (unconfigured channel, provider failure, number
                # mismatch). Identical semantics for JSON and form clients.
                if wants_json:
                    return jsonify({
                        "success": True,
                        "message": "If that email is registered, a 6-digit "
                                   "verification code has been sent to your "
                                   "inbox.",
                    })
                flash(
                    "If that email is registered, a 6-digit verification code "
                    "has been sent to your inbox.",
                    "success",
                )
        else:
            # No account enumeration — identical semantics for JSON clients:
            # the same generic success message whether or not the email exists.
            if wants_json:
                return jsonify({
                    "success": True,
                    "message": "If that email is registered, a 6-digit "
                               "verification code has been sent to your inbox.",
                })
            flash(
                "If that email is registered, a 6-digit verification code has "
                "been sent to your inbox.",
                "success",
            )

        session["reset_email"] = email
        return redirect(url_for("auth.reset_password"))

    return render_template("auth/forgot_password.html", active="login", form={})


@auth_bp.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    if g.get("user"):
        return redirect(url_for("pages.dashboard"))

    wants_json = request.is_json
    payload = request.get_json(silent=True) if wants_json else None
    payload = payload if isinstance(payload, dict) else {}

    email = (
        payload.get("email")
        or request.form.get("email")
        or request.args.get("email")
        or session.get("reset_email")
        or ""
    ).strip().lower()

    # Reset codes are NEVER stored in the session or rendered into any
    # template — they live only in the database (hashed) and in the email
    # that was sent. During local development without SMTP, mailer.py
    # prints them to the server terminal ([DEV MAIL] log).
    if request.method == "POST":
        code = (payload.get("code") or request.form.get("code") or "").strip()
        password = payload.get("password") or request.form.get("password") or ""
        confirm = payload.get("confirm_password") or request.form.get("confirm_password") or ""

        errors = []
        if not _valid_email(email):
            errors.append("Please enter the email you requested the reset for.")
        if not re.fullmatch(r"\d{6}", code):
            errors.append("Please enter the 6-digit code we sent you.")
        if len(password) < MIN_PASSWORD_LEN:
            errors.append(
                "New password must be at least %d characters." % MIN_PASSWORD_LEN
            )
        # JSON clients may omit the confirmation field; form posts always send it.
        if confirm and password != confirm:
            errors.append("Passwords do not match.")
        if errors:
            if wants_json:
                return jsonify({"success": False, "error": errors[0]}), 400
            for e in errors:
                flash(e, "error")
            return render_template(
                "auth/reset_password.html",
                active="login",
                form={"email": email, "code": code},
            ), 400

        # Atomic verify + consume: the code can never be reused.
        if not database.consume_reset_code(email, code):
            if wants_json:
                return jsonify({
                    "success": False,
                    "error": "That code is invalid or has expired. Please request a new one.",
                }), 400
            flash(
                "That code is invalid or has expired. Please request a new one.",
                "error",
            )
            return render_template(
                "auth/reset_password.html",
                active="login",
                form={"email": email, "code": code},
            ), 400

        if not database.update_password(email, password):
            if wants_json:
                return jsonify(
                    {"success": False, "error": "No account found for that email."}
                ), 404
            flash("No account found for that email.", "error")
            return redirect(url_for("auth.forgot_password"))

        session.pop("reset_email", None)
        if wants_json:
            return jsonify({
                "success": True,
                "message": "Password updated successfully. You can now log in "
                           "with your new password.",
            })
        flash(
            "Password updated successfully. You can now log in with your new "
            "password.",
            "success",
        )
        return redirect(url_for("auth.login"))

    return render_template(
        "auth/reset_password.html",
        active="login",
        form={"email": email, "code": ""},
    )

