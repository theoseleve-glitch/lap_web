"""Tests for FIX #5 (HIGH): entitlement + quota + rate-limit gating on the
track-surface analysis and per-corner OCP solver endpoints.

Background: both endpoint groups let ANY authenticated account (including a
locked/lapsed one) trigger expensive solver compute for free, never charged
a customer's quota, and (for track-surface) had no rate limiter at all. A
sibling fix also found that track_surface_analysis.py's ``_get_conn()``
imported a non-existent ``web.db.get_conn``, so its shared compute-budget
check was silently swallowed by a broad ``except Exception`` and never
actually ran in production.

Covers:
  - _FEATURE_GATES / _QUOTA_GATES entries for POST .../track-surface/
    sessions/<id>/run and POST .../sessions/<id>/ocp-corner (middleware
    level, mirroring the existing TestEnduranceRaceBridgeGate pattern in
    test_entitlement_middleware.py).
  - force_rerun on the track-surface /run route requires an active
    entitlement even when the base route is otherwise reachable.
  - @rate_limit(tier="analyze") is now applied to the track-surface /run
    route (it previously had none).
  - The per-corner OCP solver's hard caps: corner_ids count per request,
    and total corners x laps solves.
  - The web.db.get_conn -> get_db_connection import fix in
    track_surface_analysis.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask, g

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ══════════════════════════════════════════════════════════════════
# Middleware-level feature + quota gate tests
# ══════════════════════════════════════════════════════════════════

@pytest.fixture
def mw_app():
    """Flask app configured for PG + auth mode, mirroring
    test_entitlement_middleware.py's fixture, with the two newly-gated
    routes (plus an unrelated sibling route) registered as dummy endpoints.
    """
    app = Flask(__name__)
    app.config["USE_PG"] = True
    app.config["AUTH_REQUIRED"] = True
    app.config["TESTING"] = True

    @app.route("/api/v1/track-surface/sessions/<int:sid>/run", methods=["POST"])
    def ts_run(sid):
        return {"ok": True}, 202

    @app.route("/api/v1/track-surface/sessions/<int:sid>/summary", methods=["GET"])
    def ts_summary(sid):
        return {"ok": True}

    @app.route("/api/v1/sessions/<int:sid>/ocp-corner", methods=["POST"])
    def ocp_corner(sid):
        return {"ok": True}

    @app.route("/api/v1/sessions/<int:sid>/stints/assign", methods=["POST"])
    def stints_assign(sid):
        return {"ok": True}

    from web.middleware.entitlements import (
        entitlement_middleware,
        record_successful_usage,
    )
    app.before_request(entitlement_middleware)
    app.after_request(record_successful_usage)
    return app


class TestTrackSurfaceFeatureGate:
    """POST .../track-surface/sessions/<id>/run must be feature-gated by
    race_strategy (no dedicated feature column exists for this app; it
    reuses the same gate as the Simulations endpoints)."""

    def test_locked_user_blocked(self, mw_app):
        with mw_app.test_request_context(
            "/api/v1/track-surface/sessions/42/run", method="POST"
        ):
            g.current_user_id = 1
            g.workspace_id = 1

            ctx = {"reason": "race_strategy requires racer",
                   "upgrade_tier": "racer",
                   "upgrade_url": "/billing?plan=RACER",
                   "current_tier": "locked"}
            with patch("auth.entitlements.authorize_feature", return_value=(False, ctx)):
                with patch("auth.entitlements._get_conn"):
                    from web.middleware.entitlements import entitlement_middleware
                    result = entitlement_middleware()
                    assert result is not None, \
                        "locked-tier user must be blocked from track-surface run"
                    resp, status = result
                    data = resp.get_json()
                    assert status == 403
                    assert data["error"]["code"] == "PLAN_REQUIRED"

    def test_racer_allowed(self, mw_app):
        with mw_app.test_request_context(
            "/api/v1/track-surface/sessions/42/run", method="POST"
        ):
            g.current_user_id = 1
            g.workspace_id = 1
            ctx = {"remaining": 4, "limit": 5, "used": 1, "resets_at": "2026-08-01"}
            with patch("auth.entitlements.authorize_feature",
                       return_value=(True, {"current_tier": "racer"})):
                with patch("auth.entitlements.check_and_record_quota",
                           return_value=(True, ctx)):
                    with patch("auth.entitlements._get_conn"):
                        from web.middleware.entitlements import entitlement_middleware
                        assert entitlement_middleware() is None

    def test_get_routes_not_gated_by_run_suffix(self, mw_app):
        """GET .../track-surface/sessions/42/summary must not trigger the
        POST-only /run feature gate."""
        with mw_app.test_request_context(
            "/api/v1/track-surface/sessions/42/summary", method="GET"
        ):
            g.current_user_id = 1
            g.workspace_id = 1
            with patch("auth.entitlements.authorize_feature") as mock_auth:
                with patch("auth.entitlements._get_conn"):
                    from web.middleware.entitlements import entitlement_middleware
                    entitlement_middleware()
                    for call_args in mock_auth.call_args_list:
                        feature = call_args[0][2] if len(call_args[0]) > 2 else None
                        assert feature != "race_strategy"


class TestOcpCornerFeatureGate:
    """POST .../sessions/<id>/ocp-corner must be feature-gated by
    race_strategy (same reasoning as track-surface above)."""

    def test_locked_user_blocked(self, mw_app):
        with mw_app.test_request_context(
            "/api/v1/sessions/42/ocp-corner", method="POST"
        ):
            g.current_user_id = 1
            g.workspace_id = 1

            ctx = {"reason": "race_strategy requires racer",
                   "upgrade_tier": "racer",
                   "upgrade_url": "/billing?plan=RACER",
                   "current_tier": "locked"}
            with patch("auth.entitlements.authorize_feature", return_value=(False, ctx)):
                with patch("auth.entitlements._get_conn"):
                    from web.middleware.entitlements import entitlement_middleware
                    result = entitlement_middleware()
                    assert result is not None
                    resp, status = result
                    data = resp.get_json()
                    assert status == 403
                    assert data["error"]["code"] == "PLAN_REQUIRED"

    def test_racer_allowed(self, mw_app):
        with mw_app.test_request_context(
            "/api/v1/sessions/42/ocp-corner", method="POST"
        ):
            g.current_user_id = 1
            g.workspace_id = 1
            ctx = {"remaining": 4, "limit": 5, "used": 1, "resets_at": "2026-08-01"}
            with patch("auth.entitlements.authorize_feature",
                       return_value=(True, {"current_tier": "racer"})):
                with patch("auth.entitlements.check_and_record_quota",
                           return_value=(True, ctx)):
                    with patch("auth.entitlements._get_conn"):
                        from web.middleware.entitlements import entitlement_middleware
                        assert entitlement_middleware() is None

    def test_other_sessions_posts_not_gated_by_ocp_corner(self, mw_app):
        """POST .../sessions/42/stints/assign must NOT trigger the new
        /ocp-corner suffix gate (suffix matching keeps it scoped)."""
        with mw_app.test_request_context(
            "/api/v1/sessions/42/stints/assign", method="POST"
        ):
            g.current_user_id = 1
            g.workspace_id = 1
            with patch("auth.entitlements.authorize_feature") as mock_auth:
                with patch("auth.entitlements._get_conn"):
                    from web.middleware.entitlements import entitlement_middleware
                    entitlement_middleware()
                    for call_args in mock_auth.call_args_list:
                        feature = call_args[0][2] if len(call_args[0]) > 2 else None
                        assert feature != "race_strategy"


class TestTrackSurfaceQuotaGate:
    """POST .../track-surface/sessions/<id>/run must be quota-gated by the
    shared 'analyses' meter (no distinct solver_compute meter exists in
    auth.entitlements._METER_TO_QUOTA)."""

    def test_quota_exceeded_blocks(self, mw_app):
        with mw_app.test_request_context(
            "/api/v1/track-surface/sessions/42/run", method="POST"
        ):
            g.current_user_id = 1
            g.workspace_id = 1
            ctx = {"remaining": 0, "limit": 1, "used": 1, "resets_at": "2026-08-01"}
            with patch("auth.entitlements.authorize_feature", return_value=(True, {})):
                with patch("auth.entitlements.check_and_record_quota",
                           return_value=(False, ctx)):
                    with patch("auth.entitlements._get_conn"):
                        from web.middleware.entitlements import entitlement_middleware
                        result = entitlement_middleware()
                        assert result is not None
                        resp, status = result
                        data = resp.get_json()
                        assert status == 429
                        assert data["error"]["code"] == "QUOTA_EXCEEDED"

    def test_entitled_user_consumes_analyses_meter(self, mw_app):
        with mw_app.test_request_context(
            "/api/v1/track-surface/sessions/42/run", method="POST"
        ):
            g.current_user_id = 1
            g.workspace_id = 1
            ctx = {"remaining": 4, "limit": 5, "used": 1, "resets_at": "2026-08-01"}
            with patch("auth.entitlements.authorize_feature", return_value=(True, {})):
                with patch("auth.entitlements.check_and_record_quota",
                           return_value=(True, ctx)) as mock_quota:
                    with patch("auth.entitlements._get_conn") as mock_conn:
                        mock_conn.return_value = MagicMock()
                        from web.middleware.entitlements import entitlement_middleware
                        result = entitlement_middleware()
                        assert result is None
                        mock_quota.assert_called_once_with(
                            mock_conn.return_value, 1, 1, "analyses", 1,
                        )


class TestOcpCornerQuotaGate:
    """POST .../sessions/<id>/ocp-corner must be quota-gated by the same
    shared 'analyses' meter."""

    def test_quota_exceeded_blocks(self, mw_app):
        with mw_app.test_request_context(
            "/api/v1/sessions/42/ocp-corner", method="POST"
        ):
            g.current_user_id = 1
            g.workspace_id = 1
            ctx = {"remaining": 0, "limit": 1, "used": 1, "resets_at": "2026-08-01"}
            with patch("auth.entitlements.authorize_feature", return_value=(True, {})):
                with patch("auth.entitlements.check_and_record_quota",
                           return_value=(False, ctx)):
                    with patch("auth.entitlements._get_conn"):
                        from web.middleware.entitlements import entitlement_middleware
                        result = entitlement_middleware()
                        assert result is not None
                        resp, status = result
                        data = resp.get_json()
                        assert status == 429
                        assert data["error"]["code"] == "QUOTA_EXCEEDED"

    def test_entitled_user_consumes_analyses_meter(self, mw_app):
        with mw_app.test_request_context(
            "/api/v1/sessions/42/ocp-corner", method="POST"
        ):
            g.current_user_id = 1
            g.workspace_id = 1
            ctx = {"remaining": 4, "limit": 5, "used": 1, "resets_at": "2026-08-01"}
            with patch("auth.entitlements.authorize_feature", return_value=(True, {})):
                with patch("auth.entitlements.check_and_record_quota",
                           return_value=(True, ctx)) as mock_quota:
                    with patch("auth.entitlements._get_conn") as mock_conn:
                        mock_conn.return_value = MagicMock()
                        from web.middleware.entitlements import entitlement_middleware
                        result = entitlement_middleware()
                        assert result is None
                        mock_quota.assert_called_once_with(
                            mock_conn.return_value, 1, 1, "analyses", 1,
                        )


# ══════════════════════════════════════════════════════════════════
# Route-level tests: track-surface /run (force_rerun gate, rate limit,
# conn-import fix)
# ══════════════════════════════════════════════════════════════════

@pytest.fixture
def ts_app(tmp_path):
    """Minimal Flask app with the track-surface blueprint mounted, mirroring
    tests/test_track_surface_app/test_routes.py's fixture but with
    USE_PG/AUTH_REQUIRED turned on so the new force_rerun gate is active."""
    import sqlite3

    app = Flask(__name__)
    app.config["RESULTS_DIR"] = str(tmp_path)
    app.config["TESTING"] = True
    app.config["USE_PG"] = True
    app.config["AUTH_REQUIRED"] = True

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE analysis_runs (
            run_id TEXT PRIMARY KEY,
            session_id INTEGER NOT NULL,
            workspace_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            support_tier TEXT, support_reason TEXT, confidence_level TEXT,
            fallback_depth_distribution TEXT, validated_vehicle_profile TEXT,
            validated_track_profile TEXT, planner_mode_availability TEXT,
            warnings TEXT NOT NULL DEFAULT '[]',
            artifacts_index TEXT NOT NULL DEFAULT '{}',
            release_decision TEXT, pipeline_summary TEXT,
            error_code TEXT, error_message TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            completed_at TEXT
        )
        """
    )
    conn.commit()

    @app.before_request
    def fake_tenant():
        g.workspace_id = 1
        g.current_user_id = 1
        g.plan_tier = "locked"
        g.request_id = "test-req-id"

    from web.routes.track_surface_analysis import bp as ts_bp, inject_conn_factory
    inject_conn_factory(lambda: conn)
    app.register_blueprint(ts_bp)

    yield app
    conn.close()


