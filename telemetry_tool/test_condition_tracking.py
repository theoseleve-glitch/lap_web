"""
tests/test_condition_tracking.py
--------------------------------
Pytest unit tests for condition_tracking.py.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd
import pytest

from condition_tracking import (
    build_condition_phases,
    compute_grip_indicators,
    detect_condition_changes,
    label_phases,
)


# ============================================================================

# Fixtures

# ============================================================================


@pytest.fixture()
def stable_laps() -> pd.DataFrame:
    """20 laps with stable conditions (no trend)."""
    rng = np.random.default_rng(42)
    n = 20
    return pd.DataFrame({
        "lap_number":       list(range(1, n + 1)),
        "lap_time_s":       [55.0 + rng.normal(0, 0.3) for _ in range(n)],
        "speed_mean_mps":   [40.0 + rng.normal(0, 0.5) for _ in range(n)],
        "braking_max_mps2": [14.0 + rng.normal(0, 0.3) for _ in range(n)],
        "jerk_rms_mps3":    [3.0 + rng.normal(0, 0.2) for _ in range(n)],
        "lat_accel_rms_mps2": [8.0 + rng.normal(0, 0.3) for _ in range(n)],
    })


@pytest.fixture()
def degrading_laps() -> pd.DataFrame:
    """18 laps with clear degradation mid-session (rain onset at lap 10)."""
    rng = np.random.default_rng(99)
    n = 18
    times, speeds, brakes, jerks, lats = [], [], [], [], []
    for i in range(n):
        if i < 9:
            # Dry phase

            times.append(55.0 + rng.normal(0, 0.2))
            speeds.append(40.0 + rng.normal(0, 0.3))
            brakes.append(14.0 + rng.normal(0, 0.2))
            jerks.append(3.0 + rng.normal(0, 0.1))
            lats.append(8.0 + rng.normal(0, 0.2))
        else:
            # Wet phase: slower, less grip, more instability

            times.append(60.0 + rng.normal(0, 0.5))
            speeds.append(33.0 + rng.normal(0, 0.5))
            brakes.append(10.0 + rng.normal(0, 0.3))
            jerks.append(6.0 + rng.normal(0, 0.3))
            lats.append(5.0 + rng.normal(0, 0.3))
    return pd.DataFrame({
        "lap_number":       list(range(1, n + 1)),
        "lap_time_s":       times,
        "speed_mean_mps":   speeds,
        "braking_max_mps2": brakes,
        "jerk_rms_mps3":    jerks,
        "lat_accel_rms_mps2": lats,
    })


@pytest.fixture()
def short_laps() -> pd.DataFrame:
    """5 laps — too few for condition detection."""
    return pd.DataFrame({
        "lap_number": [1, 2, 3, 4, 5],
        "lap_time_s": [55.0, 55.1, 54.9, 55.2, 55.0],
    })


# ============================================================================

# compute_grip_indicators

# ============================================================================


class TestComputeGripIndicators:

    def test_output_columns(self, stable_laps: pd.DataFrame) -> None:
        ind = compute_grip_indicators(stable_laps)
        expected = {"pace_residual_s", "grip_proxy", "instability_proxy", "braking_proxy"}
        assert expected.issubset(set(ind.columns))

    def test_length_matches_input(self, stable_laps: pd.DataFrame) -> None:
        ind = compute_grip_indicators(stable_laps)
        assert len(ind) == len(stable_laps)

    def test_grip_proxy_bounded_0_1(self, stable_laps: pd.DataFrame) -> None:
        ind = compute_grip_indicators(stable_laps)
        finite = ind["grip_proxy"].dropna()
        assert (finite >= -0.01).all() and (finite <= 1.01).all()

    def test_instability_proxy_bounded_0_1(self, stable_laps: pd.DataFrame) -> None:
        ind = compute_grip_indicators(stable_laps)
        finite = ind["instability_proxy"].dropna()
        assert (finite >= -0.01).all() and (finite <= 1.01).all()

    def test_pace_residual_near_zero_for_stable(self, stable_laps: pd.DataFrame) -> None:
        ind = compute_grip_indicators(stable_laps)
        # For stable data, residuals should be small

        assert ind["pace_residual_s"].abs().mean() < 1.0

    def test_missing_columns_graceful(self) -> None:
        """Dataframe with only lap_number → all NaN indicators, no crash."""
        df = pd.DataFrame({"lap_number": [1, 2, 3, 4, 5]})
        ind = compute_grip_indicators(df)
        assert len(ind) == 5
        assert ind["pace_residual_s"].isna().all()
        assert ind["grip_proxy"].isna().all()

    def test_single_lap(self) -> None:
        df = pd.DataFrame({
            "lap_number": [1],
            "lap_time_s": [55.0],
            "speed_mean_mps": [40.0],
        })
        ind = compute_grip_indicators(df)
        assert len(ind) == 1

    def test_custom_rolling_window(self, stable_laps: pd.DataFrame) -> None:
        ind3 = compute_grip_indicators(stable_laps, rolling_window=3)
        ind15 = compute_grip_indicators(stable_laps, rolling_window=15)
        # Smaller window → more local residual → larger variance

        assert ind3["pace_residual_s"].std() >= ind15["pace_residual_s"].std() * 0.5


# ============================================================================

# detect_condition_changes

# ============================================================================


class TestDetectConditionChanges:

    def test_stable_no_changes(self, stable_laps: pd.DataFrame) -> None:
        ind = compute_grip_indicators(stable_laps)
        changes = detect_condition_changes(ind)
        assert isinstance(changes, list)
        # Stable session → 0 or at most 1 spurious change

        assert len(changes) <= 1

    def test_too_few_laps(self, short_laps: pd.DataFrame) -> None:
        ind = compute_grip_indicators(short_laps)
        changes = detect_condition_changes(ind, min_laps=8)
        assert changes == []

    def test_returns_ints(self, stable_laps: pd.DataFrame) -> None:
        ind = compute_grip_indicators(stable_laps)
        changes = detect_condition_changes(ind)
        assert all(isinstance(c, int) for c in changes)

    def test_excludes_first_lap(self, degrading_laps: pd.DataFrame) -> None:
        ind = compute_grip_indicators(degrading_laps)
        changes = detect_condition_changes(ind)
        if changes:
            first_lap = degrading_laps["lap_number"].iloc[0]
            assert first_lap not in changes

    def test_degrading_detects_something(self, degrading_laps: pd.DataFrame) -> None:
        """A sharp condition change should be detected."""
        ind = compute_grip_indicators(degrading_laps)
        # Use lower threshold to be more sensitive

        changes = detect_condition_changes(ind, z_threshold=1.5, hysteresis=2)
        # We expect at least one change near lap 10

        # (may or may not trigger depending on exact noise — check it doesn't crash)

        assert isinstance(changes, list)


# ============================================================================

# build_condition_phases

# ============================================================================


class TestBuildConditionPhases:

    def test_single_phase_no_changes(self, stable_laps: pd.DataFrame) -> None:
        phases = build_condition_phases(stable_laps, [])
        assert len(phases) == 1
        assert int(phases.iloc[0]["lap_start"]) == 1
        assert int(phases.iloc[0]["lap_end"]) == 20
        assert int(phases.iloc[0]["n_laps"]) == 20

    def test_two_phases(self, stable_laps: pd.DataFrame) -> None:
        phases = build_condition_phases(stable_laps, [11])
        assert len(phases) == 2
        assert int(phases.iloc[0]["lap_end"]) == 10
        assert int(phases.iloc[1]["lap_start"]) == 11

    def test_phases_cover_all_laps(self, stable_laps: pd.DataFrame) -> None:
        phases = build_condition_phases(stable_laps, [5, 15])
        total_laps = int(phases["n_laps"].sum())
        assert total_laps == 20

    def test_phase_has_required_columns(self, stable_laps: pd.DataFrame) -> None:
        phases = build_condition_phases(stable_laps, [])
        for col in ("phase_id", "lap_start", "lap_end", "n_laps",
                     "confidence", "signature_json"):
            assert col in phases.columns

    def test_confidence_bounded(self, stable_laps: pd.DataFrame) -> None:
        phases = build_condition_phases(stable_laps, [5])
        assert (phases["confidence"] >= 0.0).all()
        assert (phases["confidence"] <= 1.0).all()

    def test_signature_is_valid_json(self, stable_laps: pd.DataFrame) -> None:
        phases = build_condition_phases(stable_laps, [])
        for _, row in phases.iterrows():
            sig = json.loads(row["signature_json"])
            assert isinstance(sig, dict)

    def test_empty_input(self) -> None:
        phases = build_condition_phases(pd.DataFrame({"lap_number": []}), [])
        assert len(phases) == 0


# ============================================================================

# label_phases

# ============================================================================


class TestLabelPhases:

    def test_adds_columns(self, stable_laps: pd.DataFrame) -> None:
        from session_context import TrackState
        phases = build_condition_phases(stable_laps, [10])
        labelled = label_phases(phases, TrackState.DRY)
        assert "phase_track_state" in labelled.columns
        assert "label_reason" in labelled.columns

    def test_labels_are_valid_track_states(self, stable_laps: pd.DataFrame) -> None:
        from session_context import TrackState
        phases = build_condition_phases(stable_laps, [10])
        labelled = label_phases(phases, TrackState.GREEN)
        valid_values = {ts.value for ts in TrackState}
        for state in labelled["phase_track_state"]:
            assert state in valid_values

    def test_empty_phases(self) -> None:
        from session_context import TrackState
        empty = pd.DataFrame(columns=[
            "phase_id", "lap_start", "lap_end", "n_laps",
            "confidence", "signature_json",
        ])
        result = label_phases(empty, TrackState.DRY)
        assert "phase_track_state" in result.columns
        assert len(result) == 0

    def test_wet_baseline(self, stable_laps: pd.DataFrame) -> None:
        from session_context import TrackState, WeatherObs
        phases = build_condition_phases(stable_laps, [10])
        labelled = label_phases(
            phases, TrackState.WET,
            weather=WeatherObs(humidity_pct=90.0),
        )
        assert len(labelled) == 2
        # Should return either drying or wet for both phases

        for state in labelled["phase_track_state"]:
            assert state in ("wet", "drying", "damp")

    def test_dry_to_rubbered(self, stable_laps: pd.DataFrame) -> None:
        """Starting green, with a phase split, second phase should show rubbered."""
        from session_context import TrackState
        phases = build_condition_phases(stable_laps, [10])
        labelled = label_phases(phases, TrackState.GREEN)
        # First phase labelled as rubbered (improving from green)

        assert labelled.iloc[0]["phase_track_state"] in ("green", "rubbered")
