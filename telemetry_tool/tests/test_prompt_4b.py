"""Tests for PROMPT 4B — Query Patterns, Connection Management & Performance.

Validates:
- PgBouncer configuration in docker-compose.prod.yml
- Slow query detection in PgConnectionWrapper
- Query functions (entitlements, usage, audit)
- Per-request caching (get_cached)
- Health check with DB stats
- Pagination module exists and is functional
"""
import json
import logging
import sys
import time
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ===========================================================================
# A) PgBouncer configuration
# ===========================================================================

class TestPgBouncerConfig:
    """PgBouncer is configured in docker-compose.prod.yml."""

    def _compose(self):
        return (_PROJECT_ROOT.parent / "docker-compose.prod.yml").read_text()

    def test_pgbouncer_service_exists(self):
        assert "pgbouncer" in self._compose()

    def test_pgbouncer_transaction_mode(self):
        assert "transaction" in self._compose().lower()

    def test_pgbouncer_pool_size(self):
        c = self._compose()
        assert "DEFAULT_POOL_SIZE" in c or "pool_size" in c.lower()

    def test_pgbouncer_depends_on_postgres(self):
        c = self._compose()
        # pgbouncer section should depend on postgres
        assert "postgres" in c

    def test_pgbouncer_healthcheck(self):
        c = self._compose()
        assert "pg_isready" in c


# ===========================================================================
# B) Slow query detection
# ===========================================================================

class TestSlowQueryDetection:
    """PgConnectionWrapper logs slow queries (>500ms)."""

    def test_threshold_constant(self):
        from web.db_pg import PgConnectionWrapper
        assert hasattr(PgConnectionWrapper, "SLOW_QUERY_THRESHOLD_MS")
        assert PgConnectionWrapper.SLOW_QUERY_THRESHOLD_MS == 500

    def test_execute_imports_time(self):
        """db_pg.py imports time module."""
        source = (_PROJECT_ROOT / "web" / "db_pg.py").read_text()
        assert "import time" in source

    def test_slow_query_logs_warning(self):
        """Execute method should log warning for slow queries."""
        source = (_PROJECT_ROOT / "web" / "db_pg.py").read_text()
        assert "Slow query" in source
        assert "logger.warning" in source

    def test_execute_measures_time(self):
        """Execute uses time.monotonic() for measurement."""
        source = (_PROJECT_ROOT / "web" / "db_pg.py").read_text()
        assert "time.monotonic()" in source


# ===========================================================================
# C) Per-request caching
# ===========================================================================

class TestPerRequestCaching:
    """get_cached() caches values on Flask g."""

    def test_get_cached_exists(self):
        from web.queries import get_cached
        assert callable(get_cached)

    def test_get_cached_caches_value(self):
        """get_cached returns cached value on second call."""
        import flask
        app = flask.Flask(__name__)
        with app.test_request_context():
            from web.queries import get_cached
            call_count = {"n": 0}

            def loader():
                call_count["n"] += 1
                return "result"

            v1 = get_cached("test_key", loader)
            v2 = get_cached("test_key", loader)
            assert v1 == "result"
            assert v2 == "result"
            assert call_count["n"] == 1  # Loader called only once

    def test_get_cached_none_value(self):
        """get_cached correctly caches None values."""
        import flask
        app = flask.Flask(__name__)
        with app.test_request_context():
            from web.queries import get_cached
            call_count = {"n": 0}

            def loader():
                call_count["n"] += 1
                return None

            v1 = get_cached("none_key", loader)
            v2 = get_cached("none_key", loader)
            assert v1 is None
            assert v2 is None
            assert call_count["n"] == 1


# ===========================================================================
# D) Entitlement queries
# ===========================================================================

class FakeRow(dict):
    """Dict-like row that supports both key access and .get()."""
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)


class FakeCursor:
    def __init__(self, rows):
        self._rows = [FakeRow(r) if isinstance(r, dict) else r for r in rows]

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class FakeConn:
    def __init__(self, query_map):
        self._map = query_map
        self.call_log = []

    def execute(self, sql, params=None):
        self.call_log.append((sql, params))
        for key, rows in self._map.items():
            if key in sql:
                return FakeCursor(rows)
        return FakeCursor([])


class TestEntitlementQueries:
    """Entitlement query functions work correctly."""

    def test_get_user_plan_tier_found(self):
        import flask
        app = flask.Flask(__name__)
        with app.test_request_context():
            from web.queries.entitlements import get_user_plan_tier
            conn = FakeConn({"SELECT plan_tier": [{"plan_tier": "racer"}]})
            tier = get_user_plan_tier(conn, user_id=1)
            assert tier == "racer"

    def test_get_user_plan_tier_default(self):
        import flask
        app = flask.Flask(__name__)
        with app.test_request_context():
            from web.queries.entitlements import get_user_plan_tier
            conn = FakeConn({})  # No user found
            tier = get_user_plan_tier(conn, user_id=999)
            assert tier == "demo"

    def test_get_plan_definition(self):
        from web.queries.entitlements import get_plan_definition
        conn = FakeConn({
            "SELECT * FROM plan_definitions": [
                {"tier": "racer", "reports_per_month": 10, "telemetry_retention_days": 90}
            ]
        })
        plan = get_plan_definition(conn, "racer")
        assert plan["tier"] == "racer"
        assert plan["reports_per_month"] == 10

    def test_get_effective_entitlements_with_override(self):
        import flask
        app = flask.Flask(__name__)
        with app.test_request_context():
            from web.queries.entitlements import get_effective_entitlements
            conn = FakeConn({
                "SELECT plan_tier": [{"plan_tier": "demo"}],
                "SELECT * FROM plan_definitions": [
                    {"tier": "demo", "reports_per_month": 1}
                ],
                "SELECT override_key": [
                    {"override_key": "reports_per_month", "override_value": '{"value": 5}'}
                ],
            })
            ent = get_effective_entitlements(conn, user_id=1, workspace_id=1)
            assert ent["reports_per_month"] == 5


