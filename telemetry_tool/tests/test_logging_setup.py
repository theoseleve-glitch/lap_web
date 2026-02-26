"""Tests for structured logging setup."""
import json
import logging
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from flask import Flask, g

from web.logging_setup import JsonFormatter, RequestIdFilter, setup_logging


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def app():
    """Minimal Flask app."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def log_record():
    """A plain LogRecord for testing filters and formatters."""
    return logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=42,
        msg="Something happened",
        args=(),
        exc_info=None,
    )


# ---------------------------------------------------------------------------
# RequestIdFilter
# ---------------------------------------------------------------------------

class TestRequestIdFilter:
    def test_adds_request_id_from_g(self, app, log_record):
        filt = RequestIdFilter()
        with app.test_request_context("/"):
            g.request_id = "abc123"
            g.workspace_id = "ws_001"
            g.user_id = "user_42"
            filt.filter(log_record)
            assert log_record.request_id == "abc123"
            assert log_record.workspace_id == "ws_001"
            assert log_record.user_id == "user_42"

    def test_uses_dash_when_no_g_context(self, log_record):
        filt = RequestIdFilter()
        # Outside request context — no Flask g
        filt.filter(log_record)
        assert log_record.request_id == "-"
        assert log_record.workspace_id == "-"
        assert log_record.user_id == "-"

    def test_partial_g_attributes(self, app, log_record):
        filt = RequestIdFilter()
        with app.test_request_context("/"):
            g.request_id = "req_xyz"
            # workspace_id and user_id not set
            filt.filter(log_record)
            assert log_record.request_id == "req_xyz"
            assert log_record.workspace_id == "-"
            assert log_record.user_id == "-"

    def test_filter_returns_true(self, app, log_record):
        filt = RequestIdFilter()
        with app.test_request_context("/"):
            result = filt.filter(log_record)
            assert result is True


# ---------------------------------------------------------------------------
# JsonFormatter
# ---------------------------------------------------------------------------

class TestJsonFormatter:
    def test_outputs_valid_json(self, log_record):
        # Attach expected attributes that the filter would add
        log_record.request_id = "r_001"
        log_record.workspace_id = "ws_001"
        log_record.user_id = "u_001"
        fmt = JsonFormatter()
        output = fmt.format(log_record)
        parsed = json.loads(output)
        assert isinstance(parsed, dict)

    def test_includes_required_fields(self, log_record):
        log_record.request_id = "r_002"
        log_record.workspace_id = "ws_002"
        log_record.user_id = "u_002"
        fmt = JsonFormatter()
        output = fmt.format(log_record)
        parsed = json.loads(output)
        assert "timestamp" in parsed
        assert "level" in parsed
        assert "message" in parsed
        assert "request_id" in parsed
        assert "workspace_id" in parsed
        assert "user_id" in parsed
        assert "logger" in parsed

    def test_message_content(self, log_record):
        log_record.request_id = "-"
        log_record.workspace_id = "-"
        log_record.user_id = "-"
        fmt = JsonFormatter()
        output = fmt.format(log_record)
        parsed = json.loads(output)
        assert parsed["message"] == "Something happened"
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "test.logger"

    def test_level_names(self):
        fmt = JsonFormatter()
        for level_name, level_no in [("DEBUG", logging.DEBUG), ("WARNING", logging.WARNING), ("ERROR", logging.ERROR)]:
            record = logging.LogRecord(
                name="t", level=level_no, pathname="t.py",
                lineno=1, msg="msg", args=(), exc_info=None,
            )
            record.request_id = "-"
            record.workspace_id = "-"
            record.user_id = "-"
            output = fmt.format(record)
            parsed = json.loads(output)
            assert parsed["level"] == level_name


# ---------------------------------------------------------------------------
# setup_logging
# ---------------------------------------------------------------------------

class TestSetupLogging:
    def test_attaches_filter(self, app):
        setup_logging(app)
        root = logging.getLogger()
        filter_types = [type(f).__name__ for f in root.filters]
        assert "RequestIdFilter" in filter_types

    def test_json_format_when_env_set(self, app, monkeypatch):
        monkeypatch.setenv("TELEMETRY_LOG_FORMAT", "json")
        setup_logging(app)
        root = logging.getLogger()
        # At least one handler should use JsonFormatter
        formatter_types = [
            type(h.formatter).__name__
            for h in root.handlers
            if h.formatter is not None
        ]
        assert "JsonFormatter" in formatter_types
