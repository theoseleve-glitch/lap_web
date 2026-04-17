"""Tests for IntakeService — full intake pipeline with real validator/storage/repo."""
from __future__ import annotations

import io

import pytest

from bundle_intake.domain import BundleStatus, SimKey
from bundle_intake.errors import (
    BundleChecksumMismatchError,
    BundleDuplicateError,
    BundleFileMissingError,
    BundleManifestInvalidError,
    BundleManifestMissingError,
    BundleSchemaVersionUnsupportedError,
)
from bundle_intake.persistence import BundleRepository
from bundle_intake.service import IntakeInput, IntakeService
from bundle_intake.storage import ImmutableBundleStore


def _make_service(tmp_path, sqlite_conn):
    store = ImmutableBundleStore(tmp_path / "bundles")
    repo_factory = lambda: BundleRepository(sqlite_conn)   # noqa: E731
    return IntakeService(store=store, repo_factory=repo_factory)


def _intake_input(good_bundle, workspace_id=1, declared_checksum=None):
    return IntakeInput(
        stream=io.BytesIO(good_bundle["bytes"]),
        declared_checksum=declared_checksum,
        content_length=len(good_bundle["bytes"]),
        uploaded_by_user_id=42,
        workspace_id=workspace_id,
    )


class TestHappyPath:
    def test_good_bundle_produces_accepted(self, tmp_path, sqlite_conn, good_bundle):
        svc = _make_service(tmp_path, sqlite_conn)
        outcome = svc.intake(_intake_input(good_bundle))
        assert outcome.bundle.status is BundleStatus.ACCEPTED
        assert outcome.bundle.readiness.is_ready
        assert outcome.bundle.canonical.identity.sim is SimKey.IRACING
        assert outcome.bundle.intake_reasons == ["clean_accept"]

    def test_good_bundle_persists_to_store(self, tmp_path, sqlite_conn, good_bundle):
        svc = _make_service(tmp_path, sqlite_conn)
        outcome = svc.intake(_intake_input(good_bundle))
        # raw_path is within the store and readable
        from pathlib import Path
        assert Path(outcome.bundle.raw_path).is_file()
        assert Path(outcome.bundle.raw_path).read_bytes() == good_bundle["bytes"]

    def test_declared_checksum_match(self, tmp_path, sqlite_conn, good_bundle):
        svc = _make_service(tmp_path, sqlite_conn)
        outcome = svc.intake(_intake_input(
            good_bundle, declared_checksum=good_bundle["checksum"],
        ))
        assert outcome.bundle.checksum_sha256 == good_bundle["checksum"]


class TestDegradedPath:
    def test_degraded_bundle_accepted_as_degraded(
        self, tmp_path, sqlite_conn, degraded_bundle,
    ):
        svc = _make_service(tmp_path, sqlite_conn)
        outcome = svc.intake(_intake_input(degraded_bundle))
        assert outcome.bundle.status is BundleStatus.DEGRADED
        assert not outcome.bundle.readiness.is_ready
        assert "unknown_sim" in outcome.bundle.readiness.reasons
        assert outcome.bundle.intake_reasons == ["schema_valid_but_metadata_incomplete"]

    def test_unknown_sim_accepted_as_degraded(
        self, tmp_path, sqlite_conn, unknown_sim_bundle,
    ):
        svc = _make_service(tmp_path, sqlite_conn)
        outcome = svc.intake(_intake_input(unknown_sim_bundle))
        assert outcome.bundle.status is BundleStatus.DEGRADED
        assert outcome.bundle.canonical.identity.sim is SimKey.UNKNOWN
        assert "unknown_sim" in outcome.bundle.readiness.reasons

    def test_no_telemetry_bundle_accepted_as_degraded(
        self, tmp_path, sqlite_conn, no_telemetry_bundle,
    ):
        svc = _make_service(tmp_path, sqlite_conn)
        outcome = svc.intake(_intake_input(no_telemetry_bundle))
        assert outcome.bundle.status is BundleStatus.DEGRADED
        assert "no_telemetry_file" in outcome.bundle.readiness.reasons


class TestChecksumAndSize:
    def test_outer_checksum_mismatch_rejects(self, tmp_path, sqlite_conn, good_bundle):
        svc = _make_service(tmp_path, sqlite_conn)
        with pytest.raises(BundleChecksumMismatchError):
            svc.intake(_intake_input(
                good_bundle, declared_checksum="0" * 64,
            ))

    def test_empty_upload_rejected(self, tmp_path, sqlite_conn):
        svc = _make_service(tmp_path, sqlite_conn)
        with pytest.raises(BundleFileMissingError):
            svc.intake(IntakeInput(
                stream=io.BytesIO(b""),
                declared_checksum=None, content_length=0,
                uploaded_by_user_id=1, workspace_id=1,
            ))

    def test_max_size_enforced(self, tmp_path, sqlite_conn):
        from bundle_intake.errors import BundleSizeExceededError
        store = ImmutableBundleStore(tmp_path / "bundles")
        svc = IntakeService(
            store=store,
            repo_factory=lambda: BundleRepository(sqlite_conn),
            max_bundle_bytes=10,
        )
        with pytest.raises(BundleSizeExceededError):
            svc.intake(IntakeInput(
                stream=io.BytesIO(b"a" * 100),
                declared_checksum=None, content_length=100,
                uploaded_by_user_id=1, workspace_id=1,
            ))


class TestValidation:
    def test_no_manifest_rejects(self, tmp_path, sqlite_conn, no_manifest_bundle):
        svc = _make_service(tmp_path, sqlite_conn)
        with pytest.raises(BundleManifestMissingError):
            svc.intake(_intake_input(no_manifest_bundle))

    def test_invalid_json_rejects(self, tmp_path, sqlite_conn, invalid_json_bundle):
        svc = _make_service(tmp_path, sqlite_conn)
        with pytest.raises(BundleManifestInvalidError):
            svc.intake(_intake_input(invalid_json_bundle))

    def test_v1_bundle_rejected(self, tmp_path, sqlite_conn, v1_legacy_bundle):
        svc = _make_service(tmp_path, sqlite_conn)
        with pytest.raises(BundleSchemaVersionUnsupportedError):
            svc.intake(_intake_input(v1_legacy_bundle))


class TestDuplicate:
    def test_duplicate_same_workspace_rejects(
        self, tmp_path, sqlite_conn, good_bundle,
    ):
        svc = _make_service(tmp_path, sqlite_conn)
        svc.intake(_intake_input(good_bundle))

        # Second upload of identical bytes → duplicate
        with pytest.raises(BundleDuplicateError) as exc_info:
            svc.intake(_intake_input(good_bundle))
        details = exc_info.value.details
        assert len(details) == 1
        assert "existing_bundle_id" in details[0]

    def test_same_bytes_different_workspaces_both_accepted(
        self, tmp_path, sqlite_conn, good_bundle,
    ):
        svc = _make_service(tmp_path, sqlite_conn)
        o1 = svc.intake(_intake_input(good_bundle, workspace_id=1))
        o2 = svc.intake(_intake_input(good_bundle, workspace_id=2))
        assert o1.bundle.bundle_id != o2.bundle.bundle_id
        # Physical file is deduplicated
        assert o1.bundle.raw_path == o2.bundle.raw_path
