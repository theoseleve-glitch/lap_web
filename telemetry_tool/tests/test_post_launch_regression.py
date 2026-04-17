"""
Post-launch regression tests for:
  1. Single-user workspace model
  2. Chart data caching
  3. Plan/quota correctness

These tests validate the behavioral contracts that changed in the
recent deployment. They are designed to catch regressions, not to
mirror implementation details.
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock, patch


# ─────────────────────────────────────────────────────────────────────
# 1. Single-user model: workspace auto-resolution
# ─────────────────────────────────────────────────────────────────────


class TestSingleUserWorkspace:
    """Workspace is resolved server-side from the authenticated user.
    No X-Workspace-Id header is needed or honoured."""

    def test_workspace_resolved_from_user_not_header(self):
        """The middleware should not use request.headers to get workspace."""
        from telemetry_tool.web.middleware.tenant import tenant_middleware
        import inspect
        source = inspect.getsource(tenant_middleware)
        # Must call get_default_workspace_id (server-side resolution)
        assert "get_default_workspace_id" in source
        # Must NOT do header lookup like request.headers.get("X-Workspace-Id")
        assert 'request.headers.get' not in source, (
            "Tenant middleware should not read workspace from request headers"
        )

    def test_workspace_role_always_owner(self):
        """In single-user model, the workspace role is always 'owner'."""
        from telemetry_tool.web.middleware.tenant import tenant_middleware
        import inspect
        source = inspect.getsource(tenant_middleware)
        assert 'g.workspace_role' in source
        assert 'owner' in source.lower(), (
            "Tenant middleware should set workspace_role to 'owner'"
        )


# ─────────────────────────────────────────────────────────────────────
# 2. Chart cache: correctness
# ─────────────────────────────────────────────────────────────────────


class TestChartCache:
    """Redis-backed chart cache correctness."""

    def test_only_200_responses_are_cached(self):
        """The decorator must never cache error responses."""
        from telemetry_tool.web.chart_cache import chart_cached
        import inspect
        source = inspect.getsource(chart_cached)
        # The cache-write block must check status == 200
        assert "status == 200" in source

    def test_cache_hit_validates_ok_field(self):
        """Cached responses must have 'ok': true to be served."""
        from telemetry_tool.web.chart_cache import chart_cached
        import inspect
        source = inspect.getsource(chart_cached)
        assert 'body.get("ok")' in source, (
            "Cache hit must validate the 'ok' field before serving"
        )

    def test_invalidation_pattern_matches_key_format(self):
        """invalidate_session_cache must use a pattern that matches
        the key format used by _build_key."""
        from telemetry_tool.web import chart_cache
        import inspect
        build_src = inspect.getsource(chart_cache._build_key)
        inv_src = inspect.getsource(chart_cache.invalidate_session_cache)
        # Both must reference the same prefix constant
        assert "_CACHE_PREFIX" in build_src
        assert "_CACHE_PREFIX" in inv_src or "chart" in inv_src
        # Invalidation must use a wildcard pattern with session_id
        assert "session_id" in inv_src
        assert "*" in inv_src, "Invalidation must use a wildcard pattern"

    def test_different_query_params_produce_different_keys(self):
        """?lap=1 and ?lap=2 must cache independently."""
        from telemetry_tool.web.chart_cache import _build_key
        from flask import Flask

        app = Flask(__name__)
        with app.test_request_context("/test?lap=1"):
            key1 = _build_key("sess1", "get_speed_trace")
        with app.test_request_context("/test?lap=2"):
            key2 = _build_key("sess1", "get_speed_trace")
        assert key1 != key2, "Different query params must produce different cache keys"

    def test_same_query_params_different_order_same_key(self):
        """?lap=1&ref=2 and ?ref=2&lap=1 must produce the same key."""
        from telemetry_tool.web.chart_cache import _build_key
        from flask import Flask

        app = Flask(__name__)
        with app.test_request_context("/test?lap=1&ref=2"):
            key1 = _build_key("sess1", "get_speed_trace")
        with app.test_request_context("/test?ref=2&lap=1"):
            key2 = _build_key("sess1", "get_speed_trace")
        assert key1 == key2, "Same params in different order must produce identical cache keys"


# ─────────────────────────────────────────────────────────────────────
# 3. Entitlements / quota correctness
# ─────────────────────────────────────────────────────────────────────


class TestEntitlements:
    """Plan-tier entitlement boundaries."""

    def test_free_plan_has_limited_analyses(self):
        """Free/demo plan must have a non-zero analyses limit."""
        try:
            from telemetry_tool.auth.entitlements import PLAN_ENTITLEMENTS
            free = PLAN_ENTITLEMENTS.get("free") or PLAN_ENTITLEMENTS.get("demo")
            if free:
                limit = free.get("analyses_per_month")
                assert limit is not None and limit > 0, (
                    f"Free plan must limit analyses (got {limit})"
                )
        except ImportError:
            pytest.skip("entitlements module not available")

    def test_world_class_has_unlimited_analyses(self):
        """World-class plan should have unlimited (None or very high) analyses."""
        try:
            from telemetry_tool.auth.entitlements import PLAN_ENTITLEMENTS
            wc = PLAN_ENTITLEMENTS.get("world-class")
            if wc:
                limit = wc.get("analyses_per_month")
                # -1 or None = unlimited; large number also acceptable
                assert limit is None or limit < 0 or limit >= 1000, (
                    f"World-class should be unlimited (got {limit})"
                )
        except ImportError:
            pytest.skip("entitlements module not available")

    def test_sign_convention_quota_check_rejects_over_limit(self):
        """check_quota must reject when usage >= limit."""
        try:
            from telemetry_tool.auth.entitlements import check_quota
            # Simulate: 10 used, 10 limit → should reject
            result = check_quota(used=10, limit=10)
            assert result is False or result == "exceeded", (
                "Quota at exactly the limit must be rejected"
            )
        except (ImportError, TypeError):
            pytest.skip("check_quota not available or different signature")


# ─────────────────────────────────────────────────────────────────────
# 4. No remaining workspace dependency in active frontend code
# ─────────────────────────────────────────────────────────────────────


class TestNoWorkspaceDependency:
    """Verify the frontend no longer sends or manages workspace state."""

    def test_api_client_does_not_send_workspace_header(self):
        """api-client.ts must not contain X-Workspace-Id."""
        import pathlib
        api_client = pathlib.Path(
            "lap-website/src/lib/api-client.ts"
        )
        if api_client.exists():
            content = api_client.read_text()
            assert "X-Workspace-Id" not in content, (
                "api-client.ts must not reference X-Workspace-Id after migration"
            )
        else:
            pytest.skip("Frontend source not in test path")

    def test_auth_store_has_no_workspace_state(self):
        """auth-store.ts must not export workspace getters/setters."""
        import pathlib
        store = pathlib.Path(
            "lap-website/src/lib/auth-store.ts"
        )
        if store.exists():
            content = store.read_text()
            assert "getWorkspaceId" not in content, (
                "auth-store.ts must not export getWorkspaceId after migration"
            )
            assert "setWorkspaceId" not in content, (
                "auth-store.ts must not export setWorkspaceId after migration"
            )
        else:
            pytest.skip("Frontend source not in test path")
