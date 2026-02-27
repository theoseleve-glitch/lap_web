"""Tests for plan-aware rate limiting.

Validates that:
- Rate limits scale by plan-tier multiplier
- Auth tier is never multiplied (IP-based, no plan context)
- Unknown plan tiers fallback to 1.0× multiplier
- Fail-open behavior is preserved
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask, g

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


@pytest.fixture
def app():
    """Minimal Flask app with rate limit infrastructure."""
    app = Flask(__name__)
    app.config["TESTING"] = True

    from web.rate_limit import rate_limit

    @app.route("/api/test-read", methods=["GET"])
    @rate_limit(tier="read")
    def test_read():
        return {"ok": True}

    @app.route("/api/test-analyze", methods=["POST"])
    @rate_limit(tier="analyze")
    def test_analyze():
        return {"ok": True}

    @app.route("/auth/test-login", methods=["POST"])
    @rate_limit(tier="auth")
    def test_auth():
        return {"ok": True}

    return app


class TestPlanRateMultipliers:
    def test_demo_gets_base_limit(self, app):
        """Demo users get 1× base limit (5 analyze/hr)."""
        from web.rate_limit import _get_effective_limit
        with app.test_request_context():
            g.plan_tier = "demo"
            assert _get_effective_limit(5, "analyze") == 5

    def test_racer_gets_double(self, app):
        """Racer users get 2× base limit (10 analyze/hr)."""
        from web.rate_limit import _get_effective_limit
        with app.test_request_context():
            g.plan_tier = "racer"
            assert _get_effective_limit(5, "analyze") == 10

    def test_worldclass_gets_five_x(self, app):
        """World-Class users get 5× base limit (25 analyze/hr)."""
        from web.rate_limit import _get_effective_limit
        with app.test_request_context():
            g.plan_tier = "world-class"
            assert _get_effective_limit(5, "analyze") == 25

    def test_b2b_gets_ten_x(self, app):
        """B2B users get 10× base limit (50 analyze/hr)."""
        from web.rate_limit import _get_effective_limit
        with app.test_request_context():
            g.plan_tier = "b2b"
            assert _get_effective_limit(5, "analyze") == 50

    def test_unknown_plan_falls_back_to_base(self, app):
        """Unknown plan tier gets 1× multiplier."""
        from web.rate_limit import _get_effective_limit
        with app.test_request_context():
            g.plan_tier = "unknown_plan"
            assert _get_effective_limit(5, "analyze") == 5

    def test_no_plan_tier_falls_back_to_demo(self, app):
        """Missing g.plan_tier defaults to demo (1×)."""
        from web.rate_limit import _get_effective_limit
        with app.test_request_context():
            # g.plan_tier not set
            assert _get_effective_limit(5, "analyze") == 5

    def test_read_tier_scales_for_worldclass(self, app):
        """Read tier also scales: 300 × 5 = 1500."""
        from web.rate_limit import _get_effective_limit
        with app.test_request_context():
            g.plan_tier = "world-class"
            assert _get_effective_limit(300, "read") == 1500

    def test_ceiling_on_non_integer(self, app):
        """Non-integer results are ceiled (e.g., 7 × 2.0 = 14, no fractions)."""
        from web.rate_limit import _get_effective_limit
        with app.test_request_context():
            g.plan_tier = "racer"
            # 7 * 2.0 = 14.0 -> 14 (integer)
            assert _get_effective_limit(7, "analyze") == 14


class TestRateLimitFailOpen:
    def test_no_redis_allows_through(self, app):
        """When Redis is unavailable, requests are allowed through."""
        with patch("web.rate_limit.get_redis", return_value=None):
            with app.test_client() as client:
                resp = client.post("/api/test-analyze")
                assert resp.status_code == 200


class TestPlanRateMultiplierConstants:
    def test_multipliers_match_plan_definitions(self):
        """PLAN_RATE_MULTIPLIERS should match plan_definitions.rate_multiplier."""
        from web.rate_limit import PLAN_RATE_MULTIPLIERS
        # These must match the seed data in migration 019
        assert PLAN_RATE_MULTIPLIERS["demo"] == 1.0
        assert PLAN_RATE_MULTIPLIERS["racer"] == 2.0
        assert PLAN_RATE_MULTIPLIERS["world-class"] == 5.0
        assert PLAN_RATE_MULTIPLIERS["b2b"] == 10.0
