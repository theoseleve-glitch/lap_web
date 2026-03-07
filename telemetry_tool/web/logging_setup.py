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
            record.user_id = getattr(g, "current_user_id", "-")
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
            "service": os.environ.get("SERVICE_NAME", "api"),
            "env": os.environ.get("ENV", "development"),
            "message": message,
            "request_id": getattr(record, "request_id", "-"),
            "workspace_id": getattr(record, "workspace_id", "-"),
            "user_id": getattr(record, "user_id", "-"),
            "version": os.environ.get("APP_VERSION", "1.4.0"),
        }
        return json.dumps(log_obj, default=str)


# ---------------------------------------------------------------------------
# Setup — wire filter + formatter into the root logger
# ---------------------------------------------------------------------------

def setup_logging(app: Flask) -> None:
    """Configure the app logger with request-ID enrichment.

    When the ``TELEMETRY_LOG_FORMAT`` environment variable is set to
    ``"json"``, all handlers use :class:`JsonFormatter`.
    Otherwise the default human-readable format is used with the
    request-scoped fields appended.

    The :class:`RequestIdFilter` is attached to the **app logger**
    (not root) to avoid polluting other loggers in test suites.
    """
    logger = app.logger

    # Always attach the enrichment filter
    request_filter = RequestIdFilter()
    logger.addFilter(request_filter)

    # Also attach to the web.* namespace so route/middleware loggers get it
    web_logger = logging.getLogger("web")
    web_logger.addFilter(request_filter)

    # Attach to telemetry_tool.* namespace — route modules use
    # logging.getLogger(__name__) which resolves to e.g.
    # "telemetry_tool.web.routes.sessions_v2".  Without a handler on
    # this namespace, exception logs from routes are silently dropped.
    tt_logger = logging.getLogger("telemetry_tool")
    tt_logger.addFilter(request_filter)

    # Also attach to root logger so third-party libs (celery, psycopg2) get request_id
    logging.getLogger().addFilter(request_filter)

    log_format = os.environ.get("TELEMETRY_LOG_FORMAT", "").lower()

    if log_format == "json":
        json_formatter = JsonFormatter()
        for target in (logger, web_logger, tt_logger):
            for handler in target.handlers:
                handler.setFormatter(json_formatter)
            if not target.handlers:
                handler = logging.StreamHandler()
                handler.setFormatter(json_formatter)
                target.addHandler(handler)
    else:
        # Human-readable format with request context
        human_format = (
            "%(asctime)s %(levelname)-8s "
            "[%(request_id)s] %(name)s: %(message)s"
        )
        formatter = logging.Formatter(human_format)
        for target in (logger, web_logger, tt_logger):
            if target.handlers:
                for handler in target.handlers:
                    handler.setFormatter(formatter)
            else:
                handler = logging.StreamHandler()
                handler.setFormatter(formatter)
                target.addHandler(handler)
