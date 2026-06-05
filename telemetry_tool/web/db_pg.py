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


def _get_migration_url() -> str:
    """DSN for DDL: alembic migrations + partition rotation.

    Runs as the table OWNER (``telemetry``). Falls back to the app DSN so
    single-role dev/test environments keep working unchanged.
    """
    return os.environ.get("TELEMETRY_PG_MIGRATION_URL", _get_pg_url())


def _get_maint_url() -> str:
    """DSN for legitimately cross-tenant maintenance (``telemetry_maint``).

    BYPASSRLS but NOSUPERUSER — retention enforcement, usage aggregation,
    admin storage metrics. Falls back to the app DSN for dev/test.
    """
    return os.environ.get("TELEMETRY_PG_MAINT_URL", _get_pg_url())


_MAX_CONNECT_RETRIES = 2
_CONNECT_RETRY_DELAY = 0.5  # seconds


def _new_connection():
    """Create a fresh psycopg2 connection with RealDictCursor.

    Connection and statement timeouts are configurable via environment
    variables to prevent indefinite hangs:
      - TELEMETRY_PG_CONNECT_TIMEOUT: seconds to wait for connection (default 5)
      - TELEMETRY_PG_STATEMENT_TIMEOUT: milliseconds for query timeout (default 30000)

    Retries up to 2 times on transient connection failures (e.g. too many
    connections, temporary network issues) with a short backoff.
    """
    import psycopg2
    import psycopg2.extras

    connect_timeout = int(os.environ.get("TELEMETRY_PG_CONNECT_TIMEOUT", "5"))
    statement_timeout = os.environ.get("TELEMETRY_PG_STATEMENT_TIMEOUT", "30000")

    last_exc: Exception | None = None
    for attempt in range(_MAX_CONNECT_RETRIES + 1):
        try:
            conn = psycopg2.connect(
                _get_pg_url(),
                connect_timeout=connect_timeout,
                options=f"-c statement_timeout={statement_timeout}",
            )
            conn.cursor_factory = psycopg2.extras.RealDictCursor
            return conn
        except psycopg2.OperationalError as exc:
            last_exc = exc
            if attempt < _MAX_CONNECT_RETRIES:
                logger.warning(
                    "PG connection attempt %d/%d failed: %s — retrying in %.1fs",
                    attempt + 1, _MAX_CONNECT_RETRIES + 1, exc, _CONNECT_RETRY_DELAY,
                )
                time.sleep(_CONNECT_RETRY_DELAY)
            else:
                logger.error(
                    "PG connection exhausted after %d attempts: %s",
                    _MAX_CONNECT_RETRIES + 1, exc,
                )
    raise last_exc  # type: ignore[misc]


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

    def execute(self, sql, params=None):
        """Execute SQL and return the cursor (sqlite3.Connection-compatible).

        The SQL is translated from SQLite to PostgreSQL dialect before
        execution (named params, positional params, INSERT OR IGNORE, etc.).
        Accepts plain strings or SQLAlchemy ``text()`` objects (auto-unwrapped).
        Queries exceeding SLOW_QUERY_THRESHOLD_MS are logged as warnings.
        """
        from db.sql_compat import translate_params

        # Unwrap SQLAlchemy text() objects to plain strings
        if not isinstance(sql, str):
            sql = str(sql)

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

    def _reapply_rls_context(self, event: str) -> None:
        """Re-apply the RLS workspace context after a transaction boundary.

        SET LOCAL (both the GUC and ROLE) is scoped to the transaction;
        COMMIT/ROLLBACK ends it and clears the context. Re-apply BOTH via
        set_workspace_context — re-applying only the GUC (the old behaviour)
        silently reverted the role to the login role mid-request, which
        bypassed RLS entirely when that login role was a superuser.
        """
        try:
            from flask import g
            ws_id = getattr(g, "workspace_id", None)
            if ws_id is not None:
                from auth.workspace import set_workspace_context
                set_workspace_context(self, ws_id)
                logger.debug(
                    "Re-applied RLS context after %s (ws=%s)", event, ws_id
                )
        except (ImportError, RuntimeError):
            pass  # Outside Flask context — no RLS to re-apply

    def commit(self):
        """Commit and re-apply RLS context if inside a Flask request."""
        self._conn.commit()
        self._reapply_rls_context("commit")

    def rollback(self):
        """Rollback and re-apply RLS context if inside a Flask request.

        Without this, the first rollback in a request dropped the SET LOCAL
        context and every later query ran unscoped as the login role.
        """
        self._conn.rollback()
        self._reapply_rls_context("rollback")

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