@pytest.fixture
def ts_client(ts_app):
    return ts_app.test_client()


class TestForceRerunGate:
    """force_rerun bypasses the in-flight conflict check (see
    AnalysisOrchestrator.enqueue) — a locked/lapsed account must not be able
    to force expensive recompute."""

    def test_force_rerun_denied_without_entitlement(self, ts_app, ts_client):
        ctx = {"reason": "race_strategy requires racer", "upgrade_tier": "racer",
               "upgrade_url": "/billing?plan=RACER", "current_tier": "locked"}
        with patch("web.routes.track_surface_analysis.dispatch_celery_task"), \
             patch("auth.entitlements.authorize_feature", return_value=(False, ctx)):
            resp = ts_client.post(
                "/api/v1/track-surface/sessions/42/run",
                json={"force_rerun": True},
            )
        assert resp.status_code == 403
        body = resp.get_json()
        assert body["ok"] is False
        assert body["error"]["reason_code"] == "FEATURE_LOCKED"

    def test_force_rerun_allowed_with_entitlement(self, ts_app, ts_client):
        with patch("web.routes.track_surface_analysis.dispatch_celery_task"), \
             patch("auth.entitlements.authorize_feature",
                   return_value=(True, {"current_tier": "racer"})):
            resp = ts_client.post(
                "/api/v1/track-surface/sessions/42/run",
                json={"force_rerun": True},
            )
        assert resp.status_code == 202

    def test_non_force_rerun_skips_entitlement_check(self, ts_app, ts_client):
        """A plain (non-force) run must not invoke the force_rerun
        entitlement check at all."""
        with patch("web.routes.track_surface_analysis.dispatch_celery_task"), \
             patch("auth.entitlements.authorize_feature") as mock_auth:
            resp = ts_client.post(
                "/api/v1/track-surface/sessions/42/run", json={},
            )
        assert resp.status_code == 202
        mock_auth.assert_not_called()


