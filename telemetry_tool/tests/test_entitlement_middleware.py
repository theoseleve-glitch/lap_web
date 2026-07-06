"""Tests for centralized entitlement middleware and usage recording.

Validates that:
- Feature gates block requests on plan-restricted routes
- Quota gates block requests when quota is exceeded
- Exempt paths are not gated
- Usage is recorded after successful mutations
- Middleware fails gracefully when PG/auth is not configured
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask, g

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


@pytest.fixture
def app():
    """Flask app configured for PG + auth mode."""
    app = Flask(__name__)
    app.config["USE_PG"] = True
    app.config["AUTH_REQUIRED"] = True
    app.config["TESTING"] = True

    # Register dummy routes that the middleware will gate
    @app.route("/compare/sessions", methods=["GET"])
    def compare_sessions():
        return {"ok": True}

    @app.route("/visualize/s1", methods=["GET"])
    def visualize_session():
        return {"ok": True}

    @app.route("/analyze/api/start", methods=["POST"])
    def analyze_start():
        return {"ok": True}, 202

    @app.route("/auth/login", methods=["POST"])
    def login():
        return {"ok": True}

    @app.route("/api/v1/me", methods=["GET"])
    def me():
        return {"ok": True}

    @app.route("/healthz", methods=["GET"])
    def healthz():
        return {"ok": True}

    @app.route("/api/v1/billing/webhook", methods=["POST"])
    def billing_webhook():
        return {"ok": True}

    # Wire the middleware
    from web.middleware.entitlements import (
        entitlement_middleware,
        record_successful_usage,
    )
    app.before_request(entitlement_middleware)
    app.after_request(record_successful_usage)

    return app


class TestFeatureGating:
    def test_comparison_blocked_for_demo(self, app):
        with app.test_request_context("/compare/sessions", method="GET"):
            g.current_user_id = 1
            g.workspace_id = 1
            g.plan_tier = "demo"

            ctx = {"reason": "comparison requires world-class",
                   "upgrade_tier": "world-class",
                   "upgrade_url": "/billing?plan=WORLD-CLASS",
                   "current_tier": "demo"}
            with patch("auth.entitlements.authorize_feature", return_value=(False, ctx)):
                with patch("auth.entitlements._get_conn"):
                    from web.middleware.entitlements import entitlement_middleware
                    result = entitlement_middleware()
                    assert result is not None  # Should return a response (blocked)
                    resp, status = result
                    data = resp.get_json()
                    assert status == 403
                    assert data["error"]["code"] == "PLAN_REQUIRED"

    def test_comparison_allowed_for_worldclass(self, app):
        with app.test_request_context("/compare/sessions", method="GET"):
            g.current_user_id = 1
            g.workspace_id = 1
            g.plan_tier = "world-class"

            with patch("auth.entitlements.authorize_feature", return_value=(True, {"current_tier": "world-class"})):
                with patch("auth.entitlements._get_conn"):
                    from web.middleware.entitlements import entitlement_middleware
                    result = entitlement_middleware()
                    assert result is None  # Should pass through

    def test_visualization_blocked_for_demo(self, app):
        with app.test_request_context("/visualize/s1", method="GET"):
            g.current_user_id = 1
            g.workspace_id = 1

            ctx = {"reason": "visualization requires racer",
                   "upgrade_tier": "racer",
                   "upgrade_url": "/billing?plan=RACER",
                   "current_tier": "demo"}
            with patch("auth.entitlements.authorize_feature", return_value=(False, ctx)):
                with patch("auth.entitlements._get_conn"):
                    from web.middleware.entitlements import entitlement_middleware
                    result = entitlement_middleware()
                    assert result is not None
                    resp, status = result
                    assert status == 403


class TestV1PathGateFixes:
    """Tests for v1 API path gate mismatches (Gap 1-3).

    The frontend calls v1-prefixed paths that the original gates didn't cover:
    - Gap 1: GET /api/v1/compare/sessions  (comparison feature)
    - Gap 2: GET /api/v1/sessions/{id}/visualize  (visualization feature)
    - Gap 3: POST /api/v1/files/upload  (upload quota)
    """

    # ── Gap 1: Comparison gate on /api/v1/compare/ ────────────────────

    def test_compare_sessions_v1_blocked_for_demo(self, app):
        """GET /api/v1/compare/sessions must be feature-gated by comparison."""
        with app.test_request_context("/api/v1/compare/sessions", method="GET"):
            g.current_user_id = 1
            g.workspace_id = 1

            ctx = {"reason": "comparison requires world-class",
                   "upgrade_tier": "world-class",
                   "upgrade_url": "/billing?plan=WORLD-CLASS",
                   "current_tier": "demo"}
            with patch("auth.entitlements.authorize_feature", return_value=(False, ctx)):
                with patch("auth.entitlements._get_conn"):
                    from web.middleware.entitlements import entitlement_middleware
                    result = entitlement_middleware()
                    assert result is not None, \
                        "GET /api/v1/compare/sessions should be blocked for demo users"
                    resp, status = result
                    data = resp.get_json()
                    assert status == 403
                    assert data["error"]["code"] == "PLAN_REQUIRED"

    def test_compare_drivers_v1_blocked_for_demo(self, app):
        """GET /api/v1/compare/drivers must be feature-gated by comparison."""
        with app.test_request_context("/api/v1/compare/drivers", method="GET"):
            g.current_user_id = 1
            g.workspace_id = 1

            ctx = {"reason": "comparison requires world-class",
                   "upgrade_tier": "world-class",
                   "upgrade_url": "/billing?plan=WORLD-CLASS",
                   "current_tier": "demo"}
            with patch("auth.entitlements.authorize_feature", return_value=(False, ctx)):
                with patch("auth.entitlements._get_conn"):
                    from web.middleware.entitlements import entitlement_middleware
                    result = entitlement_middleware()
                    assert result is not None, \
                        "GET /api/v1/compare/drivers should be blocked for demo users"
                    resp, status = result
                    data = resp.get_json()
                    assert status == 403
                    assert data["error"]["code"] == "PLAN_REQUIRED"

    def test_compare_v1_allowed_for_worldclass(self, app):
        """GET /api/v1/compare/sessions should pass for world-class users."""
        with app.test_request_context("/api/v1/compare/sessions", method="GET"):
            g.current_user_id = 1
            g.workspace_id = 1

            with patch("auth.entitlements.authorize_feature",
                       return_value=(True, {"current_tier": "world-class"})):
                with patch("auth.entitlements._get_conn"):
                    from web.middleware.entitlements import entitlement_middleware
                    result = entitlement_middleware()
                    assert result is None

    # ── Gap 2: Visualization gate on /api/v1/sessions/{id}/visualize ─

    def test_session_visualize_v1_blocked_for_demo(self, app):
        """GET /api/v1/sessions/42/visualize must be feature-gated by visualization."""
        with app.test_request_context("/api/v1/sessions/42/visualize", method="GET"):
            g.current_user_id = 1
            g.workspace_id = 1

            ctx = {"reason": "visualization requires racer",
                   "upgrade_tier": "racer",
                   "upgrade_url": "/billing?plan=RACER",
                   "current_tier": "demo"}
            with patch("auth.entitlements.authorize_feature", return_value=(False, ctx)):
                with patch("auth.entitlements._get_conn"):
                    from web.middleware.entitlements import entitlement_middleware
                    result = entitlement_middleware()
                    assert result is not None, \
                        "GET /api/v1/sessions/42/visualize should be blocked for demo users"
                    resp, status = result
                    data = resp.get_json()
                    assert status == 403
                    assert data["error"]["code"] == "PLAN_REQUIRED"

    def test_session_visualize_v1_allowed_for_racer(self, app):
        """GET /api/v1/sessions/42/visualize should pass for racer users."""
        with app.test_request_context("/api/v1/sessions/42/visualize", method="GET"):
            g.current_user_id = 1
            g.workspace_id = 1

            with patch("auth.entitlements.authorize_feature",
                       return_value=(True, {"current_tier": "racer"})):
                with patch("auth.entitlements._get_conn"):
                    from web.middleware.entitlements import entitlement_middleware
                    result = entitlement_middleware()
                    assert result is None

    def test_session_list_v1_not_gated_by_visualization(self, app):
        """GET /api/v1/sessions/ must NOT be caught by the visualization gate.

        The visualization gate uses suffix matching (/visualize) so that
        plain session list/detail endpoints remain ungated.
        """
        with app.test_request_context("/api/v1/sessions/", method="GET"):
            g.current_user_id = 1
            g.workspace_id = 1

            with patch("auth.entitlements.authorize_feature") as mock_auth:
                with patch("auth.entitlements._get_conn"):
                    from web.middleware.entitlements import entitlement_middleware
                    result = entitlement_middleware()
                    # authorize_feature should NOT be called for visualization
                    # (it might be called for other gates, but not visualization)
                    for call_args in mock_auth.call_args_list:
                        _, feature = call_args[0][1], call_args[0][2] if len(call_args[0]) > 2 else None
                        assert feature != "visualization", \
                            "GET /api/v1/sessions/ should NOT trigger visualization gate"

    def test_session_detail_v1_not_gated_by_visualization(self, app):
        """GET /api/v1/sessions/42 must NOT be caught by the visualization gate."""
        with app.test_request_context("/api/v1/sessions/42", method="GET"):
            g.current_user_id = 1
            g.workspace_id = 1

            with patch("auth.entitlements.authorize_feature") as mock_auth:
                with patch("auth.entitlements._get_conn"):
                    from web.middleware.entitlements import entitlement_middleware
                    result = entitlement_middleware()
                    for call_args in mock_auth.call_args_list:
                        _, feature = call_args[0][1], call_args[0][2] if len(call_args[0]) > 2 else None
                        assert feature != "visualization", \
                            "GET /api/v1/sessions/42 should NOT trigger visualization gate"

    # ── Gap 3: Upload quota on /api/v1/files/upload ──────────────────

    def test_files_upload_v1_quota_blocked(self, app):
        """POST /api/v1/files/upload must be quota-gated by uploads."""
        with app.test_request_context("/api/v1/files/upload", method="POST"):
            g.current_user_id = 1
            g.workspace_id = 1

            ctx = {"remaining": 0, "limit": 5, "used": 5, "resets_at": "2026-04-01"}
            with patch("auth.entitlements.check_and_record_quota", return_value=(False, ctx)):
                with patch("auth.entitlements._get_conn"):
                    from web.middleware.entitlements import entitlement_middleware
                    result = entitlement_middleware()
                    assert result is not None, \
                        "POST /api/v1/files/upload should be quota-gated"
                    resp, status = result
                    data = resp.get_json()
                    assert status == 429
                    assert data["error"]["code"] == "QUOTA_EXCEEDED"

    def test_files_upload_v1_quota_allowed(self, app):
        """POST /api/v1/files/upload should pass when under quota."""
        with app.test_request_context("/api/v1/files/upload", method="POST"):
            g.current_user_id = 1
            g.workspace_id = 1

            ctx = {"remaining": 4, "limit": 5, "used": 1, "resets_at": "2026-04-01"}
            with patch("auth.entitlements.check_and_record_quota", return_value=(True, ctx)):
                with patch("auth.entitlements._get_conn"):
                    from web.middleware.entitlements import entitlement_middleware
                    result = entitlement_middleware()
                    assert result is None


class TestExpandedFeatureGates:
    """Tests for newly added feature gates (race-strategy v1, exports, simulations)."""

    def test_race_strategy_v1_post_gated(self, app):
        """POST to /api/v1/race-strategy/123 should be feature-gated by race_strategy."""
        @app.route("/api/v1/race-strategy/123", methods=["POST"])
        def race_strategy_v1_post():
            return {"ok": True}

        with app.test_request_context("/api/v1/race-strategy/123", method="POST"):
            g.current_user_id = 1
            g.workspace_id = 1

            ctx = {"reason": "race_strategy requires racer",
                   "upgrade_tier": "racer",
                   "upgrade_url": "/billing?plan=RACER",
                   "current_tier": "demo"}
            with patch("auth.entitlements.authorize_feature", return_value=(False, ctx)):
                with patch("auth.entitlements._get_conn"):
                    from web.middleware.entitlements import entitlement_middleware
                    result = entitlement_middleware()
                    assert result is not None
                    resp, status = result
                    data = resp.get_json()
                    assert status == 403
                    assert data["error"]["code"] == "PLAN_REQUIRED"

    def test_race_strategy_v1_put_gated(self, app):
        """PUT to /api/v1/race-strategy/123 should be feature-gated."""
        @app.route("/api/v1/race-strategy/123", methods=["PUT"])
        def race_strategy_v1_put():
            return {"ok": True}

        with app.test_request_context("/api/v1/race-strategy/123", method="PUT"):
            g.current_user_id = 1
            g.workspace_id = 1

            ctx = {"reason": "race_strategy requires racer",
                   "upgrade_tier": "racer",
                   "upgrade_url": "/billing?plan=RACER",
                   "current_tier": "demo"}
            with patch("auth.entitlements.authorize_feature", return_value=(False, ctx)):
                with patch("auth.entitlements._get_conn"):
                    from web.middleware.entitlements import entitlement_middleware
                    result = entitlement_middleware()
                    assert result is not None
                    resp, status = result
                    data = resp.get_json()
                    assert status == 403
                    assert data["error"]["code"] == "PLAN_REQUIRED"

    def test_race_strategy_v1_delete_gated(self, app):
        """DELETE to /api/v1/race-strategy/123 should be feature-gated."""
        @app.route("/api/v1/race-strategy/123", methods=["DELETE"])
        def race_strategy_v1_delete():
            return {"ok": True}

        with app.test_request_context("/api/v1/race-strategy/123", method="DELETE"):
            g.current_user_id = 1
            g.workspace_id = 1

            ctx = {"reason": "race_strategy requires racer",
                   "upgrade_tier": "racer",
                   "upgrade_url": "/billing?plan=RACER",
                   "current_tier": "demo"}
            with patch("auth.entitlements.authorize_feature", return_value=(False, ctx)):
                with patch("auth.entitlements._get_conn"):
                    from web.middleware.entitlements import entitlement_middleware
                    result = entitlement_middleware()
                    assert result is not None
                    resp, status = result
                    data = resp.get_json()
                    assert status == 403
                    assert data["error"]["code"] == "PLAN_REQUIRED"

    def test_export_route_gated(self, app):
        """POST to /api/data/export/session/1 should be feature-gated by exports."""
        @app.route("/api/data/export/session/1", methods=["POST"])
        def export_session():
            return {"ok": True}

        with app.test_request_context("/api/data/export/session/1", method="POST"):
            g.current_user_id = 1
            g.workspace_id = 1

            ctx = {"reason": "exports requires racer",
                   "upgrade_tier": "racer",
                   "upgrade_url": "/billing?plan=RACER",
                   "current_tier": "demo"}
            with patch("auth.entitlements.authorize_feature", return_value=(False, ctx)):
                with patch("auth.entitlements._get_conn"):
                    from web.middleware.entitlements import entitlement_middleware
                    result = entitlement_middleware()
                    assert result is not None
                    resp, status = result
                    data = resp.get_json()
                    assert status == 403
                    assert data["error"]["code"] == "PLAN_REQUIRED"

    def test_simulation_route_gated(self, app):
        """POST to /api/data/simulate-race should be feature-gated by race_strategy."""
        @app.route("/api/data/simulate-race", methods=["POST"])
        def simulate_race():
            return {"ok": True}

        with app.test_request_context("/api/data/simulate-race", method="POST"):
            g.current_user_id = 1
            g.workspace_id = 1

            ctx = {"reason": "race_strategy requires racer",
                   "upgrade_tier": "racer",
                   "upgrade_url": "/billing?plan=RACER",
                   "current_tier": "demo"}
            with patch("auth.entitlements.authorize_feature", return_value=(False, ctx)):
                with patch("auth.entitlements._get_conn"):
                    from web.middleware.entitlements import entitlement_middleware
                    result = entitlement_middleware()
                    assert result is not None
                    resp, status = result
                    data = resp.get_json()
                    assert status == 403
                    assert data["error"]["code"] == "PLAN_REQUIRED"


class TestEnduranceRaceBridgeGate:
    """POST /api/v1/sessions/<id>/endurance-race must be feature-gated by
    race_strategy, matching the primary /api/v1/race-strategy/ create path.
    Uses the existing suffix-matching mechanism (4th tuple element) so only
    the /endurance-race sub-path is gated, not every /api/v1/sessions/ POST.
    """

    def test_endurance_race_post_blocked_for_locked_tier(self, app):
        """POST /api/v1/sessions/42/endurance-race must be feature-gated."""
        @app.route("/api/v1/sessions/42/endurance-race", methods=["POST"])
        def endurance_race_post():
            return {"ok": True}

        with app.test_request_context("/api/v1/sessions/42/endurance-race", method="POST"):
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
                        "POST /api/v1/sessions/42/endurance-race should be blocked for locked tier"
                    resp, status = result
                    data = resp.get_json()
                    assert status == 403
                    assert data["error"]["code"] == "PLAN_REQUIRED"

    def test_endurance_race_post_allowed_for_racer(self, app):
        """POST /api/v1/sessions/42/endurance-race should pass for racer+ tiers."""
        with app.test_request_context("/api/v1/sessions/42/endurance-race", method="POST"):
            g.current_user_id = 1
            g.workspace_id = 1

            with patch("auth.entitlements.authorize_feature",
                       return_value=(True, {"current_tier": "racer"})):
                with patch("auth.entitlements._get_conn"):
                    from web.middleware.entitlements import entitlement_middleware
                    result = entitlement_middleware()
                    assert result is None

    def test_other_sessions_posts_not_gated_by_race_strategy(self, app):
        """POST /api/v1/sessions/42/stints/assign (and other non-bridge POSTs
        under /api/v1/sessions/) must NOT trigger the race_strategy gate —
        the suffix match keeps this gate scoped to /endurance-race only."""
        with app.test_request_context("/api/v1/sessions/42/stints/assign", method="POST"):
            g.current_user_id = 1
            g.workspace_id = 1

            with patch("auth.entitlements.authorize_feature") as mock_auth:
                with patch("auth.entitlements._get_conn"):
                    from web.middleware.entitlements import entitlement_middleware
                    entitlement_middleware()
                    for call_args in mock_auth.call_args_list:
                        feature = call_args[0][2] if len(call_args[0]) > 2 else None
                        assert feature != "race_strategy", \
                            "POST .../stints/assign should NOT trigger the endurance-race gate"


class TestQuotaGating:
    def test_analysis_blocked_when_quota_exceeded(self, app):
        with app.test_request_context("/analyze/api/start", method="POST"):
            g.current_user_id = 1
            g.workspace_id = 1

            # Feature gate passes (analysis allowed for all tiers)
            # But quota is exceeded
            ctx = {"remaining": 0, "limit": 1, "used": 1, "resets_at": "2026-04-01"}
            with patch("auth.entitlements.authorize_feature", return_value=(True, {})):
                with patch("auth.entitlements.check_and_record_quota", return_value=(False, ctx)):
                    with patch("auth.entitlements._get_conn"):
                        from web.middleware.entitlements import entitlement_middleware
                        result = entitlement_middleware()
                        assert result is not None
                        resp, status = result
                        data = resp.get_json()
                        assert status == 429
                        assert data["error"]["code"] == "QUOTA_EXCEEDED"

    def test_analysis_allowed_under_quota(self, app):
        with app.test_request_context("/analyze/api/start", method="POST"):
            g.current_user_id = 1
            g.workspace_id = 1

            ctx = {"remaining": 5, "limit": 10, "used": 5, "resets_at": "2026-04-01"}
            with patch("auth.entitlements.check_and_record_quota", return_value=(True, ctx)):
                with patch("auth.entitlements._get_conn"):
                    from web.middleware.entitlements import entitlement_middleware
                    result = entitlement_middleware()
                    assert result is None  # Pass through

    def test_middleware_calls_check_and_record_quota_not_check_quota(self, app):
        """G-01: Verify middleware uses atomic check_and_record_quota (SELECT FOR UPDATE)
        instead of non-atomic check_quota to prevent concurrent quota overspend."""
        with app.test_request_context("/analyze/api/start", method="POST"):
            g.current_user_id = 1
            g.workspace_id = 1

            ctx = {"remaining": 9, "limit": 10, "used": 1, "resets_at": "2026-04-01"}
            with patch("auth.entitlements._get_conn") as mock_get_conn:
                mock_conn = MagicMock()
                mock_get_conn.return_value = mock_conn

                with patch("auth.entitlements.check_and_record_quota",
                           return_value=(True, ctx)) as mock_atomic:
                    with patch("auth.entitlements.check_quota") as mock_non_atomic:
                        from web.middleware.entitlements import entitlement_middleware
                        result = entitlement_middleware()

                        # Atomic version MUST be called
                        mock_atomic.assert_called_once_with(
                            mock_conn, 1, 1, "reports", 1,
                        )
                        # Non-atomic version must NOT be called
                        mock_non_atomic.assert_not_called()

                        # Request should pass through
                        assert result is None

    def test_upload_quota_gated(self, app):
        """POST to /api/data/files/upload should be quota-gated by uploads."""
        @app.route("/api/data/files/upload", methods=["POST"])
        def upload_file():
            return {"ok": True}

        with app.test_request_context("/api/data/files/upload", method="POST"):
            g.current_user_id = 1
            g.workspace_id = 1

            ctx = {"remaining": 0, "limit": 5, "used": 5, "resets_at": "2026-04-01"}
            with patch("auth.entitlements.check_and_record_quota", return_value=(False, ctx)):
                with patch("auth.entitlements._get_conn"):
                    from web.middleware.entitlements import entitlement_middleware
                    result = entitlement_middleware()
                    assert result is not None
                    resp, status = result
                    data = resp.get_json()
                    assert status == 429
                    assert data["error"]["code"] == "QUOTA_EXCEEDED"

    def test_ingest_quota_gated(self, app):
        """POST to /api/v1/ingest/start should be quota-gated by uploads."""
        @app.route("/api/v1/ingest/start", methods=["POST"])
        def ingest_start():
            return {"ok": True}

        with app.test_request_context("/api/v1/ingest/start", method="POST"):
            g.current_user_id = 1
            g.workspace_id = 1

            ctx = {"remaining": 0, "limit": 10, "used": 10, "resets_at": "2026-04-01"}
            with patch("auth.entitlements.check_and_record_quota", return_value=(False, ctx)):
                with patch("auth.entitlements._get_conn"):
                    from web.middleware.entitlements import entitlement_middleware
                    result = entitlement_middleware()
                    assert result is not None
                    resp, status = result
                    data = resp.get_json()
                    assert status == 429
                    assert data["error"]["code"] == "QUOTA_EXCEEDED"


class TestExemptPaths:
    @pytest.mark.parametrize("path", [
        "/auth/login",
        "/healthz",
        "/api/v1/billing/webhook",
        "/api/v1/me",
        "/api/v1/account/profile",
        "/api/v1/workspaces/list",
        "/api/v1/teams/1/members",
        "/static/css/main.css",
    ])
    def test_exempt_paths_not_gated(self, app, path):
        with app.test_request_context(path, method="POST"):
            g.current_user_id = 1
            g.workspace_id = 1
            from web.middleware.entitlements import entitlement_middleware
            result = entitlement_middleware()
            assert result is None  # Always passes through


class TestGracefulDegradation:
    def test_skips_when_no_pg(self, app):
        app.config["USE_PG"] = False
        with app.test_request_context("/compare/sessions", method="GET"):
            g.current_user_id = 1
            from web.middleware.entitlements import entitlement_middleware
            result = entitlement_middleware()
            assert result is None

    def test_skips_when_no_auth_required(self, app):
        app.config["AUTH_REQUIRED"] = False
        with app.test_request_context("/compare/sessions", method="GET"):
            g.current_user_id = 1
            from web.middleware.entitlements import entitlement_middleware
            result = entitlement_middleware()
            assert result is None

    def test_skips_when_no_user(self, app):
        with app.test_request_context("/compare/sessions", method="GET"):
            g.current_user_id = None
            from web.middleware.entitlements import entitlement_middleware
            result = entitlement_middleware()
            assert result is None


class TestUsageRecording:
    def test_records_usage_on_successful_non_atomic_route(self, app):
        """After a successful POST to a non-atomic route, usage should be recorded."""
        with app.test_client() as client:
            with app.test_request_context("/race-strategy/import", method="POST"):
                g.current_user_id = 1
                g.workspace_id = 1

                # Create a mock response
                from flask import make_response
                response = make_response({"ok": True}, 200)

                with patch("auth.entitlements.record_usage") as mock_record:
                    with patch("auth.entitlements._get_conn") as mock_conn:
                        mock_conn.return_value = MagicMock()
                        from web.middleware.entitlements import record_successful_usage
                        result = record_successful_usage(response)
                        assert result.status_code == 200
                        mock_record.assert_called_once()

    def test_skips_usage_on_error_response(self, app):
        """Usage should NOT be recorded for 4xx/5xx responses."""
        with app.test_request_context("/analyze/api/start", method="POST"):
            g.current_user_id = 1
            g.workspace_id = 1

            from flask import make_response
            response = make_response({"error": "bad"}, 400)

            with patch("auth.entitlements.record_usage") as mock_record:
                from web.middleware.entitlements import record_successful_usage
                result = record_successful_usage(response)
                assert result.status_code == 400
                mock_record.assert_not_called()

    def test_skips_usage_on_non_matching_path(self, app):
        """Usage should NOT be recorded for paths not in _USAGE_EVENTS."""
        with app.test_request_context("/api/v1/me", method="GET"):
            g.current_user_id = 1
            g.workspace_id = 1

            from flask import make_response
            response = make_response({"ok": True}, 200)

            with patch("auth.entitlements.record_usage") as mock_record:
                from web.middleware.entitlements import record_successful_usage
                result = record_successful_usage(response)
                mock_record.assert_not_called()

    def test_skips_double_recording_for_atomic_quota_routes(self, app):
        """Routes already recorded atomically by check_and_record_quota must not
        be double-counted in record_successful_usage."""
        with app.test_request_context("/analyze/api/start", method="POST"):
            g.current_user_id = 1
            g.workspace_id = 1

            from flask import make_response
            response = make_response({"ok": True}, 202)

            with patch("auth.entitlements.record_usage") as mock_record:
                from web.middleware.entitlements import record_successful_usage
                result = record_successful_usage(response)
                assert result.status_code == 202
                # record_usage must NOT be called because /analyze/api/start
                # is in _ATOMIC_QUOTA_ROUTES and already recorded by the middleware
                mock_record.assert_not_called()


class TestCheckAndRecordQuota:
    """Tests for the atomic check_and_record_quota function."""

    def test_allows_and_records_under_quota(self):
        from auth.entitlements import check_and_record_quota
        conn = MagicMock()

        # Mock: user is racer, plan has 10 reports/month
        class FakeCursor:
            def __init__(self, rows):
                self._rows = rows
                self._pos = 0
            def fetchone(self):
                if self._pos < len(self._rows):
                    r = self._rows[self._pos]; self._pos += 1; return r
                return None
            def fetchall(self):
                return self._rows

        cursors = [
            FakeCursor([{"plan_tier": "racer"}]),     # get_user_plan_tier
            FakeCursor([{                             # get_plan_definitions
                "tier": "racer", "reports_per_month": 10,
                "max_upload_size_mb": 2000, "telemetry_retention_days": 90,
                "api_access": False, "comparison_enabled": False,
                "coaching_plans_enabled": True, "visualization_enabled": True,
                "race_strategy_limit": "full", "live_monitoring": True,
                "export_formats": '["pdf","csv"]', "max_concurrent_jobs": 2,
                "rate_multiplier": 2.0,
            }]),
            FakeCursor([{"total": 5}]),               # SELECT FOR UPDATE (5 used)
            FakeCursor([]),                           # INSERT usage_events
            FakeCursor([]),                           # UPSERT usage_monthly
        ]
        conn.execute = MagicMock(side_effect=cursors)

        allowed, ctx = check_and_record_quota(conn, 1, 1, "reports", cost=1)
        assert allowed is True
        assert ctx["remaining"] == 4  # 10 - 5 - 1 = 4
        assert ctx["used"] == 6  # 5 + 1

    def test_blocks_over_quota(self):
        from auth.entitlements import check_and_record_quota
        conn = MagicMock()

        class FakeCursor:
            def __init__(self, rows):
                self._rows = rows; self._pos = 0
            def fetchone(self):
                if self._pos < len(self._rows):
                    r = self._rows[self._pos]; self._pos += 1; return r
                return None

        cursors = [
            FakeCursor([{"plan_tier": "demo"}]),
            FakeCursor([{
                "tier": "demo", "reports_per_month": 1,
                "max_upload_size_mb": 500, "telemetry_retention_days": 30,
                "api_access": False, "comparison_enabled": False,
                "coaching_plans_enabled": False, "visualization_enabled": False,
                "race_strategy_limit": "limited_4h", "live_monitoring": False,
                "export_formats": '["csv"]', "max_concurrent_jobs": 1,
                "rate_multiplier": 1.0,
            }]),
            FakeCursor([{"total": 1}]),  # Already used 1 of 1
        ]
        conn.execute = MagicMock(side_effect=cursors)

        allowed, ctx = check_and_record_quota(conn, 1, 1, "reports", cost=1)
        assert allowed is False
        assert ctx["remaining"] == 0
        assert ctx["used"] == 1


class TestRequireUploadSize:
    """Tests for the require_upload_size decorator."""

    def test_require_upload_size_blocks_oversized(self):
        """require_upload_size decorator rejects files exceeding tier limit."""
        from io import BytesIO

        app = Flask(__name__)
        app.config["USE_PG"] = True
        app.config["TESTING"] = True

        from web.middleware.entitlements import require_upload_size

        @app.route("/upload", methods=["POST"])
        @require_upload_size("file")
        def upload():
            return {"ok": True}

        # 10 MB limit, upload 11 MB
        fake_snapshot = {"max_upload_size_mb": 10, "plan_tier": "demo"}
        with patch("web.middleware.entitlements.entitlement_snapshot", return_value=fake_snapshot):
            with app.test_client() as client:
                # Create a file larger than 10MB
                data = b"x" * (11 * 1024 * 1024)
                resp = client.post(
                    "/upload",
                    data={"file": (BytesIO(data), "big.csv")},
                    content_type="multipart/form-data",
                )
                assert resp.status_code == 413
                body = resp.get_json()
                assert body["error"]["code"] == "FILE_TOO_LARGE"

    def test_require_upload_size_allows_small_file(self):
        """require_upload_size decorator allows files under the tier limit."""
        from io import BytesIO

        app = Flask(__name__)
        app.config["USE_PG"] = True
        app.config["TESTING"] = True

        from web.middleware.entitlements import require_upload_size

        @app.route("/upload", methods=["POST"])
        @require_upload_size("file")
        def upload():
            return {"ok": True}

        fake_snapshot = {"max_upload_size_mb": 10, "plan_tier": "demo"}
        with patch("web.middleware.entitlements.entitlement_snapshot", return_value=fake_snapshot):
            with app.test_client() as client:
                data = b"x" * (5 * 1024 * 1024)  # 5 MB — under 10 MB limit
                resp = client.post(
                    "/upload",
                    data={"file": (BytesIO(data), "small.csv")},
                    content_type="multipart/form-data",
                )
                assert resp.status_code == 200

    def test_require_upload_size_skips_when_no_pg(self):
        """require_upload_size falls through in SQLite/desktop mode."""
        from io import BytesIO

        app = Flask(__name__)
        app.config["USE_PG"] = False
        app.config["TESTING"] = True

        from web.middleware.entitlements import require_upload_size

        @app.route("/upload", methods=["POST"])
        @require_upload_size("file")
        def upload():
            return {"ok": True}

        with app.test_client() as client:
            # Large file — should be allowed because USE_PG is off
            data = b"x" * (100 * 1024 * 1024)
            resp = client.post(
                "/upload",
                data={"file": (BytesIO(data), "huge.csv")},
                content_type="multipart/form-data",
            )
            assert resp.status_code == 200
