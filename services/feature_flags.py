from functools import wraps
from flask import jsonify


class FeatureFlagManager:
    """In-memory feature flag manager (swap to Redis-backed store in production)."""
    _flags = {
        "solar_predictions": True,
        "deep_analytics_lab": False,
        "v2_weather_maps": True,
        "forecast_accuracy": True
    }

    @classmethod
    def is_enabled(cls, flag_name: str) -> bool:
        return cls._flags.get(flag_name, False)

    @classmethod
    def set_flag(cls, flag_name: str, status: bool):
        cls._flags[flag_name] = status

    @classmethod
    def list_flags(cls):
        return dict(cls._flags)


def feature_flag_required(flag_name):
    """Decorator that blocks access when the feature flag is disabled (503)."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not FeatureFlagManager.is_enabled(flag_name):
                return jsonify({
                    "error": "Service Unavailable",
                    "message": f"The feature '{flag_name}' is currently disabled by system administrators."
                }), 503
            return f(*args, **kwargs)
        return decorated_function
    return decorator