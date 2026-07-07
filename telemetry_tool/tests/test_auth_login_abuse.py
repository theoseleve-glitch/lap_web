"""Integration tests for /auth/login abuse-prevention fixes.

Covers two confirmed HIGH defects on the live login path:

  #4 -- the rate limiter AND account lockout used to fail fully open on a
        Redis outage (unbounded credential brute-force). Fixed with a
        bounded, in-process degraded-mode fallback (see web/rate_limit.py
        and auth/lockout.py).
  #5 -- the lockout key was email-only (no IP) AND a failed login was
        recorded twice (once in auth/service.py, once in the route's
        except block), so 3 bad-password POSTs tripped a 5-attempt
        lockout -- letting a remote attacker who only knows a victim's
        email permanently lock them out. Fixed by recording exactly once
        and scoping the hard lock to (email, IP).

These exercise the real Flask blueprint + auth.service.login_user() with a
stubbed DB connection, mirroring the pattern used in
tests/test_password_management.py.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import auth.lockout as lockout_mod
import web.rate_limit as rate_limit_mod
from auth.lockout import MAX_ATTEMPTS
from web.api_utils import init_request_id
from web.routes.auth import bp as auth_bp

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_auth_app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["USE_PG"] = True
    app.config["JWT_SECRET"] = "test-secret-key-1234567890123456"
    init_request_id(app)
    app.register_blueprint(auth_bp)
    return app


def _conn_with_user(email: str, password_hash: str, user_id: int = 1):
    """Minimal DB-connection stub covering every query login() touches."""
    conn = MagicMock()

    def execute(sql, params=None):
        cur = MagicMock()
        if "SELECT id, email, password_hash" in sql:
            cur.fetchone.return_value = {
                "id": user_id,
                "email": email,
                "password_hash": password_hash,
                "display_name": "Test User",
                "totp_enabled": False,
            }
        elif "SELECT suspension_reason" in sql:
            cur.fetchone.return_value = None
        elif "SELECT 1 FROM audit_log" in sql:
            cur.fetchone.return_value = None
        elif "SELECT COUNT" in sql:
            cur.fetchone.return_value = {"cnt": 0}
        else:
            cur.fetchone.return_value = None
        return cur

    conn.execute.side_effect = execute
    return conn


def _conn_no_user():
    """DB-connection stub where every SELECT misses (unknown email)."""
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = None
    conn.execute.return_value = cur
    return conn


class _FakeRedis:
    """Minimal stateful fake of the sorted-set ops auth/lockout.py uses --
    enough to prove real per-(email, IP)-key isolation, unlike a flat
    MagicMock that would return the same canned value for every key."""

    def __init__(self):
        self._sets: dict[str, dict[str, float]] = {}

    def zadd(self, key, mapping):
        self._sets.setdefault(key, {}).update(mapping)

    def zcard(self, key):
        return len(self._sets.get(key, {}))

    def zremrangebyscore(self, key, lo, hi):
        cutoff = float(hi)
        s = self._sets.get(key, {})
        self._sets[key] = {m: sc for m, sc in s.items() if sc > cutoff}

    def zrange(self, key, start, end, withscores=False):
        items = sorted(self._sets.get(key, {}).items(), key=lambda kv: kv[1])
        return items[start:] if end == -1 else items[start:end + 1]

    def expire(self, key, ttl):
        pass

    def delete(self, key):
        self._sets.pop(key, None)


@pytest.fixture(autouse=True)
def _reset_degraded_state():
    """Degraded-mode buckets are module-level (per-worker) -- reset around
    every test so these don't bleed into each other or other test modules."""
    rate_limit_mod._degraded_auth_buckets.clear()
    lockout_mod._degraded_buckets.clear()
    yield
    rate_limit_mod._degraded_auth_buckets.clear()
    lockout_mod._degraded_buckets.clear()


# ---------------------------------------------------------------------------
# Fix #5(a): no more double-counted failed attempts
# ---------------------------------------------------------------------------