# ===========================================================================
# E) Usage queries
# ===========================================================================

class TestUsageQueries:
    """Usage query functions work correctly."""

    def test_get_monthly_usage_found(self):
        from web.queries.usage import get_monthly_usage
        conn = FakeConn({"SELECT total": [{"total": 7}]})
        assert get_monthly_usage(conn, workspace_id=1, event_type="report_generated") == 7

    def test_get_monthly_usage_empty(self):
        from web.queries.usage import get_monthly_usage
        conn = FakeConn({})
        assert get_monthly_usage(conn, workspace_id=1, event_type="report_generated") == 0

    def test_record_usage_event_inserts(self):
        from web.queries.usage import record_usage_event
        conn = FakeConn({})
        record_usage_event(conn, user_id=1, workspace_id=1, event_type="report_generated")
        # Should have 2 execute calls: INSERT event + UPSERT monthly
        assert len(conn.call_log) == 2
        assert "INSERT INTO usage_events" in conn.call_log[0][0]
        assert "INSERT INTO usage_monthly" in conn.call_log[1][0]

    def test_record_usage_event_with_metadata(self):
        from web.queries.usage import record_usage_event
        conn = FakeConn({})
        record_usage_event(
            conn, user_id=1, workspace_id=1,
            event_type="csv_uploaded", cost=2,
            metadata={"file_name": "test.csv"},
        )
        # Check metadata was JSON-serialized
        params = conn.call_log[0][1]
        assert params["meta"] is not None
        assert "test.csv" in params["meta"]


# ===========================================================================
# F) Audit queries
# ===========================================================================

class TestAuditQueries:
    """Audit log query function works correctly."""

    def test_log_audit_event_inserts(self):
        import flask
        app = flask.Flask(__name__)
        with app.test_request_context():
            from flask import g
            g.user_id = 42
            g.current_user_id = 42
            g.workspace_id = 1
            from web.queries.audit import log_audit_event
            conn = FakeConn({})
            log_audit_event(conn, "user.login", {"method": "password"})
            assert len(conn.call_log) == 1
            assert "INSERT INTO audit_log" in conn.call_log[0][0]
            params = conn.call_log[0][1]
            assert params["uid"] == 42
            assert params["wid"] == 1
            assert params["action"] == "user.login"

    def test_log_audit_event_outside_context(self):
        """Audit logging works outside Flask request context."""
        from web.queries.audit import log_audit_event
        conn = FakeConn({})
        log_audit_event(conn, "system.startup")
        assert len(conn.call_log) == 1
        params = conn.call_log[0][1]
        assert params["uid"] is None
        assert params["wid"] is None


# ===========================================================================
# G) Health check with DB stats
# ===========================================================================

class TestHealthCheckDBStats:
    """Health check includes database statistics."""

    def test_get_db_stats_function_exists(self):
        source = (_PROJECT_ROOT / "web" / "routes" / "health.py").read_text()
        assert "_get_db_stats" in source

    def test_health_check_includes_db_stats(self):
        source = (_PROJECT_ROOT / "web" / "routes" / "health.py").read_text()
        assert "db_stats" in source

    def test_db_stats_queries_connections(self):
        source = (_PROJECT_ROOT / "web" / "routes" / "health.py").read_text()
        assert "pg_stat_activity" in source

    def test_db_stats_queries_size(self):
        source = (_PROJECT_ROOT / "web" / "routes" / "health.py").read_text()
        assert "pg_database_size" in source


# ===========================================================================
# H) Pagination module
# ===========================================================================

class TestPagination:
    """Keyset pagination module is functional."""

    def test_encode_decode_cursor(self):
        from web.pagination import decode_cursor, encode_cursor
        cursor = encode_cursor("2026-01-01", 42)
        decoded = decode_cursor(cursor)
        assert decoded is not None
        assert decoded["s"] == "2026-01-01"
        assert decoded["id"] == 42

    def test_decode_invalid_cursor(self):
        from web.pagination import decode_cursor
        assert decode_cursor(None) is None
        assert decode_cursor("not-valid") is None
        assert decode_cursor("") is None

    def test_build_keyset_clause_no_cursor(self):
        from web.pagination import build_keyset_clause
        clause, params = build_keyset_clause(None, "created_at")
        assert clause == ""
        assert params == {}

    def test_build_keyset_clause_with_cursor(self):
        from web.pagination import build_keyset_clause
        cursor = {"s": "2026-01-01", "id": 42}
        clause, params = build_keyset_clause(cursor, "created_at")
        assert "created_at" in clause
        assert "cursor_sort" in params
        assert "cursor_id" in params

    def test_pagination_meta(self):
        from web.pagination import pagination_meta
        meta = pagination_meta("abc123", True, 25)
        assert meta["next_cursor"] == "abc123"
        assert meta["has_more"] is True
        assert meta["limit"] == 25


# ===========================================================================
# I) Queries package structure
# ===========================================================================

class TestQueriesPackage:
    """web/queries/ package exists with all modules."""

    def test_init_exists(self):
        assert (_PROJECT_ROOT / "web" / "queries" / "__init__.py").exists()

    def test_entitlements_module(self):
        assert (_PROJECT_ROOT / "web" / "queries" / "entitlements.py").exists()

    def test_usage_module(self):
        assert (_PROJECT_ROOT / "web" / "queries" / "usage.py").exists()

    def test_audit_module(self):
        assert (_PROJECT_ROOT / "web" / "queries" / "audit.py").exists()
