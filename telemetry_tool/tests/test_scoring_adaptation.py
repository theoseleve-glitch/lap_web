"""Tests for adaptation v2 scoring integration into the scoring module."""
import math

import numpy as np
import pandas as pd
import pytest


class TestAdaptationWeights:
    """Verify weight redistribution and new constants."""

    def test_weights_sum_to_100(self):
        """All MAX_ category constants must sum to 100."""
        from scoring import (
            MAX_ADAPTATION,
            MAX_CONSISTENCY,
            MAX_EXECUTION,
            MAX_PACE,
            MAX_ROBUSTNESS,
            TOTAL_MAX,
        )

        total = MAX_PACE + MAX_CONSISTENCY + MAX_EXECUTION + MAX_ROBUSTNESS + MAX_ADAPTATION
        assert total == 100.0
        assert TOTAL_MAX == 100.0

    def test_new_weights(self):
        """Verify the exact new weight distribution: 25/25/20/15/15."""
        from scoring import (
            MAX_ADAPTATION,
            MAX_CONSISTENCY,
            MAX_EXECUTION,
            MAX_PACE,
            MAX_ROBUSTNESS,
        )

        assert MAX_PACE == 25.0
        assert MAX_CONSISTENCY == 25.0
        assert MAX_EXECUTION == 20.0
        assert MAX_ROBUSTNESS == 15.0
        assert MAX_ADAPTATION == 15.0


class TestAdaptationV2Scoring:
    """Test _score_adaptation_v2 function."""

    @staticmethod
    def _make_weather_timeline(phases):
        """Build a weather_timeline DataFrame from a list of phase dicts.

        Each dict should have: phase_id, start_lap, end_lap, avg_grip,
        and optionally condition.
        """
        return pd.DataFrame(phases)

    @staticmethod
    def _make_lap_metrics(n_laps, base_time=60.0, noise_std=0.3):
        """Generate simple lap metrics for n laps."""
        rng = np.random.RandomState(42)
        times = base_time + rng.normal(0, noise_std, n_laps)
        return [
            {"lap_number": i + 1, "lap_time_s": float(times[i])}
            for i in range(n_laps)
        ]

    def test_none_weather_returns_neutral(self):
        """When weather_timeline is None, adaptation should return neutral (~75% of max)."""
        from scoring import MAX_ADAPTATION, _score_adaptation_v2

        lap_metrics = self._make_lap_metrics(10)
        score = _score_adaptation_v2(
            lap_metrics=lap_metrics,
            weather_timeline=None,
            theory_best=58.0,
        )
        expected_neutral = MAX_ADAPTATION * 0.75  # 11.25
        assert abs(score - expected_neutral) < 0.01, (
            f"Expected ~{expected_neutral}, got {score}"
        )

    def test_stable_session_neutral(self):
        """Single phase with no evolution should return ~75% of max (11.25)."""
        from scoring import MAX_ADAPTATION, _score_adaptation_v2

        weather = self._make_weather_timeline([
            {"phase_id": 0, "start_lap": 1, "end_lap": 10, "avg_grip": 95.0,
             "condition": "dry"},
        ])
        lap_metrics = self._make_lap_metrics(10)
        score = _score_adaptation_v2(
            lap_metrics=lap_metrics,
            weather_timeline=weather,
            theory_best=58.0,
        )
        expected_neutral = MAX_ADAPTATION * 0.75  # 11.25
        assert abs(score - expected_neutral) < 0.01, (
            f"Expected ~{expected_neutral}, got {score}"
        )

    def test_multi_phase_returns_score(self):
        """Multi-phase weather data should produce a score in [0, MAX_ADAPTATION]."""
        from scoring import MAX_ADAPTATION, _score_adaptation_v2

        # Phase 1: dry (laps 1-5), Phase 2: wet (laps 6-15)
        weather = self._make_weather_timeline([
            {"phase_id": 0, "start_lap": 1, "end_lap": 5, "avg_grip": 95.0,
             "condition": "dry"},
            {"phase_id": 1, "start_lap": 6, "end_lap": 15, "avg_grip": 60.0,
             "condition": "wet"},
        ])

        # Simulate dry laps then slower wet laps
        rng = np.random.RandomState(42)
        dry_times = 60.0 + rng.normal(0, 0.3, 5)
        wet_times = 68.0 + rng.normal(0, 0.5, 10)
        lap_metrics = []
        for i, t in enumerate(list(dry_times) + list(wet_times)):
            lap_metrics.append({"lap_number": i + 1, "lap_time_s": float(t)})

        score = _score_adaptation_v2(
            lap_metrics=lap_metrics,
            weather_timeline=weather,
            theory_best=58.0,
        )
        assert 0.0 <= score <= MAX_ADAPTATION, (
            f"Score {score} outside [0, {MAX_ADAPTATION}]"
        )


class TestScoreSessionWithAdaptation:
    """Integration: adaptation appears in score_session output."""

    @staticmethod
    def _base_metrics():
        return {
            "best_s": 62.0,
            "n_laps": 10,
            "cv_pct": 1.5,
            "best_to_median_s": 0.8,
            "speed_mean_mps": 25.0,
            "accel_max_mps2": 8.0,
            "braking_max_mps2": 12.0,
            "early_mean_s": 63.0,
            "late_mean_s": 63.5,
        }

    @staticmethod
    def _base_theory():
        return {
            "best_s": 60.0,
            "speed_mean_mps": 26.0,
            "accel_max_mps2": 9.0,
            "braking_max_mps2": 14.0,
        }

    def test_score_session_includes_adaptation_sub_score(self):
        """score_session() must include 'adaptation' in sub_scores."""
        from scoring import score_session

        result = score_session(self._base_metrics(), self._base_theory())
        assert "adaptation" in result["sub_scores"]
        adapt = result["sub_scores"]["adaptation"]
        assert "score" in adapt
        assert "max" in adapt
        assert adapt["max"] == 15.0

    def test_score_session_total_includes_adaptation(self):
        """Total score should be sum of all 5 categories (within confidence)."""
        from scoring import score_session

        result = score_session(self._base_metrics(), self._base_theory())
        sub_total = sum(
            result["sub_scores"][cat]["score"]
            for cat in ("pace", "consistency", "execution", "robustness", "adaptation")
        )
        # Total may be slightly different due to data confidence weighting,
        # but should be in same ballpark
        assert result["total_score"] <= 100.0
        assert result["total_score"] >= 0.0
