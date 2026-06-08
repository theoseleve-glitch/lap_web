# tests/test_marketing_public_access.py
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def test_marketing_rate_tier_exists():
    from web.rate_limit import RATE_TIERS
    assert "marketing" in RATE_TIERS
    assert RATE_TIERS["marketing"]["max_requests"] == 60
    assert RATE_TIERS["marketing"]["window_seconds"] == 60


def test_marketing_path_is_public():
    """auth_middleware must let /api/v1/marketing-events through unauthenticated."""
    from flask import Flask
    from web.middleware.auth import auth_middleware

    app = Flask(__name__)
    app.config["AUTH_REQUIRED"] = True
    app.config["JWT_SECRET"] = "test-secret"

    with app.test_request_context("/api/v1/marketing-events", method="POST"):
        # No Authorization header — must NOT short-circuit with a 401.
        result = auth_middleware()
        assert result is None
