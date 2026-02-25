"""
SQLite connection management for the Flask app.

Uses Flask's ``g`` object for per-request connection pooling
and ``app.teardown_appcontext`` for automatic cleanup.

Also provides a standalone ``get_db_connection()`` for use
outside Flask (e.g. from the pipeline).
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Module-level default so the pipeline can open a connection
# without a Flask app context.
_default_db_path: Optional[Path] = None


def set_default_db_path(path: Path) -> None:
    """Set the default database path for non-Flask usage."""
    global _default_db_path
    _default_db_path = path


def _connect(db_path: Path) -> sqlite3.Connection:
    """Open a new SQLite connection with sensible defaults."""
    conn = sqlite3.connect(
        str(db_path),
        timeout=10.0,
        detect_types=sqlite3.PARSE_DECLTYPES,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn


def get_db_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """
    Return a new SQLite connection.

    When called inside a Flask request, uses ``flask.g`` for caching.
    When called outside Flask (e.g. from the pipeline), opens a fresh
    connection to *db_path* or the module-level default.
    """
    # Try Flask context first.
    try:
        from flask import g, current_app
        if "db" not in g:
            g.db = _connect(Path(current_app.config["DB_PATH"]))
        return g.db
    except (ImportError, RuntimeError):
        pass

    # Standalone mode.
    path = db_path or _default_db_path
    if path is None:
        try:
            from path_manager import get_base_dir
            path = get_base_dir() / "telemetry.db"
        except ImportError:
            path = Path("telemetry.db")

    return _connect(path)


def close_db(exc: Optional[BaseException] = None) -> None:
    """Close the Flask per-request connection (teardown hook)."""
    try:
        from flask import g
        db = g.pop("db", None)
        if db is not None:
            db.close()
    except (ImportError, RuntimeError):
        pass


def init_db(db_path: Optional[Path] = None) -> None:
    """Create all tables (idempotent). Called on app startup."""
    from db.migrate import ensure_schema

    conn = get_db_connection(db_path)
    try:
        ensure_schema(conn)
    finally:
        # Only close if we opened it ourselves (not in Flask context).
        try:
            from flask import g
            _ = g  # noqa: F841  — just test if we're in Flask context
        except (ImportError, RuntimeError):
            conn.close()
