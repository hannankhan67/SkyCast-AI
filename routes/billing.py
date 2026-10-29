"""
routes/billing.py — Stripe Checkout for SkyCast AI premium subscriptions.

Endpoints
---------
POST /api/billing/checkout   Create a Stripe Checkout Session -> ``{"url": ...}``
GET  /billing/success        Stripe redirect target; verifies payment, grants premium
GET  /billing/cancel         Stripe redirect target when the user backs out
POST /api/billing/portal     Stripe Billing Portal (manage/cancel subscription)
POST /api/billing/webhook    Signature-verified webhook (authoritative grant)

Design notes
------------
* The Stripe SDK is imported lazily: the app must boot — and every other route
  must keep working — even when ``stripe`` is not installed or no key is set.
* When ``STRIPE_SECRET_KEY`` is absent, ``/api/billing/checkout`` answers
  ``503 {"error": ..., "demo_available": true}`` so ``static/js/billing.js`` can
  fall back to the pre-existing demo upgrade endpoint.
* Credentials come from the environment only (``.env`` in development) — never
  hardcoded. See ``.env.example`` for the required keys.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from flask import (
    Blueprint,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    request,
    session,
    url_for,
)

import database

billing_bp = Blueprint("billing", __name__)

# --- Plan configuration -----------------------------------------------------
# Amounts are in the currency's minor unit (cents for USD).
DEFAULT_PRICE_CENTS = 1500
DEFAULT_CURRENCY = "usd"
DEFAULT_PLAN_NAME = "SkyCast Premium"
DEFAULT_PLAN_DESC = (
    "Unlock specialized climate reports, insights telemetry and "
    "unlimited saved cities."
)


def _env(name: str, default: str = "") -> str:
    """Read an environment variable, trimmed. Never raises."""
    try:
        return (os.getenv(name) or default).strip()
    except Exception:
        return default


def secret_key() -> str:
    """Stripe secret key (``sk_test_…`` or ``sk_live_…``)."""
    return _env("STRIPE_SECRET_KEY")


def publishable_key() -> str:
    """Stripe publishable key (``pk_test_…`` / ``pk_live_…``)."""
    return _env("STRIPE_PUBLISHABLE_KEY")


def webhook_secret() -> str:
    """Stripe webhook signing secret (``whsec_…``), optional."""
    return _env("STRIPE_WEBHOOK_SECRET")


def price_cents() -> int:
    """Checkout amount in cents, overridable via ``STRIPE_PRICE_CENTS``."""
    raw = _env("STRIPE_PRICE_CENTS")
    if raw:
        try:
            value = int(float(raw))
            if value > 0:
                return value
        except (TypeError, ValueError):
            current_app.logger.warning(
                "Ignoring invalid STRIPE_PRICE_CENTS=%r; using %s",
                raw,
                DEFAULT_PRICE_CENTS,
            )
    return DEFAULT_PRICE_CENTS


def currency() -> str:
    """Checkout currency code (ISO-4217, lower-case)."""
    return (_env("STRIPE_CURRENCY", DEFAULT_CURRENCY) or DEFAULT_CURRENCY).lower()


def stripe_enabled() -> bool:
    """True when a Stripe secret key is configured (test or live mode)."""
    return bool(secret_key())


def _stripe():
    """Return a configured ``stripe`` module, or ``None`` when unavailable.

    Imported lazily so a missing dependency or key degrades to the demo flow
    instead of crashing app startup.
    """
    if not secret_key():
        return None
    try:
        import stripe
    except Exception as exc:  # pragma: no cover - depends on host env
        current_app.logger.warning("stripe SDK unavailable (%s); billing disabled", exc)
        return None
    stripe.api_key = secret_key()
    return stripe


def current_user():
    """Session user dict from ``g`` (set by the app's before_request hook)."""
    user = g.get("user") if hasattr(g, "get") else getattr(g, "user", None)
    return user if isinstance(user, dict) else None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _field(obj, name, default=None):
    """Read a field from a Stripe object or plain dict without raising."""
    try:
        return obj[name]
    except Exception:
        return getattr(obj, name, default)


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_next(candidate, fallback="/maps"):
    """Open-redirect guard: allow only same-origin relative targets."""
    value = (candidate or "").strip()
    if not value.startswith("/") or value.startswith("//"):
        return fallback
    return value


def _json_body():
    """Best-effort JSON body parse (never raises)."""
    try:
        return request.get_json(silent=True) or {}
    except Exception:
        return {}


def _absolute(endpoint, **values):
    """Absolute URL for an endpoint, falling back to the request host."""
    try:
        return url_for(endpoint, _external=True, **values)
    except Exception:
        return request.host_url.rstrip("/") + "/"


def _grant_premium(user_id, checkout, plan="premium"):
    """Persist premium access + the payment ledger row for a paid session."""
    if not user_id:
        return False

    granted = False
    try:
        granted = bool(database.set_user_subscription(user_id, plan))
    except Exception as exc:
        current_app.logger.warning("set_user_subscription failed: %s", exc)

    details = _field(checkout, "customer_details") or {}
    try:
        database.record_payment(
            user_id=user_id,
            stripe_session_id=_field(checkout, "id"),
            amount_cents=_as_int(_field(checkout, "amount_total")),
            currency=_field(checkout, "currency") or currency(),
            status=_field(checkout, "payment_status") or "paid",
            plan=plan,
            email=_field(details, "email") or _field(checkout, "customer_email"),
            payment_intent=_field(checkout, "payment_intent"),
            customer_id=_field(checkout, "customer"),
        )
    except Exception as exc:
        current_app.logger.warning("record_payment failed: %s", exc)

    customer_id = _field(checkout, "customer")
    if customer_id:
        try:
            database.set_stripe_customer(user_id, customer_id)
        except Exception:
            pass

    return granted


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@billing_bp.route("/api/billing/config", methods=["GET"])
def billing_config():
    """Report whether Stripe is live (the publishable key is safe to expose)."""
    return jsonify({
        "configured": stripe_enabled(),
        "publishable_key": publishable_key(),
        "currency": currency(),
        "amount_cents": price_cents(),
    }), 200


@billing_bp.route("/api/billing/checkout", methods=["POST"])
def create_checkout_session():
    """Create a Stripe Checkout Session and return its hosted-page URL."""
    user = current_user()
    if not user:
        return jsonify({"error": "Please sign in to upgrade.", "login_required": True}), 401

    sdk = _stripe()
    if sdk is None:
        # No key / no SDK -> the client falls back to the offline demo upgrade.
        return jsonify({
            "error": "Stripe is not configured on this server.",
            "demo_available": True,
        }), 503

    next_url = _safe_next(_json_body().get("next"))
    try:
        checkout = sdk.checkout.Session.create(
            mode="payment",
            payment_method_types=["card"],
            client_reference_id=str(user.get("id")),
            customer_email=user.get("email") or None,
            line_items=[{
                "quantity": 1,
                "price_data": {
                    "currency": currency(),
                    "unit_amount": price_cents(),
                    "product_data": {
                        "name": DEFAULT_PLAN_NAME,
                        "description": DEFAULT_PLAN_DESC,
                    },
                },
            }],
            metadata={
                "user_id": str(user.get("id")),
                "plan": "premium",
                "next": next_url,
            },
            success_url=(
                _absolute("billing.success") + "?session_id={CHECKOUT_SESSION_ID}"
            ),
            cancel_url=_absolute("billing.cancel"),
        )
    except Exception as exc:
        current_app.logger.warning("Stripe checkout failed: %s", exc)
        return jsonify({"error": "Could not start checkout. Please try again."}), 502

    return jsonify({"id": _field(checkout, "id"), "url": _field(checkout, "url")}), 200


@billing_bp.route("/billing/success", methods=["GET"])
def success():
    """Stripe redirect target: verify the payment, then grant Premium."""
    session_id = (request.args.get("session_id") or "").strip()
    sdk = _stripe()
    if sdk is None or not session_id:
        flash("Payment could not be verified — billing is not configured.", "error")
        return redirect(_absolute("pages.pricing"))

    try:
        checkout = sdk.checkout.Session.retrieve(session_id)
    except Exception as exc:
        current_app.logger.warning("Stripe session retrieve failed: %s", exc)
        flash("We could not verify that payment. Please contact support.", "error")
        return redirect(_absolute("pages.pricing"))

    meta = _field(checkout, "metadata") or {}
    user = current_user()
    user_id = (user or {}).get("id") or _as_int(
        _field(checkout, "client_reference_id") or _field(meta, "user_id")
    )

    paid = _field(checkout, "payment_status") == "paid" or (
        _field(checkout, "status") == "complete"
    )

    if paid and user_id:
        _grant_premium(user_id, checkout, _field(meta, "plan") or "premium")
        session["subscription"] = "premium"
        session["membership_cancelled"] = False
        flash("Payment received — Premium is now active.", "success")
    else:
        flash("That checkout is not paid yet. If you were charged, contact support.", "error")

    return redirect(_safe_next(_field(meta, "next")))


@billing_bp.route("/billing/cancel", methods=["GET"])
def cancel():
    """Stripe redirect target when the user backs out of Checkout."""
    flash("Checkout cancelled — you are still on the Free plan.", "error")
    return redirect(_absolute("pages.pricing"))


@billing_bp.route("/api/billing/portal", methods=["POST"])
def customer_portal():
    """Open Stripe's Billing Portal so the user can manage/cancel."""
    user = current_user()
    if not user:
        return jsonify({"error": "Please sign in.", "login_required": True}), 401

    sdk = _stripe()
    if sdk is None:
        return jsonify({
            "error": "Stripe is not configured on this server.",
            "demo_available": True,
        }), 503

    try:
        customer_id = database.get_stripe_customer_id(user.get("id"))
    except Exception:
        customer_id = None
    if not customer_id:
        return jsonify({"error": "No billing profile on file yet."}), 400

    try:
        portal = sdk.billing_portal.Session.create(
            customer=customer_id,
            return_url=_absolute("pages.pricing"),
        )
    except Exception as exc:
        current_app.logger.warning("Stripe portal failed: %s", exc)
        return jsonify({"error": "Could not open the billing portal."}), 502

    return jsonify({"url": _field(portal, "url")}), 200


@billing_bp.route("/api/billing/webhook", methods=["POST"])
def webhook():
    """Signature-verified Stripe webhook — the authoritative premium grant.

    Works without ``STRIPE_WEBHOOK_SECRET`` (unsigned JSON) so local
    development and the test suite can drive it; production should always
    set the signing secret.
    """
    sdk = _stripe()
    secret = webhook_secret()

    if sdk is not None and secret:
        try:
            event = sdk.Webhook.construct_event(
                request.get_data(),
                request.headers.get("Stripe-Signature", ""),
                secret,
            )
        except Exception as exc:
            current_app.logger.warning("Stripe webhook signature rejected: %s", exc)
            return jsonify({"error": "Invalid signature"}), 400
    else:
        event = _json_body()
        if not event:
            return jsonify({"error": "Invalid payload"}), 400

    etype = _field(event, "type") or ""
    data = _field(event, "data") or {}
    obj = _field(data, "object") or {}
    handled = etype in (
        "checkout.session.completed",
        "checkout.session.async_payment_succeeded",
        "customer.subscription.deleted",
        "invoice.payment_failed",
    )

    if etype in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        meta = _field(obj, "metadata") or {}
        user_id = _as_int(
            _field(obj, "client_reference_id") or _field(meta, "user_id")
        )
        settled = _field(obj, "payment_status") in ("paid", "no_payment_required") or (
            _field(obj, "status") == "complete"
        )
        if settled:
            _grant_premium(user_id, obj, _field(meta, "plan") or "premium")
    elif etype in ("customer.subscription.deleted", "invoice.payment_failed"):
        try:
            user_id = database.get_user_id_by_stripe_customer(_field(obj, "customer"))
        except Exception:
            user_id = None
        if user_id:
            try:
                database.set_user_subscription(user_id, "free")
            except Exception as exc:
                current_app.logger.warning("Premium revoke failed: %s", exc)

    return jsonify({"received": True, "type": etype, "handled": handled}), 200
