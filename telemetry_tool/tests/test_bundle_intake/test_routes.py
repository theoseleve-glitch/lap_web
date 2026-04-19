"""HTTP integration tests for the bundle intake blueprint."""
from __future__ import annotations

import io
import sqlite3

import pytest
from flask import Flask, g


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
    # Reuse the schema our conftest builds + analysis_runs for /analyze.
    conn.executescript(
        """
        CREATE TABLE uploaded_bundles (
            bundle_id TEXT PRIMARY KEY,
            workspace_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            checksum_sha256 TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            raw_path TEXT NOT NULL,
            identity_fingerprint TEXT NOT NULL,
            uploaded_by_user_id INTEGER,
            uploaded_at TEXT NOT NULL DEFAULT (datetime('now')),
            intake_reasons TEXT NOT NULL DEFAULT '[]',
            UNIQUE (workspace_id, checksum_sha256)
        );
        CREATE TABLE bundle_session_metadata (
            bundle_id TEXT PRIMARY KEY REFERENCES uploaded_bundles(bundle_id) ON DELETE CASCADE,
            workspace_id INTEGER NOT NULL,
            sim TEXT NOT NULL,
            vehicle_key TEXT NOT NULL,
            track_key TEXT NOT NULL,
            session_type TEXT NOT NULL,
            started_at TEXT NOT NULL,
            vehicle_spec TEXT NOT NULL,
            track_spec TEXT NOT NULL,
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
            bundle_id TEXT NOT NULL,
            workspace_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            path TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            checksum_sha256 TEXT NOT NULL,
            PRIMARY KEY (bundle_id, path)
        );
        CREATE TABLE bundle_source_provenance (
            bundle_id TEXT PRIMARY KEY,
            workspace_id INTEGER NOT NULL,
            logger_version TEXT NOT NULL,
            logger_build TEXT,
            capture_method TEXT NOT NULL,
            captured_by_user_id INTEGER,
            captured_at TEXT NOT NULL,
            uploaded_by_user_id INTEGER,
            uploaded_at TEXT NOT NULL,
            client_hostname TEXT,
            client_os TEXT
        );
        CREATE TABLE analysis_runs (
            run_id TEXT PRIMARY KEY,
            session_id TEXT,
            bundle_id TEXT,
            workspace_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            support_tier TEXT, support_reason TEXT, confidence_level TEXT,
            release_decision TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            completed_at TEXT
        );
        """
    )
    conn.commit()

    inject_conn_factory(lambda: conn)
    inject_store(ImmutableBundleStore(tmp_path / "bundles"))

    dispatched = []

    def fake_enqueue(bundle_id, workspace_id, force_rerun):
        import uuid
        run_id = uuid.uuid4().hex
        conn.execute(
            """
            INSERT INTO analysis_runs (run_id, bundle_id, workspace_id, status, created_at)
            VALUES (:r, :b, :w, 'queued', datetime('now'))
            """,
            {"r": run_id, "b": bundle_id, "w": workspace_id},
        )
        conn.commit()
        dispatched.append((bundle_id, workspace_id, force_rerun))
        return run_id

    inject_analysis_enqueuer(fake_enqueue)

    @app.before_request
    def fake_tenant():
        g.workspace_id = 1
        g.current_user_id = 7
        g.request_id = "test-req-id"

    app.register_blueprint(bundles_bp)
    app.config["_conn"] = conn
    app.config["_dispatched"] = dispatched
    yield app
    conn.close()


@pytest.fixture
def client(app):
    return app.test_client()


def _upload(client, bytes_, headers=None, filename="bundle.zip"):
    data = {"bundle": (io.BytesIO(bytes_), filename)}
    return client.post(
        "/api/v1/bundles", data=data,
        content_type="multipart/form-data",
        headers=headers or {},
    )


# ── Upload tests ────────────────────────────────────────────


