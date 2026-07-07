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
    DISTRIBUTED_ATTACK_IP_THRESHOLD,
    MAX_ATTEMPTS,
    _key,
    check_lockout,
    clear_attempts,
    record_failed_attempt,
)
from web.redis_health import get_degraded_mode_stats


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


# ---------------------------------------------------------------------------
# Follow-up Fix #1: bounded degraded-mode buckets (crash-DoS).
#
# During a Redis outage every distinct (email, IP) scope key used to create
# a dict entry that was never removed -- an attacker spraying distinct
# emails/IPs (or just rotating IPs) could grow the dict without bound and
# OOM a worker. Empty buckets must be popped, and the dict must be capped.
# ---------------------------------------------------------------------------

class TestDegradedBucketBounding:
    def setup_method(self):
        lockout_mod._degraded_buckets.clear()

    def test_empty_bucket_is_popped_not_left_stale(self):
        """Once a bucket's timestamps age out of the window, the dict entry
        is removed entirely -- not left behind as an empty list forever."""
        with patch("auth.lockout._get_redis", return_value=None):
            record_failed_attempt("stale@example.com", "1.1.1.1")
        key = lockout_mod._degraded_key("stale@example.com", "1.1.1.1")
        assert key in lockout_mod._degraded_buckets

        # Age the recorded timestamp out of the degraded window.
        lockout_mod._degraded_buckets[key] = [
            time.time() - lockout_mod._DEGRADED_WINDOW_SECONDS - 1
        ]
        with patch("auth.lockout._get_redis", return_value=None):
            result = check_lockout("stale@example.com", "1.1.1.1")
        assert result is None
        assert key not in lockout_mod._degraded_buckets

    def test_spraying_distinct_keys_stays_bounded_by_cap(self):
        """Many distinct (email, IP) scope keys during an outage must not
        grow the in-process dict without bound -- LRU eviction caps it."""
        with (
            patch("auth.lockout._get_redis", return_value=None),
            patch("auth.lockout._DEGRADED_MAX_KEYS", 50),
        ):
            for i in range(500):
                record_failed_attempt(f"attacker{i}@example.com", f"10.0.{i % 255}.1")
        assert len(lockout_mod._degraded_buckets) <= 50

    def test_same_key_throttling_still_works(self):
        """Normal per-(email, IP) throttling is unaffected by the bounding
        change -- the Nth attempt for a fresh key is still allowed and the
        (N+1)th is still throttled."""
        email, ip = "normal-throttle@example.com", "2.2.2.2"
        with patch("auth.lockout._get_redis", return_value=None):
            for _ in range(_DEGRADED_MAX_ATTEMPTS):
                assert check_lockout(email, ip) is None
                record_failed_attempt(email, ip)
            assert check_lockout(email, ip) is not None

    def test_clear_attempts_evicts_degraded_bucket_when_redis_down(self):
        """A successful login during an outage frees the in-process bucket
        instead of leaving it to sit in memory until it ages out."""
        email, ip = "cleared@example.com", "3.3.3.3"
        with patch("auth.lockout._get_redis", return_value=None):
            record_failed_attempt(email, ip)
            key = lockout_mod._degraded_key(email, ip)
            assert key in lockout_mod._degraded_buckets
            clear_attempts(email, ip)
        assert key not in lockout_mod._degraded_buckets


# ---------------------------------------------------------------------------
# Follow-up Fix #2: soft, email-scoped distributed-attack DETECTION signal.
#
# The (email, IP) hard lock above correctly stops the "attacker locks out my
# email" DoS (Fix #5), but that also removed the only email-global signal --
# a botnet failing one victim email from many distinct IPs (<= MAX_ATTEMPTS
# per IP) trips no hard lock at all. This is detection/alert-only, never a
# block.
# ---------------------------------------------------------------------------