class TestNoDoubleCountOnBadPassword:
    def test_three_bad_passwords_record_exactly_three_attempts(self):
        from auth.service import hash_password

        password_hash = hash_password("correct-horse-battery-staple")
        conn = _conn_with_user("victim@example.com", password_hash)

        app = _make_auth_app()
        client = app.test_client()

        with (
            patch("web.routes.auth._get_conn", return_value=conn),
            patch("web.rate_limit.get_redis", return_value=None),
            patch("auth.lockout._get_redis", return_value=None),
            patch("auth.lockout.record_failed_attempt") as mock_record,
        ):
            for _ in range(3):
                resp = client.post(
                    "/auth/login",
                    json={"email": "victim@example.com", "password": "wrong-password"},
                    environ_base={"REMOTE_ADDR": "192.0.2.10"},
                )
                assert resp.status_code == 401

        # Before the fix this was 6 (once in auth/service.py, once again in
        # the route's `except AuthError` block) -- 3 bad passwords tripped
        # the 5-attempt lockout after only 3 requests.
        assert mock_record.call_count == 3

    def test_user_not_found_also_records_exactly_once(self):
        """Unknown-email path (constant-time dummy-hash branch) must not be
        double-counted either."""
        conn = _conn_no_user()

        app = _make_auth_app()
        client = app.test_client()

        with (
            patch("web.routes.auth._get_conn", return_value=conn),
            patch("web.rate_limit.get_redis", return_value=None),
            patch("auth.lockout._get_redis", return_value=None),
            patch("auth.lockout.record_failed_attempt") as mock_record,
        ):
            resp = client.post(
                "/auth/login",
                json={"email": "unknown@example.com", "password": "whatever"},
                environ_base={"REMOTE_ADDR": "192.0.2.11"},
            )
        assert resp.status_code == 401
        assert mock_record.call_count == 1


# ---------------------------------------------------------------------------
# Fix #5(b): hard lock scoped by (email, IP)
# ---------------------------------------------------------------------------


class TestVictimNotLockedByAttackerIP:
    def test_attacker_ip_cannot_lock_victim_from_different_ip(self):
        from auth.service import hash_password

        password_hash = hash_password("correct-horse-battery-staple")
        conn = _conn_with_user("victim@example.com", password_hash)
        fake_redis = _FakeRedis()
        # Redis "available" with generous headroom for rate_limit so this
        # test isolates lockout behaviour specifically.
        rl_redis = MagicMock()
        rl_redis.eval.return_value = 1

        app = _make_auth_app()
        client = app.test_client()

        with (
            patch("web.routes.auth._get_conn", return_value=conn),
            patch("web.rate_limit.get_redis", return_value=rl_redis),
            patch("auth.lockout._get_redis", return_value=fake_redis),
        ):
            for _ in range(MAX_ATTEMPTS):
                resp = client.post(
                    "/auth/login",
                    json={"email": "victim@example.com", "password": "wrong"},
                    environ_base={"REMOTE_ADDR": "9.9.9.9"},
                )
                assert resp.status_code == 401

            # The attacker has now locked out THEIR OWN (email, ip) pair.
            locked_resp = client.post(
                "/auth/login",
                json={"email": "victim@example.com", "password": "wrong"},
                environ_base={"REMOTE_ADDR": "9.9.9.9"},
            )
            assert locked_resp.status_code == 429

            # The victim logs in with the CORRECT password from a DIFFERENT
            # IP -- must succeed, not be blocked by the attacker's failures
            # against the same email address.
            victim_resp = client.post(
                "/auth/login",
                json={"email": "victim@example.com", "password": "correct-horse-battery-staple"},
                environ_base={"REMOTE_ADDR": "1.2.3.4"},
            )
        assert victim_resp.status_code == 200

    def test_same_ip_repeated_bad_password_still_locks(self):
        """IP-scoping must not weaken the genuine same-IP lockout case."""
        from auth.service import hash_password

        password_hash = hash_password("correct-horse-battery-staple")
        conn = _conn_with_user("user@example.com", password_hash)
        fake_redis = _FakeRedis()
        rl_redis = MagicMock()
        rl_redis.eval.return_value = 1

        app = _make_auth_app()
        client = app.test_client()

        with (
            patch("web.routes.auth._get_conn", return_value=conn),
            patch("web.rate_limit.get_redis", return_value=rl_redis),
            patch("auth.lockout._get_redis", return_value=fake_redis),
        ):
            for _ in range(MAX_ATTEMPTS):
                resp = client.post(
                    "/auth/login",
                    json={"email": "user@example.com", "password": "wrong"},
                    environ_base={"REMOTE_ADDR": "203.0.113.9"},
                )
                assert resp.status_code == 401

            locked_resp = client.post(
                "/auth/login",
                json={"email": "user@example.com", "password": "correct-horse-battery-staple"},
                environ_base={"REMOTE_ADDR": "203.0.113.9"},
            )
        assert locked_resp.status_code == 429
