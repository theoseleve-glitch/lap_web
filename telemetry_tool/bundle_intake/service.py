"""IntakeService — glues validator, store, repo, and readiness together.

Synchronous end-to-end intake. Each call either persists a bundle (accepted
or degraded) or raises a typed exception from ``bundle_intake.errors``.
"""
from __future__ import annotations

import hashlib
import logging
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Callable

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
from bundle_intake.errors import (
    BundleChecksumMismatchError,
    BundleDuplicateError,
    BundleFileMissingError,
    BundleSizeExceededError,
)
from bundle_intake.manifest_schema import ManifestV2
from bundle_intake.persistence import BundleRepository
from bundle_intake.readiness import AnalysisReadinessEvaluator
from bundle_intake.storage import ImmutableBundleStore
from bundle_intake.validator import BundleValidator

logger = logging.getLogger(__name__)

_CHUNK = 1024 * 1024
_DEFAULT_MAX_BUNDLE_BYTES = 500 * 1024 * 1024   # 500 MB


@dataclass
class IntakeInput:
    """Everything the HTTP adapter hands to the service."""
    stream: BinaryIO
    declared_checksum: str | None
    content_length: int | None
    uploaded_by_user_id: int
    workspace_id: int
    client_hostname: str | None = None
    client_os: str | None = None


@dataclass
class IntakeOutcome:
    bundle: UploadedBundle
    was_duplicate: bool = False