def get_migration_connection():
    """Standalone wrapped connection on the migration/owner DSN.

    For runtime DDL only (partition rotation in tasks/archival_tasks.py) —
    the app role deliberately lacks CREATE/DROP rights. Caller must close
    via ``return_pg_connection``. Never cached on ``flask.g``.
    """
    import psycopg2
    import psycopg2.extras

    conn = psycopg2.connect(_get_migration_url(), connect_timeout=5)
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return PgConnectionWrapper(conn)


def get_maint_connection():
    """Standalone wrapped connection on the maintenance DSN (telemetry_maint).

    For legitimately cross-tenant background work that must see/modify rows
    across ALL workspaces without a per-workspace GUC: retention enforcement,
    GDPR account purge, usage aggregation, training, alerting, admin reads.
    The role is BYPASSRLS but NOSUPERUSER. Caller must close via
    ``return_pg_connection``. Never cached on ``flask.g``.
    """
    import psycopg2
    import psycopg2.extras

    conn = psycopg2.connect(_get_maint_url(), connect_timeout=5)
    conn.cursor_factory = psycopg2.extras.RealDictCursor
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
    # Locate alembic.ini — try telemetry_tool/ first (Docker layout),
    # then project root (local dev layout).
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    pkg_root = Path(__file__).resolve().parent.parent  # telemetry_tool/
    ini_path = pkg_root / "alembic.ini"
    if not ini_path.exists():
        ini_path = pkg_root.parent / "alembic.ini"  # project root fallback
    if not ini_path.exists():
        logger.warning("alembic.ini not found -- skipping migrations")
        return

    cfg = Config(str(ini_path))
    # Override the DB URL so we always use the runtime value. Migrations
    # perform owner-only DDL (CREATE TABLE / POLICY / FORCE RLS), so prefer
    # the dedicated migration DSN when configured — the app role
    # (telemetry_app) is deliberately not allowed to run them.
    cfg.set_main_option("sqlalchemy.url", _get_migration_url())
    # Resolve script_location relative to alembic.ini (handles Docker layout
    # where CWD != the directory containing alembic.ini).
    script_dir = ini_path.parent / cfg.get_main_option("script_location", "alembic")
    cfg.set_main_option("script_location", str(script_dir))
    try:
        command.upgrade(cfg, "head")
        logger.info("Alembic migrations applied to head")
    except Exception as exc:
        # Don't crash the app — the DB is likely already at the latest
        # revision. Log the error so operators can fix the migration chain.
        logger.warning("Alembic upgrade failed (app continues): %s", exc)


def assert_rls_enforcement(auth_required: bool) -> None:
    """Fail loud at startup when the app DSN cannot enforce RLS.

    Superusers and BYPASSRLS roles ignore row-level security policies, so a
    multi-tenant deployment connecting as one has NO tenant isolation (the
    P0 cross-tenant bypass found in the 2026-06-03 launch audit). In
    multi-tenant mode (``AUTH_REQUIRED``) this refuses to start unless the
    operator explicitly opts out via ``TELEMETRY_ALLOW_PRIVILEGED_DB=1``
    (single-role dev / migration containers). Outside multi-tenant mode it
    logs an error but lets the app run.
    """
    import psycopg2

    try:
        conn = psycopg2.connect(_get_pg_url(), connect_timeout=5)
    except Exception as exc:
        # Connectivity problems surface elsewhere (init_pg / first request);
        # the guard only rules on privilege level.
        logger.warning("RLS enforcement check skipped — cannot connect: %s", exc)
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT rolsuper, rolbypassrls FROM pg_roles "
                "WHERE rolname = current_user"
            )
            row = cur.fetchone()
    finally:
        conn.close()

    if row is None:
        return
    rolsuper, rolbypassrls = row[0], row[1]
    if not (rolsuper or rolbypassrls):
        logger.info("RLS enforcement check OK — app role is non-privileged")
        return

    problem = (
        "TELEMETRY_PG_URL connects as a role with "
        f"{'SUPERUSER' if rolsuper else ''}{' and ' if rolsuper and rolbypassrls else ''}"
        f"{'BYPASSRLS' if rolbypassrls else ''} — row-level security is "
        "BYPASSED and tenants can read each other's data. Point the app DSN "
        "at the telemetry_app role (see docs/rls-cutover-runbook.md)."
    )
    if auth_required and os.environ.get("TELEMETRY_ALLOW_PRIVILEGED_DB") != "1":
        raise RuntimeError(problem)
    logger.error("%s (continuing: %s)", problem,
                 "TELEMETRY_ALLOW_PRIVILEGED_DB=1" if auth_required
                 else "AUTH_REQUIRED is off")


def close_pool() -> None:
    """No-op — kept for API compatibility (pool was removed)."""
    pass
