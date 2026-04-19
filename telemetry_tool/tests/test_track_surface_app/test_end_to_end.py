"""End-to-end integration test for the track-surface analysis app layer.

Exercises the full stack:
    POST /api/v1/track-surface/sessions/<sid>/run
        → orchestrator.enqueue → Celery task dispatched inline
        → orchestrator.execute → real session_loader → real adapters
        → real compute_metrics → real evaluate_session → real SupportTierResolver
        → real ArtifactWriter → real AnalysisRunRepository
    GET  /api/v1/track-surface/sessions/<sid>               (AnalysisRunSummary)
    GET  /api/v1/track-surface/sessions/<sid>/summary       (SessionSummary)
    GET  /api/v1/track-surface/sessions/<sid>/surface       (or 451 on tier D)
    GET  /api/v1/track-surface/sessions/<sid>/planner       (or 451 on tier C/D)
    GET  /api/v1/track-surface/sessions/<sid>/uncertainty
    GET  /api/v1/track-surface/sessions/<sid>/artifacts

Only ``track_surface.validation.harness.run_pipeline`` is stubbed — no
synthetic .ibt fixture ships with the repo. Every other layer runs real code.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from flask import Flask, g

from track_surface.validation.harness import PipelineResult
from track_surface_app.persistence import AnalysisRunRepository


_VALID_VEHICLE_SPEC = {
    "name": "Mazda MX-5 2024", "klass": "MX5", "drive_layout": "RWD",
    "mass_kg": 1100.0, "wheelbase_m": 2.31,
    "track_front_m": 1.495, "track_rear_m": 1.505,
    "weight_dist_front": 0.52, "aero_cla": 0.35, "cg_height_m": 0.50,
    "brake_bias_front": 0.58, "steer_ratio": 15.0,
    "camber_front_deg": -2.5, "camber_rear_deg": -1.5,
}

_VALID_TRACK_SPEC = {
    "name": "Daytona", "layout": "road_course", "regime": "banked",
    "expected_max_bank_deg": 31.0, "track_length_m": 5726.0,
}


def _make_tier_a_pipeline_result(session_id: int, ibt_path: str) -> PipelineResult:
    """PipelineResult with metrics that yield Tier A (PASS, low fallback)."""
    return PipelineResult(
        dataset_id=f"saas_session_{session_id}", ibt_path=ibt_path,
        n_samples_total=10_000, n_valid=9_500,
        best_lap=3, best_lap_time_s=88.123, n_laps=5,
        lap_times_s={1: 90.0, 2: 89.1, 3: 88.1, 4: 88.5, 5: 89.7},
        track_length_m=5726.0,
        field_coverage_pct=85.0, field_mean_confidence=0.82,
        field_cells_observed=450, field_cells_total=500,
        field_high_conf_cells=300, field_zero_conf_cells=20,
        bucket_active_count=6, bucket_sparse_count=0,
        bucket_fallback_distribution={0: 900, 1: 50, 2: 50},
        planner_nominal_mean_mu=1.05, planner_robust_mean_mu=0.98,
        planner_exploitable_mean_mu=1.12,
        planner_n_trusted=900, planner_n_degraded=100,
        calibration_profile_id="iracing_mx5_2024",
        calibration_source="registry_active",
    )


@pytest.fixture
def app_with_real_adapters(tmp_path):
    """Flask app where the blueprint uses the REAL adapter factory.

    Only ``run_pipeline`` is patched at the lowest seam — everything else
    (session_loader, compute_metrics, evaluate_session, SupportTierResolver,
    ArtifactWriter, AnalysisRunRepository) runs for real.
    """
    app = Flask(__name__)
    app.config["RESULTS_DIR"] = str(tmp_path)
    app.config["TESTING"] = True

    # In-memory sqlite with both sessions AND analysis_runs
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE sessions (
            session_id INTEGER PRIMARY KEY,
            source_path TEXT,
            analysis_json TEXT,
            track_id TEXT,
            kart_id INTEGER
        );
        CREATE TABLE tracks (
            track_id TEXT PRIMARY KEY,
            track_name TEXT,
            lap_length_m REAL
        );
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
        );
        """
    )
    conn.commit()
    app.config["_test_conn"] = conn
    app.config["_tmp_path"] = tmp_path

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
def client(app_with_real_adapters):
    return app_with_real_adapters.test_client()


