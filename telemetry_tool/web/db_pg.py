"""
PostgreSQL connection management for the Flask app.

Mirrors the SQLite ``db.py`` interface using per-request connections.

The ``PgConnectionWrapper`` bridges the API gap between sqlite3.Connection
and psycopg2 — it provides ``.execute()`` / ``.executemany()`` directly
on the connection object, and translates SQLite-flavoured SQL via
``sql_compat.translate_params()`` automatically.

Enabled when the ``USE_PG`` environment variable is set to ``"1"``.

Connection strategy: simple per-request connections instead of a pool.
Gunicorn sync workers handle 1 request at a time, so pooling offers no
concurrency benefit. Per-request connections are simpler and eliminate
pool-exhaustion bugs that arise with ThreadedConnectionPool in pre-fork
Gunicorn deployments.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ensure the project root is importable so we can reach db.sql_compat
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


_PG_URL_DEFAULT = "postgresql://telemetry:telemetry@localhost:5432/telemetry"


def _get_pg_url() -> str:
    """Return the PostgreSQL connection URL from the environment."""
    return os.environ.get("TELEMETRY_PG_URL", _PG_URL_DEFAULT)


def _new_connection():
    """Create a fresh psycopg2 connection with RealDictCursor."""
    import psycopg2
    import psycopg2.extras

    conn = psycopg2.connect(_get_pg_url())
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn


# ---------------------------------------------------------------------------
# Cursor wrapper — translates SQLite SQL in cur.execute() calls
# ---------------------------------------------------------------------------

class _PgCursorWrapper:
    """Thin wrapper around a psycopg2 cursor that translates SQL."""

    def __init__(self, raw_cursor):
        self._cur = raw_cursor

    def execute(self, sql: str, params=None):
        from db.sql_compat import translate_params
        translated = translate_params(sql)
        if params is not None:
            self._cur.execute(translated, params)
        else:
            self._cur.execute(translated)
        return self  # allow chaining: cur.execute(...).fetchone()

    def executemany(self, sql: str, seq_of_params):
        from db.sql_compat import translate_params
        translated = translate_params(sql)
        self._cur.executemany(translated, seq_of_params)
        return self

    def __getattr__(self, name):
        return getattr(self._cur, name)


# ---------------------------------------------------------------------------
# Connection wrapper — makes psycopg2 behave like sqlite3.Connection
# ---------------------------------------------------------------------------

class PgConnectionWrapper:
    """Thin wrapper around a psycopg2 connection.

    Provides ``.execute()`` and ``.executemany()`` directly on the
    connection object (matching the sqlite3.Connection API) and
    transparently translates SQLite-flavoured SQL to PostgreSQL via
    ``sql_compat.translate_params()``.

    All other attribute access is forwarded to the underlying psycopg2
    connection so that ``conn.commit()``, ``conn.rollback()``,
    ``conn.cursor()``, etc. work as expected.
    """

    def __init__(self, raw_conn):
        self._conn = raw_conn

    # -- sqlite3-compatible execute API -----------------------------------

    # Slow query threshold (milliseconds)
    SLOW_QUERY_THRESHOLD_MS = 500

    def execute(self, sql: str, params=None):
        """Execute SQL and return the cursor (sqlite3.Connection-compatible).

        The SQL is translated from SQLite to PostgreSQL dialect before
        execution (named params, positional params, INSERT OR IGNORE, etc.).
        Queries exceeding SLOW_QUERY_THRESHOLD_MS are logged as warnings.
        """
        from db.sql_compat import translate_params

        translated = translate_params(sql)
        cur = self._conn.cursor()
        start = time.monotonic()
        if params is not None:
            cur.execute(translated, params)
        else:
            cur.execute(translated)
        elapsed_ms = (time.monotonic() - start) * 1000
        if elapsed_ms > self.SLOW_QUERY_THRESHOLD_MS:
            req_id = None
            try:
                from flask import g
                req_id = getattr(g, "request_id", None)
            except (ImportError, RuntimeError):
                pass
            logger.warning(
                "Slow query (%.0fms): %s",
                elapsed_ms,
                sql[:200],
                extra={"duration_ms": elapsed_ms, "request_id": req_id},
            )
        return cur

    def executemany(self, sql: str, seq_of_params):
        """Execute SQL with multiple param sets (sqlite3-compatible)."""
        from db.sql_compat import translate_params

        translated = translate_params(sql)
        cur = self._conn.cursor()
        cur.executemany(translated, seq_of_params)
        return cur

    def cursor(self):
        """Return a translating cursor wrapper with **tuple** rows.

        Code that calls ``conn.cursor()`` then ``cur.execute(sql)`` (e.g.
        RaceStateEngine.save) gets SQL translation automatically.  Uses a
        plain tuple cursor (not RealDictCursor) because legacy code like
        RaceStateEngine uses positional indexing (``row[0]``).
        """
        import psycopg2.extensions
        raw_cur = self._conn.cursor(cursor_factory=psycopg2.extensions.cursor)
        return _PgCursorWrapper(raw_cur)

    # -- Forward everything else to the underlying connection -------------

    def __getattr__(self, name):
        return getattr(self._conn, name)

    # Expose the raw connection for code that explicitly needs it
    @property
    def raw_connection(self):
        return self._conn


def get_pg_connection():
    """
    Return a wrapped PostgreSQL connection with ``RealDictCursor``.

    The returned ``PgConnectionWrapper`` provides ``.execute()`` directly
    on the connection (matching the sqlite3 API) and translates SQLite
    SQL dialect automatically.

    Inside a Flask request the connection is cached on ``flask.g``
    (identical pattern to ``db.py``).  Outside Flask a new connection
    is returned directly -- callers are responsible for closing it
    via ``return_pg_connection()``.
    """
    # Try Flask context first.
    try:
        from flask import g

        if "pg_conn" not in g:
            conn = _new_connection()
            g.pg_conn = PgConnectionWrapper(conn)
        return g.pg_conn
    except (ImportError, RuntimeError):
        pass

    # Standalone mode -- caller must close the connection.
    conn = _new_connection()
    return PgConnectionWrapper(conn)


def _unwrap(conn):
    """Extract the raw psycopg2 connection from a PgConnectionWrapper."""
    if isinstance(conn, PgConnectionWrapper):
        return conn._conn
    return conn


def return_pg_connection(conn) -> None:
    """Close a standalone connection (for non-Flask usage)."""
    if conn is not None:
        raw = _unwrap(conn)
        try:
            raw.rollback()
        except Exception:
            pass
        try:
            raw.close()
        except Exception:
            pass


def close_pg(exc: Optional[BaseException] = None) -> None:
    """
    Flask teardown hook -- close the per-request connection.

    On success the connection is committed, on error it is rolled back.
    The connection is always closed in the ``finally`` block.
    """
    try:
        from flask import g

        conn = g.pop("pg_conn", None)
        if conn is not None:
            raw = _unwrap(conn)
            try:
                if exc is not None:
                    raw.rollback()
                else:
                    try:
                        raw.commit()
                    except Exception:
                        try:
                            raw.rollback()
                        except Exception:
                            pass
            except Exception:
                pass
            finally:
                try:
                    raw.close()
                except Exception:
                    pass
    except (ImportError, RuntimeError):
        pass


def init_pg() -> None:
    """
    Run Alembic migrations to head.

    Call once at app startup (e.g. in the factory function).
    """
    from alembic import command
    from alembic.config import Config

    # Locate alembic.ini — try telemetry_tool/ first (Docker layout),
    # then project root (local dev layout).
    from pathlib import Path

    pkg_root = Path(__file__).resolve().parent.parent  # telemetry_tool/
    ini_path = pkg_root / "alembic.ini"
    if not ini_path.exists():
        ini_path = pkg_root.parent / "alembic.ini"  # project root fallback
    if not ini_path.exists():
        logger.warning("alembic.ini not found -- skipping migrations")
        return

    cfg = Config(str(ini_path))
    # Override the DB URL so we always use the runtime value.
    cfg.set_main_option("sqlalchemy.url", _get_pg_url())
    # Resolve script_location relative to alembic.ini (handles Docker layout
    # where CWD != the directory containing alembic.ini).
    script_dir = ini_path.parent / cfg.get_main_option("script_location", "alembic")
    cfg.set_main_option("script_location", str(script_dir))
    command.upgrade(cfg, "head")
    logger.info("Alembic migrations applied to head")


def close_pool() -> None:
    """No-op — kept for API compatibility (pool was removed)."""
    pass