class TestRateLimitApplied:
    """track_surface_analysis.py previously had no rate limiter at all."""

    def test_run_route_is_rate_limited(self, ts_app, ts_client):
        mock_redis = MagicMock()
        mock_redis.eval.return_value = 999  # far over any tier's limit
        with patch("web.rate_limit.get_redis", return_value=mock_redis), \
             patch("web.routes.track_surface_analysis.dispatch_celery_task"):
            resp = ts_client.post(
                "/api/v1/track-surface/sessions/42/run", json={},
            )
        assert resp.status_code == 429
        body = resp.get_json()
        assert body["error"]["code"] == "RATE_LIMITED"

    def test_run_route_allows_under_limit(self, ts_app, ts_client):
        mock_redis = MagicMock()
        mock_redis.eval.return_value = 1  # well under any tier's limit
        with patch("web.rate_limit.get_redis", return_value=mock_redis), \
             patch("web.routes.track_surface_analysis.dispatch_celery_task"):
            resp = ts_client.post(
                "/api/v1/track-surface/sessions/42/run", json={},
            )
        assert resp.status_code == 202


class TestTrackSurfaceConnImportFix:
    """Regression test for the fail-open bug: _get_conn() previously
    imported a non-existent `web.db.get_conn`, silently swallowed by the
    broad `except Exception` around the shared compute-budget check in
    run_analysis(), so that check never actually ran in production."""

    def test_get_conn_resolves_via_get_db_connection(self):
        import web.routes.track_surface_analysis as tsa
        original_factory = tsa._CONN_FACTORY
        tsa.inject_conn_factory(None)  # force the real (non-test) fallback branch
        try:
            sentinel = object()
            with patch("web.db.get_db_connection", return_value=sentinel) as mock_get:
                result = tsa._get_conn()
            assert result is sentinel
            mock_get.assert_called_once()
        finally:
            tsa.inject_conn_factory(original_factory)

    def test_budget_check_runs_end_to_end_without_conn_factory_override(
        self, ts_app, ts_client
    ):
        """Without the test-only conn-factory override, the shared
        compute-budget check must still execute (and correctly deny) —
        proving the conn import no longer raises ImportError under the
        hood (previously swallowed silently, so the check was a no-op)."""
        import web.routes.track_surface_analysis as tsa
        original_factory = tsa._CONN_FACTORY
        tsa.inject_conn_factory(None)
        try:
            over = (False, {"running_jobs": 5, "max_jobs": 1,
                            "max_duration_minutes": 10, "plan_tier": "locked"})
            with patch("web.db.get_db_connection", return_value=MagicMock()), \
                 patch("web.compute_budget.check_shared_compute_budget",
                       return_value=over) as mock_budget, \
                 patch("web.routes.track_surface_analysis.dispatch_celery_task"):
                resp = ts_client.post(
                    "/api/v1/track-surface/sessions/42/run", json={},
                )
            assert resp.status_code == 429
            mock_budget.assert_called_once()
        finally:
            tsa.inject_conn_factory(original_factory)


