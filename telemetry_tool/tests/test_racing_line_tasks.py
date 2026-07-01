"""Tests for compute_racing_lines Celery task (Task 2.5).

All external boundaries (solver, repo, DB) are mocked so the suite runs
locally without PG, Redis, or CasADi.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# Ensure telemetry_tool/ is on sys.path for internal imports (celery_app,
# web.db_pg, track_surface.*) even when pytest is invoked from the repo root.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import telemetry_tool.tasks.racing_line_tasks as rlt  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_surface(has_grip: bool = True, mu_val: float = 0.9):
    """Build a minimal mock TrackSurface."""
    surf = MagicMock()
    if has_grip:
        grip = MagicMock()
        grip.mu_grid = np.full((10, 10), mu_val, dtype=np.float32)
        grip.count_grid = np.ones((10, 10), dtype=np.int32) * 15
        surf.grip_2d = grip
    else:
        surf.grip_2d = None
    # Explicitly None so the wet solve does not attempt compute_drainage on a Mock
    surf.elevation_surface = None
    return surf


def _make_sol(status: str = "Solve_Succeeded"):
    """Build a minimal mock solution object."""
    sol = MagicMock()
    n = 50
    sol.distance_m = np.linspace(0, 100, n)
    sol.lateral_offset_m = np.zeros(n)
    sol.speed_mps = np.full(n, 30.0)
    sol.solver_status = status
    sol.solver_time_s = 1.5
    sol.optimal_lap_time_s = 42.0
    return sol


# ---------------------------------------------------------------------------
# Test 1 (from brief verbatim): grip_2d None → failed, never calls solver
# ---------------------------------------------------------------------------

@patch.object(rlt, "get_maint_connection", return_value=MagicMock())
@patch.object(rlt, "return_pg_connection")
@patch.object(rlt, "upsert_racing_line")
@patch.object(rlt, "set_racing_line_status")
@patch.object(rlt, "load_track_model")
@patch.object(rlt, "solve_optimal_line_2d")
def test_degrades_to_failed_when_insufficient_laps(msolve, mload, mstatus, mupsert, *_):
    surf = MagicMock()
    surf.grip_2d = None
    mload.return_value = surf
    result = rlt._compute_racing_lines_impl("T1", "generic")
    # grip_2d None => never solves, marks failed, never raises
    msolve.assert_not_called()
    assert mstatus.called


# ---------------------------------------------------------------------------
# Test 2: successful dry + wet solve
# ---------------------------------------------------------------------------

@patch.object(rlt, "get_maint_connection", return_value=MagicMock())
@patch.object(rlt, "return_pg_connection")
@patch.object(rlt, "get_racing_lines", return_value=[])
@patch.object(rlt, "upsert_racing_line")
@patch.object(rlt, "set_racing_line_status")
@patch.object(rlt, "load_track_model")
@patch.object(rlt, "solve_optimal_line_2d")
def test_writes_dry_and_wet(msolve, mload, mstatus, mupsert, mget_lines, *_):
    sol = _make_sol("Solve_Succeeded")
    msolve.return_value = sol
    mload.return_value = _make_surface(has_grip=True)

    result = rlt._compute_racing_lines_impl("KCT", "generic")

    # Both conditions solved
    assert set(result["ok"]) == {"dry", "wet"}
    assert result["failed"] == []
    # Solver called once per condition (dry + wet)
    assert msolve.call_count == 2
    # Upsert called once per condition
    assert mupsert.call_count == 2
    # No failed status written
    mstatus.assert_not_called()


# ---------------------------------------------------------------------------
# Test 3: solver raises → degrades to failed (never re-raises)
# ---------------------------------------------------------------------------

@patch.object(rlt, "get_maint_connection", return_value=MagicMock())
@patch.object(rlt, "return_pg_connection")
@patch.object(rlt, "get_racing_lines", return_value=[])
@patch.object(rlt, "upsert_racing_line")
@patch.object(rlt, "set_racing_line_status")
@patch.object(rlt, "load_track_model")
@patch.object(rlt, "solve_optimal_line_2d")
def test_solver_error_degrades_to_failed(msolve, mload, mstatus, mupsert, *_):
    msolve.side_effect = ValueError("infeasible NLP")
    mload.return_value = _make_surface(has_grip=True)

    result = rlt._compute_racing_lines_impl("MKR", "generic")

    assert result["failed"] == ["dry", "wet"]
    assert result["ok"] == []
    mupsert.assert_not_called()
    # set_racing_line_status called for both conditions
    assert mstatus.call_count == 2


# ---------------------------------------------------------------------------
# Test 4: grip hash unchanged → no-op (skip)
# ---------------------------------------------------------------------------

@patch.object(rlt, "get_maint_connection", return_value=MagicMock())
@patch.object(rlt, "return_pg_connection")
@patch.object(rlt, "upsert_racing_line")
@patch.object(rlt, "set_racing_line_status")
@patch.object(rlt, "load_track_model")
@patch.object(rlt, "solve_optimal_line_2d")
@patch.object(rlt, "get_racing_lines")
def test_skips_when_hash_unchanged(mget_lines, msolve, mload, mstatus, mupsert, *_):
    surface = _make_surface(has_grip=True)
    mload.return_value = surface

    # Pre-compute the hash the task will compute
    snap = rlt._grip_hash(surface.grip_2d)

    # Pretend both conditions already have this hash stored
    mget_lines.return_value = [
        {"condition": "dry", "grip_snapshot_hash": snap},
        {"condition": "wet", "grip_snapshot_hash": snap},
    ]

    result = rlt._compute_racing_lines_impl("KCT", "generic")

    # No changes — solver and upsert should be skipped
    msolve.assert_not_called()
    mupsert.assert_not_called()
    mstatus.assert_not_called()
    assert result["ok"] == []
    assert result["failed"] == []


# ---------------------------------------------------------------------------
# Test 5: grip_2d None for one condition, ok for the other
# ---------------------------------------------------------------------------

@patch.object(rlt, "get_maint_connection", return_value=MagicMock())
@patch.object(rlt, "return_pg_connection")
@patch.object(rlt, "get_racing_lines", return_value=[])
@patch.object(rlt, "upsert_racing_line")
@patch.object(rlt, "set_racing_line_status")
@patch.object(rlt, "load_track_model")
@patch.object(rlt, "solve_optimal_line_2d")
def test_partial_grip_dry_ok_wet_failed(msolve, mload, mstatus, mupsert, *_):
    dry_surface = _make_surface(has_grip=True)
    wet_surface = _make_surface(has_grip=False)
    mload.side_effect = [dry_surface, wet_surface]
    msolve.return_value = _make_sol("Solve_Succeeded")

    result = rlt._compute_racing_lines_impl("OVAL", "generic")

    assert "dry" in result["ok"]
    assert "wet" in result["failed"]
    assert msolve.call_count == 1   # only dry solved
    assert mupsert.call_count == 1
    # set_racing_line_status called once (for wet)
    mstatus.assert_called_once()
