"""Tests for Task 2.6: debounced racing-line trigger after grip upsert.

The trigger lives inside run_full_analysis (step 09j) and is guarded so that:
  - compute_racing_lines.apply_async is called once when _ts_updated > 0.
  - it is NOT called when _ts_updated == 0 (grip unchanged).
  - a broker/import failure in the enqueue path never propagates out of the
    pipeline (non-fatal try/except).

All external boundaries (PG, Celery broker, track_surface store) are mocked so
the suite runs locally without infrastructure, following the pattern in
test_racing_line_tasks.py and test_grip_pipeline.py.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from pipeline.orchestrator import _RACING_LINE_DEBOUNCE_S  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_csv(tmp_path: Path, n_laps: int = 8) -> Path:
    """Build a minimal RaceChrono-style CSV that yields a non-None grip_map."""
    rng = np.random.default_rng(42)
    n_per_lap = 200
    lap_length = 500.0
    frames = []
    for lap in range(1, n_laps + 1):
        t_start = (lap - 1) * 30.0
        t = np.linspace(t_start, t_start + 25.0, n_per_lap)
        dist = np.linspace(0, lap_length, n_per_lap)
        speed = np.full(n_per_lap, 20.0) + rng.normal(0, 0.5, n_per_lap)
        lat = np.linspace(45.0, 45.002, n_per_lap) + rng.normal(0, 1e-5, n_per_lap)
        lon = np.linspace(9.0, 9.002, n_per_lap) + rng.normal(0, 1e-5, n_per_lap)
        mu = np.where(dist < lap_length / 2, 1.3, 0.7)
        lat_g = (
            mu
            * rng.choice([-1, 1], n_per_lap)
            * (0.8 + rng.uniform(0, 0.2, n_per_lap))
        )
        frames.append(
            pd.DataFrame(
                {
                    "Lap #": np.full(n_per_lap, lap),
                    "Time (s)": t,
                    "Distance (m)": dist + (lap - 1) * lap_length,
                    "Speed (m/s)": speed,
                    "Latitude (deg)": lat,
                    "Longitude (deg)": lon,
                    "Bearing (deg)": np.full(n_per_lap, 90.0)
                    + rng.normal(0, 1, n_per_lap),
                    "Longitudinal acceleration (G) *calc": rng.normal(
                        0, 0.02, n_per_lap
                    ),
                    "Lateral acceleration (G) *calc": lat_g,
                }
            )
        )
    pd.concat(frames, ignore_index=True).to_csv(tmp_path / "trigger_test.csv", index=False)
    return tmp_path / "trigger_test.csv"


def _pg_patches(upsert_session_return_value: int):
    """Return a list of context managers that mock all PG/broker boundaries."""
    mock_conn = MagicMock()
    # Make fetchall / fetchone return empty iterables so DB-reading code is safe
    mock_conn.execute.return_value.fetchone.return_value = None
    mock_conn.execute.return_value.fetchall.return_value = []
    mock_conn.execute.return_value.description = []
    return [
        patch.dict(os.environ, {"USE_PG": "1"}),
        patch("web.db.get_db_connection", return_value=mock_conn),
        patch("track_surface.upsert_session_grip", return_value=upsert_session_return_value),
        patch("track_surface.upsert_global_grip"),
        patch("track_surface.persistence.save_snapshot"),
    ]


# ---------------------------------------------------------------------------
# Test 1: grip changed (_ts_updated > 0) → task enqueued once with right args
# ---------------------------------------------------------------------------

def test_enqueues_once_after_grip_change(tmp_path):
    """apply_async is called exactly once with (track_id, vehicle_class) + countdown."""
    import pipeline

    csv = _make_csv(tmp_path)

    with (
        patch("track_surface.upsert_session_grip", return_value=3),
        patch("track_surface.upsert_global_grip"),
        patch("track_surface.persistence.save_snapshot"),
        patch("web.db.get_db_connection", return_value=MagicMock(
            **{
                "execute.return_value.fetchone.return_value": None,
                "execute.return_value.fetchall.return_value": [],
                "execute.return_value.description": [],
            }
        )),
        patch.dict(os.environ, {"USE_PG": "1"}),
        patch("tasks.racing_line_tasks.compute_racing_lines") as mock_task,
    ):
        summary = pipeline.run_full_analysis(
            str(csv),
            {"track_id": "KCT", "vehicle_class": "car"},
            enable_ml=False,
            enable_report=False,
        )

    mock_task.apply_async.assert_called_once()
    args, kwargs = mock_task.apply_async.call_args
    # track_id may be resolved/rewritten by the pipeline (track matcher);
    # verify it matches what the pipeline actually settled on.
    resolved_track_id = summary.get("track_id", "unknown_track")
    assert args[0] == (resolved_track_id, "car"), (
        f"Expected ({resolved_track_id!r}, 'car'), got {args[0]}"
    )
    assert "countdown" in kwargs, "countdown kwarg missing"
    assert kwargs["countdown"] == _RACING_LINE_DEBOUNCE_S


# ---------------------------------------------------------------------------
# Test 2: grip unchanged (_ts_updated == 0) → task NOT enqueued
# ---------------------------------------------------------------------------

def test_no_enqueue_when_grip_unchanged(tmp_path):
    """When upsert_session_grip returns 0, apply_async must not be called."""
    import pipeline

    csv = _make_csv(tmp_path)

    with (
        patch("track_surface.upsert_session_grip", return_value=0),
        patch("track_surface.upsert_global_grip"),
        patch("track_surface.persistence.save_snapshot"),
        patch("web.db.get_db_connection", return_value=MagicMock(
            **{
                "execute.return_value.fetchone.return_value": None,
                "execute.return_value.fetchall.return_value": [],
                "execute.return_value.description": [],
            }
        )),
        patch.dict(os.environ, {"USE_PG": "1"}),
        patch("tasks.racing_line_tasks.compute_racing_lines") as mock_task,
    ):
        pipeline.run_full_analysis(
            str(csv),
            {"track_id": "KCT", "vehicle_class": "car"},
            enable_ml=False,
            enable_report=False,
        )

    mock_task.apply_async.assert_not_called()


# ---------------------------------------------------------------------------
# Test 3: broker failure in enqueue path → pipeline still returns (non-fatal)
# ---------------------------------------------------------------------------

def test_enqueue_failure_is_non_fatal(tmp_path):
    """A ConnectionError from apply_async must not propagate; pipeline completes."""
    import pipeline

    csv = _make_csv(tmp_path)

    broken_task = MagicMock()
    broken_task.apply_async.side_effect = ConnectionError("broker down")

    with (
        patch("track_surface.upsert_session_grip", return_value=5),
        patch("track_surface.upsert_global_grip"),
        patch("track_surface.persistence.save_snapshot"),
        patch("web.db.get_db_connection", return_value=MagicMock(
            **{
                "execute.return_value.fetchone.return_value": None,
                "execute.return_value.fetchall.return_value": [],
                "execute.return_value.description": [],
            }
        )),
        patch.dict(os.environ, {"USE_PG": "1"}),
        patch("tasks.racing_line_tasks.compute_racing_lines", broken_task),
    ):
        # Must complete without raising
        result = pipeline.run_full_analysis(
            str(csv),
            {"track_id": "KCT", "vehicle_class": "car"},
            enable_ml=False,
            enable_report=False,
        )

    # Pipeline returned normally despite broker failure
    assert isinstance(result, dict), "run_full_analysis must return a dict"
    # apply_async was attempted (broker was called, then raised)
    broken_task.apply_async.assert_called_once()
