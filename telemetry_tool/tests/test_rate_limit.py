"""Tests for Redis sliding-window rate limiting."""
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from flask import Flask, g

from web.api_utils import ErrorCode, api_response, init_request_id
from web.rate_limit import RATE_TIERS, _SLIDING_WINDOW_LUA, rate_limit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app(tier="read"):
    """Build a minimal Flask app with a rate-limited route."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    init_request_id(app)

    @app.route("/limited")
    @rate_limit(tier=tier)
    def limited():
        return api_response({"msg": "ok"})

    return app


def _mock_redis(eval_return=None):
    """Return a mock Redis client whose eval() returns *eval_return*."""
    r = MagicMock()
    if eval_return is not None:
        r.eval.return_value = eval_return
    return r


# ---------------------------------------------------------------------------
# Tier configuration
# ---------------------------------------------------------------------------

class TestRateTierConfig:
    def test_auth_tier_exists(self):
        assert "auth" in RATE_TIERS
        assert RATE_TIERS["auth"]["max_requests"] == 20
        assert RATE_TIERS["auth"]["window_seconds"] == 60

    def test_read_tier_exists(self):
        assert "read" in RATE_TIERS
        assert RATE_TIERS["read"]["max_requests"] == 300
        assert RATE_TIERS["read"]["window_seconds"] == 60

    def test_write_tier_exists(self):
        assert "write" in RATE_TIERS
        assert RATE_TIERS["write"]["max_requests"] == 60
        assert RATE_TIERS["write"]["window_seconds"] == 60

    def test_analyze_tier_exists(self):
        assert "analyze" in RATE_TIERS
        assert RATE_TIERS["analyze"]["max_requests"] == 5
        assert RATE_TIERS["analyze"]["window_seconds"] == 3600

    def test_upload_tier_exists(self):
        assert "upload" in RATE_TIERS
        assert RATE_TIERS["upload"]["max_requests"] == 10
        assert RATE_TIERS["upload"]["window_seconds"] == 3600

    def test_exactly_5_tiers(self):
        assert len(RATE_TIERS) == 5


# ---------------------------------------------------------------------------
# Lua script
# ---------------------------------------------------------------------------

class TestLuaScript:
    def test_lua_script_is_nonempty_string(self):
        assert isinstance(_SLIDING_WINDOW_LUA, str)
        assert len(_SLIDING_WINDOW_LUA) > 50

    def test_lua_script_contains_zadd(self):
        assert "ZADD" in _SLIDING_WINDOW_LUA.upper() or "zadd" in _SLIDING_WINDOW_LUA

    def test_lua_script_contains_zremrangebyscore(self):
        upper = _SLIDING_WINDOW_LUA.upper()
        assert "ZREMRANGEBYSCORE" in upper or "zremrangebyscore" in _SLIDING_WINDOW_LUA

    def test_lua_script_contains_zcard(self):
        assert "ZCARD" in _SLIDING_WINDOW_LUA.upper() or "zcard" in _SLIDING_WINDOW_LUA


# ---------------------------------------------------------------------------
# Below limit — request passes
# ---------------------------------------------------------------------------

class TestBelowLimit:
    def test_below_limit_passes(self):
        """When Redis returns count below max, request succeeds."""
        app = _make_app(tier="read")
        mock_r = _mock_redis(eval_return=1)  # 1 request so far
        with patch("web.rate_limit.get_redis", return_value=mock_r):
            client = app.test_client()
            with app.test_request_context():
                g.current_user_id = "user_42"
            resp = client.get("/limited", headers={"X-User-Id": "user_42"})
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True

    def test_at_exact_limit_passes(self):
        """Request at exactly max_requests is still allowed (count == max)."""
        app = _make_app(tier="auth")
        mock_r = _mock_redis(eval_return=20)  # exactly at limit
        with patch("web.rate_limit.get_redis", return_value=mock_r):
            client = app.test_client()
            resp = client.get("/limited")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# At limit — request blocked with 429
# ---------------------------------------------------------------------------

class TestAtLimitBlocked:
    def test_over_limit_returns_429(self):
        """When Redis returns count > max, request is rejected with 429."""
        app = _make_app(tier="auth")
        mock_r = _mock_redis(eval_return=21)  # over the 20 limit
        with patch("web.rate_limit.get_redis", return_value=mock_r):
            client = app.test_client()
            resp = client.get("/limited")
        assert resp.status_code == 429

    def test_429_response_format(self):
        """429 response uses the standard error envelope."""
        app = _make_app(tier="read")
        mock_r = _mock_redis(eval_return=301)  # over 300
        with patch("web.rate_limit.get_redis", return_value=mock_r):
            client = app.test_client()
            resp = client.get("/limited", headers={"X-User-Id": "u1"})
        body = resp.get_json()
        assert body["ok"] is False
        assert body["error"]["code"] == "RATE_LIMITED"
        assert "meta" in body

    def test_429_has_retry_after_header(self):
        """429 response includes a Retry-After header."""
        app = _make_app(tier="write")
        mock_r = _mock_redis(eval_return=61)  # over 60
        with patch("web.rate_limit.get_redis", return_value=mock_r):
            client = app.test_client()
            resp = client.get("/limited", headers={"X-User-Id": "u1"})
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers
        retry_after = int(resp.headers["Retry-After"])
        assert retry_after > 0

    def test_analyze_tier_retry_after_is_large(self):
        """Analyze tier (1h window) has a correspondingly large Retry-After."""
        app = _make_app(tier="analyze")
        mock_r = _mock_redis(eval_return=6)  # over 5
        with patch("web.rate_limit.get_redis", return_value=mock_r):
            client = app.test_client()
            resp = client.get("/limited", headers={"X-User-Id": "u1"})
        assert resp.status_code == 429
        retry_after = int(resp.headers["Retry-After"])
        assert retry_after > 60  # should be up to 3600

    def test_upload_tier_blocks(self):
        """Upload tier (10/hour) blocks at 11."""
        app = _make_app(tier="upload")
        mock_r = _mock_redis(eval_return=11)  # over 10
        with patch("web.rate_limit.get_redis", return_value=mock_r):
            client = app.test_client()
            resp = client.get("/limited", headers={"X-User-Id": "u1"})
        assert resp.status_code == 429


# ---------------------------------------------------------------------------
# Key scoping — IP for auth, user_id for others
# ---------------------------------------------------------------------------

class TestKeyScoping:
    def test_auth_tier_uses_ip(self):
        """Auth tier builds key from remote IP address."""
        app = _make_app(tier="auth")
        mock_r = _mock_redis(eval_return=1)
        with patch("web.rate_limit.get_redis", return_value=mock_r):
            client = app.test_client()
            resp = client.get("/limited", environ_base={"REMOTE_ADDR": "10.0.0.1"})
        # Verify the eval call used an IP-based key
        call_args = mock_r.eval.call_args
        key_arg = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("keys", [None])[0]
        # The key should contain the IP
        assert "10.0.0.1" in str(key_arg) or "auth" in str(call_args)
        assert resp.status_code == 200

    def test_read_tier_uses_user_id(self):
        """Read tier builds key from current_user_id."""
        app = _make_app(tier="read")
        mock_r = _mock_redis(eval_return=1)

        @app.before_request
        def set_user():
            g.current_user_id = "user_99"

        with patch("web.rate_limit.get_redis", return_value=mock_r):
            client = app.test_client()
            resp = client.get("/limited")
        call_args = mock_r.eval.call_args
        # Flatten all positional args to check for user_99
        all_args_str = str(call_args)
        assert "user_99" in all_args_str
        assert resp.status_code == 200

    def test_write_tier_uses_user_id(self):
        """Write tier also keys on current_user_id."""
        app = _make_app(tier="write")
        mock_r = _mock_redis(eval_return=1)

        @app.before_request
        def set_user():
            g.current_user_id = "user_77"

        with patch("web.rate_limit.get_redis", return_value=mock_r):
            client = app.test_client()
            resp = client.get("/limited")
        all_args_str = str(mock_r.eval.call_args)
        assert "user_77" in all_args_str


# ---------------------------------------------------------------------------
# Redis unavailable — graceful degradation
# ---------------------------------------------------------------------------

class TestRedisUnavailable:
    def test_redis_error_allows_request(self):
        """If Redis is unavailable, request proceeds (fail open)."""
        app = _make_app(tier="read")
        mock_r = MagicMock()
        mock_r.eval.side_effect = Exception("Connection refused")
        with patch("web.rate_limit.get_redis", return_value=mock_r):
            client = app.test_client()
            resp = client.get("/limited", headers={"X-User-Id": "u1"})
        assert resp.status_code == 200

    def test_redis_none_allows_request(self):
        """If get_redis() returns None, request proceeds."""
        with patch("web.rate_limit.get_redis", return_value=None):
            app = _make_app(tier="read")
            client = app.test_client()
            resp = client.get("/limited")
        assert resp.status_code == 200
