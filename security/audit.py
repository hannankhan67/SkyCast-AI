import os
from flask import request, g
from datetime import datetime, timezone
from functools import wraps


def audit_admin_action(action_type):
    """Decorator to log administrative operations into an immutable audit collection."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            response = f(*args, **kwargs)

            try:
                from database import mongo_db
                admin_id = g.user.get("id") if g.user else "system_admin"
                audit_entry = {
                    "action_type": action_type,
                    "admin_id": admin_id,
                    "ip_address": request.remote_addr,
                    "user_agent": request.headers.get("User-Agent"),
                    "endpoint": request.path,
                    "method": request.method,
                    "payload_summary": request.get_json(silent=True),
                    "timestamp": datetime.now(timezone.utc)
                }
                mongo_db.immutable_audit_logs.insert_one(audit_entry)
            except Exception as e:
                print(f"CRITICAL: Failed to write audit log: {e}")

            return response
        return decorated_function
    return decorator