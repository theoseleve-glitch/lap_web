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

def _make_surface(has_grip: bool = True, mu_val: float = 0.9,
                  boundary_source: str = "gt_anchored_native",
                  quality_tier: str = "gold"):
    """Build a minimal mock TrackSurface.

    Defaults (gt_anchored_native geometry + gold grip) make the honesty layer
    resolve to ``optimal_line`` when validation is green; override to exercise
    the degraded tiers.
    """
    surf = MagicMock()
    if has_grip:
        grip = MagicMock()
        grip.mu_grid = np.full((10, 10), mu_val, dtype=np.float32)
        grip.count_grid = np.ones((10, 10), dtype=np.int32) * 15
        grip.confidence = np.full((10, 10), 0.8, dtype=np.float32)
        surf.grip_2d = grip
    else:
        surf.grip_2d = None
    # Real strings so honesty.decide_tier is deterministic (a bare MagicMock
    # attr would compare unequal to every tier string and mis-degrade).
    surf.boundary_source = boundary_source
    surf.quality_tier = quality_tier
    # Explicitly None so the wet solve does not attempt compute_drainage on a Mock
    surf.elevation_surface = None
    return surf


# Conditions the task solves, in order (dry measured, damp measured, wet inverted).
_CONDITIONS = {"dry", "damp", "wet"}


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

@patch.object(rlt, "_validate_solution_safe", return_value=(True, {"passed": True}))
@patch.object(rlt, "get_maint_connection", return_value=MagicMock())
@patch.object(rlt, "return_pg_connection")
@patch.object(rlt, "get_racing_lines", return_value=[])
@patch.object(rlt, "upsert_racing_line")
@patch.object(rlt, "set_racing_line_status")
@patch.object(rlt, "load_track_model")
@patch.object(rlt, "solve_optimal_line_2d")
def test_writes_all_conditions_with_optimal_tier(msolve, mload, mstatus, mupsert, mget_lines, *_):
    sol = _make_sol("Solve_Succeeded")
    msolve.return_value = sol
    mload.return_value = _make_surface(has_grip=True)  # gt_anchored_native + gold

    result = rlt._compute_racing_lines_impl("KCT", "generic")

    # All three conditions solved (dry + damp + wet)
    assert set(result["ok"]) == _CONDITIONS
    assert result["failed"] == []
    assert msolve.call_count == 3
    assert mupsert.call_count == 3
    mstatus.assert_not_called()
    # Honesty: GT geometry + gold grip + validation green -> optimal_line, with
    # provenance carrying the audit.
    for call in mupsert.call_args_list:
        assert call.kwargs["tier"] == "optimal_line"
        assert call.kwargs["geometry_source"] == "gt_anchored_native"
        assert "laps_used" in call.kwargs["provenance"]


@patch.object(rlt, "_validate_solution_safe", return_value=(False, {"passed": False}))
@patch.object(rlt, "get_maint_connection", return_value=MagicMock())
@patch.object(rlt, "return_pg_connection")
@patch.object(rlt, "get_racing_lines", return_value=[])
@patch.object(rlt, "upsert_racing_line")
@patch.object(rlt, "set_racing_line_status")
@patch.object(rlt, "load_track_model")
@patch.object(rlt, "solve_optimal_line_2d")
def test_validation_red_degrades_to_speed_profile_only(msolve, mload, mstatus, mupsert, mget_lines, *_):
    """Even on GT+gold, a red physics validation must NOT be labelled optimal_line."""
    msolve.return_value = _make_sol("Solve_Succeeded")
    mload.return_value = _make_surface(has_grip=True)

    rlt._compute_racing_lines_impl("KCT", "generic")

    for call in mupsert.call_args_list:
        assert call.kwargs["tier"] == "speed_profile_only"
        assert call.kwargs["provenance"].get("tier_reason") == "validation_red"


@patch.object(rlt, "_validate_solution_safe", return_value=(True, {"passed": True}))
@patch.object(rlt, "get_maint_connection", return_value=MagicMock())
@patch.object(rlt, "return_pg_connection")
@patch.object(rlt, "get_racing_lines", return_value=[])
@patch.object(rlt, "upsert_racing_line")
@patch.object(rlt, "set_racing_line_status")
@patch.object(rlt, "load_track_model")
@patch.object(rlt, "solve_optimal_line_2d")
def test_predicted_geometry_degrades_to_speed_profile_only(msolve, mload, mstatus, mupsert, mget_lines, *_):
    """Derived (non-GT) geometry can never be an optimal_line, even if all else is green."""
    msolve.return_value = _make_sol("Solve_Succeeded")
    mload.return_value = _make_surface(has_grip=True, boundary_source="predicted")

    rlt._compute_racing_lines_impl("KCT", "generic")

    for call in mupsert.call_args_list:
        assert call.kwargs["tier"] == "speed_profile_only"


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

    assert set(result["failed"]) == _CONDITIONS
    assert result["ok"] == []
    mupsert.assert_not_called()
    # set_racing_line_status called for every condition, each marked refused
    assert mstatus.call_count == 3
    for call in mstatus.call_args_list:
        assert call.kwargs.get("tier") == "refused"


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
        {"condition": "damp", "grip_snapshot_hash": snap},
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

@patch.object(rlt, "_validate_solution_safe", return_value=(True, {"passed": True}))
@patch.object(rlt, "get_maint_connection", return_value=MagicMock())
@patch.object(rlt, "return_pg_connection")
@patch.object(rlt, "get_racing_lines", return_value=[])
@patch.object(rlt, "upsert_racing_line")
@patch.object(rlt, "set_racing_line_status")
@patch.object(rlt, "load_track_model")
@patch.object(rlt, "solve_optimal_line_2d")
def test_partial_grip_dry_ok_others_failed(msolve, mload, mstatus, mupsert, mget_lines, *_):
    # dry has grip; damp + wet do not -> only dry solves, the rest degrade.
    mload.side_effect = [
        _make_surface(has_grip=True),
        _make_surface(has_grip=False),
        _make_surface(has_grip=False),
    ]
    msolve.return_value = _make_sol("Solve_Succeeded")

    result = rlt._compute_racing_lines_impl("OVAL", "generic")

    assert "dry" in result["ok"]
    assert {"damp", "wet"} <= set(result["failed"])
    assert msolve.call_count == 1   # only dry solved
    assert mupsert.call_count == 1
    assert mstatus.call_count == 2  # damp + wet marked failed