# ══════════════════════════════════════════════════════════════════
# Route-level tests: per-corner OCP solver caps
# ══════════════════════════════════════════════════════════════════

@pytest.fixture
def data_v2_app():
    app = Flask(__name__)
    app.config["TESTING"] = True

    @app.before_request
    def fake_tenant():
        g.workspace_id = 1
        g.current_user_id = 1
        g.request_id = "test-req-id"

    from web.routes.data_v2 import bp as data_v2_bp
    app.register_blueprint(data_v2_bp)
    return app


@pytest.fixture
def data_v2_client(data_v2_app):
    return data_v2_app.test_client()


class TestOcpCornerIdsCap:
    """A request with an unbounded corner_ids list must be rejected before
    any DB or solver work happens."""

    def test_over_cap_corner_ids_rejected(self, data_v2_client):
        from web.routes.data_v2 import MAX_OCP_CORNER_IDS_PER_REQUEST
        corner_ids = list(range(MAX_OCP_CORNER_IDS_PER_REQUEST + 1))
        resp = data_v2_client.post(
            "/api/v1/sessions/42/ocp-corner",
            json={"corner_ids": corner_ids},
        )
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["ok"] is False
        assert body["error"]["code"] == "VALIDATION_ERROR"

    def test_at_cap_corner_ids_passes_cap_check(self, data_v2_client):
        """Exactly at the cap must pass the cap check itself (a 404 on a
        nonexistent session proves we got past the cap to the DB lookup,
        not blocked by it)."""
        from web.routes.data_v2 import MAX_OCP_CORNER_IDS_PER_REQUEST
        corner_ids = list(range(MAX_OCP_CORNER_IDS_PER_REQUEST))
        with patch("web.routes.data_v2.get_db_connection", return_value=MagicMock()), \
             patch("web.models.get_session_by_id", return_value=None):
            resp = data_v2_client.post(
                "/api/v1/sessions/999999/ocp-corner",
                json={"corner_ids": corner_ids},
            )
        assert resp.status_code == 404


