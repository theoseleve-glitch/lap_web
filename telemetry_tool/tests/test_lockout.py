"""Tests for auth.lockout — Redis-backed brute-force protection."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from auth.lockout import MAX_ATTEMPTS, check_lockout, clear_attempts, record_failed_attempt


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
