"""Structured logging setup for the Flask application.

Provides a ``RequestIdFilter`` that enriches log records with
``request_id``, ``workspace_id``, and ``user_id`` from Flask's ``g``
object, and a ``JsonFormatter`` that outputs one JSON object per line
for production log aggregation.

Usage::

    from web.logging_setup import setup_logging

    # In app factory
    app = Flask(__name__)
    setup_logging(app)
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

from flask import Flask, g


# ---------------------------------------------------------------------------
# Filter — enriches records with request-scoped context
# ---------------------------------------------------------------------------

class RequestIdFilter(logging.Filter):
    """Add ``request_id``, ``workspace_id``, and ``user_id`` to log records.

    Values are read from :data:`flask.g`.  When called outside a request
    context (or when the attributes are missing), each field defaults to
    ``"-"``.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.request_id = getattr(g, "request_id", "-")
            record.workspace_id = getattr(g, "workspace_id", "-")
            record.user_id = getattr(g, "user_id", "-")
        except RuntimeError:
            # Outside Flask request context
            record.request_id = "-"
            record.workspace_id = "-"
            record.user_id = "-"
        return True


# ---------------------------------------------------------------------------
# Formatter — structured JSON output
# ---------------------------------------------------------------------------

class JsonFormatter(logging.Formatter):
    """Format log records as single-line JSON objects.

    Output fields: ``timestamp``, ``level``, ``logger``, ``message``,
    ``request_id``, ``workspace_id``, ``user_id``.

    ``timestamp`` is ISO-8601 UTC.  Exception info, if present, is
    appended to ``message``.
    """

    def format(self, record: logging.LogRecord) -> str:
        # Let the base class handle exc_info → string conversion
        message = record.getMessage()
        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            message = f"{message}\n{record.exc_text}"

        log_obj = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": message,
            "request_id": getattr(record, "request_id", "-"),
            "workspace_id": getattr(record, "workspace_id", "-"),
            "user_id": getattr(record, "user_id", "-"),
        }
        return json.dumps(log_obj, default=str)


# ---------------------------------------------------------------------------
# Setup — wire filter + formatter into the root logger
# ---------------------------------------------------------------------------

def setup_logging(app: Flask) -> None:
    """Configure the root logger with request-ID enrichment.

    When the ``TELEMETRY_LOG_FORMAT`` environment variable is set to
    ``"json"``, all handlers on the root logger use :class:`JsonFormatter`.
    Otherwise the default human-readable format is used with the
    request-scoped fields appended.

    The :class:`RequestIdFilter` is always attached to the root logger
    so that any handler — including third-party — sees the extra fields.
    """
    root = logging.getLogger()

    # Always attach the enrichment filter
    request_filter = RequestIdFilter()
    root.addFilter(request_filter)

    log_format = os.environ.get("TELEMETRY_LOG_FORMAT", "").lower()

    if log_format == "json":
        json_formatter = JsonFormatter()
        # Apply to existing handlers
        for handler in root.handlers:
            handler.setFormatter(json_formatter)
        # If no handlers exist yet, add a StreamHandler
        if not root.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(json_formatter)
            root.addHandler(handler)
    else:
        # Human-readable format with request context
        human_format = (
            "%(asctime)s %(levelname)-8s "
            "[%(request_id)s] %(name)s: %(message)s"
        )
        formatter = logging.Formatter(human_format)
        if root.handlers:
            for handler in root.handlers:
                handler.setFormatter(formatter)
        else:
            handler = logging.StreamHandler()
            handler.setFormatter(formatter)
            root.addHandler(handler)
