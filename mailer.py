"""SkyCast AI - Email delivery (stdlib smtplib, no third-party deps).

Reads SMTP settings from environment variables or a ``.env`` file in the
project root (see ``.env.example``):

    SMTP_HOST=smtp.gmail.com
    SMTP_PORT=587
    SMTP_USER=you@gmail.com
    SMTP_PASS=your-16-char-app-password
    MAIL_FROM="SkyCast <you@gmail.com>"

If SMTP is NOT configured, the app runs in DEV MODE: the email is printed to
the server console instead, so the forgot-password flow still works locally.
"""

import os
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")

_BRAND = "SkyCast"


def _load_dotenv():
    """Minimal .env loader (KEY=VALUE lines); real env vars win."""
    if not os.path.exists(ENV_PATH):
        return
    try:
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key, value = key.strip(), value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError:
        pass


_load_dotenv()


def smtp_configured():
    """True when SMTP_HOST is present (auth optional for local relays)."""
    return bool(os.environ.get("SMTP_HOST"))


def _from_header():
    raw = os.environ.get("MAIL_FROM") or os.environ.get("SMTP_USER") or _BRAND
    if "<" in raw and ">" in raw:
        return formataddr(_split_addr(raw))
    return formataddr((_BRAND, raw)) if "@" in raw else raw


def _split_addr(raw):
    name, _, addr = raw.partition("<")
    return name.strip().strip('"'), addr.replace(">", "").strip()


def _html_reset_email(code, minutes):
    return f"""\
<div style="font-family:Segoe UI,Arial,sans-serif;background:#f1f5f9;padding:32px">
  <div style="max-width:480px;margin:auto;background:#ffffff;border-radius:16px;overflow:hidden;border:1px solid #e2e8f0">
    <div style="background:linear-gradient(135deg,#0ea5e9,#2563eb);padding:28px 32px;color:#fff">
      <h1 style="margin:0;font-size:22px">SkyCast <span style="font-weight:300">AI</span></h1>
      <p style="margin:6px 0 0;opacity:.85;font-size:13px">Password reset verification</p>
    </div>
    <div style="padding:32px;color:#0f172a">
    <p style="margin:0 0 14px;font-size:15px">Use the verification code below to reset your SkyCast password:</p>
      <div style="text-align:center;margin:22px 0">
        <span style="display:inline-block;font-size:34px;letter-spacing:10px;font-weight:700;background:#eff6ff;border:1px solid #bfdbfe;color:#1d4ed8;border-radius:12px;padding:14px 26px">{code}</span>
      </div>
      <p style="margin:0 0 8px;font-size:14px">This code expires in <strong>{minutes} minutes</strong> and can be used only once.</p>
      <p style="margin:0;font-size:13px;color:#64748b">If you didn't request a password reset, you can safely ignore this email — your password stays unchanged.</p>
    </div>
    <div style="padding:16px 32px;background:#f8fafc;border-top:1px solid #e2e8f0;font-size:12px;color:#94a3b8">
    &copy; SkyCast &mdash; made for the sky, powered by data.
    </div>
  </div>
</div>"""


def send_reset_code(to_email, code, ttl_minutes=15):
    """Email the 6-digit reset code.

    Returns a tuple ``(delivered, detail)``:
      * SMTP mode    -> (True, "email sent to <addr>")
      * DEV fallback -> (False, "dev-mode: code printed to server console")
      * SMTP failure -> (False, error message)
        """
    if not smtp_configured():
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print("=" * 62)
        print("  [SERVER TERMINAL LOG] SMTP not configured - no email was sent.")
        print(f"  [SERVER TERMINAL LOG] Reset OTP for {to_email}: {code}")
        print(f"  [SERVER TERMINAL LOG] Expires in {ttl_minutes} minutes  ({now})")
        print("=" * 62)
        return False, "dev-mode: code printed to server console"

    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASS")
    # Gmail displays App Passwords in 4-character groups ("abcd efgh ijkl
    # mnop"), but the SMTP LOGIN mechanism must receive them WITHOUT spaces.
    if password:
        password = "".join(password.split())

    try:
        msg = EmailMessage()
        msg["Subject"] = f"{_BRAND} password reset code: {code}"
        msg["From"] = _from_header()
        msg["To"] = to_email
        msg.set_content(
            f"Your {_BRAND} password reset code is {code}.\n"
            f"It expires in {ttl_minutes} minutes and can be used only once.\n"
            "If you did not request this, ignore this email."
        )
        msg.add_alternative(_html_reset_email(code, ttl_minutes), subtype="html")

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
        print(f"  [SERVER TERMINAL LOG] Reset code email successfully sent to {to_email}")
        return True, f"email sent to {to_email}"
    except Exception as exc:  # noqa: BLE001 - logged to terminal, never sent to clients
        print("=" * 62)
        print("  [SERVER TERMINAL LOG] FAILED TO SEND EMAIL:")
        print(f"  [SERVER TERMINAL LOG] Error Type: {type(exc).__name__}")
        print(f"  [SERVER TERMINAL LOG] Error Message: {exc}")
        print("=" * 62)
        return False, f"email delivery failed: {type(exc).__name__}"