class TestUpload:
    def test_good_bundle_returns_201(self, client, good_bundle):
        resp = _upload(client, good_bundle["bytes"])
        assert resp.status_code == 201
        data = resp.get_json()["data"]
        assert data["status"] == "accepted"
        assert data["analyze_url"] is not None
        assert data["readiness"]["is_ready"]

    def test_degraded_bundle_returns_202(self, client, degraded_bundle):
        resp = _upload(client, degraded_bundle["bytes"])
        assert resp.status_code == 202
        data = resp.get_json()["data"]
        assert data["status"] == "degraded"
        assert data["analyze_url"] is None
        assert "unknown_sim" in data["readiness"]["reasons"]

    def test_unknown_sim_returns_202_degraded(self, client, unknown_sim_bundle):
        resp = _upload(client, unknown_sim_bundle["bytes"])
        assert resp.status_code == 202
        data = resp.get_json()["data"]
        assert data["status"] == "degraded"
        assert "unknown_sim" in data["readiness"]["reasons"]

    def test_missing_file_part_returns_400(self, client):
        resp = client.post("/api/v1/bundles", data={}, content_type="multipart/form-data")
        assert resp.status_code == 400
        assert resp.get_json()["error"]["code"] == "BUNDLE_FILE_MISSING"

    def test_v1_legacy_bundle_rejected(self, client, v1_legacy_bundle):
        resp = _upload(client, v1_legacy_bundle["bytes"])
        assert resp.status_code == 422
        assert resp.get_json()["error"]["code"] == "BUNDLE_SCHEMA_VERSION_UNSUPPORTED"

    def test_no_manifest_rejected(self, client, no_manifest_bundle):
        resp = _upload(client, no_manifest_bundle["bytes"])
        assert resp.status_code == 422
        assert resp.get_json()["error"]["code"] == "BUNDLE_MANIFEST_MISSING"

    def test_invalid_json_rejected(self, client, invalid_json_bundle):
        resp = _upload(client, invalid_json_bundle["bytes"])
        assert resp.status_code == 422
        assert resp.get_json()["error"]["code"] == "BUNDLE_MANIFEST_INVALID"

    def test_bad_inner_checksum_rejected(self, client, bad_checksum_bundle):
        resp = _upload(client, bad_checksum_bundle["bytes"])
        assert resp.status_code == 422
        assert resp.get_json()["error"]["code"] == "BUNDLE_INNER_CHECKSUM_MISMATCH"

    def test_checksum_mismatch_rejected(self, client, good_bundle):
        resp = _upload(client, good_bundle["bytes"],
                       headers={"X-Bundle-Sha256": "0" * 64})
        assert resp.status_code == 422
        assert resp.get_json()["error"]["code"] == "BUNDLE_CHECKSUM_MISMATCH"

    def test_declared_checksum_match_accepted(self, client, good_bundle):
        resp = _upload(client, good_bundle["bytes"],
                       headers={"X-Bundle-Sha256": good_bundle["checksum"]})
        assert resp.status_code == 201

    def test_duplicate_upload_returns_409(self, client, good_bundle):
        _upload(client, good_bundle["bytes"])
        resp = _upload(client, good_bundle["bytes"])
        assert resp.status_code == 409
        body = resp.get_json()
        assert body["error"]["code"] == "BUNDLE_DUPLICATE"
        assert body["error"]["details"][0]["existing_bundle_id"]


# ── List / get tests ────────────────────────────────────────


