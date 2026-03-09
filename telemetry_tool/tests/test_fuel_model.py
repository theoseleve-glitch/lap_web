"""Tests for telemetry_tool.physics.fuel_model module."""

import sys
from pathlib import Path

import numpy as np
import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from physics.fuel_model import (
    analyze_fuel_session,
    compute_consumption_stats,
    compute_fuel_corrected_pace,
    detect_fuel_saving_opportunities,
    predict_fuel_remaining,
)

# ===================================================================
# TestFuelCorrectedPace
# ===================================================================

class TestFuelCorrectedPace:
    """Tests for compute_fuel_corrected_pace."""

    def test_heavier_is_slower(self):
        """More fuel = slower raw time; corrected times should equalise."""
        # 5 laps, fuel drops 2 kg/lap from 40 kg
        lap_times = [62.0, 61.9, 61.8, 61.7, 61.6]  # getting faster as fuel drops
        fuel_levels = [40.0, 38.0, 36.0, 34.0, 32.0]
        corrected = compute_fuel_corrected_pace(lap_times, fuel_levels, 0.035)
        # All corrected times normalised to 40 kg
        # Lap 1 has max fuel -> correction = 0
        # Lap 5 correction = 0.035 * (40-32) = 0.28s added
        assert corrected[0] == pytest.approx(62.0, abs=0.01)
        assert corrected[4] > lap_times[4]  # correction added
        # Corrected times should be closer together than raw
        raw_spread = max(lap_times) - min(lap_times)
        corr_spread = max(corrected) - min(corrected)
        assert corr_spread < raw_spread

    def test_no_fuel_change(self):
        """Constant fuel -> same corrected times (correction = 0)."""
        lap_times = [60.0, 60.1, 59.9]
        fuel_levels = [30.0, 30.0, 30.0]
        corrected = compute_fuel_corrected_pace(lap_times, fuel_levels)
        for raw, corr in zip(lap_times, corrected):
            assert corr == pytest.approx(raw, abs=0.001)

    def test_empty_input(self):
        """Empty lists -> empty output."""
        assert compute_fuel_corrected_pace([], []) == []

    def test_mismatched_lengths(self):
        """Shorter list determines output length."""
        corrected = compute_fuel_corrected_pace([60.0, 61.0], [40.0])
        assert len(corrected) == 1

    def test_nan_handling(self):
        """NaN in input -> preserved in output."""
        corrected = compute_fuel_corrected_pace(
            [60.0, float("nan"), 60.0],
            [40.0, 38.0, 36.0],
        )
        assert len(corrected) == 3
        assert np.isnan(corrected[1])


# ===================================================================
# TestFuelPrediction
# ===================================================================

class TestFuelPrediction:
    """Tests for predict_fuel_remaining."""

    def test_linear_consumption(self):
        """Steady 2 kg/lap from 40 kg -> predict correctly."""
        fuel_history = [40.0, 38.0, 36.0, 34.0, 32.0]
        # After 5 more laps at 2 kg/lap: 32 - 10 = 22
        predicted = predict_fuel_remaining(fuel_history, 5)
        assert predicted == pytest.approx(22.0, abs=1.0)

    def test_runs_out(self):
        """Predict negative if fuel will be exhausted."""
        fuel_history = [10.0, 8.0, 6.0, 4.0]
        # At 2 kg/lap, after 5 more laps: 4 - 10 = -6
        predicted = predict_fuel_remaining(fuel_history, 5)
        assert predicted < 0

    def test_empty_history(self):
        """No data -> returns 0."""
        assert predict_fuel_remaining([], 10) == 0.0

    def test_single_entry(self):
        """One entry -> returns 0 (can't fit a line)."""
        assert predict_fuel_remaining([40.0], 10) == 0.0

    def test_zero_target(self):
        """Zero future laps -> current fuel level."""
        fuel_history = [40.0, 38.0, 36.0]
        predicted = predict_fuel_remaining(fuel_history, 0)
        assert predicted == pytest.approx(36.0, abs=0.5)


# ===================================================================
# TestConsumptionStats
# ===================================================================

