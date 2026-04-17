"""Tests for BundleRepository."""
from __future__ import annotations

from datetime import datetime, timezone

from bundle_intake.domain import (
    AnalysisReadiness,
    ArtifactManifest,
    ArtifactManifestEntry,
    ArtifactRole,
    BundleSchemaVersion,
    BundleStatus,
    CanonicalSessionMetadata,
    SessionIdentity,
    SimKey,
    SourceProvenance,
    UploadedBundle,
)
from bundle_intake.persistence import BundleRepository


def _make_bundle(
    *, bundle_id: str = "b1", workspace_id: int = 1,
    checksum: str = "a" * 64, is_ready: bool = True,
    status: BundleStatus = BundleStatus.ACCEPTED,
) -> UploadedBundle:
    identity = SessionIdentity(
        sim=SimKey.IRACING, vehicle_key="mx5", track_key="daytona",
        session_type="practice",
        started_at=datetime(2026, 4, 15, 10, 0, tzinfo=timezone.utc),
    )
    canonical = CanonicalSessionMetadata(
        identity=identity,
        vehicle_spec={"name": "MX-5", "mass_kg": 1100.0},
        track_spec={"name": "Daytona", "regime": "banked"},
        session_info={"type": "practice"},
        channels_present=["Speed"],
        lap_count=5,
        duration_s=300.0,
    )
    provenance = SourceProvenance(
        logger_version="2.3.0", logger_build=None,
        capture_method="iracing_ibt",
        captured_by_user_id=1,
        captured_at=datetime(2026, 4, 15, 10, 0, tzinfo=timezone.utc),
        uploaded_by_user_id=1,
        uploaded_at=datetime(2026, 4, 15, 10, 5, tzinfo=timezone.utc),
    )
    manifest = ArtifactManifest(files=[
        ArtifactManifestEntry(path="telemetry.ibt", size_bytes=100,
                              checksum_sha256="b" * 64, role=ArtifactRole.TELEMETRY),
    ])
    return UploadedBundle(
        bundle_id=bundle_id,
        workspace_id=workspace_id,
        identity_fingerprint=identity.fingerprint(),
        status=status,
        schema_version=BundleSchemaVersion.V2,
        checksum_sha256=checksum,
        size_bytes=1024,
        raw_path=f"/bundles/{checksum[:2]}/{checksum}.zip",
        canonical=canonical,
        provenance=provenance,
        readiness=AnalysisReadiness(
            is_ready=is_ready, reasons=[] if is_ready else ["unknown_sim"],
            degraded_fields=[] if is_ready else ["identity.sim"],
        ),
        artifact_manifest=manifest,
        intake_reasons=[],
    )


class TestInsertBundle:
    def test_round_trip_get(self, sqlite_conn):
        repo = BundleRepository(sqlite_conn)
        bundle = _make_bundle()
        repo.insert_bundle(bundle)

        got = repo.get("b1", workspace_id=1)
        assert got is not None
        assert got.bundle_id == "b1"
        assert got.status is BundleStatus.ACCEPTED
        assert got.canonical.identity.sim is SimKey.IRACING
        assert got.canonical.vehicle_spec == {"name": "MX-5", "mass_kg": 1100.0}
        assert len(got.artifact_manifest.files) == 1
        assert got.artifact_manifest.files[0].role is ArtifactRole.TELEMETRY

    def test_get_missing_returns_none(self, sqlite_conn):
        repo = BundleRepository(sqlite_conn)
        assert repo.get("does_not_exist", workspace_id=1) is None

    def test_cross_workspace_isolation_in_get(self, sqlite_conn):
        repo = BundleRepository(sqlite_conn)
        repo.insert_bundle(_make_bundle(bundle_id="b1", workspace_id=1))
        # Querying wrong workspace must return None.
        assert repo.get("b1", workspace_id=999) is None


class TestDuplicate:
    def test_same_checksum_same_workspace_raises(self, sqlite_conn):
        repo = BundleRepository(sqlite_conn)
        repo.insert_bundle(_make_bundle(bundle_id="b1", checksum="a" * 64))
        # Insert a different bundle_id with the same checksum+workspace
        import sqlite3
        try:
            repo.insert_bundle(_make_bundle(bundle_id="b2", checksum="a" * 64))
        except sqlite3.IntegrityError:
            return   # expected
        raise AssertionError("expected IntegrityError for duplicate checksum")

    def test_same_checksum_different_workspaces_both_succeed(self, sqlite_conn):
        repo = BundleRepository(sqlite_conn)
        repo.insert_bundle(_make_bundle(bundle_id="b1", workspace_id=1, checksum="a" * 64))
        repo.insert_bundle(_make_bundle(bundle_id="b2", workspace_id=2, checksum="a" * 64))
        assert repo.get("b1", workspace_id=1) is not None
        assert repo.get("b2", workspace_id=2) is not None


class TestFindByChecksum:
    def test_finds_existing(self, sqlite_conn):
        repo = BundleRepository(sqlite_conn)
        repo.insert_bundle(_make_bundle(bundle_id="b1", checksum="c" * 64))
        found = repo.find_by_checksum(workspace_id=1, checksum="c" * 64)
        assert found is not None
        assert found["bundle_id"] == "b1"

    def test_returns_none_for_unknown(self, sqlite_conn):
        repo = BundleRepository(sqlite_conn)
        assert repo.find_by_checksum(workspace_id=1, checksum="0" * 64) is None


class TestOverview:
    def test_overview_row(self, sqlite_conn):
        repo = BundleRepository(sqlite_conn)
        repo.insert_bundle(_make_bundle())

        ov = repo.get_overview("b1", workspace_id=1)
        assert ov is not None
        assert ov.sim is SimKey.IRACING
        assert ov.vehicle_name == "MX-5"
        assert ov.track_name == "Daytona"
        assert ov.track_regime == "banked"
        assert ov.lap_count == 5
        assert ov.is_ready

    def test_overview_degraded(self, sqlite_conn):
        repo = BundleRepository(sqlite_conn)
        repo.insert_bundle(_make_bundle(is_ready=False, status=BundleStatus.DEGRADED))
        ov = repo.get_overview("b1", workspace_id=1)
        assert ov.status is BundleStatus.DEGRADED
        assert not ov.is_ready
        assert "unknown_sim" in ov.readiness_reasons


class TestListForWorkspace:
    def test_returns_newest_first(self, sqlite_conn):
        repo = BundleRepository(sqlite_conn)
        # Older
        repo.insert_bundle(_make_bundle(bundle_id="old", checksum="a" * 64))
        # Nudge clock
        sqlite_conn.execute(
            "UPDATE uploaded_bundles SET uploaded_at='2020-01-01' WHERE bundle_id='old'",
        )
        sqlite_conn.commit()
        repo.insert_bundle(_make_bundle(bundle_id="new", checksum="b" * 64))

        results = repo.list_for_workspace(workspace_id=1, limit=10)
        ids = [r.bundle_id for r in results]
        assert ids == ["new", "old"]

    def test_respects_workspace_filter(self, sqlite_conn):
        repo = BundleRepository(sqlite_conn)
        repo.insert_bundle(_make_bundle(bundle_id="b1", workspace_id=1, checksum="a" * 64))
        repo.insert_bundle(_make_bundle(bundle_id="b2", workspace_id=2, checksum="b" * 64))
        assert [r.bundle_id for r in repo.list_for_workspace(workspace_id=1)] == ["b1"]
        assert [r.bundle_id for r in repo.list_for_workspace(workspace_id=2)] == ["b2"]
