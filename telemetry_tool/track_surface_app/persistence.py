"""AnalysisRunRepository — CRUD for the analysis_runs table.

SQL is written with ``:name`` placeholders so it runs against SQLite (dev) and
PostgreSQL (prod) via ``db/sql_compat``. When used from a Flask request, the
caller is responsible for supplying a PG-wrapped connection; RLS filtering is
automatic via ``SET LOCAL app.current_workspace_id``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from track_surface_app.domain import (
    AnalysisRunStatus,
    ConfidenceLevel,
    SupportTier,
)


@dataclass
class AnalysisRunRecord:
    """Snapshot of one row from analysis_runs.

    ``session_id`` tolerates both integers (legacy CSV-path sessions) and
    strings (bundle-path runs that use the bundle_id as the run's session
    surrogate). Callers treat it as opaque.
    """
    run_id: str
    session_id: int | str
    workspace_id: int
    status: AnalysisRunStatus
    support_tier: SupportTier | None
    support_reason: str | None
    confidence_level: ConfidenceLevel | None
    fallback_depth_distribution: dict[str, float] | None
    validated_vehicle_profile: str | None
    validated_track_profile: str | None
    planner_mode_availability: dict[str, bool] | None
    warnings: list[str]
    artifacts_index: dict[str, str]
    release_decision: str | None
    pipeline_summary: dict[str, Any] | None
    error_code: str | None
    error_message: str | None
    created_at: datetime | str
    completed_at: datetime | str | None


def _parse_json(value: Any, default):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _coerce_session_id(value: Any):
    """Return int when parseable, otherwise the original string."""
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return str(value)


def _enum_or_none(cls, value: Any):
    if value is None or value == "":
        return None
    try:
        return cls(value)
    except ValueError:
        return None


class AnalysisRunRepository:
    """CRUD for analysis_runs.

    Uses ``:name`` placeholders; compatible with both raw sqlite3 (tests) and
    the PG wrapper (production). Commits after each write so rows land even if
    the caller forgets — mirrors ``sessions_v2.py`` style.
    """

    def __init__(self, conn):
        self._conn = conn

    # ── Helpers ───────────────────────────────────────────────

    def _execute(self, sql: str, params: dict[str, Any]):
        cur = self._conn.cursor()
        try:
            cur.execute(sql, params)
            return cur
        except Exception:
            cur.close()
            raise

    def _commit(self):
        if hasattr(self._conn, "commit"):
            self._conn.commit()

    def _row_to_record(self, row) -> AnalysisRunRecord:
        def _g(key):
            try:
                return row[key]
            except (KeyError, IndexError, TypeError):
                return None

        return AnalysisRunRecord(
            run_id=_g("run_id"),
            session_id=_coerce_session_id(_g("session_id")),
            workspace_id=int(_g("workspace_id")),
            status=AnalysisRunStatus(_g("status")),
            support_tier=_enum_or_none(SupportTier, _g("support_tier")),
            support_reason=_g("support_reason"),
            confidence_level=_enum_or_none(ConfidenceLevel, _g("confidence_level")),
            fallback_depth_distribution=_parse_json(_g("fallback_depth_distribution"), None),
            validated_vehicle_profile=_g("validated_vehicle_profile"),
            validated_track_profile=_g("validated_track_profile"),
            planner_mode_availability=_parse_json(_g("planner_mode_availability"), None),
            warnings=_parse_json(_g("warnings"), []),
            artifacts_index=_parse_json(_g("artifacts_index"), {}),
            release_decision=_g("release_decision"),
            pipeline_summary=_parse_json(_g("pipeline_summary"), None),
            error_code=_g("error_code"),
            error_message=_g("error_message"),
            created_at=_g("created_at"),
            completed_at=_g("completed_at"),
        )

    # ── Writes ────────────────────────────────────────────────

    def insert_queued(self, *, run_id: str, session_id: int, workspace_id: int) -> None:
        cur = self._execute(
            """
            INSERT INTO analysis_runs (run_id, session_id, workspace_id, status)
            VALUES (:run_id, :session_id, :workspace_id, 'queued')
            """,
            {"run_id": run_id, "session_id": session_id, "workspace_id": workspace_id},
        )
        cur.close()
        self._commit()

    def update_status(self, run_id: str, status: AnalysisRunStatus) -> None:
        cur = self._execute(
            "UPDATE analysis_runs SET status = :status WHERE run_id = :run_id",
            {"status": status.value, "run_id": run_id},
        )
        cur.close()
        self._commit()

    def mark_succeeded(
        self,
        *,
        run_id: str,
        support_tier: SupportTier,
        support_reason: str,
        confidence_level: ConfidenceLevel,
        fallback_depth_distribution: dict[str, float] | None,
        validated_vehicle_profile: str | None,
        validated_track_profile: str | None,
        planner_mode_availability: dict[str, bool],
        warnings: list[str],
        artifacts_index: dict[str, str],
        release_decision: str | None,
        pipeline_summary: dict[str, Any] | None,
    ) -> None:
        cur = self._execute(
            """
            UPDATE analysis_runs SET
              status = 'succeeded',
              support_tier = :support_tier,
              support_reason = :support_reason,
              confidence_level = :confidence_level,
              fallback_depth_distribution = :fallback_depth_distribution,
              validated_vehicle_profile = :validated_vehicle_profile,
              validated_track_profile = :validated_track_profile,
              planner_mode_availability = :planner_mode_availability,
              warnings = :warnings,
              artifacts_index = :artifacts_index,
              release_decision = :release_decision,
              pipeline_summary = :pipeline_summary,
              completed_at = :completed_at
            WHERE run_id = :run_id
            """,
            {
                "run_id": run_id,
                "support_tier": support_tier.value,
                "support_reason": support_reason,
                "confidence_level": confidence_level.value,
                "fallback_depth_distribution": json.dumps(fallback_depth_distribution or {}),
                "validated_vehicle_profile": validated_vehicle_profile,
                "validated_track_profile": validated_track_profile,
                "planner_mode_availability": json.dumps(planner_mode_availability or {}),
                "warnings": json.dumps(list(warnings or [])),
                "artifacts_index": json.dumps(artifacts_index or {}),
                "release_decision": release_decision,
                "pipeline_summary": json.dumps(pipeline_summary or {}),
                "completed_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        cur.close()
        self._commit()

    def mark_failed(
        self,
        *,
        run_id: str,
        error_code: str,
        error_message: str,
        support_tier: SupportTier | None = None,
        support_reason: str | None = None,
    ) -> None:
        cur = self._execute(
            """
            UPDATE analysis_runs SET
              status = 'failed',
              error_code = :error_code,
              error_message = :error_message,
              support_tier = :support_tier,
              support_reason = :support_reason,
              completed_at = :completed_at
            WHERE run_id = :run_id
            """,
            {
                "run_id": run_id,
                "error_code": error_code,
                "error_message": error_message,
                "support_tier": support_tier.value if support_tier else None,
                "support_reason": support_reason,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        cur.close()
        self._commit()

    # ── Reads ─────────────────────────────────────────────────

    def get(self, run_id: str) -> AnalysisRunRecord | None:
        cur = self._execute(
            "SELECT * FROM analysis_runs WHERE run_id = :run_id",
            {"run_id": run_id},
        )
        try:
            row = cur.fetchone()
        finally:
            cur.close()
        if row is None:
            return None
        return self._row_to_record(row)

    def get_latest_for_session(self, session_id: int) -> AnalysisRunRecord | None:
        cur = self._execute(
            """
            SELECT * FROM analysis_runs
            WHERE session_id = :session_id
            ORDER BY created_at DESC
            LIMIT 1
            """,
            {"session_id": session_id},
        )
        try:
            row = cur.fetchone()
        finally:
            cur.close()
        if row is None:
            return None
        return self._row_to_record(row)

    def has_in_flight(self, session_id: int) -> bool:
        cur = self._execute(
            """
            SELECT 1 FROM analysis_runs
            WHERE session_id = :session_id
              AND status IN ('queued', 'running')
            LIMIT 1
            """,
            {"session_id": session_id},
        )
        try:
            row = cur.fetchone()
        finally:
            cur.close()
        return row is not None