class TestOcpCornerTotalSolvesCap:
    """Total solver work is corners_matched x laps_in_session — an
    endurance session with hundreds of laps must not be able to multiply
    that out into thousands of synchronous solves."""

    def test_total_solves_over_cap_raises_value_error(self):
        import numpy as np
        import pandas as pd

        from web.routes.data_v2 import (
            MAX_OCP_TOTAL_SOLVES_PER_REQUEST,
            _run_corner_ocp,
        )

        n_corners = 10
        n_laps = 100  # 10 x 100 = 1000 > 500 default cap
        assert n_corners * n_laps > MAX_OCP_TOTAL_SOLVES_PER_REQUEST

        corner_ids = list(range(n_corners))
        analysis_json = {
            "corners": [
                {"corner_id": cid, "s_start": 0.0, "s_end": 50.0}
                for cid in corner_ids
            ]
        }
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = {
            "analysis_json": json.dumps(analysis_json)
        }

        ref_line = {
            "distances": list(np.linspace(0, 500, 50)),
            "latitudes": list(np.linspace(45.0, 45.01, 50)),
            "longitudes": list(np.linspace(6.0, 6.01, 50)),
        }
        curvature_df = pd.DataFrame({
            "distance_m": np.linspace(0, 500, 50),
            "curvature_1pm": np.zeros(50),
        })
        laps = [{"lap_number": i, "is_best": i == 0} for i in range(n_laps)]

        with patch("web.repos.theoretical_repo.get_reference_line", return_value=ref_line), \
             patch("tasks.ocp_tasks._curvature_from_reference_line", return_value=curvature_df), \
             patch("web.repos.lap_repo.get_laps_for_session", return_value=laps):
            with pytest.raises(ValueError, match="exceeds max"):
                _run_corner_ocp(conn, "42", corner_ids)

    def test_route_returns_400_when_total_solves_capped(self, data_v2_client):
        """The route must translate the ValueError raised by
        _run_corner_ocp into a 400, not a 500."""
        with patch("web.routes.data_v2.get_db_connection", return_value=MagicMock()), \
             patch("web.models.get_session_by_id", return_value={"session_id": "42"}), \
             patch("web.routes.data_v2._run_corner_ocp",
                   side_effect=ValueError("OCP solve request too large: exceeds max")):
            resp = data_v2_client.post(
                "/api/v1/sessions/42/ocp-corner",
                json={"corner_ids": [1, 2, 3]},
            )
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["ok"] is False
        assert body["error"]["code"] == "VALIDATION_ERROR"
