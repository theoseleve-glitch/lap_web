"""Domain enums + dataclasses for bundle intake.

These are the vocabulary of the intake boundary. Translated to HTTP shapes
by web/schemas/bundles.py; translated to research-layer shapes by the
bundle-aware session loader in track_surface_app.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


# ── Enums ───────────────────────────────────────────────────


class BundleStatus(str, Enum):
    ACCEPTED = "accepted"     # stored, analyzable
    DEGRADED = "degraded"     # stored, not analyzable (see readiness reasons)
    REJECTED = "rejected"     # never persisted (validator-only tag)


class BundleSchemaVersion(int, Enum):
    V2 = 2

    @classmethod
    def supported(cls) -> frozenset[int]:
        return frozenset({cls.V2.value})


class SimKey(str, Enum):
    IRACING = "iracing"
    AC = "ac"
    ACC = "acc"
    RF2 = "rf2"
    LMU = "lmu"
    F1 = "f1"
    UNKNOWN = "unknown"

    @classmethod
    def parse(cls, raw) -> "SimKey":
        if raw is None:
            return cls.UNKNOWN
        try:
            return cls(str(raw).strip().lower())
        except ValueError:
            return cls.UNKNOWN


class TrackRegime(str, Enum):
    FLAT = "flat"
    BANKED = "banked"
    MIXED = "mixed"
    UNKNOWN = "unknown"

    @classmethod
    def parse(cls, raw) -> "TrackRegime":
        if raw is None:
            return cls.UNKNOWN
        try:
            return cls(str(raw).strip().lower())
        except ValueError:
            return cls.UNKNOWN


class ArtifactRole(str, Enum):
    TELEMETRY = "telemetry"
    ANALYSIS_JSON = "analysis_json"
    MANIFEST = "manifest"
    AUX = "aux"


# ── Structured failure reasons (closed set) ────────────────


READINESS_REASONS = frozenset({
    "unknown_sim",
    "vehicle_spec_incomplete",
    "vehicle_spec_invalid",
    "track_spec_incomplete",
    "track_spec_invalid",
    "no_telemetry_file",
    "no_analysis_json",
    "unsupported_capture_method",
})


INTAKE_REASONS = frozenset({
    "clean_accept",
    "schema_valid_but_metadata_incomplete",
    "unknown_sim_tolerated",
    "archive_missing_analysis_json",
})


# ── Value objects ──────────────────────────────────────────


@dataclass(frozen=True)
class SourceProvenance:
    """Where the bundle came from. Immutable once set."""
    logger_version: str
    logger_build: str | None
    capture_method: str
    captured_by_user_id: int | None
    captured_at: datetime
    uploaded_by_user_id: int
    uploaded_at: datetime
    client_hostname: str | None = None
    client_os: str | None = None


@dataclass(frozen=True)
class SessionIdentity:
    """The dedup key for identifying one logical session."""
    sim: SimKey
    vehicle_key: str
    track_key: str
    session_type: str
    started_at: datetime

    def fingerprint(self) -> str:
        """SHA-256 hex over canonicalized components. Stable across servers."""
        payload = "|".join([
            self.sim.value,
            self.vehicle_key,
            self.track_key,
            self.session_type,
            self.started_at.replace(microsecond=0).isoformat(),
        ])
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CanonicalSessionMetadata:
    """What the logger tells us about the session. Extracted, never inferred."""
    identity: SessionIdentity
    vehicle_spec: dict[str, Any]
    track_spec: dict[str, Any]
    session_info: dict[str, Any]
    channels_present: list[str]
    lap_count: int
    duration_s: float
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ArtifactManifestEntry:
    path: str
    size_bytes: int
    checksum_sha256: str
    role: ArtifactRole


@dataclass(frozen=True)
class ArtifactManifest:
    files: list[ArtifactManifestEntry]

    def roles(self) -> set[ArtifactRole]:
        return {f.role for f in self.files}

    def find_role(self, role: ArtifactRole) -> ArtifactManifestEntry | None:
        for f in self.files:
            if f.role is role:
                return f
        return None


@dataclass(frozen=True)
class AnalysisReadiness:
    """Can this bundle feed the analysis pipeline?"""
    is_ready: bool
    reasons: list[str] = field(default_factory=list)
    degraded_fields: list[str] = field(default_factory=list)


@dataclass
class UploadedBundle:
    """Aggregate root — one row in uploaded_bundles + side rows."""
    bundle_id: str
    workspace_id: int
    identity_fingerprint: str
    status: BundleStatus
    schema_version: BundleSchemaVersion
    checksum_sha256: str
    size_bytes: int
    raw_path: str
    canonical: CanonicalSessionMetadata | None
    provenance: SourceProvenance
    readiness: AnalysisReadiness
    artifact_manifest: ArtifactManifest
    intake_reasons: list[str] = field(default_factory=list)
