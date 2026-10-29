"""SkyCast AI - Notification dispatcher.

Supports Web Push browser alerts and email fallback.
"""
import json
import os
import smtplib
import ssl
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage

import mailer
import database

try:
    from pywebpush import WebPushException, webpush
except ImportError:  # Keep non-push development workflows usable until deps install.
    WebPushException = None
    webpush = None

_CHANNEL_LABELS = {
    "browser": "Browser Push",
    "email": "Email",
    "sms": "SMS",
}


def _log(user_id, alert_id, channel, status, detail=None):
    try:
        database.log_notification(user_id, alert_id, channel, status, detail)
    except Exception:
        pass


def _send_browser_push(user_id, title, body):
    private_key = os.getenv("VAPID_PRIVATE_KEY")
    if not webpush or not private_key:
        return False, "web-push-not-configured"

    payload = json.dumps({"title": title, "message": body, "url": "/alerts"})
    subscriptions = database.get_push_subscriptions(user_id)
    if not subscriptions:
        return False, "no-push-subscription"

    delivered = 0
    expired = 0
    for saved in subscriptions:
        try:
            webpush(
                subscription_info=json.loads(saved["subscription"]),
                data=payload,
                vapid_private_key=private_key,
                vapid_claims={"sub": os.getenv("VAPID_SUBJECT", "mailto:admin@skycast.ai")},
            )
            delivered += 1
        except WebPushException as exc:
            response = getattr(exc, "response", None)
            if response is not None and response.status_code in (404, 410):
                database.delete_push_subscription(saved["endpoint"])
                expired += 1
        except Exception:
            continue
    if delivered:
        return True, "delivered-to-%d-device%s" % (delivered, "s" if delivered != 1 else "")
    return False, "expired-%d-subscription%s" % (expired, "s" if expired != 1 else "")


def trigger_global_push_alert(title, message, target_url="/alerts"):
    """Deliver one Web Push notification to every registered device."""
    private_key = os.getenv("VAPID_PRIVATE_KEY")
    if not webpush or not private_key:
        return {"sent": 0, "failed": 0, "detail": "web-push-not-configured"}
    payload = json.dumps({"title": title, "message": message, "url": target_url})
    sent = failed = 0
    for saved in database.get_push_subscriptions():
        try:
            webpush(
                subscription_info=json.loads(saved["subscription"]),
                data=payload,
                vapid_private_key=private_key,
                vapid_claims={"sub": os.getenv("VAPID_SUBJECT", "mailto:admin@skycast.ai")},
            )
            sent += 1
            _log(saved["user_id"], None, "browser", "sent", title)
        except WebPushException as exc:
            response = getattr(exc, "response", None)
            if response is not None and response.status_code in (404, 410):
                database.delete_push_subscription(saved["endpoint"])
            failed += 1
        except Exception:
            failed += 1
    return {"sent": sent, "failed": failed}


def _send_email(to_email, subject, body):
    if not mailer.smtp_configured():
        return False, "smtp-not-configured"
    html = (
        "<div style='font-family:Segoe UI,Arial,sans-serif;padding:24px;background:#f1f5f9'>"
        "<div style='max-width:520px;margin:auto;background:#fff;border-radius:16px;overflow:hidden;border:1px solid #e2e8f0'>"
        "<div style='background:linear-gradient(135deg,#0ea5e9,#2563eb);padding:22px 28px;color:#fff'>"
        "<h1 style='margin:0;font-size:20px'>SkyCast <span style='font-weight:300'>AI</span></h1>"
        "<p style='margin:6px 0 0;opacity:.85;font-size:13px'>Weather Alert</p></div>"
        "<div style='padding:24px;color:#0f172a'><p style='margin:0 0 12px;font-size:15px'>{body}</p>"
        "<p style='margin:0;font-size:13px;color:#64748b'>SkyCast automated alert.</p></div>"
        "</div></div>"
    ).format(body=body)
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = mailer._from_header()
    msg["To"] = to_email
    msg.set_content(body)
    msg.add_alternative(html, subtype="html")

    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASS")

    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=20) as server:
                if user:
                    server.login(user, password or "")
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=20) as server:
                server.ehlo()
                try:
                    context = ssl.create_default_context()
                    server.starttls(context=context)
                    server.ehlo()
                except smtplib.SMTPNotSupportedError:
                    pass  # local relay without STARTTLS
                if user:
                    server.login(user, password or "")
                server.send_message(msg)
        return True, "email sent to %s" % to_email
    except Exception as exc:
        return False, "email delivery failed: %s" % exc


