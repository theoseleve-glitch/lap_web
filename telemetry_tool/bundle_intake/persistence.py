"""BundleRepository — CRUD across the 4 bundle intake tables.

Uses ``:name`` placeholders so the same SQL runs against SQLite (tests) and
PostgreSQL (production) via web.db's sql_compat translation.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

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

logger = logging.getLogger(__name__)


@dataclass
class BundleOverviewRow:
    """Denormalized read-model row for list views."""
    bundle_id: str
    status: BundleStatus
    sim: SimKey
    vehicle_key: str
    track_key: str
    vehicle_name: str
    track_name: str
    track_regime: str
    session_type: str
    started_at: str
    lap_count: int
    duration_s: float
    is_ready: bool
    readiness_reasons: list[str]
    readiness_degraded: list[str]
    latest_run_id: str | None
    uploaded_at: str


class BundleRepository:
    def __init__(self, conn):
        self._conn = conn

    # ── Helpers ─────────────────────────────────────────────

    def _cursor(self):
        return self._conn.cursor()

    def _commit(self):
        if hasattr(self._conn, "commit"):
            self._conn.commit()

    # ── Insert ──────────────────────────────────────────────

    def insert_bundle(self, b: UploadedBundle) -> None:
        """Atomic INSERT across all 4 tables. Caller commits."""
        cur = self._cursor()
        try:
            # 1. uploaded_bundles
            cur.execute(
                """
                INSERT INTO uploaded_bundles (
                    bundle_id, workspace_id, status, schema_version,
                    checksum_sha256, size_bytes, raw_path, identity_fingerprint,
                    uploaded_by_user_id, uploaded_at, intake_reasons
                ) VALUES (
                    :bundle_id, :workspace_id, :status, :schema_version,
                    :checksum_sha256, :size_bytes, :raw_path, :identity_fingerprint,
                    :uploaded_by_user_id, :uploaded_at, :intake_reasons
                )
                """,
                {
                    "bundle_id": b.bundle_id,
                    "workspace_id": b.workspace_id,
                    "status": b.status.value,
                    "schema_version": b.schema_version.value,
                    "checksum_sha256": b.checksum_sha256,
                    "size_bytes": b.size_bytes,
                    "raw_path": b.raw_path,
                    "identity_fingerprint": b.identity_fingerprint,
                    "uploaded_by_user_id": b.provenance.uploaded_by_user_id,
                    "uploaded_at": _iso(b.provenance.uploaded_at),
                    "intake_reasons": json.dumps(list(b.intake_reasons or [])),
                },
            )

            # 2. bundle_session_metadata (if canonical metadata present)
            if b.canonical is not None:
                c = b.canonical
                cur.execute(
                    """
                    INSERT INTO bundle_session_metadata (
                        bundle_id, workspace_id, sim, vehicle_key, track_key,
                        session_type, started_at,
                        vehicle_spec, track_spec, session_info,
                        channels_present, lap_count, duration_s,
                        readiness_is_ready, readiness_reasons, readiness_degraded,
                        extra
                    ) VALUES (
                        :bundle_id, :workspace_id, :sim, :vehicle_key, :track_key,
                        :session_type, :started_at,
                        :vehicle_spec, :track_spec, :session_info,
                        :channels_present, :lap_count, :duration_s,
                        :readiness_is_ready, :readiness_reasons, :readiness_degraded,
                        :extra
                    )
                    """,
                    {
                        "bundle_id": b.bundle_id,
                        "workspace_id": b.workspace_id,
                        "sim": c.identity.sim.value,
                        "vehicle_key": c.identity.vehicle_key,
                        "track_key": c.identity.track_key,
                        "session_type": c.identity.session_type,
                        "started_at": _iso(c.identity.started_at),
                        "vehicle_spec": json.dumps(c.vehicle_spec),
                        "track_spec": json.dumps(c.track_spec),
                        "session_info": json.dumps(c.session_info),
                        "channels_present": json.dumps(c.channels_present),
                        "lap_count": c.lap_count,
                        "duration_s": c.duration_s,
                        "readiness_is_ready": _bool_int(b.readiness.is_ready),
                        "readiness_reasons": json.dumps(b.readiness.reasons),
                        "readiness_degraded": json.dumps(b.readiness.degraded_fields),
                        "extra": json.dumps(c.extra),
                    },
                )

            # 3. bundle_artifacts
            for entry in b.artifact_manifest.files:
                cur.execute(
                    """
                    INSERT INTO bundle_artifacts (
                        bundle_id, workspace_id, role, path, size_bytes, checksum_sha256
                    ) VALUES (
                        :bundle_id, :workspace_id, :role, :path, :size_bytes, :checksum_sha256
                    )
                    """,
                    {
                        "bundle_id": b.bundle_id,
                        "workspace_id": b.workspace_id,
                        "role": entry.role.value,
                        "path": entry.path,
                        "size_bytes": entry.size_bytes,
                        "checksum_sha256": entry.checksum_sha256,
                    },
                )

            # 4. bundle_source_provenance
            p = b.provenance
            cur.execute(
                """
                INSERT INTO bundle_source_provenance (
                    bundle_id, workspace_id, logger_version, logger_build,
                    capture_method, captured_by_user_id, captured_at,
                    uploaded_by_user_id, uploaded_at, client_hostname, client_os
                ) VALUES (
                    :bundle_id, :workspace_id, :logger_version, :logger_build,
                    :capture_method, :captured_by_user_id, :captured_at,
                    :uploaded_by_user_id, :uploaded_at, :client_hostname, :client_os
                )
                """,
                {
                    "bundle_id": b.bundle_id,
                    "workspace_id": b.workspace_id,
                    "logger_version": p.logger_version,
                    "logger_build": p.logger_build,
                    "capture_method": p.capture_method,
                    "captured_by_user_id": p.captured_by_user_id,
                    "captured_at": _iso(p.captured_at),
                    "uploaded_by_user_id": p.uploaded_by_user_id,
                    "uploaded_at": _iso(p.uploaded_at),
                    "client_hostname": p.client_hostname,
                    "client_os": p.client_os,
                },
            )
        finally:
            cur.close()
        self._commit()

    # ── Reads ───────────────────────────────────────────────

    def find_by_checksum(self, workspace_id: int, checksum: str) -> dict | None:
        cur = self._cursor()
        try:
            cur.execute(
                """
                SELECT bundle_id, status, uploaded_at
                FROM uploaded_bundles
                WHERE workspace_id = :ws AND checksum_sha256 = :ck
                """,
                {"ws": workspace_id, "ck": checksum},
            )
            row = cur.fetchone()
        finally:
            cur.close()
        if row is None:
            return None
        return {
            "bundle_id": _g(row, "bundle_id"),
            "status": _g(row, "status"),
            "uploaded_at": _g(row, "uploaded_at"),
        }

    def get(self, bundle_id: str, workspace_id: int) -> UploadedBundle | None:
        cur = self._cursor()
        try:
            cur.execute(
                """
                SELECT b.*, m.*, p.*
                FROM uploaded_bundles b
                LEFT JOIN bundle_session_metadata m ON m.bundle_id = b.bundle_id
                LEFT JOIN bundle_source_provenance p ON p.bundle_id = b.bundle_id
                WHERE b.bundle_id = :bid AND b.workspace_id = :ws
                """,
                {"bid": bundle_id, "ws": workspace_id},
            )
            row = cur.fetchone()
            if row is None:
                return None
            artifacts = self._fetch_artifacts(bundle_id, workspace_id)
        finally:
            cur.close()
        return self._row_to_bundle(row, artifacts)

    def _fetch_artifacts(self, bundle_id: str, workspace_id: int) -> list[ArtifactManifestEntry]:
        cur = self._cursor()
        try:
            cur.execute(
                """
                SELECT role, path, size_bytes, checksum_sha256
                FROM bundle_artifacts
                WHERE bundle_id = :bid AND workspace_id = :ws
                ORDER BY path
                """,
                {"bid": bundle_id, "ws": workspace_id},
            )
            rows = cur.fetchall()
        finally:
            cur.close()
        return [
            ArtifactManifestEntry(
                path=_g(r, "path"),
                size_bytes=int(_g(r, "size_bytes")),
                checksum_sha256=_g(r, "checksum_sha256"),
                role=ArtifactRole(_g(r, "role")),
            )
            for r in rows
        ]

    def get_overview(self, bundle_id: str, workspace_id: int) -> BundleOverviewRow | None:
        cur = self._cursor()
        try:
            cur.execute(
                """
                SELECT
                    b.bundle_id, b.status, b.uploaded_at,
                    m.sim, m.vehicle_key, m.track_key, m.session_type,
                    m.started_at, m.vehicle_spec, m.track_spec,
                    m.lap_count, m.duration_s,
                    m.readiness_is_ready, m.readiness_reasons, m.readiness_degraded
                FROM uploaded_bundles b
                LEFT JOIN bundle_session_metadata m ON m.bundle_id = b.bundle_id
                WHERE b.bundle_id = :bid AND b.workspace_id = :ws
                """,
                {"bid": bundle_id, "ws": workspace_id},
            )
            row = cur.fetchone()
        finally:
            cur.close()
        if row is None:
            return None

        vehicle_spec = _load_json(_g(row, "vehicle_spec"))
        track_spec = _load_json(_g(row, "track_spec"))
        latest_run_id = self._fetch_latest_run_id(bundle_id, workspace_id)
        return BundleOverviewRow(
            bundle_id=_g(row, "bundle_id"),
            status=BundleStatus(_g(row, "status")),
            sim=SimKey.parse(_g(row, "sim")),
            vehicle_key=_g(row, "vehicle_key") or "",
            track_key=_g(row, "track_key") or "",
            vehicle_name=(vehicle_spec or {}).get("name", "") if vehicle_spec else "",
            track_name=(track_spec or {}).get("name", "") if track_spec else "",
            track_regime=(track_spec or {}).get("regime", "unknown") if track_spec else "unknown",
            session_type=_g(row, "session_type") or "",
            started_at=str(_g(row, "started_at") or ""),
            lap_count=int(_g(row, "lap_count") or 0),
            duration_s=float(_g(row, "duration_s") or 0.0),
            is_ready=bool(_g(row, "readiness_is_ready")),
            readiness_reasons=_load_json(_g(row, "readiness_reasons")) or [],
            readiness_degraded=_load_json(_g(row, "readiness_degraded")) or [],
            latest_run_id=latest_run_id,
            uploaded_at=str(_g(row, "uploaded_at")),
        )

    def _fetch_latest_run_id(self, bundle_id: str, workspace_id: int) -> str | None:
        cur = self._cursor()
        try:
            cur.execute(
                """
                SELECT run_id FROM analysis_runs
                WHERE bundle_id = :bid AND workspace_id = :ws
                ORDER BY created_at DESC LIMIT 1
                """,
                {"bid": bundle_id, "ws": workspace_id},
            )
            row = cur.fetchone()
        except Exception:
            # analysis_runs may not have bundle_id column in older deployments
            row = None
        finally:
            cur.close()
        return _g(row, "run_id") if row else None

    def list_for_workspace(
        self, workspace_id: int, *, limit: int = 25,
    ) -> list[BundleOverviewRow]:
        cur = self._cursor()
        try:
            cur.execute(
                """
                SELECT bundle_id FROM uploaded_bundles
                WHERE workspace_id = :ws
                ORDER BY uploaded_at DESC
                LIMIT :limit
                """,
                {"ws": workspace_id, "limit": limit},
            )
            rows = cur.fetchall()
        finally:
            cur.close()
        return [
            overview for overview in
            (self.get_overview(_g(r, "bundle_id"), workspace_id) for r in rows)
            if overview is not None
        ]

    def link_run(self, bundle_id: str, run_id: str, workspace_id: int) -> None:
        cur = self._cursor()
        try:
            cur.execute(
                "UPDATE analysis_runs SET bundle_id = :bid "
                "WHERE run_id = :rid AND workspace_id = :ws",
                {"bid": bundle_id, "rid": run_id, "ws": workspace_id},
            )
        finally:
            cur.close()
        self._commit()

    # ── Row mapping ─────────────────────────────────────────

    def _row_to_bundle(self, row, artifacts: list[ArtifactManifestEntry]) -> UploadedBundle:
        canonical = None
        sim_value = _g(row, "sim")
        if sim_value is not None:
            canonical = CanonicalSessionMetadata(
                identity=SessionIdentity(
                    sim=SimKey.parse(sim_value),
                    vehicle_key=_g(row, "vehicle_key") or "",
                    track_key=_g(row, "track_key") or "",
                    session_type=_g(row, "session_type") or "",
                    started_at=_parse_datetime(_g(row, "started_at")),
                ),
                vehicle_spec=_load_json(_g(row, "vehicle_spec")) or {},
                track_spec=_load_json(_g(row, "track_spec")) or {},
                session_info=_load_json(_g(row, "session_info")) or {},
                channels_present=_load_json(_g(row, "channels_present")) or [],
                lap_count=int(_g(row, "lap_count") or 0),
                duration_s=float(_g(row, "duration_s") or 0.0),
                extra=_load_json(_g(row, "extra")) or {},
            )
        provenance = SourceProvenance(
            logger_version=_g(row, "logger_version") or "",
            logger_build=_g(row, "logger_build"),
            capture_method=_g(row, "capture_method") or "",
            captured_by_user_id=_g(row, "captured_by_user_id"),
            captured_at=_parse_datetime(_g(row, "captured_at")),
            uploaded_by_user_id=_g(row, "uploaded_by_user_id"),
            uploaded_at=_parse_datetime(_g(row, "uploaded_at")),
            client_hostname=_g(row, "client_hostname"),
            client_os=_g(row, "client_os"),
        )
        readiness = AnalysisReadiness(
            is_ready=bool(_g(row, "readiness_is_ready") or False),
            reasons=_load_json(_g(row, "readiness_reasons")) or [],
            degraded_fields=_load_json(_g(row, "readiness_degraded")) or [],
        )
        return UploadedBundle(
            bundle_id=_g(row, "bundle_id"),
            workspace_id=int(_g(row, "workspace_id")),
            identity_fingerprint=_g(row, "identity_fingerprint"),
            status=BundleStatus(_g(row, "status")),
            schema_version=BundleSchemaVersion(int(_g(row, "schema_version"))),
            checksum_sha256=_g(row, "checksum_sha256"),
            size_bytes=int(_g(row, "size_bytes")),
            raw_path=_g(row, "raw_path"),
            canonical=canonical,
            provenance=provenance,
            readiness=readiness,
            artifact_manifest=ArtifactManifest(files=artifacts),
            intake_reasons=_load_json(_g(row, "intake_reasons")) or [],
        )


# ── Module-level helpers ────────────────────────────────────


def _g(row, key: str):
    if row is None:
        return None
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return None


def _load_json(value):
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat()


def _parse_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.min


def _bool_int(value: bool) -> int:
    """SQLite stores booleans as int; PG handles real booleans too."""
    return 1 if value else 0