class TestDistributedAttackDetection:
    def test_below_threshold_does_not_alert(self):
        r = MagicMock()
        r.scard.return_value = DISTRIBUTED_ATTACK_IP_THRESHOLD - 1
        with (
            patch("auth.lockout._get_redis", return_value=r),
            patch("auth.lockout._alert_distributed_credential_attack") as mock_alert,
        ):
            record_failed_attempt("victim@example.com", "1.2.3.4")
        mock_alert.assert_not_called()

    def test_at_threshold_distinct_ips_alerts_exactly_once(self):
        r = MagicMock()
        r.scard.return_value = DISTRIBUTED_ATTACK_IP_THRESHOLD
        r.set.return_value = True  # SET NX succeeds -- first caller claims it
        with (
            patch("auth.lockout._get_redis", return_value=r),
            patch("auth.lockout._alert_distributed_credential_attack") as mock_alert,
        ):
            record_failed_attempt("victim2@example.com", "9.9.9.1")
        mock_alert.assert_called_once()
        args = mock_alert.call_args[0]
        assert args[0] == "victim2@example.com"
        assert args[1] == DISTRIBUTED_ATTACK_IP_THRESHOLD

    def test_further_crossings_in_same_window_do_not_realert(self):
        """The SET-NX dedup key means additional attacking IPs within the
        same window must not trigger a second alert."""
        r = MagicMock()
        r.scard.return_value = DISTRIBUTED_ATTACK_IP_THRESHOLD + 3
        r.set.return_value = None  # NX failed -- already claimed this window
        with (
            patch("auth.lockout._get_redis", return_value=r),
            patch("auth.lockout._alert_distributed_credential_attack") as mock_alert,
        ):
            record_failed_attempt("victim3@example.com", "9.9.9.2")
        mock_alert.assert_not_called()

    def test_single_ip_fat_fingering_does_not_alert(self):
        """One IP repeatedly failing must not trigger the distributed
        (many-IPs) alert -- a Redis set's distinct-member count for one
        member stays at 1 no matter how many times it's re-added."""
        r = MagicMock()
        r.scard.return_value = 1
        with (
            patch("auth.lockout._get_redis", return_value=r),
            patch("auth.lockout._alert_distributed_credential_attack") as mock_alert,
        ):
            for _ in range(10):
                record_failed_attempt("fatfinger@example.com", "5.5.5.5")
        mock_alert.assert_not_called()

    def test_hard_lock_behavior_is_unchanged(self):
        """The (email, IP) hard lock's own decision (Fix #5) is unaffected
        by the new distributed-detection bookkeeping running alongside it."""
        r = MagicMock()
        r.zcard.return_value = MAX_ATTEMPTS
        r.zrange.return_value = [("member", time.time())]
        r.scard.return_value = 1
        with patch("auth.lockout._get_redis", return_value=r):
            result = check_lockout("hardlock-check@example.com", "7.7.7.1")
        assert result is not None and result > 0

    def test_ip_none_skips_detection_without_raising(self):
        r = MagicMock()
        with patch("auth.lockout._get_redis", return_value=r):
            record_failed_attempt("noip@example.com", None)
        r.sadd.assert_not_called()

    def test_detection_never_raises_when_redis_errors_mid_call(self):
        r = MagicMock()
        r.sadd.side_effect = ConnectionError("redis down mid-call")
        with patch("auth.lockout._get_redis", return_value=r):
            record_failed_attempt("errorcase@example.com", "6.6.6.6")  # must not raise

    def test_skipped_entirely_when_redis_down(self):
        """Best-effort: no crash and no alert when Redis is unavailable --
        the bounded per-(email, IP) degraded fallback is the real control
        during an outage, this signal is allowed to go dark too."""
        with (
            patch("auth.lockout._get_redis", return_value=None),
            patch("auth.lockout._alert_distributed_credential_attack") as mock_alert,
        ):
            record_failed_attempt("downcase@example.com", "4.4.4.4")
        mock_alert.assert_not_called()


# ---------------------------------------------------------------------------
# Follow-up Fix #3 (integration): degraded-mode stats reflect Redis recovery.
# ---------------------------------------------------------------------------

class TestLockoutDegradedRecoveryIntegration:
    def setup_method(self):
        from web import redis_health as redis_health_mod
        redis_health_mod._degraded_state.clear()

    def test_check_lockout_marks_recovery_on_next_successful_redis_call(self):
        # Simulate an outage first.
        with patch("auth.lockout._get_redis", return_value=None):
            check_lockout("recover-user@example.com", "1.1.1.1")
        assert get_degraded_mode_stats()["lockout"]["recovered"] is False

        # Redis is back.
        r = MagicMock()
        r.zcard.return_value = 0
        with patch("auth.lockout._get_redis", return_value=r):
            check_lockout("recover-user@example.com", "1.1.1.1")
        assert get_degraded_mode_stats()["lockout"]["recovered"] is True


# ---------------------------------------------------------------------------
# Chain-A: step-up challenge decision -- turns the distributed-attack
# DETECTION signal above into an actual (mild) response. See
# auth/turnstile.py for the token-verification half.
# ---------------------------------------------------------------------------

class TestChallengeRequired:
    def test_false_when_turnstile_unconfigured_even_past_threshold(self):
        r = MagicMock()
        r.scard.return_value = DISTRIBUTED_ATTACK_IP_THRESHOLD
        with (
            patch("auth.lockout._get_redis", return_value=r),
            patch("auth.turnstile.turnstile_configured", return_value=False),
        ):
            assert lockout_mod.challenge_required("victim@example.com", "1.2.3.4") is False
        r.scard.assert_not_called()  # short-circuits before touching Redis

    def test_false_when_below_threshold_even_if_configured(self):
        r = MagicMock()
        r.scard.return_value = DISTRIBUTED_ATTACK_IP_THRESHOLD - 1
        with (
            patch("auth.lockout._get_redis", return_value=r),
            patch("auth.turnstile.turnstile_configured", return_value=True),
        ):
            assert lockout_mod.challenge_required("victim@example.com", "1.2.3.4") is False

    def test_true_when_past_threshold_and_configured(self):
        r = MagicMock()
        r.scard.return_value = DISTRIBUTED_ATTACK_IP_THRESHOLD
        with (
            patch("auth.lockout._get_redis", return_value=r),
            patch("auth.turnstile.turnstile_configured", return_value=True),
        ):
            assert lockout_mod.challenge_required("victim@example.com", "1.2.3.4") is True

    def test_false_when_redis_down_even_if_configured(self):
        with (
            patch("auth.lockout._get_redis", return_value=None),
            patch("auth.turnstile.turnstile_configured", return_value=True),
        ):
            assert lockout_mod.challenge_required("victim@example.com", "1.2.3.4") is False

    def test_false_and_no_raise_on_redis_error_mid_call(self):
        r = MagicMock()
        r.scard.side_effect = ConnectionError("redis down mid-call")
        with (
            patch("auth.lockout._get_redis", return_value=r),
            patch("auth.turnstile.turnstile_configured", return_value=True),
        ):
            assert lockout_mod.challenge_required("victim@example.com", "1.2.3.4") is False
