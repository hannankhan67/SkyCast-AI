"""SkyCast AI — Feedback & Support blueprint.

Lets authenticated users open support tickets, track them, and reply in a
threaded conversation. Each new ticket emails the site admin (via mailer.py)
and every reply notifies the other party.

Routes:
    GET  /support                 Ticket list + new-ticket form
    POST /api/support/tickets     Create a ticket (JSON)
    GET  /support/<id>            Threaded ticket detail + reply form
    POST /api/support/<id>/reply  Post a reply (JSON)
"""
from flask import Blueprint, g, jsonify, render_template, request

import database
import mailer
from routes.auth import login_required

support_bp = Blueprint("support", __name__)

CATEGORIES = ["general", "bug", "feature", "billing", "other"]
PRIORITIES = ["low", "normal", "high", "urgent"]


def _notify_admin_new_ticket(ticket, user):
    """Email the admin about a new ticket (dev-mode fallback if no SMTP).

    Best-effort by design: the whole body is guarded and every field is read
    defensively, so a missing key or a mail failure can never turn a
    successful ticket creation into a 500.
    """
    try:
        ticket = dict(ticket or {})
        user = dict(user or {})
        ticket_id = ticket.get("id")
        category = ticket.get("category") or "general"
        priority = ticket.get("priority") or "normal"
        title = ticket.get("subject") or "(no subject)"
        subject = f"[SkyCast Support] #{ticket_id} {category.upper()} — {title}"
        body = (
            f"New support ticket #{ticket_id}\n\n"
            f"From: {user.get('name') or 'unknown user'} <{user.get('email') or 'unknown'}>\n"
            f"Category: {category}   Priority: {priority}\n\n"
            f"View in admin console for the full message."
        )
        mailer.send_raw(_admin_email(), subject, body)
    except Exception:
        # Email is best-effort; never block ticket creation on mail failure.
        pass


def _admin_email():
    return "admin@skycast.ai"


@support_bp.route("/support")
@login_required
def support_page():
    """List the current user's tickets and present the new-ticket form."""
    tickets = database.get_support_tickets_for_user(g.user["id"])
    return render_template(
        "support.html",
        active="support",
        tickets=[dict(t) for t in tickets],
        categories=CATEGORIES,
        priorities=PRIORITIES,
    )


@support_bp.route("/api/support/tickets", methods=["POST"])
@login_required
def api_create_ticket():
    data = request.get_json(silent=True) or {}
    subject = (data.get("subject") or "").strip()
    body = (data.get("body") or "").strip()
    category = (data.get("category") or "general").strip().lower()
    priority = (data.get("priority") or "normal").strip().lower()

    if not subject or not body:
        return jsonify({"error": "Subject and message are required."}), 400
    if category not in CATEGORIES:
        category = "general"
    if priority not in PRIORITIES:
        priority = "normal"

    ticket_id = database.create_support_ticket(
        g.user["id"], subject, category, priority
    )
    # Persist the initial message as the first reply so the thread is complete.
    database.add_support_reply(ticket_id, g.user["id"], body, is_staff=False)

    # Re-read the stored row and notify from it: the notification helper needs
    # the persisted fields (including priority), which a hand-built dict missed.
    ticket = database.get_support_ticket(ticket_id) or {
        "id": ticket_id,
        "subject": subject,
        "category": category,
        "priority": priority,
    }
    _notify_admin_new_ticket(ticket, g.user)
    return jsonify({"id": ticket_id, "ok": True, "ticket": ticket}), 201


@support_bp.route("/support/<int:ticket_id>")
@login_required
def support_ticket_page(ticket_id):
    """Threaded view of a single ticket with a reply box."""
    ticket = database.get_support_ticket(ticket_id, user_id=g.user["id"])
    if ticket is None:
        return render_template("support.html", active="support", error="Ticket not found."), 404
    replies = database.get_support_replies(ticket_id)
    return render_template(
        "support_ticket.html",
        active="support",
        ticket=ticket,
        replies=[dict(r) for r in replies],
    )


@support_bp.route("/api/support/<int:ticket_id>/reply", methods=["POST"])
@login_required
def api_reply(ticket_id):
    ticket = database.get_support_ticket(ticket_id, user_id=g.user["id"])
    if ticket is None:
        return jsonify({"error": "Ticket not found."}), 404
    if ticket["status"] == "closed":
        return jsonify({"error": "Ticket is closed."}), 409

    data = request.get_json(silent=True) or {}
    body = (data.get("body") or "").strip()
    if not body:
        return jsonify({"error": "Reply cannot be empty."}), 400

    reply_id = database.add_support_reply(ticket_id, g.user["id"], body, is_staff=False)
    return jsonify({"id": reply_id, "ok": True}), 201