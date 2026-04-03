"""Tests for the Lap Oracle orchestrator and final report."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from telemetry_tool.lap_oracle.config import OracleConfig
from telemetry_tool.lap_oracle.data_lake import DataLake
from telemetry_tool.lap_oracle.orchestrator import Orchestrator
from telemetry_tool.lap_oracle.report import generate_final_report


@pytest.fixture()
def tmp_config(tmp_path: Path) -> OracleConfig:
    """OracleConfig pointing at a temporary directory."""
    return OracleConfig(
        data_dir=tmp_path / "oracle",
        db_path=tmp_path / "oracle" / "oracle.db",
        run_hours=0.01,  # ~36 seconds
        harvest_workers=1,
        identify_workers=1,
        solve_workers=1,
        sweep_workers=1,
        enable_ac_driver=False,
        enable_neural_training=False,
    )


@pytest.fixture()
def tmp_lake(tmp_config: OracleConfig) -> DataLake:
    """DataLake backed by a temporary directory."""
    return DataLake(tmp_config)


# ── Phase scheduling ─────────────────────────────────────────────────


class TestPhaseScheduling:
    """Orchestrator._get_phase returns correct phase for each hour range."""

    @pytest.mark.parametrize(
        "hours, expected",
        [
            (0.0, "harvest"),
            (1.0, "harvest"),
            (1.99, "harvest"),
            (2.0, "identify"),
            (4.0, "identify"),
            (5.99, "identify"),
            (6.0, "solve"),
            (12.0, "solve"),
            (23.99, "solve"),
            (24.0, "full"),
            (30.0, "full"),
            (39.99, "full"),
            (40.0, "refine"),
            (45.0, "refine"),
            (45.99, "refine"),
            (46.0, "report"),
            (47.0, "report"),
            (100.0, "report"),
        ],
    )
    def test_phase_for_hour(self, hours: float, expected: str) -> None:
        assert Orchestrator._get_phase(hours) == expected


# ── Worker spawning ──────────────────────────────────────────────────


class TestEnsureWorkers:
    """Orchestrator creates workers of correct types for each phase."""

    def test_harvest_phase_spawns_harvest_only(
        self, tmp_config: OracleConfig,
    ) -> None:
        orch = Orchestrator(tmp_config)
        orch._ensure_workers_for_phase("harvest")

        types = {w.worker_type for w in orch._workers}
        assert types == {"harvest"}
        assert len(orch._workers) == tmp_config.harvest_workers

    def test_identify_phase_adds_identify(
        self, tmp_config: OracleConfig,
    ) -> None:
        orch = Orchestrator(tmp_config)
        orch._ensure_workers_for_phase("identify")

        types = {w.worker_type for w in orch._workers}
        assert "harvest" in types
        assert "identify" in types

    def test_solve_phase_adds_solve(
        self, tmp_config: OracleConfig,
    ) -> None:
        orch = Orchestrator(tmp_config)
        orch._ensure_workers_for_phase("solve")

        types = {w.worker_type for w in orch._workers}
        assert "harvest" in types
        assert "identify" in types
        assert "solve" in types

    def test_full_phase_adds_sweep(
        self, tmp_config: OracleConfig,
    ) -> None:
        orch = Orchestrator(tmp_config)
        orch._ensure_workers_for_phase("full")

        types = {w.worker_type for w in orch._workers}
        assert "sweep" in types

    def test_ac_driver_spawned_when_enabled(
        self, tmp_config: OracleConfig,
    ) -> None:
        tmp_config.enable_ac_driver = True
        orch = Orchestrator(tmp_config)
        orch._ensure_workers_for_phase("identify")

        types = {w.worker_type for w in orch._workers}
        assert "ac_driver" in types

    def test_no_duplicate_spawns(
        self, tmp_config: OracleConfig,
    ) -> None:
        """Calling _ensure twice does not double the workers."""
        orch = Orchestrator(tmp_config)
        orch._ensure_workers_for_phase("harvest")
        count_1 = len(orch._workers)
        orch._ensure_workers_for_phase("harvest")
        count_2 = len(orch._workers)
        assert count_1 == count_2

    def test_report_phase_spawns_nothing(
        self, tmp_config: OracleConfig,
    ) -> None:
        orch = Orchestrator(tmp_config)
        orch._ensure_workers_for_phase("report")
        assert len(orch._workers) == 0


# ── Progress writing ─────────────────────────────────────────────────


class TestProgressWrite:
    """Orchestrator writes progress.json."""

    def test_progress_file_created(
        self, tmp_config: OracleConfig,
    ) -> None:
        orch = Orchestrator(tmp_config)
        orch._start_time = time.time()
        orch._write_progress("harvest", 0.5)

        progress_path = tmp_config.data_dir / "reports" / "progress.json"
        assert progress_path.exists()

        data = json.loads(progress_path.read_text(encoding="utf-8"))
        assert data["phase"] == "harvest"
        assert data["elapsed_hours"] == 0.5
        assert "solutions" in data
        assert "vehicles" in data
        assert "tracks" in data
        assert "jobs" in data


# ── Quick integration run ────────────────────────────────────────────


class TestQuickRun:
    """Orchestrator with a very short run completes without error."""

    def test_tiny_run_completes(
        self, tmp_config: OracleConfig,
    ) -> None:
        """Run for ~0.01 hours (36s) with mocked workers."""
        tmp_config.run_hours = 0.001  # ~3.6 seconds

        # Patch time.sleep to speed up the loop
        with patch("telemetry_tool.lap_oracle.orchestrator.time.sleep"):
            # Patch worker start to be no-op (avoid real threads)
            with patch.object(
                Orchestrator, "_ensure_workers_for_phase",
            ):
                orch = Orchestrator(tmp_config)
                orch.run()

        # Final report should exist
        report_path = tmp_config.data_dir / "reports" / "final_report.md"
        assert report_path.exists()


# ── Final report ─────────────────────────────────────────────────────


class TestFinalReport:
    """generate_final_report creates a markdown file."""

    def test_report_created(
        self, tmp_config: OracleConfig, tmp_lake: DataLake,
    ) -> None:
        path = generate_final_report(tmp_lake, tmp_config)
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "# Lap Oracle -- Final Report" in content
        assert "## Summary" in content
        assert "## Vehicles Identified" in content
        assert "## Tracks Extracted" in content

    def test_report_includes_counts(
        self, tmp_config: OracleConfig, tmp_lake: DataLake,
    ) -> None:
        path = generate_final_report(tmp_lake, tmp_config)
        content = path.read_text(encoding="utf-8")
        # Empty lake should report 0s
        assert "Solutions computed: 0" in content
        assert "Vehicle models: 0" in content
        assert "Track models: 0" in content

    def test_report_with_jobs(
        self, tmp_config: OracleConfig, tmp_lake: DataLake,
    ) -> None:
        """Report includes job breakdown when jobs exist."""
        tmp_lake.add_job("harvest", sim="ac", car="car1")
        tmp_lake.add_job("solve", sim="ac", car="car1", track="monza")
        tmp_lake.complete_job(1)

        path = generate_final_report(tmp_lake, tmp_config)
        content = path.read_text(encoding="utf-8")
        assert "## Job Breakdown" in content
        assert "harvest" in content
