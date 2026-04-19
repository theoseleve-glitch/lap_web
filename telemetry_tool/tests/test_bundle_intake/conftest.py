"""Fixtures for bundle_intake tests."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from .fixtures.build_fixtures import (
    build_bad_inner_checksum_bundle,
    build_degraded_bundle,
    build_good_bundle,
    build_invalid_json_manifest_bundle,
    build_no_manifest_bundle,
    build_no_telemetry_bundle,
    build_unknown_sim_bundle,
    build_v1_legacy_bundle,
    write_bundle_to,
)


# ── Bundle byte-blob fixtures ──────────────────────────────


@pytest.fixture
def good_bundle(tmp_path: Path):
    zip_bytes, manifest = build_good_bundle()
    path = tmp_path / "good.zip"
    checksum = write_bundle_to(path, zip_bytes)
    return {"path": path, "checksum": checksum, "manifest": manifest, "bytes": zip_bytes}


@pytest.fixture
def degraded_bundle(tmp_path: Path):
    zip_bytes, manifest = build_degraded_bundle()
    path = tmp_path / "degraded.zip"
    checksum = write_bundle_to(path, zip_bytes)
    return {"path": path, "checksum": checksum, "manifest": manifest, "bytes": zip_bytes}


@pytest.fixture
def unknown_sim_bundle(tmp_path: Path):
    zip_bytes, manifest = build_unknown_sim_bundle()
    path = tmp_path / "unknown_sim.zip"
    checksum = write_bundle_to(path, zip_bytes)
    return {"path": path, "checksum": checksum, "manifest": manifest, "bytes": zip_bytes}


@pytest.fixture
def bad_checksum_bundle(tmp_path: Path):
    zip_bytes, manifest = build_bad_inner_checksum_bundle()
    path = tmp_path / "bad_inner.zip"
    checksum = write_bundle_to(path, zip_bytes)
    return {"path": path, "checksum": checksum, "manifest": manifest, "bytes": zip_bytes}


@pytest.fixture
def v1_legacy_bundle(tmp_path: Path):
    zip_bytes, manifest = build_v1_legacy_bundle()
    path = tmp_path / "v1.zip"
    checksum = write_bundle_to(path, zip_bytes)
    return {"path": path, "checksum": checksum, "manifest": manifest, "bytes": zip_bytes}


@pytest.fixture
def no_manifest_bundle(tmp_path: Path):
    zip_bytes = build_no_manifest_bundle()
    path = tmp_path / "no_manifest.zip"
    checksum = write_bundle_to(path, zip_bytes)
    return {"path": path, "checksum": checksum, "bytes": zip_bytes}


@pytest.fixture
def invalid_json_bundle(tmp_path: Path):
    zip_bytes = build_invalid_json_manifest_bundle()
    path = tmp_path / "invalid_json.zip"
    checksum = write_bundle_to(path, zip_bytes)
    return {"path": path, "checksum": checksum, "bytes": zip_bytes}


@pytest.fixture
def no_telemetry_bundle(tmp_path: Path):
    zip_bytes, manifest = build_no_telemetry_bundle()
    path = tmp_path / "no_telemetry.zip"
    checksum = write_bundle_to(path, zip_bytes)
    return {"path": path, "checksum": checksum, "manifest": manifest, "bytes": zip_bytes}


# ── DB fixtures ────────────────────────────────────────────


@pytest.fixture
def sqlite_conn():
    """In-memory SQLite mirroring the PG schema closely enough for tests."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
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
            bundle_id TEXT NOT NULL REFERENCES uploaded_bundles(bundle_id) ON DELETE CASCADE,
            workspace_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            path TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            checksum_sha256 TEXT NOT NULL,
            PRIMARY KEY (bundle_id, path)
        );
        CREATE TABLE bundle_source_provenance (
            bundle_id TEXT PRIMARY KEY REFERENCES uploaded_bundles(bundle_id) ON DELETE CASCADE,
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
        """
    )
    conn.commit()
    yield conn
    conn.close()