def _send_sms(to_number, body):
    _log(0, None, "sms", "dev-mode", to_number)
    return False, "twilio-not-configured"


def dispatch(user_id, alert, title, body):
    channels = [c.strip() for c in (alert["channels"] or "").split(",") if c.strip()]
    results = []
    user = database.get_user_by_id(user_id)
    email = user["email"] if user else None
    for ch in channels:
        try:
            if ch == "browser":
                ok, detail = _send_browser_push(user_id, title, body)
            elif ch == "email" and email:
                ok, detail = _send_email(email, title, body)
            elif ch == "sms":
                ok, detail = _send_sms("", body)
            else:
                ok, detail = False, "unknown-channel"
            _log(user_id, alert.get("id"), ch, "sent" if ok else "failed", detail)
            results.append({"channel": ch, "ok": ok, "detail": detail})
        except Exception as exc:
            _log(user_id, alert.get("id"), ch, "error", str(exc))
            results.append({"channel": ch, "ok": False, "detail": str(exc)})
    return results


def evaluate_alert(alert, weather):
    """Evaluate one alert against a weather snapshot.

    Returns ``(value, triggered, title, body)`` or ``None`` when the metric is
    not present in the weather payload.
    """
    metric = alert["metric"]
    threshold = float(alert["threshold"])
    op = alert["operator"]
    value = None
    if metric == "wind":
        value = float(weather.get("wind") or 0)
    elif metric == "uv":
        value = float(weather.get("uv") or 0)
    elif metric == "temp":
        value = float(weather.get("temp") or 0)
    elif metric == "humidity":
        value = float(weather.get("humidity") or 0)
    elif metric == "pressure":
        value = float(weather.get("pressure") or 0)
    if value is None:
        return None

    triggered = False
    if op == ">" and value > threshold:
        triggered = True
    elif op == "<" and value < threshold:
        triggered = True
    elif op == ">=" and value >= threshold:
        triggered = True
    elif op == "<=" and value <= threshold:
        triggered = True

    title = "SkyCast Alert: %s %s %s in %s" % (
        metric, op, threshold, weather.get("city", "?"),
    )
    body = "Current %s is %s (threshold %s %s)." % (metric, value, op, threshold)
    return value, triggered, title, body


def evaluate_and_notify(user_id, weather):
    """Fire every alert that matches ``weather`` (a shared snapshot)."""
    alerts = database.get_alerts_by_user(user_id)
    if not alerts:
        return []
    fired = []
    for a in alerts:
        res = evaluate_alert(a, weather)
        if not res:
            continue
        value, triggered, title, body = res
        if triggered:
            results = dispatch(user_id, dict(a), title, body)
            fired.append({"alert": dict(a), "value": value, "results": results})
    return fired


def evaluate_user_cities(user_id):
    """Fetch live weather per configured city and fire matching alerts.

    Prefer this over ``evaluate_and_notify`` when the user's alerts span
    multiple cities: each alert is evaluated against its own city's readings.
    """
    alerts = database.get_alerts_by_user(user_id)
    if not alerts:
        return []
    from app import CITIES, _live_forecast, _live_payload, _simulated_payload

    city_keys = []
    for a in alerts:
        if a["city"] not in city_keys:
            city_keys.append(a["city"])

    fired = []
    for city_key in city_keys:
        c = CITIES.get(city_key)
        if not c:
            continue
        try:
            weather = _live_payload(city_key, _live_forecast(c["lat"], c["lon"]))
        except Exception:
            weather = _simulated_payload(city_key)
        fired.extend(evaluate_and_notify(user_id, weather))
    return fired
