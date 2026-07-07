"""Tests for the shared Redis fail-open alerting helper."""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from web import redis_health as redis_health_mod
from web.redis_health import (
    alert_redis_failopen,
    get_degraded_mode_stats,
    record_degraded_mode,
    record_recovery,
)


class TestAlertRedisFailopen:
    def test_logs_error_with_component_name(self, caplog):
        with caplog.at_level(logging.ERROR, logger="web.redis_health"):
            alert_redis_failopen("rate_limit")
        assert any("Redis fail-open: rate_limit" in r.message for r in caplog.records)

    def test_logs_detail_when_provided(self, caplog):
        with caplog.at_level(logging.ERROR, logger="web.redis_health"):
            alert_redis_failopen("lockout", "connection refused")
        assert any("connection refused" in r.message for r in caplog.records)

    def test_forwards_to_sentry_when_available(self):
        fake_sentry = MagicMock()
        with patch.dict(sys.modules, {"sentry_sdk": fake_sentry}):
            alert_redis_failopen("idempotency")
        fake_sentry.capture_message.assert_called_once()
        args, kwargs = fake_sentry.capture_message.call_args
        assert "Redis fail-open: idempotency" in args[0]
        assert kwargs.get("level") == "error"

    def test_never_raises_when_sentry_missing(self):
        with patch.dict(sys.modules, {"sentry_sdk": None}):
            alert_redis_failopen("rate_limit")  # must not raise

    def test_never_raises_when_sentry_capture_fails(self):
        fake_sentry = MagicMock()
        fake_sentry.capture_message.side_effect = RuntimeError("network down")
        with patch.dict(sys.modules, {"sentry_sdk": fake_sentry}):
            alert_redis_failopen("rate_limit")  # must not raise


# ---------------------------------------------------------------------------
# Follow-up Fix #3: degraded-mode stats never reset on recovery.
#
# ``seconds`` used to grow forever from the first-ever degraded call for a
# component, and nothing ever marked a component "recovered" -- dashboards
# could never show an outage had ended.
# ---------------------------------------------------------------------------

class TestDegradedModeRecovery:
    def setup_method(self):
        redis_health_mod._degraded_state.clear()

    def test_fresh_component_is_not_recovered(self):
        record_degraded_mode("lockout")
        stats = get_degraded_mode_stats()
        assert stats["lockout"]["requests"] == 1
        assert stats["lockout"]["recovered"] is False

    def test_recovery_marks_recovered(self):
        record_degraded_mode("lockout")
        record_recovery("lockout")
        stats = get_degraded_mode_stats()
        assert stats["lockout"]["recovered"] is True

    def test_recovery_freezes_seconds_instead_of_growing_forever(self):
        record_degraded_mode("lockout")
        record_recovery("lockout")
        frozen = get_degraded_mode_stats()["lockout"]["seconds"]
        time.sleep(0.02)
        # No further degraded calls happened -- "seconds" must stay frozen,
        # not keep climbing with wall-clock time.
        assert get_degraded_mode_stats()["lockout"]["seconds"] == frozen

    def test_new_episode_after_recovery_starts_a_fresh_window(self):
        record_degraded_mode("rate_limit_auth")
        record_recovery("rate_limit_auth")
        assert get_degraded_mode_stats()["rate_limit_auth"]["recovered"] is True

        record_degraded_mode("rate_limit_auth")  # a NEW outage begins
        stats = get_degraded_mode_stats()
        assert stats["rate_limit_auth"]["recovered"] is False
        # Cumulative request count survives across episodes.
        assert stats["rate_limit_auth"]["requests"] == 2

    def test_recovery_is_noop_when_never_degraded(self):
        record_recovery("idempotency")  # never recorded as degraded
        assert get_degraded_mode_stats() == {}

    def test_recovery_never_raises(self):
        record_recovery("anything")  # no prior state at all -- must not raise
        record_recovery("anything")  # already-recovered/absent -- must not raise
