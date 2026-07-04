"""Tests for the shared Redis fail-open alerting helper."""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from web.redis_health import alert_redis_failopen


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