def send_raw(to_email, subject, body):
    """Send a plain (HTML-wrapped) email to an arbitrary recipient.

    Uses the same SMTP/dev-mode pathway as send_reset_code. Returns the
    same ``(delivered, detail)`` tuple. Falls back to dev-mode console
    output when SMTP is not configured.
    """
    if not _is_valid_email(to_email):
        return False, f"invalid recipient: {to_email}"
    if not smtp_configured():
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print("=" * 62)
        print("  [SERVER TERMINAL LOG] SMTP not configured — support notification not sent.")
        print(f"  [SERVER TERMINAL LOG] To: {to_email}")
        print(f"  [SERVER TERMINAL LOG] Subject: {subject}")
        print(f"  [SERVER TERMINAL LOG] {now}")
        print("=" * 62)
        return False, "dev-mode: message printed to server console"

    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASS")
    # Gmail App Passwords: strip the display spaces before SMTP LOGIN.
    if password:
        password = "".join(password.split())

    html = (
        "<div style='font-family:Segoe UI,Arial,sans-serif;padding:24px;background:#f1f5f9'>"
        "<div style='max-width:540px;margin:auto;background:#fff;border-radius:16px;"
        "overflow:hidden;border:1px solid #e2e8f0'>"
        "<div style='background:linear-gradient(135deg,#0ea5e9,#2563eb);padding:22px 28px;color:#fff'>"
        "<h1 style='margin:0;font-size:20px'>SkyCast <span style='font-weight:300'>AI</span></h1>"
        "<p style='margin:6px 0 0;opacity:.85;font-size:13px'>Support Notification</p></div>"
        "<div style='padding:24px;color:#0f172a'>"
        "<p style='margin:0;font-size:15px'>"
        + str(body).replace("\n", "<br>")
        + "</p>"
        "<p style='margin:18px 0 0;font-size:13px;color:#64748b'>SkyCast support alert.</p>"
        "</div></div></div>"
    )

    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = _from_header()
        msg["To"] = to_email
        msg.set_content(body)
        msg.add_alternative(html, subtype="html")

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
                    pass
                if user:
                    server.login(user, password or "")
                server.send_message(msg)
        print(f"  [SERVER TERMINAL LOG] Email sent to {to_email}")
        return True, f"email sent to {to_email}"
    except Exception as exc:  # noqa: BLE001 - logged to terminal, never sent to clients
        print("=" * 62)
        print("  [SERVER TERMINAL LOG] FAILED TO SEND EMAIL:")
        print(f"  [SERVER TERMINAL LOG] Error Type: {type(exc).__name__}")
        print(f"  [SERVER TERMINAL LOG] Error Message: {exc}")
        print("=" * 62)
        return False, f"email delivery failed: {type(exc).__name__}"


def _is_valid_email(email):
    import re as _re

    return bool(_re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", (email or "").strip()))


# ---------------------------------------------------------------------------
# WhatsApp (Meta Cloud API) — optional second channel for reset codes
# ---------------------------------------------------------------------------

def whatsapp_configured():
    """True when WHATSAPP_TOKEN + WHATSAPP_PHONE_NUMBER_ID are both set."""
    return bool(
        os.environ.get("WHATSAPP_TOKEN")
        and os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
    )


def send_whatsapp(to_phone, body):
    """Send a WhatsApp text message via the Meta Cloud API (stdlib urllib).

    Returns ``(delivered, detail)`` mirroring the email helpers:
      * API mode     -> (True, "whatsapp sent to <num>")
      * DEV fallback -> (False, "dev-mode: message printed to server console")
      * API failure  -> (False, error message)
    """
    if not whatsapp_configured():
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print("=" * 62)
        print("  [SERVER TERMINAL LOG] WHATSAPP_TOKEN / WHATSAPP_PHONE_NUMBER_ID not set.")
        print(f"  [SERVER TERMINAL LOG] To: {to_phone}")
        print(f"  [SERVER TERMINAL LOG] Body: {body}")
        print(f"  [SERVER TERMINAL LOG] {now}")
        print("=" * 62)
        return False, "dev-mode: message printed to server console"

    import json as _json
    import urllib.request

    token = os.environ["WHATSAPP_TOKEN"]
    number_id = os.environ["WHATSAPP_PHONE_NUMBER_ID"]
    version = os.environ.get("WHATSAPP_API_VERSION", "v19.0")
    url = "https://graph.facebook.com/%s/%s/messages" % (version, number_id)
    payload = _json.dumps(
        {
            "messaging_product": "whatsapp",
            "to": to_phone,
            "type": "text",
            "text": {"body": body},
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": "Bearer %s" % token,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            if resp.status == 200:
                return True, "whatsapp sent to %s" % to_phone
            return False, "whatsapp API returned HTTP %s" % resp.status
    except Exception as exc:  # noqa: BLE001 - logged to terminal, never sent to clients
        print("=" * 62)
        print("  [SERVER TERMINAL LOG] FAILED TO SEND WHATSAPP:")
        print(f"  [SERVER TERMINAL LOG] Error Type: {type(exc).__name__}")
        print(f"  [SERVER TERMINAL LOG] Error Message: {exc}")
        print("=" * 62)
        return False, "whatsapp delivery failed: %s" % type(exc).__name__


def send_reset_code_whatsapp(to_phone, code, ttl_minutes=15):
    """WhatsApp the 6-digit reset code. Same tuple contract as send_reset_code."""
    body = (
        "SkyCast password reset\n\n"
        "Your verification code is: %s\n\n"
        "It expires in %d minutes and can be used only once. "
        "If you didn't request a reset, ignore this message." % (code, ttl_minutes)
    )
    return send_whatsapp(to_phone, body)