class TestRead:
    def test_get_bundle_after_upload(self, client, good_bundle):
        upload_resp = _upload(client, good_bundle["bytes"])
        bundle_id = upload_resp.get_json()["data"]["bundle_id"]
        resp = client.get(f"/api/v1/bundles/{bundle_id}")
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["bundle_id"] == bundle_id
        assert data["sim"] == "iracing"
        assert data["readiness"]["is_ready"]

    def test_get_bundle_not_found(self, client):
        resp = client.get("/api/v1/bundles/nonexistent")
        assert resp.status_code == 404

    def test_list_bundles_newest_first(self, client, good_bundle, degraded_bundle):
        _upload(client, good_bundle["bytes"])
        _upload(client, degraded_bundle["bytes"])
        resp = client.get("/api/v1/bundles")
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["count"] == 2
        # Most recent first. Both share timestamp granularity so order is stable-ish.
        statuses = {b["status"] for b in data["bundles"]}
        assert statuses == {"accepted", "degraded"}

    def test_manifest_endpoint(self, client, good_bundle):
        upload = _upload(client, good_bundle["bytes"])
        bundle_id = upload.get_json()["data"]["bundle_id"]
        resp = client.get(f"/api/v1/bundles/{bundle_id}/manifest")
        assert resp.status_code == 200
        body = resp.get_json()["data"]
        assert body["schema_version"] == 2
        assert body["identity"]["sim"] == "iracing"

    def test_artifacts_endpoint_lists_all_files(self, client, good_bundle):
        upload = _upload(client, good_bundle["bytes"])
        bundle_id = upload.get_json()["data"]["bundle_id"]
        resp = client.get(f"/api/v1/bundles/{bundle_id}/artifacts")
        assert resp.status_code == 200
        artifacts = resp.get_json()["data"]["artifacts"]
        roles = {a["role"] for a in artifacts}
        assert "telemetry" in roles
        assert "analysis_json" in roles

    def test_artifact_download_streams_file(self, client, good_bundle):
        upload = _upload(client, good_bundle["bytes"])
        bundle_id = upload.get_json()["data"]["bundle_id"]
        resp = client.get(f"/api/v1/bundles/{bundle_id}/artifacts/telemetry")
        assert resp.status_code == 200
        assert len(resp.data) > 0

    def test_artifact_download_unknown_role_404(self, client, good_bundle):
        upload = _upload(client, good_bundle["bytes"])
        bundle_id = upload.get_json()["data"]["bundle_id"]
        resp = client.get(f"/api/v1/bundles/{bundle_id}/artifacts/no_such_role")
        assert resp.status_code == 404


# ── Analyze tests ───────────────────────────────────────────


class TestAnalyze:
    def test_analyze_ready_bundle_dispatches(self, app, client, good_bundle):
        upload = _upload(client, good_bundle["bytes"])
        bundle_id = upload.get_json()["data"]["bundle_id"]
        resp = client.post(f"/api/v1/bundles/{bundle_id}/analyze", json={})
        assert resp.status_code == 202
        data = resp.get_json()["data"]
        assert data["status"] == "queued"
        assert len(app.config["_dispatched"]) == 1

    def test_analyze_degraded_bundle_returns_409(self, client, degraded_bundle):
        upload = _upload(client, degraded_bundle["bytes"])
        bundle_id = upload.get_json()["data"]["bundle_id"]
        resp = client.post(f"/api/v1/bundles/{bundle_id}/analyze", json={})
        assert resp.status_code == 409
        assert resp.get_json()["error"]["code"] == "READINESS_NOT_MET"

    def test_analyze_nonexistent_bundle_404(self, client):
        resp = client.post("/api/v1/bundles/missing/analyze", json={})
        assert resp.status_code == 404

    def test_re_analyze_creates_additional_run(self, app, client, good_bundle):
        upload = _upload(client, good_bundle["bytes"])
        bundle_id = upload.get_json()["data"]["bundle_id"]
        client.post(f"/api/v1/bundles/{bundle_id}/analyze", json={})
        client.post(f"/api/v1/bundles/{bundle_id}/analyze", json={"force_rerun": True})

        conn = app.config["_conn"]
        rows = conn.execute(
            "SELECT COUNT(*) c FROM analysis_runs WHERE bundle_id=:b",
            {"b": bundle_id},
        ).fetchone()
        assert rows["c"] == 2
