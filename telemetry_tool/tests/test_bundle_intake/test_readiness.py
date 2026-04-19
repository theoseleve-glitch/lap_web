"""Tests for AnalysisReadinessEvaluator (v1 gate policy).

v1 gates: sim known + vehicle_key present + track_key present + telemetry file.
vehicle_spec completeness is NOT a gate (resolved at analysis time).
"""
from __future__ import annotations

from datetime import datetime, timezone

from bundle_intake.domain import (
    ArtifactManifest,
    ArtifactManifestEntry,
    ArtifactRole,
    CanonicalSessionMetadata,
    SessionIdentity,
    SimKey,
)
from bundle_intake.readiness import AnalysisReadinessEvaluator


def _identity(sim=SimKey.IRACING, vehicle_key="mx5", track_key="daytona") -> SessionIdentity:
    return SessionIdentity(
        sim=sim, vehicle_key=vehicle_key, track_key=track_key,
        session_type="practice",
        started_at=datetime(2026, 4, 15, 10, 0, tzinfo=timezone.utc),
    )


def _telemetry_manifest() -> ArtifactManifest:
    return ArtifactManifest(files=[
        ArtifactManifestEntry(path="telemetry.ibt", size_bytes=100,
                              checksum_sha256="a" * 64, role=ArtifactRole.TELEMETRY),
    ])


class TestReady:
    def test_full_metadata_is_ready(self):
        """Bundle with sim + vehicle_key + track_key + telemetry → ready."""
        metadata = CanonicalSessionMetadata(
            identity=_identity(),
            vehicle_spec={},        # empty is OK in v1
            track_spec={"name": "Daytona"},
            session_info={},
            channels_present=[], lap_count=0, duration_s=0.0,
        )
        r = AnalysisReadinessEvaluator().evaluate(metadata, _telemetry_manifest())
        assert r.is_ready
        assert r.reasons == []
        assert r.degraded_fields == []

    def test_empty_vehicle_spec_still_ready(self):
        """v1: vehicle_spec completeness is NOT a readiness gate."""
        metadata = CanonicalSessionMetadata(
            identity=_identity(),
            vehicle_spec={},        # deliberately empty
            track_spec={"name": "Daytona"},
            session_info={},
            channels_present=[], lap_count=0, duration_s=0.0,
        )
        r = AnalysisReadinessEvaluator().evaluate(metadata, _telemetry_manifest())
        assert r.is_ready

    def test_missing_track_regime_still_ready(self):
        """v1: track_spec.regime defaults to 'flat' — NOT a gate."""
        metadata = CanonicalSessionMetadata(
            identity=_identity(),
            vehicle_spec={},
            track_spec={"name": "Spa"},   # no regime
            session_info={},
            channels_present=[], lap_count=0, duration_s=0.0,
        )
        r = AnalysisReadinessEvaluator().evaluate(metadata, _telemetry_manifest())
        assert r.is_ready


class TestDegradedReasons:
    def test_unknown_sim_is_degraded(self):
        metadata = CanonicalSessionMetadata(
            identity=_identity(sim=SimKey.UNKNOWN),
            vehicle_spec={},
            track_spec={"name": "X"},
            session_info={},
            channels_present=[], lap_count=0, duration_s=0.0,
        )
        r = AnalysisReadinessEvaluator().evaluate(metadata, _telemetry_manifest())
        assert not r.is_ready
        assert "unknown_sim" in r.reasons
        assert "identity.sim" in r.degraded_fields

    def test_vehicle_key_missing_is_degraded(self):
        metadata = CanonicalSessionMetadata(
            identity=_identity(vehicle_key=""),    # empty
            vehicle_spec={},
            track_spec={"name": "X"},
            session_info={},
            channels_present=[], lap_count=0, duration_s=0.0,
        )
        r = AnalysisReadinessEvaluator().evaluate(metadata, _telemetry_manifest())
        assert not r.is_ready
        assert "vehicle_key_missing" in r.reasons

    def test_track_key_missing_is_degraded(self):
        metadata = CanonicalSessionMetadata(
            identity=_identity(track_key=""),    # empty
            vehicle_spec={},
            track_spec={"name": "X"},
            session_info={},
            channels_present=[], lap_count=0, duration_s=0.0,
        )
        r = AnalysisReadinessEvaluator().evaluate(metadata, _telemetry_manifest())
        assert not r.is_ready
        assert "track_key_missing" in r.reasons

    def test_no_telemetry_file_is_degraded(self):
        metadata = CanonicalSessionMetadata(
            identity=_identity(),
            vehicle_spec={},
            track_spec={"name": "X"},
            session_info={},
            channels_present=[], lap_count=0, duration_s=0.0,
        )
        aux_only = ArtifactManifest(files=[
            ArtifactManifestEntry(path="notes.txt", size_bytes=10,
                                  checksum_sha256="a" * 64, role=ArtifactRole.AUX),
        ])
        r = AnalysisReadinessEvaluator().evaluate(metadata, aux_only)
        assert not r.is_ready
        assert "no_telemetry_file" in r.reasons

    def test_multiple_reasons_all_returned(self):
        metadata = CanonicalSessionMetadata(
            identity=_identity(sim=SimKey.UNKNOWN, vehicle_key="", track_key=""),
            vehicle_spec={},
            track_spec={},
            session_info={},
            channels_present=[], lap_count=0, duration_s=0.0,
        )
        r = AnalysisReadinessEvaluator().evaluate(metadata, _telemetry_manifest())
        assert not r.is_ready
        assert "unknown_sim" in r.reasons
        assert "vehicle_key_missing" in r.reasons
        assert "track_key_missing" in r.reasons