def _seed_supported_session(app, session_id=42):
    conn = app.config["_test_conn"]
    tmp = app.config["_tmp_path"]
    ibt = tmp / f"sess_{session_id}.ibt"
    ibt.write_bytes(b"\x00" * 16)
    aj = {"track_spec": _VALID_TRACK_SPEC, "vehicle_spec": _VALID_VEHICLE_SPEC}
    conn.execute(
        "INSERT INTO sessions (session_id, source_path, analysis_json) VALUES (?,?,?)",
        (session_id, str(ibt), json.dumps(aj)),
    )
    conn.commit()
    return ibt


def _seed_csv_session(app, session_id=99):
    conn = app.config["_test_conn"]
    tmp = app.config["_tmp_path"]
    csv = tmp / f"sess_{session_id}.csv"
    csv.write_text("x")
    conn.execute(
        "INSERT INTO sessions (session_id, source_path) VALUES (?,?)",
        (session_id, str(csv)),
    )
    conn.commit()
    return csv


# ── The actual end-to-end test ──────────────────────────────


def _patch_celery_dispatch_to_run_inline(monkeypatch, app, fake_pipeline_result):
    """Re-route the Celery dispatch to execute the orchestrator inline, using
    the real pipeline_adapters wiring but a stubbed harness.run_pipeline."""
    from track_surface_app import pipeline_adapters, orchestrator as orch_mod
    from track_surface_app.session_loader import SessionLoader
    import web.routes.track_surface_analysis as routes_mod

    monkeypatch.setattr(pipeline_adapters, "run_pipeline",
                        lambda entry, config=None: fake_pipeline_result)

    def run_inline(run_id):
        loader = SessionLoader(
            conn_factory=lambda: app.config["_test_conn"],
            set_workspace_context_fn=None,
        )
        run_pipe, eval_release = pipeline_adapters.build_adapters(
            session_loader=loader,
            config=pipeline_adapters.AdapterConfig(),
        )
        orchestrator = orch_mod.AnalysisOrchestrator(
            conn_factory=lambda: app.config["_test_conn"],
            artifacts_base_dir=Path(app.config["RESULTS_DIR"]) / "track_surface",
            run_pipeline_fn=run_pipe,
            evaluate_release_fn=eval_release,
        )
        orchestrator.execute(run_id)

    monkeypatch.setattr(routes_mod, "dispatch_celery_task", run_inline)


