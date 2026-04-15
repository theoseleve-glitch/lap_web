"""Integration tests for the track-surface analysis blueprint.

Exercises the HTTP contract with a test Flask app. The orchestrator is mocked
so no Celery / physics is involved.
"""
from __future__ import annotations

import sqlite3
from unittest.mock import patch

import pytest
from flask import Flask, g

from track_surface_app.domain import SupportTier, ConfidenceLevel
from track_surface_app.persistence import AnalysisRunRepository


@pytest.fixture
def app(tmp_path):
    """Minimal Flask app with the analysis blueprint mounted."""
    app = Flask(__name__)
    app.config["RESULTS_DIR"] = str(tmp_path)
    app.config["TESTING"] = True

    # In-memory sqlite with the analysis_runs schema
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
    app.config["_test_conn"] = conn

    # Simulate tenant middleware by setting g.workspace_id directly
    @app.before_request
    def fake_tenant():
        g.workspace_id = 1
        g.current_user_id = 1
        g.request_id = "test-req-id"

    from web.routes.track_surface_analysis import bp as ts_bp, inject_conn_factory
    inject_conn_factory(lambda: conn)
    app.register_blueprint(ts_bp)

    yield app
    conn.close()


@pytest.fixture
def client(app):
    return app.test_client()


class TestRun:
    def test_post_run_returns_202_with_run_id(self, app, client):
        with patch("web.routes.track_surface_analysis.dispatch_celery_task") as dispatch:
            resp = client.post("/api/v1/track-surface/sessions/42/run", json={})
        assert resp.status_code == 202
        body = resp.get_json()
        assert body["ok"] is True
        assert "run_id" in body["data"]
        assert body["data"]["status"] == "queued"
        dispatch.assert_called_once()

    def test_post_run_in_flight_409(self, app, client):
        conn = app.config["_test_conn"]
        repo = AnalysisRunRepository(conn)
        repo.insert_queued(run_id="existing", session_id=42, workspace_id=1)
        with patch("web.routes.track_surface_analysis.dispatch_celery_task"):
            resp = client.post("/api/v1/track-surface/sessions/42/run", json={})
        assert resp.status_code == 409
        body = resp.get_json()
        assert body["ok"] is False
        assert body["error"]["code"] == "CONFLICT"

    def test_post_run_force_rerun_succeeds(self, app, client):
        conn = app.config["_test_conn"]
        repo = AnalysisRunRepository(conn)
        repo.insert_queued(run_id="existing", session_id=42, workspace_id=1)
        with patch("web.routes.track_surface_analysis.dispatch_celery_task"):
            resp = client.post("/api/v1/track-surface/sessions/42/run",
                               json={"force_rerun": True})
        assert resp.status_code == 202


