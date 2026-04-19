"""Tests for AnalysisOrchestrator — end-to-end with a mocked pipeline."""
from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock

import pytest

from track_surface_app.domain import SupportTier, AnalysisRunStatus
from track_surface_app.orchestrator import AnalysisOrchestrator
from track_surface_app.persistence import AnalysisRunRepository


@pytest.fixture
def sqlite_conn():
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


class TestEnqueue:
    def test_enqueue_creates_queued_row(self, sqlite_conn, tmp_path):
        orch = AnalysisOrchestrator(
            conn_factory=lambda: sqlite_conn,
            artifacts_base_dir=tmp_path,
            run_pipeline_fn=MagicMock(),
            evaluate_release_fn=MagicMock(),
            calibration_registry=None,
        )
        run_id = orch.enqueue(session_id=10, workspace_id=1)
        assert run_id
        repo = AnalysisRunRepository(sqlite_conn)
        run = repo.get(run_id)
        assert run.status is AnalysisRunStatus.QUEUED

    def test_enqueue_refuses_if_in_flight(self, sqlite_conn, tmp_path):
        orch = AnalysisOrchestrator(
            conn_factory=lambda: sqlite_conn,
            artifacts_base_dir=tmp_path,
            run_pipeline_fn=MagicMock(),
            evaluate_release_fn=MagicMock(),
            calibration_registry=None,
        )
        orch.enqueue(session_id=10, workspace_id=1)
        with pytest.raises(RuntimeError, match="in_flight"):
            orch.enqueue(session_id=10, workspace_id=1)

    def test_enqueue_force_rerun_allowed_when_in_flight(self, sqlite_conn, tmp_path):
        orch = AnalysisOrchestrator(
            conn_factory=lambda: sqlite_conn,
            artifacts_base_dir=tmp_path,
            run_pipeline_fn=MagicMock(),
            evaluate_release_fn=MagicMock(),
            calibration_registry=None,
        )
        r1 = orch.enqueue(session_id=10, workspace_id=1)
        r2 = orch.enqueue(session_id=10, workspace_id=1, force_rerun=True)
        assert r1 != r2


class TestExecute:
    def test_successful_tier_a_flow(self, sqlite_conn, tmp_path, tier_a_inputs):
        pr, rr = tier_a_inputs
        orch = AnalysisOrchestrator(
            conn_factory=lambda: sqlite_conn,
            artifacts_base_dir=tmp_path,
            run_pipeline_fn=lambda session_id, workspace_id: pr,
            evaluate_release_fn=lambda pipeline_result: rr,
            calibration_registry=None,
        )
        run_id = orch.enqueue(session_id=10, workspace_id=1)
        orch.execute(run_id)

        repo = AnalysisRunRepository(sqlite_conn)
        run = repo.get(run_id)
        assert run.status is AnalysisRunStatus.SUCCEEDED
        assert run.support_tier is SupportTier.A
        assert run.support_reason == "all_checks_passed"
        assert run.release_decision == "pass"
        assert "summary" in run.artifacts_index
        assert "planner_exploitable" in run.artifacts_index

    def test_tier_d_short_circuits(self, sqlite_conn, tmp_path, tier_d_inputs_no_calibration):
        pr, rr = tier_d_inputs_no_calibration
        orch = AnalysisOrchestrator(
            conn_factory=lambda: sqlite_conn,
            artifacts_base_dir=tmp_path,
            run_pipeline_fn=lambda session_id, workspace_id: pr,
            evaluate_release_fn=lambda pipeline_result: rr,
            calibration_registry=None,
        )
        run_id = orch.enqueue(session_id=10, workspace_id=1)
        orch.execute(run_id)

        repo = AnalysisRunRepository(sqlite_conn)
        run = repo.get(run_id)
        # Tier D is a "succeeded completion with advisory" semantically —
        # the run itself completed; only the advanced outputs are unavailable.
        assert run.status is AnalysisRunStatus.SUCCEEDED
        assert run.support_tier is SupportTier.D
        # Only summary + diagnostics artifacts
        assert set(run.artifacts_index.keys()) <= {"summary", "diagnostics"}

    def test_pipeline_exception_marks_failed(self, sqlite_conn, tmp_path):
        def boom(session_id, workspace_id):
            raise RuntimeError("kaboom")

        orch = AnalysisOrchestrator(
            conn_factory=lambda: sqlite_conn,
            artifacts_base_dir=tmp_path,
            run_pipeline_fn=boom,
            evaluate_release_fn=MagicMock(),
            calibration_registry=None,
        )
        run_id = orch.enqueue(session_id=10, workspace_id=1)
        orch.execute(run_id)

        repo = AnalysisRunRepository(sqlite_conn)
        run = repo.get(run_id)
        assert run.status is AnalysisRunStatus.FAILED
        assert run.error_code == "INTERNAL_ERROR"
        assert "kaboom" in run.error_message
