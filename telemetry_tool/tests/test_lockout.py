"""Tests for auth.lockout — Redis-backed brute-force protection."""
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import auth.lockout as lockout_mod
from auth.lockout import (
    _DEGRADED_MAX_ATTEMPTS,
    MAX_ATTEMPTS,
    _key,
    check_lockout,
    clear_attempts,
    record_failed_attempt,
)


class TestCheckLockout:
    def test_returns_none_when_redis_unavailable(self):
        with patch("auth.lockout._get_redis", return_value=None):
            assert check_lockout("user@example.com") is None

    def test_returns_none_under_max_attempts(self):
        r = MagicMock()
        r.zcard.return_value = MAX_ATTEMPTS - 1
        with patch("auth.lockout._get_redis", return_value=r):
            assert check_lockout("user@example.com") is None

    def test_returns_remaining_seconds_when_locked(self):
        import time
        r = MagicMock()
        r.zcard.return_value = MAX_ATTEMPTS
        now = time.time()
        r.zrange.return_value = [("member", now)]
        with patch("auth.lockout._get_redis", return_value=r):
            remaining = check_lockout("user@example.com")
        assert remaining is not None and remaining > 0

    def test_alerts_and_fails_open_on_redis_error(self):
        r = MagicMock()
        r.zremrangebyscore.side_effect = ConnectionError("redis down")
        with (
            patch("auth.lockout._get_redis", return_value=r),
            patch("auth.lockout.alert_redis_failopen") as mock_alert,
        ):
            result = check_lockout("user@example.com")
        assert result is None  # fails open
        mock_alert.assert_called_once()
        assert mock_alert.call_args[0][0] == "lockout"
        assert "redis down" in mock_alert.call_args[0][1]


class TestRecordAndClear:
    def test_record_failed_attempt_calls_zadd(self):
        r = MagicMock()
        with patch("auth.lockout._get_redis", return_value=r):
            record_failed_attempt("user@example.com")
        r.zadd.assert_called_once()

    def test_clear_attempts_calls_delete(self):
        r = MagicMock()
        with patch("auth.lockout._get_redis", return_value=r):
            clear_attempts("user@example.com")
        r.delete.assert_called_once()


# ---------------------------------------------------------------------------
# Fix #5(b): hard lock scoped by (email, IP), not email alone.
#
# An attacker who only knows a victim's email must not be able to lock the
# victim out of logging in from the victim's OWN IP just by repeatedly
# failing that email's password from the attacker's IP.
# ---------------------------------------------------------------------------

class TestIPScopedLockout:
    def test_key_includes_ip(self):
        assert _key("user@example.com", "1.2.3.4") == "login_attempts:user@example.com:1.2.3.4"

    def test_different_ips_for_same_email_get_different_keys(self):
        assert _key("user@example.com", "1.1.1.1") != _key("user@example.com", "2.2.2.2")

    def test_attacker_ip_failures_do_not_lock_victims_different_ip(self):
        """Redis has 5 recorded failures under the ATTACKER's (email, ip) key;
        checking the SAME email from the VICTIM's IP must use a different key
        and therefore see zero attempts -- not locked."""
        r = MagicMock()

        def zcard_side_effect(key):
            return MAX_ATTEMPTS if "9.9.9.9" in key else 0

        r.zcard.side_effect = zcard_side_effect
        r.zrange.return_value = [("member", time.time())]
        with patch("auth.lockout._get_redis", return_value=r):
            attacker_locked = check_lockout("victim@example.com", "9.9.9.9")
            victim_result = check_lockout("victim@example.com", "1.2.3.4")

        assert attacker_locked is not None  # attacker locked out their own IP
        assert victim_result is None        # victim's own IP is unaffected

    def test_same_ip_repeated_failure_still_locks(self):
        """The genuine 'same user fat-fingering their password' case must
        still lock -- IP-scoping must not weaken same-IP brute force
        protection."""
        r = MagicMock()
        r.zcard.return_value = MAX_ATTEMPTS
        now = time.time()
        r.zrange.return_value = [("member", now)]
        with patch("auth.lockout._get_redis", return_value=r):
            result = check_lockout("user@example.com", "203.0.113.7")
        assert result is not None and result > 0

    def test_record_failed_attempt_uses_ip_scoped_key(self):
        r = MagicMock()
        with patch("auth.lockout._get_redis", return_value=r):
            record_failed_attempt("user@example.com", "203.0.113.7")
        called_key = r.zadd.call_args[0][0]
        assert called_key == "login_attempts:user@example.com:203.0.113.7"


# ---------------------------------------------------------------------------
# Fix #4: bounded degraded mode instead of unconditional fail-open when
# Redis is unavailable for lockout checks.
# ---------------------------------------------------------------------------

class TestDegradedModeLockout:
    def setup_method(self):
        # Degraded-mode state is module-level (per-worker) — reset between
        # tests so they don't interfere with each other.
        lockout_mod._degraded_buckets.clear()

    def test_bounded_throttle_engages_when_redis_down(self):
        """With Redis unavailable, the (N+1)th rapid attempt for the same
        (email, IP) is throttled rather than allowed unbounded."""
        email, ip = "throttle-target@example.com", "5.5.5.5"
        with patch("auth.lockout._get_redis", return_value=None):
            for _ in range(_DEGRADED_MAX_ATTEMPTS):
                assert check_lockout(email, ip) is None
                record_failed_attempt(email, ip)
            throttled = check_lockout(email, ip)
        assert throttled is not None and throttled > 0

    def test_normal_single_login_still_works_when_redis_down(self):
        """A single, first-time check for a fresh (email, IP) pair is never
        throttled by the degraded-mode fallback."""
        with patch("auth.lockout._get_redis", return_value=None):
            result = check_lockout("normal-user@example.com", "6.6.6.6")
        assert result is None

    def test_redis_up_behaviour_is_unchanged(self):
        """When Redis is available, the degraded bucket is never consulted
        and normal Redis-backed lockout logic applies as before."""
        r = MagicMock()
        r.zcard.return_value = 0
        with patch("auth.lockout._get_redis", return_value=r):
            result = check_lockout("user@example.com", "7.7.7.7")
        assert result is None
        r.zcard.assert_called_once()

    def test_degraded_mode_is_scoped_per_email_ip_pair(self):
        """Throttling one (email, IP) pair must not throttle a different
        pair sharing state in the same process."""
        with patch("auth.lockout._get_redis", return_value=None):
            for _ in range(_DEGRADED_MAX_ATTEMPTS):
                record_failed_attempt("victim2@example.com", "8.8.8.8")
            # Different email, same attacker IP -- unaffected.
            assert check_lockout("someone-else@example.com", "8.8.8.8") is None
            # Same email, different IP -- unaffected.
            assert check_lockout("victim2@example.com", "1.1.1.1") is None
