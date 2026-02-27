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


def get_db_connection(db_path: Optional[Path] = None):
    """
    Return a database connection.

    When ``USE_PG=1`` is set in the environment, delegates to the
    PostgreSQL pool (``db_pg.get_pg_connection``).  Otherwise returns
    a SQLite connection, using ``flask.g`` for caching inside Flask
    and a fresh connection outside it.
    """
    import os
    if os.environ.get("USE_PG", "0") == "1":
        from web.db_pg import get_pg_connection
        return get_pg_connection()

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
        validate_karts_schema(conn)
    finally:
        # Only close if we opened it ourselves (not in Flask context).
        try:
            from flask import g
            _ = g  # noqa: F841  — just test if we're in Flask context
        except (ImportError, RuntimeError):
            conn.close()


def validate_karts_schema(conn: sqlite3.Connection) -> bool:
    """Return True when required karts tables are present, else log warning.

    This is a lightweight startup/readiness check to make schema drift visible
    in logs before user traffic hits kart endpoints.
    """
    required_tables = ("karts", "predefined_karts")
    present_rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    present = {
        row["name"] if isinstance(row, sqlite3.Row) else row[0]
        for row in present_rows
    }
    missing = sorted(set(required_tables) - present)
    if missing:
        logger.warning(
            "Startup health check: missing karts schema tables: %s. "
            "Run DB migrations to restore kart endpoints.",
            ", ".join(missing),
        )
        return False
    return True
