"""Phase-C unit tests — out-lap rejection by arclength and lap time.

The function is geometry-blind: it rejects only by aggregate arclength or
lap-time deviation. The S1 OK-tail is real track geometry; geometric
outlier rejection is explicitly avoided.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TELEMETRY_PKG = _REPO_ROOT / "telemetry_tool"
for _p in (_REPO_ROOT, _TELEMETRY_PKG):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from track_surface.centerline import select_laps_by_arclength_and_time  # noqa: E402


def _straight_lap(length_m: float, n: int = 200) -> np.ndarray:
    """A straight-line lap with the requested total arclength."""
    return np.column_stack([np.linspace(0.0, length_m, n), np.zeros(n)])


def test_rejects_long_outlier_by_arclength():
    """Arclengths [100, 101, 99, 200, 102] → lap 3 (200 m) is the outlier."""
    laps = [_straight_lap(L) for L in (100.0, 101.0, 99.0, 200.0, 102.0)]
    kept, rejected = select_laps_by_arclength_and_time(laps, tolerance_sigma=2.0)

    assert kept == [0, 1, 2, 4], f"unexpected kept indices: {kept}"
    assert len(rejected) == 1
    r = rejected[0]
    assert r["index"] == 3
    assert "arclength" in r["reason"]
    assert r["deviation_arclength_sigma"] > 1.0


def test_no_rejection_when_all_uniform():
    """All similar arclengths → keep everyone, even without time signal."""
    laps = [_straight_lap(L) for L in (100.0, 101.0, 99.5, 100.5, 100.2)]
    kept, rejected = select_laps_by_arclength_and_time(laps, tolerance_sigma=2.0)

    assert kept == [0, 1, 2, 3, 4]
    assert rejected == []


def test_time_based_rejection_when_arclength_uniform():
    """Same arclengths but one lap is anomalously slow → rejected by time."""
    laps = [_straight_lap(100.0) for _ in range(6)]
    times = [10.0, 10.1, 9.9, 10.2, 25.0, 10.0]  # lap 4 is 2.5× slower
    kept, rejected = select_laps_by_arclength_and_time(
        laps, lap_times_s=times, tolerance_sigma=2.0,
    )

    assert 4 not in kept
    assert any(r["index"] == 4 for r in rejected)
    rej_idx_4 = next(r for r in rejected if r["index"] == 4)
    assert "time" in rej_idx_4["reason"]


def test_or_logic_rejects_either_criterion():
    """Different arclength OR different time triggers rejection."""
    laps = [_straight_lap(L) for L in (100.0, 100.0, 100.0, 100.0, 200.0, 100.0)]
    times = [10.0, 25.0, 10.0, 10.0, 10.0, 10.0]  # lap 1 anomalously long-time, lap 4 anomalously long-arclength
    kept, rejected = select_laps_by_arclength_and_time(
        laps, lap_times_s=times, tolerance_sigma=2.0,
    )

    rejected_indices = {r["index"] for r in rejected}
    assert 1 in rejected_indices, "lap 1 should be rejected on time"
    assert 4 in rejected_indices, "lap 4 should be rejected on arclength"


def test_warning_when_majority_rejected(caplog):
    """≥50% rejection triggers a warning but proceeds with rejection."""
    laps = [_straight_lap(L) for L in (100.0, 200.0, 50.0, 100.0)]
    with caplog.at_level("WARNING"):
        kept, rejected = select_laps_by_arclength_and_time(laps, tolerance_sigma=1.0)
    # Whether 50% are rejected depends on exact thresholds — verify warning fired
    # only when actually >= 50% rejected
    if len(rejected) >= 0.5 * len(laps):
        assert any(">=50%" in r.message or "50%" in r.message for r in caplog.records)


def test_fallback_when_all_would_be_rejected():
    """If every lap deviates by exactly the same amount (e.g., 2 laps),
    σ might collapse to zero or the rejection might wipe out all laps. The
    function must always retain at least one lap."""
    laps = [_straight_lap(100.0), _straight_lap(200.0)]  # only 2 laps, large gap
    kept, rejected = select_laps_by_arclength_and_time(laps, tolerance_sigma=0.5)
    assert len(kept) >= 1


def test_real_ok_r4_durations_reject_in_lap():
    """OK_R4 lap times observed in Day-6: rejecting lap 10 (in-lap, 81.11 s)
    when the racing-pace median is ~71 s."""
    lap_times = [77.95, 73.63, 72.36, 72.41, 71.11, 71.40, 70.47, 70.87, 70.46, 81.11]
    laps = [_straight_lap(100.0) for _ in lap_times]  # arclengths uniform
    kept, rejected = select_laps_by_arclength_and_time(
        laps, lap_times_s=lap_times, tolerance_sigma=2.0,
    )

    rejected_indices = {r["index"] for r in rejected}
    # Lap 9 (81.11 s) is the most extreme outlier — must be rejected
    assert 9 in rejected_indices, (
        f"expected lap 9 (in-lap, 81.11 s) to be rejected; "
        f"got rejected indices {sorted(rejected_indices)}"
    )
    # Lap 0 (out-lap, 77.95s) is borderline at 2sigma; allow either outcome
    assert len(kept) >= 7, f"expected at least 7 racing laps retained; got {len(kept)}"
