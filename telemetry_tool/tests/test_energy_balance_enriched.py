"""Tests for enriched energy balance (recovery ratio, worst laps, coaching)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from energy_balance import analyze_energy_balance


class TestRecoveryRatio:
    def test_recovery_ratio_present(self):
        times = [60.0 + i * 0.1 for i in range(10)]
        r = analyze_energy_balance(times)
        d = r.to_dict()
        assert "recovery_ratio" in d
        assert 0 < d["recovery_ratio"] <= 200

    def test_constant_speed_ratio(self):
        times = [60.0, 60.01, 60.02, 60.01, 60.0]
        r = analyze_energy_balance(times)
        assert 80 < r.to_dict()["recovery_ratio"] < 120


class TestWorstBrakingLaps:
    def test_worst_laps_present(self):
        times = [60.0 + i * 0.1 for i in range(10)]
        r = analyze_energy_balance(times)
        d = r.to_dict()
        assert "worst_braking_laps" in d
        assert isinstance(d["worst_braking_laps"], list)
        assert len(d["worst_braking_laps"]) <= 3

    def test_worst_laps_are_valid_numbers(self):
        times = [60.0, 61.0, 62.0, 60.5, 63.0]
        r = analyze_energy_balance(times)
        d = r.to_dict()
        for lap_num in d["worst_braking_laps"]:
            assert isinstance(lap_num, int)
            assert lap_num >= 1


class TestEnrichedCoaching:
    def test_coaching_not_empty(self):
        times = [60.0, 60.5, 61.0]
        r = analyze_energy_balance(times)
        assert len(r.coaching) > 10


class TestEfficiencyTrendRemoved:
    def test_no_efficiency_trend_in_dict(self):
        times = [60.0 + i * 0.1 for i in range(10)]
        r = analyze_energy_balance(times)
        d = r.to_dict()
        assert "efficiency_trend" not in d