class TestConsumptionStats:
    """Tests for compute_consumption_stats."""

    def test_basic_stats(self):
        """Known fuel levels -> verify avg, min, max."""
        fuel = [40.0, 38.0, 35.0, 33.0, 31.0]
        # Per-lap: 2, 3, 2, 2 -> avg=2.25, min=2, max=3
        stats = compute_consumption_stats(fuel)
        assert stats["total_consumed"] == pytest.approx(9.0, abs=0.01)
        assert stats["avg_per_lap"] == pytest.approx(2.25, abs=0.01)
        assert stats["min_per_lap"] == pytest.approx(2.0, abs=0.01)
        assert stats["max_per_lap"] == pytest.approx(3.0, abs=0.01)
        assert stats["laps_remaining"] > 0

    def test_single_lap(self):
        """Only one fuel reading -> zero consumption."""
        stats = compute_consumption_stats([40.0])
        assert stats["total_consumed"] == 0.0
        assert stats["avg_per_lap"] == 0.0

    def test_empty_input(self):
        """No data -> zeros."""
        stats = compute_consumption_stats([])
        assert stats["total_consumed"] == 0.0

    def test_constant_fuel(self):
        """No fuel change -> zero consumption."""
        stats = compute_consumption_stats([30.0, 30.0, 30.0])
        assert stats["avg_per_lap"] == 0.0
        assert stats["variance"] == 0.0

    def test_laps_remaining(self):
        """Laps remaining = current / avg_consumption."""
        fuel = [20.0, 18.0, 16.0, 14.0]
        stats = compute_consumption_stats(fuel)
        # avg = 2 kg/lap, remaining = 14/2 = 7 laps
        assert stats["laps_remaining"] == pytest.approx(7.0, abs=0.1)


# ===================================================================
# TestSavingOpportunities
# ===================================================================

class TestSavingOpportunities:
    """Tests for detect_fuel_saving_opportunities."""

    def test_identifies_wasteful_laps(self):
        """One lap with high fuel use but no pace improvement."""
        # Average fuel ~2.0, one lap at 3.0 with no faster time
        lap_times = [60.0, 60.0, 61.0, 60.0, 60.0]
        fuel_per_lap = [2.0, 2.0, 3.0, 2.0, 2.0]
        opps = detect_fuel_saving_opportunities(lap_times, fuel_per_lap)
        assert len(opps) >= 1
        # Lap 3 (1-indexed) is the wasteful one
        assert any(o["lap"] == 3 for o in opps)

    def test_no_waste(self):
        """All laps efficient -> empty list."""
        lap_times = [60.0, 60.0, 60.0, 60.0]
        fuel_per_lap = [2.0, 2.0, 2.0, 2.0]
        opps = detect_fuel_saving_opportunities(lap_times, fuel_per_lap)
        assert opps == []

    def test_fast_lap_not_flagged(self):
        """High fuel on a fast lap should not be flagged."""
        lap_times = [60.0, 60.0, 58.0, 60.0]  # lap 3 is fastest
        fuel_per_lap = [2.0, 2.0, 3.5, 2.0]    # but high fuel on lap 3
        opps = detect_fuel_saving_opportunities(lap_times, fuel_per_lap)
        # Lap 3 is faster than average -> should NOT be flagged
        assert all(o["lap"] != 3 for o in opps)

    def test_empty_input(self):
        """Empty lists -> empty output."""
        assert detect_fuel_saving_opportunities([], []) == []

    def test_single_lap(self):
        """Single lap -> can't compare, empty."""
        opps = detect_fuel_saving_opportunities([60.0], [2.0])
        assert opps == []


# ===================================================================
# TestAnalyzeFuelSession
# ===================================================================

class TestAnalyzeFuelSession:
    """Tests for analyze_fuel_session master function."""

    def test_full_analysis(self):
        """Full session with fuel data."""
        lap_times = [62.0, 61.8, 61.6, 61.4, 61.2]
        fuel_levels = [40.0, 38.0, 36.0, 34.0, 32.0]
        result = analyze_fuel_session(lap_times, fuel_levels)
        assert "consumption_stats" in result
        assert result["consumption_stats"]["total_consumed"] > 0
        assert len(result["corrected_pace"]) == 5
        assert "fuel_after_5_laps" in result["predictions"]
        assert "fuel_after_10_laps" in result["predictions"]
        assert "fuel_after_20_laps" in result["predictions"]

    def test_empty_input(self):
        """No data -> empty result."""
        result = analyze_fuel_session([], [])
        assert result["consumption_stats"] == {}
        assert result["corrected_pace"] == []

    def test_predictions_go_negative(self):
        """Low fuel -> prediction for 20 laps should be negative."""
        lap_times = [60.0, 60.0, 60.0]
        fuel_levels = [10.0, 8.0, 6.0]
        result = analyze_fuel_session(lap_times, fuel_levels)
        assert result["predictions"]["fuel_after_20_laps"] < 0
