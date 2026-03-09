"""Tests for conditions-based lap time predictor."""
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from lap_time_predictor import (
    SessionConditions,
    HistoricalSession,
    LapTimePrediction,
    predict_lap_time,
    predict_from_partial_session,
    estimate_improvement_potential,
    _grip_time_adjustment,
    _temperature_time_adjustment,
    _compute_similarity,
    _driver_trend_adjustment,
)


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def dry_conditions():
    return SessionConditions(grip_mu=1.0, air_temp_c=22.0, session_type="practice")


@pytest.fixture
def wet_conditions():
    return SessionConditions(grip_mu=0.7, air_temp_c=15.0, rain_mm=2.0, session_type="practice")


@pytest.fixture
def history():
    """5 historical sessions at track 1 for driver 1."""
    return [
        HistoricalSession(
            session_id=f"s{i}", driver_id=1, track_id=1,
            best_lap_time_s=60.0 - i * 0.3,  # Improving trend
            mean_lap_time_s=62.0 - i * 0.3,
            n_laps=10, grip_mu=1.0, air_temp_c=20.0,
            session_type="practice",
        )
        for i in range(5)
    ] + [
        # Other driver at same track
        HistoricalSession(
            session_id="s_other", driver_id=2, track_id=1,
            best_lap_time_s=61.5, mean_lap_time_s=63.0,
            n_laps=8, grip_mu=1.0, air_temp_c=22.0,
            session_type="practice",
        ),
        # Different track (should be ignored)
        HistoricalSession(
            session_id="s_diff", driver_id=1, track_id=99,
            best_lap_time_s=55.0, mean_lap_time_s=57.0,
            n_laps=10, grip_mu=1.0, air_temp_c=20.0,
            session_type="practice",
        ),
    ]


# ── Grip adjustment ──────────────────────────────────────────────

class TestGripAdjustment:
    def test_same_grip_no_adjustment(self):
        assert _grip_time_adjustment(60.0, 1.0, 1.0) == 0.0

    def test_lower_grip_adds_time(self):
        adj = _grip_time_adjustment(60.0, 1.0, 0.8)
        assert adj > 0  # Slower

    def test_higher_grip_subtracts_time(self):
        adj = _grip_time_adjustment(60.0, 1.0, 1.2)
        assert adj < 0  # Faster

    def test_symmetry(self):
        up = _grip_time_adjustment(60.0, 1.0, 1.1)
        down = _grip_time_adjustment(60.0, 1.0, 0.9)
        # Approximately symmetric
        assert abs(abs(up) - abs(down)) < 0.5


# ── Temperature adjustment ────────────────────────────────────────

class TestTemperatureAdjustment:
    def test_same_temp_no_adjustment(self):
        assert _temperature_time_adjustment(60.0, 25.0, 25.0) == 0.0

    def test_cold_adds_time(self):
        adj = _temperature_time_adjustment(60.0, 30.0, 5.0)
        assert adj > 0  # Farther from optimal → slower

    def test_optimal_temp_fastest(self):
        adj = _temperature_time_adjustment(60.0, 10.0, 30.0)
        assert adj < 0  # Moving toward optimal → faster


# ── Similarity computation ────────────────────────────────────────

class TestSimilarity:
    def test_different_track_zero(self, dry_conditions):
        h = HistoricalSession("s1", 1, 99, 60.0, 62.0, 10)
        assert _compute_similarity(dry_conditions, h, 1, 1) == 0.0

    def test_identical_conditions_high(self, dry_conditions):
        h = HistoricalSession("s1", 1, 1, 60.0, 62.0, 10,
                              grip_mu=1.0, air_temp_c=22.0, session_type="practice")
        sim = _compute_similarity(dry_conditions, h, 1, 1)
        assert sim > 0.8

    def test_same_driver_bonus(self, dry_conditions):
        h_same = HistoricalSession("s1", 1, 1, 60.0, 62.0, 10, grip_mu=1.0, air_temp_c=22.0)
        h_diff = HistoricalSession("s2", 2, 1, 60.0, 62.0, 10, grip_mu=1.0, air_temp_c=22.0)
        sim_same = _compute_similarity(dry_conditions, h_same, 1, 1)
        sim_diff = _compute_similarity(dry_conditions, h_diff, 1, 1)
        assert sim_same > sim_diff


# ── Driver trend ─────────────────────────────────────────────────

class TestDriverTrend:
    def test_improving_trend_negative(self, history):
        trend = _driver_trend_adjustment(history, 1, 1)
        assert trend < 0  # Improving = faster = negative

    def test_insufficient_data_zero(self, history):
        trend = _driver_trend_adjustment(history, 999, 1)
        assert trend == 0.0


# ── Core prediction ──────────────────────────────────────────────

