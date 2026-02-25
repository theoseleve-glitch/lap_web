"""Tests for race_simulator.py -- deterministic race simulation engine."""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from race_simulator import SimulationParams, simulate_race


def _default_params(**overrides) -> SimulationParams:
    defaults = dict(
        race_laps=25,
        pit_stop_loss_s=30.0,
        num_pit_stops=1,
        tire_deg_rate_s=0.05,
        fuel_effect_s=0.0,
        target_lap_time_s=62.0,
        consistency_cv_pct=1.5,
        fatigue_onset_lap=18,
        stint_length=12,
        traffic_penalty_s=0.3,
    )
    defaults.update(overrides)
    return SimulationParams(**defaults)


class TestSimulateRace:
    def test_basic_output_shape(self):
        params = _default_params()
        result = simulate_race(params)
        assert len(result.predicted_laps) == 25
        assert result.total_race_time_s > 0
        assert all(math.isfinite(t) for t in result.predicted_laps)

    def test_pit_stops_inserted(self):
        params = _default_params(num_pit_stops=2, stint_length=8, race_laps=25)
        result = simulate_race(params)
        assert len(result.pit_stop_laps) == 2
        for pit_lap in result.pit_stop_laps:
            assert result.predicted_laps[pit_lap - 1] > params.target_lap_time_s + params.pit_stop_loss_s * 0.5

    def test_no_pit_stops(self):
        params = _default_params(num_pit_stops=0)
        result = simulate_race(params)
        assert len(result.pit_stop_laps) == 0

    def test_tire_degradation_increases_times(self):
        params = _default_params(tire_deg_rate_s=0.1, num_pit_stops=0,
                                  fuel_effect_s=0.0, traffic_penalty_s=0.0,
                                  consistency_cv_pct=0.0, fatigue_onset_lap=999)
        result = simulate_race(params)
        assert result.predicted_laps[-1] > result.predicted_laps[0]
        assert result.tire_impact_s > 0

    def test_fuel_effect_decreases_times(self):
        params = _default_params(fuel_effect_s=0.02, tire_deg_rate_s=0.0,
                                  num_pit_stops=0, traffic_penalty_s=0.0,
                                  consistency_cv_pct=0.0, fatigue_onset_lap=999)
        result = simulate_race(params)
        assert result.predicted_laps[-1] < result.predicted_laps[0]

    def test_fatigue_onset(self):
        params = _default_params(fatigue_onset_lap=10, tire_deg_rate_s=0.0,
                                  fuel_effect_s=0.0, traffic_penalty_s=0.0,
                                  consistency_cv_pct=0.0, num_pit_stops=0)
        result = simulate_race(params)
        assert result.fatigue_impact_s > 0
        assert result.predicted_laps[15] > result.predicted_laps[5]

    def test_tire_resets_after_pit(self):
        params = _default_params(tire_deg_rate_s=0.1, num_pit_stops=1,
                                  stint_length=12, race_laps=24,
                                  fuel_effect_s=0.0, traffic_penalty_s=0.0,
                                  consistency_cv_pct=0.0, fatigue_onset_lap=999)
        result = simulate_race(params)
        pit_lap = result.pit_stop_laps[0]
        if pit_lap < 24:
            next_lap_time = result.predicted_laps[pit_lap]
            assert next_lap_time < params.target_lap_time_s + 0.5

    def test_deterministic(self):
        params = _default_params(consistency_cv_pct=0.0)
        r1 = simulate_race(params)
        r2 = simulate_race(params)
        assert r1.predicted_laps == r2.predicted_laps
        assert r1.total_race_time_s == r2.total_race_time_s

    def test_coaching_not_empty(self):
        params = _default_params()
        result = simulate_race(params)
        assert len(result.coaching) > 10

    def test_best_worst_stint_pace(self):
        params = _default_params(num_pit_stops=1, stint_length=12, race_laps=24)
        result = simulate_race(params)
        assert result.best_stint_pace_s > 0
        assert result.worst_stint_pace_s >= result.best_stint_pace_s

    def test_serialization(self):
        import json
        params = _default_params()
        result = simulate_race(params)
        d = result.to_dict()
        json.dumps(d)
        assert "predicted_laps" in d
        assert "coaching" in d
        assert "pit_stop_laps" in d

    def test_zero_race_laps(self):
        params = _default_params(race_laps=0)
        result = simulate_race(params)
        assert len(result.predicted_laps) == 0
        assert result.total_race_time_s == 0

    def test_single_lap_race(self):
        params = _default_params(race_laps=1, num_pit_stops=0)
        result = simulate_race(params)
        assert len(result.predicted_laps) == 1