class TestSupportedSessionEndToEnd:
    def test_post_run_produces_real_tier_decision(
        self, monkeypatch, app_with_real_adapters, client
    ):
        app = app_with_real_adapters
        ibt = _seed_supported_session(app, session_id=42)
        _patch_celery_dispatch_to_run_inline(
            monkeypatch, app,
            _make_tier_a_pipeline_result(42, str(ibt)),
        )

        # Trigger the full flow
        resp = client.post("/api/v1/track-surface/sessions/42/run", json={})
        assert resp.status_code == 202

        # Status should now be terminal (inline execution)
        resp = client.get("/api/v1/track-surface/sessions/42")
        assert resp.status_code == 200
        body = resp.get_json()
        data = body["data"]
        assert data["status"] == "succeeded"
        # Tier is DECIDED BY THE REAL RELEASE GATE against these metrics.
        # We don't assert the specific tier (release gate may WARN on some
        # thresholds) but it MUST NOT be D because calibration_source is valid.
        assert data["support_tier"] in ("A", "B", "C")
        assert data["support_tier"] != "D"
        assert data["release_decision"] in ("pass", "warn", "fail")
        assert data["validated_vehicle_profile"] == "iracing_mx5_2024"

    def test_summary_returns_real_pipeline_numbers(
        self, monkeypatch, app_with_real_adapters, client
    ):
        app = app_with_real_adapters
        ibt = _seed_supported_session(app, session_id=42)
        _patch_celery_dispatch_to_run_inline(
            monkeypatch, app,
            _make_tier_a_pipeline_result(42, str(ibt)),
        )
        client.post("/api/v1/track-surface/sessions/42/run", json={})

        resp = client.get("/api/v1/track-surface/sessions/42/summary")
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["n_samples_accepted"] == 9_500
        assert data["best_lap"] == 3
        assert data["best_lap_time_s"] == pytest.approx(88.123)

    def test_artifacts_persisted_and_listed(
        self, monkeypatch, app_with_real_adapters, client
    ):
        app = app_with_real_adapters
        ibt = _seed_supported_session(app, session_id=42)
        _patch_celery_dispatch_to_run_inline(
            monkeypatch, app,
            _make_tier_a_pipeline_result(42, str(ibt)),
        )
        client.post("/api/v1/track-surface/sessions/42/run", json={})

        resp = client.get("/api/v1/track-surface/sessions/42/artifacts")
        assert resp.status_code == 200
        artifacts = resp.get_json()["data"]["artifacts"]
        kinds = {a["kind"] for a in artifacts}
        # Summary + diagnostics always present
        assert {"summary", "diagnostics"} <= kinds
        # Artifact files exist on disk
        run_resp = client.get("/api/v1/track-surface/sessions/42")
        run_id = run_resp.get_json()["data"]["run_id"]
        artifact_dir = Path(app.config["RESULTS_DIR"]) / "track_surface" / "42" / run_id
        assert artifact_dir.is_dir()
        assert (artifact_dir / "summary.json").is_file()

    def test_planner_endpoint_gated_by_real_tier(
        self, monkeypatch, app_with_real_adapters, client
    ):
        app = app_with_real_adapters
        ibt = _seed_supported_session(app, session_id=42)
        _patch_celery_dispatch_to_run_inline(
            monkeypatch, app,
            _make_tier_a_pipeline_result(42, str(ibt)),
        )
        client.post("/api/v1/track-surface/sessions/42/run", json={})

        resp = client.get("/api/v1/track-surface/sessions/42/planner")
        # Tier A or B → 200, Tier C → 451
        run_resp = client.get("/api/v1/track-surface/sessions/42")
        tier = run_resp.get_json()["data"]["support_tier"]
        if tier in ("A", "B"):
            assert resp.status_code == 200
            data = resp.get_json()["data"]
            assert data["nominal"] is not None
            # Exploitable gated on tier A only
            if tier == "A":
                assert data["exploitable"] is not None
            else:
                assert data["exploitable"] is None
        else:
            assert resp.status_code == 451


class TestUnsupportedSessionEndToEnd:
    def test_csv_session_completes_at_tier_d(
        self, monkeypatch, app_with_real_adapters, client
    ):
        """Smoke path for the Tier D outcome — CSV-uploaded session."""
        app = app_with_real_adapters
        _seed_csv_session(app, session_id=99)
        # run_pipeline won't be called because the loader short-circuits.
        _patch_celery_dispatch_to_run_inline(
            monkeypatch, app,
            _make_tier_a_pipeline_result(99, "/should/not/be/used"),
        )
        resp = client.post("/api/v1/track-surface/sessions/99/run", json={})
        assert resp.status_code == 202

        resp = client.get("/api/v1/track-surface/sessions/99")
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["status"] == "succeeded"
        assert data["support_tier"] == "D"
        assert data["support_reason"] == "vehicle_profile_not_validated"

    def test_tier_d_refuses_planner_with_451(
        self, monkeypatch, app_with_real_adapters, client
    ):
        app = app_with_real_adapters
        _seed_csv_session(app, session_id=99)
        _patch_celery_dispatch_to_run_inline(
            monkeypatch, app,
            _make_tier_a_pipeline_result(99, "unused"),
        )
        client.post("/api/v1/track-surface/sessions/99/run", json={})

        resp = client.get("/api/v1/track-surface/sessions/99/planner")
        assert resp.status_code == 451
        assert resp.get_json()["error"]["code"] == "SUPPORT_TIER_REFUSED"


class TestSessionNotFound:
    def test_unknown_session_fails_with_clear_error(
        self, monkeypatch, app_with_real_adapters, client
    ):
        app = app_with_real_adapters
        _patch_celery_dispatch_to_run_inline(
            monkeypatch, app,
            _make_tier_a_pipeline_result(999, "unused"),
        )
        # Session 999 not seeded → loader.load() raises SessionNotFoundError →
        # orchestrator catches and marks failed.
        resp = client.post("/api/v1/track-surface/sessions/999/run", json={})
        assert resp.status_code == 202

        resp = client.get("/api/v1/track-surface/sessions/999")
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["status"] == "failed"
        assert data["error_code"] == "INTERNAL_ERROR"
        assert "not found" in data["error_message"].lower()
