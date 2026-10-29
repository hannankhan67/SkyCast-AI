from functools import wraps
from flask import g, jsonify

class Permission:
    NONE = 0
    READ = 1 << 0          # 1
    WRITE = 1 << 1         # 2
    ANALYST_METRICS = 1 << 2  # 4
    ANALYST_EXPORT = 1 << 3   # 8
    ADMIN_FLAGS = 1 << 4      # 16
    ADMIN_BROADCAST = 1 << 5  # 32
    ADMIN_AUDIT = 1 << 6      # 64

    # Predefined Role Masks
    ROLE_USER = (READ | WRITE)                              # 3
    ROLE_ANALYST = (READ | WRITE | ANALYST_METRICS | ANALYST_EXPORT)  # 15
    ROLE_ADMIN = (1 << 7) - 1                               # 127 (all)

    @classmethod
    def from_role(cls, role_str: str) -> int:
        """Map the existing role string ('user'|'analyst'|'admin') to a bitmask."""
        role_str = (role_str or "user").lower()
        if role_str == "admin":
            return cls.ROLE_ADMIN
        if role_str == "analyst":
            return cls.ROLE_ANALYST
        return cls.ROLE_USER

def require_permission(permission_bit):
    """Gate a view by checking the caller's permission bitmask against required bit.

    Works with g.user either being None (anonymous → 403) or a dict whose
    'role' key is mapped to a bitmask via Permission.from_role().
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user = getattr(g, "user", None)
            if user is None:
                return jsonify({
                    "error": "Unauthorized",
                    "message": "Authentication required"
                }), 401

            user_role = user.get("role", "user") if isinstance(user, dict) else "user"
            user_mask = Permission.from_role(user_role)

            if not (user_mask & permission_bit):
                return jsonify({
                    "error": "Forbidden",
                    "required_bit": permission_bit,
                    "message": "Insufficient bitmask privileges"
                }), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator