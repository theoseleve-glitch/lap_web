"""Cross-tenant RLS isolation proof — real PG, real roles, real policies.

The P0 launch-audit finding (2026-06-03): prod connects as the ``telemetry``
bootstrap superuser, so every tenant-isolation policy is silently bypassed.
No prior test proves isolation against a live PG — they are all mocked
middleware tests or static source-string assertions (see e.g.
tests/test_tenant_isolation.py, tests/integration/test_workspace_teams.py).

These tests run the full alembic chain (incl. 064_rls_enforcement) on a
DISPOSABLE PostgreSQL and then prove, as the actual ``telemetry_app`` role:

1. roles are provisioned with the right attribute split;
2. every RLS-enabled table is FORCEd;
3. SELECT is scoped to the GUC workspace;
4. cross-tenant INSERT is rejected (WITH CHECK);
5. an unset GUC fails CLOSED (error, not leak);
6. PgConnectionWrapper.commit()/rollback() re-apply BOTH the GUC and the
   role (regression: the old commit() re-applied only the GUC, silently
   reverting to the privileged login role mid-request);
7. telemetry_maint (BYPASSRLS, non-superuser) sees across tenants;
8. workspace-less audit_log system inserts (Stripe webhook path) succeed;
9. assert_rls_enforcement refuses a privileged DSN in multi-tenant mode.

Gating mirrors tests/test_contracts/test_migration_022.py: set
``TELEMETRY_PG_URL_TEST`` to a DISPOSABLE database's DSN (superuser),
e.g. postgresql://postgres@localhost:5433/rls_test — trust auth lets the
suite reconnect as telemetry_app/telemetry_maint without passwords.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("TELEMETRY_PG_URL_TEST"),
    reason="needs a disposable PG; set TELEMETRY_PG_URL_TEST",
)

psycopg2 = pytest.importorskip("psycopg2")
import psycopg2.extras  # noqa: E402  (after importorskip so collection skips cleanly)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ── DSN helpers ─────────────────────────────────────────────────────────


def _dsn(user: str | None = None) -> str:
    """The test DSN, optionally with the user swapped (trust auth)."""
    url = os.environ["TELEMETRY_PG_URL_TEST"]
    if user is None:
        return url
    # postgresql://[user[:pass]@]host[:port]/db → swap the credentials part
    scheme, rest = url.split("://", 1)
    hostpart = rest.split("@", 1)[-1]
    return f"{scheme}://{user}@{hostpart}"


def _connect(user: str | None = None, autocommit: bool = False):
    conn = psycopg2.connect(_dsn(user))
    conn.autocommit = autocommit
    return conn


def _alembic(*args: str) -> None:
    """Run alembic against the disposable DB (same pattern as 022 tests)."""
    env = dict(os.environ)
    env["TELEMETRY_PG_URL"] = os.environ["TELEMETRY_PG_URL_TEST"]
    env.pop("TELEMETRY_PG_MIGRATION_URL", None)  # single-role test DB
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(_PROJECT_ROOT),
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


# ── Schema + seed fixture (module-scoped — one alembic run) ─────────────


def _bootstrap_schema() -> None:
    """Bring the disposable DB from EMPTY to alembic head.

    ``upgrade head`` from base is broken by two historic defects (alembic
    wraps the whole run in ONE transaction, so each failure rolls back to
    an empty DB):

    - 004 and 019 BOTH create ``audit_log`` → DuplicateTable at 019;
    - 019 enables RLS on ``usage_counters`` which 021 creates → UndefinedTable.

    Prod never replayed this path (its alembic_version was stamped), so the
    fix is a test-side bootstrap, not a history rewrite: commit at 018,
    drop the 004 ``audit_log``, give 019 a placeholder ``usage_counters``,
    drop it again before 021 recreates the real one.
    """
    conn = _connect(autocommit=True)
    cur = conn.cursor()
    cur.execute("SELECT to_regclass('public.alembic_version')")
    if cur.fetchone()[0] is not None:
        cur.execute("SELECT version_num FROM alembic_version")
        row = cur.fetchone()
        conn.close()
        if row:  # already migrated (module re-runs against the same DB)
            _alembic("upgrade", "head")
            return
    else:
        conn.close()

    _alembic("upgrade", "018")
    conn = _connect(autocommit=True)
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS audit_log CASCADE")
    cur.execute("CREATE TABLE usage_counters (workspace_id integer)")
    conn.close()

    _alembic("upgrade", "020")
    conn = _connect(autocommit=True)
    conn.cursor().execute("DROP TABLE usage_counters CASCADE")
    conn.close()

    _alembic("upgrade", "head")


@pytest.fixture(scope="module")
def rls_db():
    """Migrate the disposable DB to head and seed two workspaces.

    Returns {"ws_a": id, "ws_b": id, "user_a": id, "user_b": id}.
    """
    _bootstrap_schema()

    conn = _connect(autocommit=True)  # superuser: seeding bypasses RLS
    cur = conn.cursor()

    cur.execute(
        "INSERT INTO users (email) "
        "VALUES ('rls-a@test.local') "
        "ON CONFLICT (email) DO UPDATE SET email = EXCLUDED.email "
        "RETURNING id"
    )
    user_a = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO users (email) "
        "VALUES ('rls-b@test.local') "
        "ON CONFLICT (email) DO UPDATE SET email = EXCLUDED.email "
        "RETURNING id"
    )
    user_b = cur.fetchone()[0]

    cur.execute(
        "INSERT INTO workspaces (type, owner_user_id, display_name) "
        "VALUES ('personal', %s, 'WS A') RETURNING id",
        (user_a,),
    )
    ws_a = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO workspaces (type, owner_user_id, display_name) "
        "VALUES ('personal', %s, 'WS B') RETURNING id",
        (user_b,),
    )
    ws_b = cur.fetchone()[0]

    # One driver row per workspace — drivers is in the original 007 RLS set
    # and FORCEd since 034, i.e. the canonical tenant table.
    cur.execute(
        "INSERT INTO drivers (driver_name, workspace_id) VALUES ('Driver A', %s)",
        (ws_a,),
    )
    cur.execute(
        "INSERT INTO drivers (driver_name, workspace_id) VALUES ('Driver B', %s)",
        (ws_b,),
    )

    conn.close()
    return {"ws_a": ws_a, "ws_b": ws_b, "user_a": user_a, "user_b": user_b}


def _set_ctx(conn, ws_id: int) -> None:
    """Mirror auth.workspace.set_workspace_context on a raw connection."""
    cur = conn.cursor()
    cur.execute("SET LOCAL app.current_workspace_id = %s", (str(ws_id),))
    cur.execute("SET LOCAL ROLE telemetry_app")


# ══════════════════════════════════════════════════════════════════════
# 1+2 — provisioning shape
# ══════════════════════════════════════════════════════════════════════


class TestProvisioning:

    def test_roles_provisioned(self, rls_db):
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles "
            "WHERE rolname IN ('telemetry_app', 'telemetry_maint')"
        )
        roles = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
        conn.close()
        assert roles.get("telemetry_app") == (False, False), roles
        assert roles.get("telemetry_maint") == (False, True), roles

    def test_all_rls_tables_forced(self, rls_db):
        """No table may be ENABLE-but-not-FORCE after 064's sweep."""
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            "SELECT c.relname FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') "
            "AND c.relrowsecurity AND NOT c.relforcerowsecurity"
        )
        stragglers = [r[0] for r in cur.fetchall()]
        conn.close()
        assert stragglers == [], f"ENABLE-but-not-FORCE: {stragglers}"


