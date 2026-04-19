"""Tests for bundle_intake domain types."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from bundle_intake.domain import (
    AnalysisReadiness,
    ArtifactManifest,
    ArtifactManifestEntry,
    ArtifactRole,
    BundleSchemaVersion,
    BundleStatus,
    SessionIdentity,
    SimKey,
    TrackRegime,
)


class TestEnums:
    def test_bundle_status_values_stable(self):
        assert BundleStatus.ACCEPTED.value == "accepted"
        assert BundleStatus.DEGRADED.value == "degraded"
        assert BundleStatus.REJECTED.value == "rejected"

    def test_bundle_schema_version_v2_only(self):
        assert BundleSchemaVersion.V2.value == 2
        assert BundleSchemaVersion.supported() == frozenset({2})

    def test_sim_key_parse_known(self):
        assert SimKey.parse("iracing") is SimKey.IRACING
        assert SimKey.parse("IRACING") is SimKey.IRACING
        assert SimKey.parse("  ac ") is SimKey.AC

    def test_sim_key_parse_unknown_returns_unknown(self):
        assert SimKey.parse("fictional") is SimKey.UNKNOWN
        assert SimKey.parse(None) is SimKey.UNKNOWN

    def test_track_regime_parse(self):
        assert TrackRegime.parse("banked") is TrackRegime.BANKED
        assert TrackRegime.parse("hilly") is TrackRegime.UNKNOWN
        assert TrackRegime.parse(None) is TrackRegime.UNKNOWN


class TestSessionIdentity:
    def test_fingerprint_is_64_hex(self):
        ident = SessionIdentity(
            sim=SimKey.IRACING,
            vehicle_key="mx5",
            track_key="daytona",
            session_type="practice",
            started_at=datetime(2026, 4, 15, 10, 0, tzinfo=timezone.utc),
        )
        fp = ident.fingerprint()
        assert len(fp) == 64
        assert all(c in "0123456789abcdef" for c in fp)

    def test_fingerprint_is_deterministic(self):
        args = dict(
            sim=SimKey.IRACING, vehicle_key="mx5", track_key="daytona",
            session_type="practice",
            started_at=datetime(2026, 4, 15, 10, 0, tzinfo=timezone.utc),
        )
        assert SessionIdentity(**args).fingerprint() == SessionIdentity(**args).fingerprint()

    def test_fingerprint_differs_across_sessions(self):
        a = SessionIdentity(
            sim=SimKey.IRACING, vehicle_key="mx5", track_key="daytona",
            session_type="practice",
            started_at=datetime(2026, 4, 15, 10, 0, tzinfo=timezone.utc),
        )
        b = SessionIdentity(
            sim=SimKey.IRACING, vehicle_key="mx5", track_key="daytona",
            session_type="race",    # only field that changes
            started_at=datetime(2026, 4, 15, 10, 0, tzinfo=timezone.utc),
        )
        assert a.fingerprint() != b.fingerprint()

    def test_fingerprint_ignores_microseconds(self):
        a = SessionIdentity(
            sim=SimKey.IRACING, vehicle_key="mx5", track_key="daytona",
            session_type="practice",
            started_at=datetime(2026, 4, 15, 10, 0, 0, 0, tzinfo=timezone.utc),
        )
        b = SessionIdentity(
            sim=SimKey.IRACING, vehicle_key="mx5", track_key="daytona",
            session_type="practice",
            started_at=datetime(2026, 4, 15, 10, 0, 0, 999999, tzinfo=timezone.utc),
        )
        assert a.fingerprint() == b.fingerprint()


class TestArtifactManifest:
    def test_find_role(self):
        entry = ArtifactManifestEntry(
            path="telemetry.ibt", size_bytes=100,
            checksum_sha256="a" * 64, role=ArtifactRole.TELEMETRY,
        )
        manifest = ArtifactManifest(files=[entry])
        assert manifest.find_role(ArtifactRole.TELEMETRY) is entry
        assert manifest.find_role(ArtifactRole.AUX) is None

    def test_roles_set(self):
        entries = [
            ArtifactManifestEntry(path="a", size_bytes=1, checksum_sha256="a" * 64,
                                  role=ArtifactRole.TELEMETRY),
            ArtifactManifestEntry(path="b", size_bytes=1, checksum_sha256="a" * 64,
                                  role=ArtifactRole.ANALYSIS_JSON),
        ]
        assert ArtifactManifest(files=entries).roles() == {
            ArtifactRole.TELEMETRY, ArtifactRole.ANALYSIS_JSON,
        }


class TestAnalysisReadiness:
    def test_ready_has_empty_reasons(self):
        r = AnalysisReadiness(is_ready=True)
        assert r.is_ready
        assert r.reasons == []
        assert r.degraded_fields == []

    def test_degraded_carries_reasons(self):
        r = AnalysisReadiness(
            is_ready=False,
            reasons=["unknown_sim"],
            degraded_fields=["identity.sim"],
        )
        assert not r.is_ready
        assert "unknown_sim" in r.reasons