class IntakeService:
    def __init__(
        self,
        *,
        store: ImmutableBundleStore,
        repo_factory: Callable[[], BundleRepository],
        validator: BundleValidator | None = None,
        readiness: AnalysisReadinessEvaluator | None = None,
        max_bundle_bytes: int = _DEFAULT_MAX_BUNDLE_BYTES,
    ):
        self._store = store
        self._repo_factory = repo_factory
        self._validator = validator or BundleValidator()
        self._readiness = readiness or AnalysisReadinessEvaluator()
        self._max_bytes = max_bundle_bytes

    # ── Public API ──────────────────────────────────────────

    def intake(self, inp: IntakeInput) -> IntakeOutcome:
        if inp.stream is None:
            raise BundleFileMissingError("no upload stream provided")

        # Step 1+2: stream to temp + checksum
        temp_path, computed_checksum, size_bytes = self._stream_to_temp(inp.stream)

        try:
            # Checksum mismatch is a reject — delete temp and raise.
            if inp.declared_checksum is not None:
                if inp.declared_checksum.strip().lower() != computed_checksum:
                    raise BundleChecksumMismatchError(
                        "X-Bundle-Sha256 does not match uploaded bytes",
                        details=[{
                            "declared": inp.declared_checksum,
                            "computed": computed_checksum,
                        }],
                    )

            if size_bytes > self._max_bytes:
                raise BundleSizeExceededError(
                    f"bundle {size_bytes} bytes exceeds limit {self._max_bytes}"
                )

            # Step 3-6: validator raises on any failure.
            manifest = self._validator.validate_archive(temp_path)
            self._validator.validate_inner_checksums(temp_path, manifest)

            # Step 7: dedup on (workspace_id, checksum)
            repo = self._repo_factory()
            existing = repo.find_by_checksum(inp.workspace_id, computed_checksum)
            if existing is not None:
                raise BundleDuplicateError(
                    "Bundle with this checksum already uploaded in this workspace.",
                    details=[{
                        "existing_bundle_id": existing["bundle_id"],
                        "existing_bundle_status": existing["status"],
                        "uploaded_at": str(existing["uploaded_at"]),
                    }],
                )

            # Step 8: promote to immutable store
            raw_path = self._store.promote(temp_path, computed_checksum)

            # Step 9-10: build aggregate + readiness
            canonical = _manifest_to_canonical(manifest)
            artifact_manifest = _manifest_to_artifacts(manifest)
            readiness = self._readiness.evaluate(canonical, artifact_manifest)
            status = BundleStatus.ACCEPTED if readiness.is_ready else BundleStatus.DEGRADED
            intake_reasons = (
                ["clean_accept"] if readiness.is_ready
                else ["schema_valid_but_metadata_incomplete"]
            )

            now = datetime.now(timezone.utc)
            bundle = UploadedBundle(
                bundle_id=uuid.uuid4().hex,
                workspace_id=inp.workspace_id,
                identity_fingerprint=canonical.identity.fingerprint(),
                status=status,
                schema_version=BundleSchemaVersion.V2,
                checksum_sha256=computed_checksum,
                size_bytes=size_bytes,
                raw_path=str(raw_path),
                canonical=canonical,
                provenance=SourceProvenance(
                    logger_version=manifest.source.logger_version,
                    logger_build=manifest.source.logger_build,
                    capture_method=manifest.source.capture_method,
                    captured_by_user_id=manifest.source.captured_by_user_id,
                    captured_at=manifest.source.captured_at,
                    uploaded_by_user_id=inp.uploaded_by_user_id,
                    uploaded_at=now,
                    client_hostname=inp.client_hostname or manifest.source.client_hostname,
                    client_os=inp.client_os or manifest.source.client_os,
                ),
                readiness=readiness,
                artifact_manifest=artifact_manifest,
                intake_reasons=intake_reasons,
            )

            # Step 11: atomic insert (in tests a single sqlite conn; in prod
            # wrapped in one transaction by the Flask request handler)
            repo.insert_bundle(bundle)

            logger.info(
                "intake_result=%s bundle_id=%s checksum=%s sim=%s ws=%s reasons=%s",
                status.value, bundle.bundle_id, computed_checksum[:12],
                canonical.identity.sim.value, inp.workspace_id,
                readiness.reasons,
            )
            return IntakeOutcome(bundle=bundle)

        except Exception:
            # Clean up temp on any failure — the store.promote() path removes
            # it on success, so this branch only fires before promotion.
            try:
                Path(temp_path).unlink()
            except FileNotFoundError:
                pass
            raise

    # ── Internals ───────────────────────────────────────────

    def _stream_to_temp(self, stream: BinaryIO) -> tuple[Path, str, int]:
        """Stream the upload to a temp file and return (path, sha256, size)."""
        fd = tempfile.NamedTemporaryFile(
            delete=False, suffix=".zip", prefix="intake_",
        )
        h = hashlib.sha256()
        total = 0
        try:
            with fd as sink:
                while True:
                    chunk = stream.read(_CHUNK)
                    if not chunk:
                        break
                    sink.write(chunk)
                    h.update(chunk)
                    total += len(chunk)
                    if total > self._max_bytes:
                        # Stop early rather than chewing more disk
                        raise BundleSizeExceededError(
                            f"bundle exceeds {self._max_bytes} bytes (streaming cap)"
                        )
        except BaseException:
            # On any error mid-stream, delete the temp
            try:
                Path(fd.name).unlink()
            except FileNotFoundError:
                pass
            raise

        if total == 0:
            Path(fd.name).unlink(missing_ok=True)
            raise BundleFileMissingError("uploaded bundle is empty")

        return Path(fd.name), h.hexdigest(), total


# ── Module-level helpers ────────────────────────────────────


def _manifest_to_canonical(manifest: ManifestV2) -> CanonicalSessionMetadata:
    identity = SessionIdentity(
        sim=SimKey.parse(manifest.identity.sim),
        vehicle_key=manifest.identity.vehicle_key,
        track_key=manifest.identity.track_key,
        session_type=manifest.identity.session_type,
        started_at=manifest.identity.started_at,
    )
    m = manifest.metadata
    return CanonicalSessionMetadata(
        identity=identity,
        vehicle_spec=dict(m.vehicle_spec),
        track_spec=dict(m.track_spec),
        session_info=dict(m.session_info),
        channels_present=list(m.channels_present),
        lap_count=int(m.lap_count or 0),
        duration_s=float(m.duration_s or 0.0),
        extra=dict(m.extra),
    )


def _manifest_to_artifacts(manifest: ManifestV2) -> ArtifactManifest:
    return ArtifactManifest(files=[
        ArtifactManifestEntry(
            path=f.path,
            size_bytes=int(f.size),
            checksum_sha256=f.sha256,
            role=ArtifactRole(f.role),
        )
        for f in manifest.files
    ])