# ══════════════════════════════════════════════════════════════════════
# 3–5 — isolation as telemetry_app
# ══════════════════════════════════════════════════════════════════════


class TestTenantIsolation:

    def test_select_scoped_to_guc_workspace(self, rls_db):
        conn = _connect(user="telemetry_app")
        cur = conn.cursor()
        _set_ctx(conn, rls_db["ws_a"])
        cur.execute("SELECT driver_name FROM drivers ORDER BY driver_name")
        names_a = [r[0] for r in cur.fetchall()]
        conn.rollback()  # end txn — context drops with it

        _set_ctx(conn, rls_db["ws_b"])
        cur.execute("SELECT driver_name FROM drivers ORDER BY driver_name")
        names_b = [r[0] for r in cur.fetchall()]
        conn.close()

        assert names_a == ["Driver A"], names_a
        assert names_b == ["Driver B"], names_b

    def test_cross_tenant_insert_rejected(self, rls_db):
        """Under workspace A's GUC, writing a row for B must fail."""
        conn = _connect(user="telemetry_app")
        cur = conn.cursor()
        _set_ctx(conn, rls_db["ws_a"])
        with pytest.raises(psycopg2.Error) as exc_info:
            cur.execute(
                "INSERT INTO drivers (driver_name, workspace_id) "
                "VALUES ('Smuggled', %s)",
                (rls_db["ws_b"],),
            )
        conn.close()
        assert "row-level security" in str(exc_info.value).lower()

    def test_unset_guc_fails_closed(self, rls_db):
        """No GUC → the policy expression errors. Never an open door."""
        conn = _connect(user="telemetry_app")
        cur = conn.cursor()
        with pytest.raises(psycopg2.Error):
            cur.execute("SELECT count(*) FROM drivers")
        conn.close()


# ══════════════════════════════════════════════════════════════════════
# 6 — PgConnectionWrapper keeps context across transaction boundaries
# ══════════════════════════════════════════════════════════════════════


