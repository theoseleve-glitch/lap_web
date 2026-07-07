"""Tests for the /api/ingest/* cross-tenant IDOR fix.

Covers the three defense-in-depth layers added on top of the pre-existing
RLS-policy fix (migration 083_ingest_policy_missing_ok):

1. auth/tenant middleware now cover ``/api/ingest/`` (previously only
   ``/api/v1/`` was enforced, so these routes ran fully unauthenticated).
2. ``JobStore.get``/``list_recent`` carry an explicit ``workspace_id``
   predicate (mirrors ``tasks.job_registry``), so even a middleware
   regression can't leak another tenant's job.
3. ``/api/ingest`` is blocked outright in production by legacy_guard
   (the blueprint is superseded by the workspace-scoped ``/api/v1/jobs``).
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Layer 1: auth + tenant middleware now cover /api/ingest/
# ---------------------------------------------------------------------------

class TestAuthTenantPrefixCoverage:
    def test_auth_enforced_prefixes_include_api_ingest(self):
        from web.middleware.auth import _AUTH_ENFORCED_PREFIXES
        assert "/api/ingest/" in _AUTH_ENFORCED_PREFIXES

    def test_tenant_enforced_prefixes_include_api_ingest(self):
        from web.middleware.tenant import _TENANT_ENFORCED_PREFIXES
        assert "/api/ingest/" in _TENANT_ENFORCED_PREFIXES

    def test_unauthenticated_ingest_jobs_call_rejected(self):
        """GET /api/ingest/jobs with no token returns 401 (was previously
        reachable with no auth at all -- see web/middleware/auth.py)."""
        from flask import Flask

        from web.api_utils import init_request_id
        from web.middleware.auth import auth_middleware
        from web.routes.ingest import bp as ingest_bp

        app = Flask(__name__)
        app.config["TESTING"] = True
        app.config["AUTH_REQUIRED"] = True
        app.config["JWT_SECRET"] = "test-secret"
        init_request_id(app)
        app.before_request(auth_middleware)
        app.register_blueprint(ingest_bp)

        client = app.test_client()
        resp = client.get("/api/ingest/jobs")
        assert resp.status_code == 401
        assert resp.get_json()["ok"] is False

    def test_unauthenticated_ingest_status_call_rejected(self):
        """Same as above for the per-job status polling endpoint."""
        from flask import Flask

        from web.api_utils import init_request_id
        from web.middleware.auth import auth_middleware
        from web.routes.ingest import bp as ingest_bp

        app = Flask(__name__)
        app.config["TESTING"] = True
        app.config["AUTH_REQUIRED"] = True
        app.config["JWT_SECRET"] = "test-secret"
        init_request_id(app)
        app.before_request(auth_middleware)
        app.register_blueprint(ingest_bp)

        client = app.test_client()
        resp = client.get("/api/ingest/some-job-id/status")
        assert resp.status_code == 401

    def test_authenticated_call_reaches_the_view(self):
        """A valid JWT clears the middleware -- the view itself runs (and
        404s because the flag-gated job doesn't exist), proving the 401
        above is specifically about the missing token, not a routing bug."""
        from flask import Flask

        from auth.service import create_access_token
        from web.api_utils import init_request_id
        from web.middleware.auth import auth_middleware
        from web.routes.ingest import bp as ingest_bp

        app = Flask(__name__)
        app.config["TESTING"] = True
        app.config["AUTH_REQUIRED"] = True
        app.config["JWT_SECRET"] = "test-secret"
        init_request_id(app)
        app.before_request(auth_middleware)
        app.register_blueprint(ingest_bp)

        token = create_access_token(user_id=1, secret="test-secret")
        client = app.test_client()
        resp = client.get(
            "/api/ingest/jobs", headers={"Authorization": f"Bearer {token}"}
        )
        # No DB configured in this minimal app -> JobStore falls back to an
        # empty list rather than erroring; the key assertion is "not 401".
        assert resp.status_code != 401


# ---------------------------------------------------------------------------
# Layer 2: JobStore workspace_id predicate
# ---------------------------------------------------------------------------

class TestJobStoreWorkspaceScoping:
    def _make_store(self):
        from web.routes.ingest import JobStore
        return JobStore()

    def test_cache_hit_denies_other_workspace(self):
        """A job registered for workspace 1 must not be readable by workspace 2,
        even straight out of the in-memory cache (no DB round-trip)."""
        store = self._make_store()
        store.register("job-1", "/data/a.csv", 100, workspace_id=1)

        assert store.get("job-1", workspace_id=1) is not None
        assert store.get("job-1", workspace_id=2) is None

    def test_cache_hit_allows_same_workspace(self):
        store = self._make_store()
        store.register("job-1", "/data/a.csv", 100, workspace_id=7)
        job = store.get("job-1", workspace_id=7)
        assert job is not None
        assert job["job_id"] == "job-1"

    def test_no_workspace_id_preserves_legacy_desktop_behavior(self):
        """workspace_id=None (desktop/SQLite mode) is unscoped, matching the
        pre-fix behavior for the single-user local app."""
        store = self._make_store()
        store.register("job-1", "/data/a.csv", 100)
        assert store.get("job-1") is not None

    def test_list_recent_filters_cache_by_workspace(self):
        store = self._make_store()
        store.register("job-a", "/data/a.csv", 100, workspace_id=1)
        store.register("job-b", "/data/b.csv", 200, workspace_id=2)

        ws1_jobs = {j["job_id"] for j in store.list_recent(workspace_id=1)}
        ws2_jobs = {j["job_id"] for j in store.list_recent(workspace_id=2)}
        assert ws1_jobs == {"job-a"}
        assert ws2_jobs == {"job-b"}

    def test_get_sql_query_carries_workspace_predicate(self):
        """When the cache misses, the fallback SQL query must filter on
        workspace_id -- mirrors tasks.job_registry.get_job's predicate."""
        store = self._make_store()
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None
        store._get_conn = MagicMock(return_value=mock_conn)

        store.get("missing-job", workspace_id=42)

        mock_conn.execute.assert_called_once()
        sql, params = mock_conn.execute.call_args[0]
        assert "workspace_id" in sql
        assert 42 in params

    def test_list_recent_sql_query_carries_workspace_predicate(self):
        store = self._make_store()
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []
        store._get_conn = MagicMock(return_value=mock_conn)

        store.list_recent(workspace_id=42)

        mock_conn.execute.assert_called_once()
        sql, params = mock_conn.execute.call_args[0]
        assert "workspace_id" in sql
        assert 42 in params


# ---------------------------------------------------------------------------
# Layer 3: legacy_guard blocks /api/ingest outright in production
# ---------------------------------------------------------------------------

class TestLegacyGuardBlocksIngest:
    @pytest.fixture
    def app_with_guard(self):
        from web.config import Config
        cfg = Config()
        cfg.ENV = "development"
        cfg.USE_PG = False
        cfg.AUTH_REQUIRED = True
        cfg.JWT_SECRET = "a" * 64
        cfg.SECRET_KEY = "b" * 64
        from web.app import create_app
        app = create_app(cfg)
        from web.middleware.legacy_guard import init_legacy_guard
        init_legacy_guard(app)
        return app

    def test_blocks_ingest_jobs_route(self, app_with_guard):
        with app_with_guard.test_client() as client:
            resp = client.get("/api/ingest/jobs")
            assert resp.status_code == 404

    def test_blocks_ingest_status_route(self, app_with_guard):
        with app_with_guard.test_client() as client:
            resp = client.get("/api/ingest/some-job/status")
            assert resp.status_code == 404

    def test_api_ingest_prefix_registered(self):
        from web.middleware.legacy_guard import _LEGACY_PREFIXES
        assert "/api/ingest" in _LEGACY_PREFIXES