class TestPredictLapTime:
    def test_returns_prediction(self, dry_conditions, history):
        pred = predict_lap_time(1, 1, dry_conditions, history)
        assert isinstance(pred, LapTimePrediction)
        assert pred.predicted_time_s > 0
        assert pred.confidence > 0

    def test_reasonable_prediction(self, dry_conditions, history):
        pred = predict_lap_time(1, 1, dry_conditions, history)
        # Should be roughly in the 58-62s range given the history
        assert 55 < pred.predicted_time_s < 65

    def test_confidence_positive(self, dry_conditions, history):
        pred = predict_lap_time(1, 1, dry_conditions, history)
        assert pred.confidence > 0.3

    def test_wet_predicts_slower(self, dry_conditions, wet_conditions, history):
        dry_pred = predict_lap_time(1, 1, dry_conditions, history)
        wet_pred = predict_lap_time(1, 1, wet_conditions, history)
        assert wet_pred.predicted_time_s > dry_pred.predicted_time_s

    def test_no_history_fallback(self, dry_conditions):
        pred = predict_lap_time(1, 1, dry_conditions, [])
        assert pred.confidence == 0.0
        assert pred.predicted_time_s == 0.0

    def test_wrong_track_fallback(self, dry_conditions):
        # History only at track 99
        history = [HistoricalSession("s1", 1, 99, 60.0, 62.0, 10)]
        pred = predict_lap_time(1, 1, dry_conditions, history)
        assert pred.confidence == 0.0

    def test_to_dict_serializable(self, dry_conditions, history):
        pred = predict_lap_time(1, 1, dry_conditions, history)
        d = pred.to_dict()
        assert isinstance(d, dict)
        assert "predicted_time_s" in d
        assert "adjustments" in d
        assert "explanation" in d

    def test_bounds_bracket_prediction(self, dry_conditions, history):
        pred = predict_lap_time(1, 1, dry_conditions, history)
        assert pred.lower_bound_s <= pred.predicted_time_s
        assert pred.upper_bound_s >= pred.predicted_time_s


# ── Partial session prediction ────────────────────────────────────

class TestPartialSession:
    def test_blends_observed_and_historical(self, dry_conditions, history):
        completed = [59.5, 59.2, 58.8]
        pred = predict_from_partial_session(
            completed, dry_conditions, history, driver_id=1, track_id=1,
        )
        assert pred.predicted_time_s > 0
        # Should be close to observed best (58.8) but influenced by history
        assert 55 < pred.predicted_time_s < 65

    def test_more_laps_higher_confidence(self, dry_conditions, history):
        few = predict_from_partial_session(
            [59.5], dry_conditions, history, driver_id=1, track_id=1,
        )
        many = predict_from_partial_session(
            [59.5, 59.2, 58.8, 58.5, 58.3], dry_conditions, history,
            driver_id=1, track_id=1,
        )
        assert many.confidence >= few.confidence

    def test_empty_laps_falls_back(self, dry_conditions, history):
        pred = predict_from_partial_session(
            [], dry_conditions, history, driver_id=1, track_id=1,
        )
        # Should fall back to historical prediction
        assert pred.predicted_time_s > 0

    def test_no_history_uses_observed(self, dry_conditions):
        pred = predict_from_partial_session(
            [60.0, 59.5, 59.0], dry_conditions, [],
            driver_id=1, track_id=1,
        )
        assert abs(pred.predicted_time_s - 59.0) < 0.1  # Should be close to best


# ── Improvement potential ─────────────────────────────────────────

class TestImprovementPotential:
    def test_gap_computed(self, dry_conditions, history):
        pred = predict_lap_time(1, 1, dry_conditions, history)
        potential = estimate_improvement_potential(pred, 55.0)
        assert potential.gap_s > 0
        assert potential.gap_pct > 0

    def test_achievable_target_between(self, dry_conditions, history):
        pred = predict_lap_time(1, 1, dry_conditions, history)
        potential = estimate_improvement_potential(pred, 55.0)
        assert potential.theoretical_time_s < potential.achievable_target_s < potential.predicted_time_s

    def test_improvement_areas_scaled(self, dry_conditions, history):
        pred = predict_lap_time(1, 1, dry_conditions, history)
        potential = estimate_improvement_potential(pred, 55.0)
        assert len(potential.improvement_areas) > 0

    def test_to_dict(self, dry_conditions, history):
        pred = predict_lap_time(1, 1, dry_conditions, history)
        potential = estimate_improvement_potential(pred, 55.0)
        d = potential.to_dict()
        assert "gap_s" in d
        assert "achievable_target_s" in d

    def test_zero_theoretical_safe(self, dry_conditions, history):
        pred = predict_lap_time(1, 1, dry_conditions, history)
        potential = estimate_improvement_potential(pred, 0)
        assert potential.gap_s == 0
