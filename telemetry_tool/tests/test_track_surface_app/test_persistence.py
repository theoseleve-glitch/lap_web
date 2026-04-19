"""Tests for AnalysisRunRepository against an in-memory SQLite schema."""
from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest

from track_surface_app.domain import AnalysisRunStatus, SupportTier, ConfidenceLevel
from track_surface_app.persistence import AnalysisRunRepository


@pytest.fixture
def sqlite_conn():
    """In-memory SQLite with the analysis_runs table mirroring the PG schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE analysis_runs (
            run_id TEXT PRIMARY KEY,
            session_id INTEGER NOT NULL,
            workspace_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            support_tier TEXT,
            support_reason TEXT,
            confidence_level TEXT,
            fallback_depth_distribution TEXT,
            validated_vehicle_profile TEXT,
            validated_track_profile TEXT,
            planner_mode_availability TEXT,
            warnings TEXT NOT NULL DEFAULT '[]',
            artifacts_index TEXT NOT NULL DEFAULT '{}',
            release_decision TEXT,
            pipeline_summary TEXT,
            error_code TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            completed_at TEXT
        )
        """
    )
    conn.commit()
    yield conn
    conn.close()


class TestInsertAndGet:
    def test_insert_queued_row(self, sqlite_conn):
        repo = AnalysisRunRepository(sqlite_conn)
        repo.insert_queued(run_id="r1", session_id=10, workspace_id=1)
        run = repo.get("r1")
        assert run is not None
        assert run.run_id == "r1"
        assert run.session_id == 10
        assert run.workspace_id == 1
        assert run.status is AnalysisRunStatus.QUEUED
        assert run.completed_at is None

    def test_get_missing_returns_none(self, sqlite_conn):
        repo = AnalysisRunRepository(sqlite_conn)
        assert repo.get("nonexistent") is None


class TestStatusTransitions:
    def test_update_status_running(self, sqlite_conn):
        repo = AnalysisRunRepository(sqlite_conn)
        repo.insert_queued(run_id="r", session_id=1, workspace_id=1)
        repo.update_status("r", AnalysisRunStatus.RUNNING)
        assert repo.get("r").status is AnalysisRunStatus.RUNNING

    def test_mark_succeeded_sets_terminal_fields(self, sqlite_conn):
        repo = AnalysisRunRepository(sqlite_conn)
        repo.insert_queued(run_id="r", session_id=1, workspace_id=1)
        repo.mark_succeeded(
            run_id="r",
            support_tier=SupportTier.A,
            support_reason="all_checks_passed",
            confidence_level=ConfidenceLevel.HIGH,
            fallback_depth_distribution={"0": 80.0, "1": 15.0, "2": 5.0},
            validated_vehicle_profile="iracing_mx5_2024",
            validated_track_profile="daytona_rc_v5",
            planner_mode_availability={"nominal": True, "robust": True, "exploitable": True},
            warnings=[],
            artifacts_index={"summary": "1/r/summary.json"},
            release_decision="pass",
            pipeline_summary={"n_valid": 9500},
        )
        run = repo.get("r")
        assert run.status is AnalysisRunStatus.SUCCEEDED
        assert run.support_tier is SupportTier.A
        assert run.confidence_level is ConfidenceLevel.HIGH
        assert run.release_decision == "pass"
        assert run.artifacts_index == {"summary": "1/r/summary.json"}
        assert run.completed_at is not None

    def test_mark_failed(self, sqlite_conn):
        repo = AnalysisRunRepository(sqlite_conn)
        repo.insert_queued(run_id="r", session_id=1, workspace_id=1)
        repo.mark_failed(
            run_id="r",
            error_code="INTERNAL_ERROR",
            error_message="boom",
            support_tier=SupportTier.D,
            support_reason="calibration_missing",
        )
        run = repo.get("r")
        assert run.status is AnalysisRunStatus.FAILED
        assert run.error_code == "INTERNAL_ERROR"
        assert run.error_message == "boom"
        assert run.support_tier is SupportTier.D
        assert run.completed_at is not None


class TestInFlightDetection:
    def test_has_in_flight_queued(self, sqlite_conn):
        repo = AnalysisRunRepository(sqlite_conn)
        repo.insert_queued(run_id="r", session_id=5, workspace_id=1)
        assert repo.has_in_flight(5)

    def test_has_in_flight_running(self, sqlite_conn):
        repo = AnalysisRunRepository(sqlite_conn)
        repo.insert_queued(run_id="r", session_id=5, workspace_id=1)
        repo.update_status("r", AnalysisRunStatus.RUNNING)
        assert repo.has_in_flight(5)

    def test_no_in_flight_after_success(self, sqlite_conn):
        repo = AnalysisRunRepository(sqlite_conn)
        repo.insert_queued(run_id="r", session_id=5, workspace_id=1)
        repo.mark_succeeded(
            run_id="r",
            support_tier=SupportTier.A, support_reason="all_checks_passed",
            confidence_level=ConfidenceLevel.HIGH,
            fallback_depth_distribution={}, validated_vehicle_profile=None,
            validated_track_profile=None, planner_mode_availability={},
            warnings=[], artifacts_index={}, release_decision="pass",
            pipeline_summary={},
        )
        assert not repo.has_in_flight(5)

    def test_no_in_flight_for_different_session(self, sqlite_conn):
        repo = AnalysisRunRepository(sqlite_conn)
        repo.insert_queued(run_id="r", session_id=5, workspace_id=1)
        assert not repo.has_in_flight(999)


class TestLatestForSession:
    def test_returns_none_when_no_run(self, sqlite_conn):
        repo = AnalysisRunRepository(sqlite_conn)
        assert repo.get_latest_for_session(42) is None

    def test_returns_most_recent(self, sqlite_conn):
        repo = AnalysisRunRepository(sqlite_conn)
        repo.insert_queued(run_id="old", session_id=42, workspace_id=1)
        # sqlite's datetime('now') has second-level granularity; nudge timestamps
        # so created_at differs between rows.
        import time
        time.sleep(1.01)
        repo.insert_queued(run_id="new", session_id=42, workspace_id=1)
        latest = repo.get_latest_for_session(42)
        assert latest is not None
        assert latest.run_id == "new"
