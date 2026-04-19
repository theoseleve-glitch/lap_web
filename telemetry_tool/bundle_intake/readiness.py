"""AnalysisReadinessEvaluator — decides whether a bundle can feed analysis.

Pure function of (CanonicalSessionMetadata, ArtifactManifest). No I/O, no DB.
Result drives the bundle's status (ACCEPTED vs DEGRADED) and the frontend's
analyze-button enablement.

v1 gate policy:
  - vehicle_spec completeness is NOT a readiness gate. The server resolves
    vehicle physics from the CalibrationProfile registry at analysis time.
  - track_spec.regime is NOT a readiness gate (defaults to "flat" if absent).
  - Readiness gates are: sim known + vehicle_key present + track_key present
    + at least one telemetry file.
"""
from __future__ import annotations

from bundle_intake.domain import (
    AnalysisReadiness,
    ArtifactManifest,
    ArtifactRole,
    CanonicalSessionMetadata,
    SimKey,
)


class AnalysisReadinessEvaluator:

    def evaluate(
        self,
        metadata: CanonicalSessionMetadata,
        artifact_manifest: ArtifactManifest,
    ) -> AnalysisReadiness:
        reasons: list[str] = []
        degraded: list[str] = []

        # Gate 1: sim must be recognized
        if metadata.identity.sim is SimKey.UNKNOWN:
            reasons.append("unknown_sim")
            degraded.append("identity.sim")

        # Gate 2: vehicle_key must be non-empty (actual spec resolved at analysis time)
        if not metadata.identity.vehicle_key:
            reasons.append("vehicle_key_missing")
            degraded.append("identity.vehicle_key")

        # Gate 3: track_key must be non-empty
        if not metadata.identity.track_key:
            reasons.append("track_key_missing")
            degraded.append("identity.track_key")

        # Gate 4: at least one telemetry file
        if not _has_telemetry_file(artifact_manifest):
            reasons.append("no_telemetry_file")

        # Track spec: name is recommended but not blocking.
        # track_spec.regime defaults to "flat" if absent — not a gate.

        return AnalysisReadiness(
            is_ready=(not reasons),
            reasons=reasons,
            degraded_fields=degraded,
        )


def _has_telemetry_file(manifest: ArtifactManifest) -> bool:
    return any(f.role is ArtifactRole.TELEMETRY for f in manifest.files)