class TestWrapperContextSurvival:

    @pytest.fixture()
    def flask_g_ws_a(self, rls_db):
        flask = pytest.importorskip("flask")
        app = flask.Flask(__name__)
        with app.app_context():
            flask.g.workspace_id = rls_db["ws_a"]
            yield

    def _wrapped_app_conn(self):
        """Wrapper over a PRIVILEGED (superuser) login connection.

        Connecting as the superuser is deliberate: it's the only way to
        prove the commit()/rollback() ROLE re-apply matters. SET LOCAL ROLE
        is transaction-scoped, so a boundary reverts to the LOGIN role. If
        the login role is privileged and the role is not re-applied (the old
        bug), RLS is bypassed for the rest of the request. The fix re-issues
        SET LOCAL ROLE on every boundary.
        """
        from web.db_pg import PgConnectionWrapper
        raw = psycopg2.connect(_dsn())  # default DSN = superuser
        raw.cursor_factory = psycopg2.extras.RealDictCursor
        return PgConnectionWrapper(raw)

    def test_commit_reapplies_role_and_guc(self, rls_db, flask_g_ws_a):
        """Regression: commit() used to restore only the GUC, leaving the
        role reverted to the (privileged) login role → RLS bypassed. Prove
        the role is re-dropped to telemetry_app AND isolation holds."""
        from auth.workspace import set_workspace_context

        conn = self._wrapped_app_conn()
        set_workspace_context(conn, rls_db["ws_a"])
        conn.commit()  # boundary — old code left current_user = superuser

        cur = conn.execute("SELECT current_user AS u")
        assert cur.fetchone()["u"] == "telemetry_app"  # role re-dropped
        cur = conn.execute("SELECT driver_name FROM drivers")
        names = [r["driver_name"] for r in cur.fetchall()]
        assert names == ["Driver A"], names  # GUC + role both enforce RLS
        conn.raw_connection.close()

    def test_rollback_reapplies_context(self, rls_db, flask_g_ws_a):
        from auth.workspace import set_workspace_context

        conn = self._wrapped_app_conn()
        set_workspace_context(conn, rls_db["ws_a"])
        conn.rollback()  # boundary — old code left the rest of the request unscoped

        cur = conn.execute("SELECT driver_name FROM drivers")
        names = [r["driver_name"] for r in cur.fetchall()]
        assert names == ["Driver A"], names
        conn.raw_connection.close()


# ══════════════════════════════════════════════════════════════════════
# 7 — maintenance role
# ══════════════════════════════════════════════════════════════════════


class TestMaintenanceRole:

    def test_maint_sees_all_workspaces(self, rls_db):
        conn = _connect(user="telemetry_maint")
        cur = conn.cursor()
        cur.execute(
            "SELECT count(*) FROM drivers WHERE workspace_id IN (%s, %s)",
            (rls_db["ws_a"], rls_db["ws_b"]),
        )
        assert cur.fetchone()[0] == 2
        conn.close()


# ══════════════════════════════════════════════════════════════════════
# 8 — system audit rows (Stripe webhook path)
# ══════════════════════════════════════════════════════════════════════


class TestAuditLogSystemEvents:

    def test_workspace_less_audit_insert_allowed(self, rls_db):
        """billing.py's webhook writes audit rows with no workspace —
        the 064 system-events policy must let them through."""
        conn = _connect(user="telemetry_app")
        cur = conn.cursor()
        _set_ctx(conn, rls_db["ws_a"])
        # 019's audit_log schema uses ``details``; the system-events policy
        # only checks workspace_id IS NULL, so the column set is irrelevant
        # to what we're proving (workspace-less insert passes RLS).
        cur.execute(
            "INSERT INTO audit_log (user_id, action, details) "
            "VALUES (%s, 'charge_refunded', '{}')",
            (rls_db["user_a"],),
        )
        conn.commit()
        conn.close()

    def test_system_rows_invisible_to_tenants(self, rls_db):
        conn = _connect(user="telemetry_app")
        cur = conn.cursor()
        _set_ctx(conn, rls_db["ws_a"])
        cur.execute(
            "SELECT count(*) FROM audit_log WHERE workspace_id IS NULL"
        )
        assert cur.fetchone()[0] == 0
        conn.close()


# ══════════════════════════════════════════════════════════════════════
# 9 — startup guard
# ══════════════════════════════════════════════════════════════════════


class TestStartupGuard:

    def test_guard_refuses_privileged_dsn(self, rls_db, monkeypatch):
        from web.db_pg import assert_rls_enforcement

        monkeypatch.setenv("TELEMETRY_PG_URL", _dsn())  # superuser DSN
        monkeypatch.delenv("TELEMETRY_ALLOW_PRIVILEGED_DB", raising=False)
        with pytest.raises(RuntimeError, match="BYPASSED|SUPERUSER|BYPASSRLS"):
            assert_rls_enforcement(auth_required=True)

    def test_guard_accepts_app_role_dsn(self, rls_db, monkeypatch):
        from web.db_pg import assert_rls_enforcement

        monkeypatch.setenv("TELEMETRY_PG_URL", _dsn("telemetry_app"))
        assert_rls_enforcement(auth_required=True)  # must not raise

    def test_guard_escape_hatch(self, rls_db, monkeypatch):
        from web.db_pg import assert_rls_enforcement

        monkeypatch.setenv("TELEMETRY_PG_URL", _dsn())
        monkeypatch.setenv("TELEMETRY_ALLOW_PRIVILEGED_DB", "1")
        assert_rls_enforcement(auth_required=True)  # must not raise