class TestGetRun:
    def _seed_succeeded(self, conn, *, tier, run_id="r", session_id=42):
        repo = AnalysisRunRepository(conn)
        repo.insert_queued(run_id=run_id, session_id=session_id, workspace_id=1)
        repo.mark_succeeded(
            run_id=run_id,
            support_tier=tier,
            support_reason="all_checks_passed" if tier is SupportTier.A else "release_gate_warn",
            confidence_level=ConfidenceLevel.HIGH,
            fallback_depth_distribution={"0": 80.0, "1": 15.0, "2": 5.0},
            validated_vehicle_profile="iracing_mx5_2024",
            validated_track_profile="daytona_rc_v5",
            planner_mode_availability={"nominal": True, "robust": True,
                                       "exploitable": tier is SupportTier.A},
            warnings=[],
            artifacts_index={"summary": f"42/{run_id}/summary.json",
                             "diagnostics": f"42/{run_id}/diagnostics.json"},
            release_decision="pass",
            pipeline_summary={"n_valid": 9500, "best_lap_time_s": 88.1,
                              "n_samples_total": 10000, "n_laps": 5,
                              "best_lap": 3, "track_length_m": 3820.0,
                              "field_coverage_pct": 85.0,
                              "field_mean_confidence": 0.82,
                              "bucket_active_count": 6, "bucket_sparse_count": 0,
                              "planner_nominal_mean_mu": 1.05,
                              "planner_robust_mean_mu": 0.98,
                              "planner_exploitable_mean_mu": 1.12,
                              "planner_n_trusted": 900,
                              "planner_n_degraded": 100,
                              "calibration_profile_id": "iracing_mx5_2024",
                              "calibration_source": "registry_active"},
        )

    def test_get_session_returns_latest_run(self, app, client):
        self._seed_succeeded(app.config["_test_conn"], tier=SupportTier.A)
        resp = client.get("/api/v1/track-surface/sessions/42")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["support_tier"] == "A"
        assert body["data"]["planner_mode_availability"] == {
            "nominal": True, "robust": True, "exploitable": True,
        }

    def test_get_session_404_when_no_run(self, client):
        resp = client.get("/api/v1/track-surface/sessions/9999")
        assert resp.status_code == 404

    def test_get_planner_refused_at_tier_c(self, app, client):
        self._seed_succeeded(app.config["_test_conn"], tier=SupportTier.C)
        resp = client.get("/api/v1/track-surface/sessions/42/planner")
        assert resp.status_code == 451
        body = resp.get_json()
        assert body["error"]["code"] == "SUPPORT_TIER_REFUSED"

    def test_get_surface_refused_at_tier_d(self, app, client):
        self._seed_succeeded(app.config["_test_conn"], tier=SupportTier.D)
        resp = client.get("/api/v1/track-surface/sessions/42/surface")
        assert resp.status_code == 451

    def test_get_summary_returns_pipeline_summary(self, app, client):
        self._seed_succeeded(app.config["_test_conn"], tier=SupportTier.A)
        resp = client.get("/api/v1/track-surface/sessions/42/summary")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["n_samples_accepted"] == 9500
        assert body["data"]["best_lap"] == 3

    def test_get_planner_at_tier_a_has_all_modes(self, app, client):
        self._seed_succeeded(app.config["_test_conn"], tier=SupportTier.A)
        resp = client.get("/api/v1/track-surface/sessions/42/planner")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["support_tier"] == "A"
        assert set(body["data"]["available_modes"]) == {"nominal", "robust", "exploitable"}
        assert body["data"]["nominal"]["mode"] == "nominal"
        assert body["data"]["exploitable"] is not None

    def test_get_planner_at_tier_b_has_two_modes(self, app, client):
        self._seed_succeeded(app.config["_test_conn"], tier=SupportTier.B)
        resp = client.get("/api/v1/track-surface/sessions/42/planner")
        assert resp.status_code == 200
        body = resp.get_json()
        assert set(body["data"]["available_modes"]) == {"nominal", "robust"}
        assert body["data"]["exploitable"] is None

    def test_get_artifacts_filters_by_tier(self, app, client):
        self._seed_succeeded(app.config["_test_conn"], tier=SupportTier.C)
        resp = client.get("/api/v1/track-surface/sessions/42/artifacts")
        assert resp.status_code == 200
        body = resp.get_json()
        kinds = [a["kind"] for a in body["data"]["artifacts"]]
        assert set(kinds) == {"summary", "diagnostics"}


class TestSupportResolve:
    def test_known_combo(self, client):
        resp = client.get("/api/v1/track-surface/support/resolve"
                          "?sim=iracing&vehicle=mx5&track=daytona_rc")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["support_tier"] == "A"

    def test_unknown_combo_tier_d(self, client):
        resp = client.get("/api/v1/track-surface/support/resolve"
                          "?sim=ac&vehicle=gt3&track=nord")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["support_tier"] == "D"
        assert body["data"]["support_reason"] == "vehicle_profile_not_validated"

    def test_missing_params_422(self, client):
        resp = client.get("/api/v1/track-surface/support/resolve?sim=iracing")
        assert resp.status_code == 422


class TestSupportMatrix:
    def test_returns_entries(self, client):
        resp = client.get("/api/v1/track-surface/support/matrix")
        assert resp.status_code == 200
        body = resp.get_json()
        assert isinstance(body["data"]["entries"], list)
        assert len(body["data"]["entries"]) >= 1
