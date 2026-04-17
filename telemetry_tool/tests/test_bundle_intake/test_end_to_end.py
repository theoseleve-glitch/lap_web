"""End-to-end: upload bundle → analyze → latest run via bundle-aware loader.

Exercises:
  - POST /api/v1/bundles  (real IntakeService, real persistence)
  - POST /api/v1/bundles/<bid>/analyze  (real track_surface_app orchestrator)
  - bundle-aware session_loader.load_from_bundle
  - real pipeline_adapters build_adapters + compute_metrics + release gate
  - real SupportTierResolver + ArtifactWriter + AnalysisRunRepository

Only ``track_surface.validation.harness.run_pipeline`` is stubbed — everything
else runs for real.
"""
from __future__ import annotations

import io
import sqlite3
import uuid
from pathlib import Path

import pytest
from flask import Flask, g

from track_surface.validation.harness import PipelineResult


def _make_tier_a_result(bundle_id: str, ibt_path: str) -> PipelineResult:
    return PipelineResult(
        dataset_id=f"bundle_{bundle_id}", ibt_path=ibt_path,
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
def app(tmp_path):
    from web.routes.bundles import (
        bp as bundles_bp,
        inject_analysis_enqueuer,
        inject_conn_factory,
        inject_store,
    )
    from bundle_intake.storage import ImmutableBundleStore

    app = Flask(__name__)
    app.config["RESULTS_DIR"] = str(tmp_path / "results")
    app.config["BUNDLES_DIR"] = str(tmp_path / "bundles")
    app.config["TESTING"] = True

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE uploaded_bundles (
            bundle_id TEXT PRIMARY KEY, workspace_id INTEGER NOT NULL,
            status TEXT NOT NULL, schema_version INTEGER NOT NULL,
            checksum_sha256 TEXT NOT NULL, size_bytes INTEGER NOT NULL,
            raw_path TEXT NOT NULL, identity_fingerprint TEXT NOT NULL,
            uploaded_by_user_id INTEGER,
            uploaded_at TEXT NOT NULL DEFAULT (datetime('now')),
            intake_reasons TEXT NOT NULL DEFAULT '[]',
            UNIQUE (workspace_id, checksum_sha256)
        );
        CREATE TABLE bundle_session_metadata (
            bundle_id TEXT PRIMARY KEY, workspace_id INTEGER NOT NULL,
            sim TEXT NOT NULL, vehicle_key TEXT NOT NULL, track_key TEXT NOT NULL,
            session_type TEXT NOT NULL, started_at TEXT NOT NULL,
            vehicle_spec TEXT NOT NULL, track_spec TEXT NOT NULL,
            session_info TEXT NOT NULL,
            channels_present TEXT NOT NULL DEFAULT '[]',
            lap_count INTEGER NOT NULL DEFAULT 0,
            duration_s REAL NOT NULL DEFAULT 0.0,
            readiness_is_ready INTEGER NOT NULL,
            readiness_reasons TEXT NOT NULL DEFAULT '[]',
            readiness_degraded TEXT NOT NULL DEFAULT '[]',
            extra TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE bundle_artifacts (
            bundle_id TEXT NOT NULL, workspace_id INTEGER NOT NULL,
            role TEXT NOT NULL, path TEXT NOT NULL,
            size_bytes INTEGER NOT NULL, checksum_sha256 TEXT NOT NULL,
            PRIMARY KEY (bundle_id, path)
        );
        CREATE TABLE bundle_source_provenance (
            bundle_id TEXT PRIMARY KEY, workspace_id INTEGER NOT NULL,
            logger_version TEXT NOT NULL, logger_build TEXT,
            capture_method TEXT NOT NULL, captured_by_user_id INTEGER,
            captured_at TEXT NOT NULL,
            uploaded_by_user_id INTEGER, uploaded_at TEXT NOT NULL,
            client_hostname TEXT, client_os TEXT
        );
        CREATE TABLE analysis_runs (
            run_id TEXT PRIMARY KEY, session_id TEXT, bundle_id TEXT,
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

    inject_conn_factory(lambda: conn)
    inject_store(ImmutableBundleStore(tmp_path / "bundles"))

    @app.before_request
    def fake_tenant():
        g.workspace_id = 1
        g.current_user_id = 7
        g.request_id = "test-req-id"

    app.register_blueprint(bundles_bp)
    app.config["_conn"] = conn
    app.config["_tmp_path"] = tmp_path
    yield app
    conn.close()


@pytest.fixture
def client(app):
    return app.test_client()


def _run_analysis_inline(app, bundle_id_being_analyzed, fake_pipeline_result):
    """Wire the analyze-dispatch to execute an orchestrator inline using the
    bundle-aware session loader."""
    from track_surface_app import orchestrator as orch_mod, pipeline_adapters
    from track_surface_app.session_loader import SessionLoader
    import web.routes.bundles as routes_mod

    # Stub the low-level pipeline but let compute_metrics + release_gate +
    # tier resolver + artifact writer run for real.
    pipeline_adapters.run_pipeline = lambda entry, config=None: fake_pipeline_result

    def enqueue(bundle_id, workspace_id, force_rerun):
        loader = SessionLoader(
            conn_factory=lambda: app.config["_conn"],
        )
        # Build adapters with a BUNDLE-aware loader wrapper.
        class _BundleLoaderProxy:
            def load(self, session_id, workspace_id):
                # session_id here is the bundle_id string we pass through.
                return loader.load_from_bundle(session_id, workspace_id)

        run_pipe, eval_rel = pipeline_adapters.build_adapters(
            session_loader=_BundleLoaderProxy(),
            config=pipeline_adapters.AdapterConfig(),
        )
        orchestrator = orch_mod.AnalysisOrchestrator(
            conn_factory=lambda: app.config["_conn"],
            artifacts_base_dir=Path(app.config["RESULTS_DIR"]) / "track_surface",
            run_pipeline_fn=run_pipe,
            evaluate_release_fn=eval_rel,
        )
        run_id = orchestrator.enqueue(
            session_id=bundle_id, workspace_id=workspace_id, force_rerun=force_rerun,
        )
        orchestrator.execute(run_id)
        return run_id

    routes_mod.inject_analysis_enqueuer(enqueue)


def _upload(client, bytes_):
    return client.post(
        "/api/v1/bundles",
        data={"bundle": (io.BytesIO(bytes_), "bundle.zip")},
        content_type="multipart/form-data",
    )


class TestEndToEnd:
    def test_full_flow_upload_analyze_latest_run(
        self, app, client, good_bundle,
    ):
        # Upload
        up = _upload(client, good_bundle["bytes"])
        assert up.status_code == 201
        bundle_id = up.get_json()["data"]["bundle_id"]

        # Wire real inline orchestrator
        _run_analysis_inline(
            app, bundle_id,
            _make_tier_a_result(bundle_id, good_bundle["path"].as_posix()),
        )

        # Analyze
        analyze = client.post(f"/api/v1/bundles/{bundle_id}/analyze", json={})
        assert analyze.status_code == 202

        # Latest run
        latest = client.get(f"/api/v1/bundles/{bundle_id}/runs/latest")
        assert latest.status_code == 200
        data = latest.get_json()["data"]
        assert data["status"] == "succeeded"
        assert data["support_tier"] in ("A", "B", "C")   # real release gate decides
        assert data["support_tier"] != "D"

    def test_degraded_bundle_blocks_analyze(self, app, client, degraded_bundle):
        up = _upload(client, degraded_bundle["bytes"])
        assert up.status_code == 202
        bundle_id = up.get_json()["data"]["bundle_id"]

        # No need to wire the orchestrator — route short-circuits on readiness
        resp = client.post(f"/api/v1/bundles/{bundle_id}/analyze", json={})
        assert resp.status_code == 409
        body = resp.get_json()
        assert body["error"]["code"] == "READINESS_NOT_MET"
        assert body["error"]["details"][0]["readiness"]["is_ready"] is False

    def test_analyze_linked_to_bundle(self, app, client, good_bundle):
        up = _upload(client, good_bundle["bytes"])
        bundle_id = up.get_json()["data"]["bundle_id"]
        _run_analysis_inline(
            app, bundle_id,
            _make_tier_a_result(bundle_id, good_bundle["path"].as_posix()),
        )
        client.post(f"/api/v1/bundles/{bundle_id}/analyze", json={})

        # analysis_runs row is linked to bundle_id via repo.link_run
        rows = app.config["_conn"].execute(
            "SELECT bundle_id FROM analysis_runs WHERE bundle_id = :b",
            {"b": bundle_id},
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["bundle_id"] == bundle_id

    def test_get_overview_includes_latest_run_id(self, app, client, good_bundle):
        up = _upload(client, good_bundle["bytes"])
        bundle_id = up.get_json()["data"]["bundle_id"]
        _run_analysis_inline(
            app, bundle_id,
            _make_tier_a_result(bundle_id, good_bundle["path"].as_posix()),
        )
        client.post(f"/api/v1/bundles/{bundle_id}/analyze", json={})

        resp = client.get(f"/api/v1/bundles/{bundle_id}")
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["latest_run_id"] is not None
