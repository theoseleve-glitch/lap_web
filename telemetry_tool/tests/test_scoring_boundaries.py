"""Scoring edge-case and boundary tests.

Covers:
- Grade boundary thresholds (_assign_grade): S=90, A=78, B=63, C=48, D=33, F<33
- Single-lap session scoring (consistency degrades gracefully)
- Invalid laps excluded from best lap computation via score_session inputs
- Null / NaN score fields handled gracefully
- Total score always stays in [0, 100]
- score_session() TypeError on bad input types
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

import pytest

# Ensure project root (telemetry_tool/) is on path — mirrors conftest.py convention
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scoring import (
    GRADE_A,
    GRADE_B,
    GRADE_C,
    GRADE_D,
    GRADE_S,
    TOTAL_MAX,
    _assign_grade,
    score_session,
)

# ---------------------------------------------------------------------------
# Minimal metric helpers
# ---------------------------------------------------------------------------

def _base_metrics(**overrides: Any) -> dict[str, Any]:
    """Return a minimal valid metrics dict suitable for score_session()."""
    base: dict[str, Any] = {
        "best_s": 60.0,
        "n_laps": 10,
        "cv_pct": 0.8,
        "best_to_median_s": 0.5,
        "speed_mean_mps": 30.0,
        "accel_max_mps2": 8.0,
        "braking_max_mps2": 10.0,
        "early_mean_s": 61.0,
        "late_mean_s": 61.5,
    }
    base.update(overrides)
    return base


def _base_theoretical(**overrides: Any) -> dict[str, Any]:
    """Return a minimal valid theoretical-metrics dict."""
    th: dict[str, Any] = {
        "best_s": 58.0,
        "speed_mean_mps": 32.0,
        "accel_max_mps2": 9.0,
        "braking_max_mps2": 11.0,
        "simulation_method": "percentile_envelope",
        "confidence": 1.0,
    }
    th.update(overrides)
    return th


# ===========================================================================
# Grade boundary tests
# ===========================================================================


class TestAssignGradeBoundaries:
    """_assign_grade() must return the correct letter at every threshold."""

    def test_s_at_threshold(self):
        assert _assign_grade(GRADE_S) == "S"

    def test_s_above_threshold(self):
        assert _assign_grade(GRADE_S + 5.0) == "S"

    def test_a_at_threshold(self):
        assert _assign_grade(GRADE_A) == "A"

    def test_a_just_below_s(self):
        assert _assign_grade(GRADE_S - 0.001) == "A"

    def test_b_at_threshold(self):
        assert _assign_grade(GRADE_B) == "B"

    def test_b_just_below_a(self):
        assert _assign_grade(GRADE_A - 0.001) == "B"

    def test_c_at_threshold(self):
        assert _assign_grade(GRADE_C) == "C"

    def test_c_just_below_b(self):
        assert _assign_grade(GRADE_B - 0.001) == "C"

    def test_d_at_threshold(self):
        assert _assign_grade(GRADE_D) == "D"

    def test_d_just_below_c(self):
        assert _assign_grade(GRADE_C - 0.001) == "D"

    def test_f_just_below_d(self):
        assert _assign_grade(GRADE_D - 0.001) == "F"

    def test_f_at_zero(self):
        assert _assign_grade(0.0) == "F"

    def test_s_at_100(self):
        assert _assign_grade(100.0) == "S"

    def test_grade_constants_ordering(self):
        """Grade thresholds must be strictly increasing F < D < C < B < A < S."""
        assert 0 < GRADE_D < GRADE_C < GRADE_B < GRADE_A < GRADE_S <= 100.0


# ===========================================================================
# score_session() grade integration tests
# ===========================================================================


class TestScoreSessionGradeIntegration:
    """score_session() must return the grade that matches _assign_grade(total)."""

    def test_grade_matches_total_score(self):
        m  = _base_metrics()
        th = _base_theoretical()
        result = score_session(m, th, session_type="practice")
        assert result["grade"] == _assign_grade(result["total_score"])

    def test_perfect_metrics_gives_high_grade(self):
        """Near-perfect metrics (driver matches theory) should yield A or S."""
        m  = _base_metrics(best_s=58.1, cv_pct=0.3, best_to_median_s=0.2)
        th = _base_theoretical(best_s=58.0)
        result = score_session(m, th)
        assert result["grade"] in ("A", "S"), (
            f"Expected A or S, got {result['grade']} (total={result['total_score']})"
        )

    def test_poor_metrics_gives_low_grade(self):
        """Driver much slower than theory and very inconsistent should yield D or F."""
        m  = _base_metrics(best_s=90.0, cv_pct=4.5, best_to_median_s=6.0)
        th = _base_theoretical(best_s=58.0)
        result = score_session(m, th)
        assert result["grade"] in ("D", "F"), (
            f"Expected D or F, got {result['grade']} (total={result['total_score']})"
        )

    def test_total_score_in_valid_range(self):
        m  = _base_metrics()
        th = _base_theoretical()
        result = score_session(m, th)
        assert 0.0 <= result["total_score"] <= TOTAL_MAX


# ===========================================================================
# Single-lap session edge cases
# ===========================================================================


class TestSingleLapSession:
    """Sessions with only one lap must not raise; consistency degrades gracefully."""

    def test_single_lap_does_not_raise(self):
        m  = _base_metrics(n_laps=1, cv_pct=float("nan"), best_to_median_s=float("nan"))
        th = _base_theoretical()
        result = score_session(m, th)
        assert isinstance(result, dict)

    def test_single_lap_total_score_in_range(self):
        m  = _base_metrics(n_laps=1, cv_pct=float("nan"), best_to_median_s=float("nan"))
        th = _base_theoretical()
        result = score_session(m, th)
        assert 0.0 <= result["total_score"] <= TOTAL_MAX

    def test_single_lap_has_required_keys(self):
        m  = _base_metrics(n_laps=1, cv_pct=float("nan"), best_to_median_s=float("nan"))
        th = _base_theoretical()
        result = score_session(m, th)
        for key in ("total_score", "grade", "sub_scores", "strengths", "weaknesses"):
            assert key in result, f"Missing key: {key}"

    def test_single_lap_consistency_score_is_zero(self):
        """_score_consistency returns 0 when n_laps < 2."""
        m  = _base_metrics(n_laps=1, cv_pct=float("nan"), best_to_median_s=float("nan"))
        th = _base_theoretical()
        result = score_session(m, th)
        assert result["sub_scores"]["consistency"]["score"] == 0.0

    def test_zero_laps_does_not_raise(self):
        m  = _base_metrics(n_laps=0, cv_pct=float("nan"), best_to_median_s=float("nan"))
        th = _base_theoretical()
        result = score_session(m, th)
        assert 0.0 <= result["total_score"] <= TOTAL_MAX


# ===========================================================================
# Invalid laps excluded — best lap correctness
# ===========================================================================


class TestInvalidLapExclusion:
    """Verify that invalid laps do not pollute the best_lap used for scoring.

    In the SaaS pipeline the caller is responsible for filtering laps before
    building metrics_dict (e.g. only valid laps contribute to best_s and cv_pct).
    These tests confirm that if the caller pre-filters correctly, the scorer
    rewards good best-lap values and penalises inflated ones.
    """

    def test_pre_filtered_best_lap_scores_higher_than_contaminated(self):
        """Metrics built from only valid laps (closer to theory) score higher."""
        th = _base_theoretical(best_s=58.0)

        # Valid laps only: best lap is 58.5 s (0.86% gap)
        m_clean = _base_metrics(best_s=58.5, cv_pct=0.5, best_to_median_s=0.3)
        # Contaminated: an invalid outlier lap at 90 s is included in best calculation
        m_dirty = _base_metrics(best_s=90.0, cv_pct=4.0, best_to_median_s=5.0)

        result_clean = score_session(m_clean, th)
        result_dirty = score_session(m_dirty, th)

        assert result_clean["total_score"] > result_dirty["total_score"], (
            f"Expected clean ({result_clean['total_score']}) > "
            f"dirty ({result_dirty['total_score']})"
        )

    def test_only_one_valid_lap_consistency_is_zero(self):
        """Caller passes n_laps=1 after filtering out the sole invalid lap."""
        m  = _base_metrics(n_laps=1, cv_pct=float("nan"), best_to_median_s=float("nan"))
        th = _base_theoretical()
        result = score_session(m, th)
        assert result["sub_scores"]["consistency"]["score"] == 0.0

    def test_all_valid_laps_pace_score_positive(self):
        """With valid laps close to theory, pace sub-score must be > 0."""
        m  = _base_metrics(best_s=59.0, n_laps=8)
        th = _base_theoretical(best_s=58.0)
        result = score_session(m, th)
        assert result["sub_scores"]["pace"]["score"] > 0.0


# ===========================================================================
# Null / NaN / missing field handling
# ===========================================================================


class TestNullScoreFieldHandling:
    """score_session() must never raise when metric fields are absent or NaN."""

    def test_entirely_empty_metrics_does_not_raise(self):
        result = score_session({}, {})
        assert isinstance(result, dict)
        assert 0.0 <= result["total_score"] <= TOTAL_MAX

    def test_nan_best_s_does_not_raise(self):
        m  = _base_metrics(best_s=float("nan"))
        th = _base_theoretical()
        result = score_session(m, th)
        assert isinstance(result, dict)

    def test_nan_best_s_pace_score_is_zero(self):
        """NaN best_s => pace scorer returns 0."""
        m  = _base_metrics(best_s=float("nan"))
        th = _base_theoretical()
        result = score_session(m, th)
        assert result["sub_scores"]["pace"]["score"] == 0.0

    def test_nan_cv_consistency_gets_partial_credit(self):
        """NaN cv_pct => _ratio_score falls back to 0.5 partial credit."""
        m  = _base_metrics(cv_pct=float("nan"), best_to_median_s=float("nan"), n_laps=5)
        th = _base_theoretical()
        result = score_session(m, th)
        # Partial credit means score > 0 for non-trivial lap count
        assert result["sub_scores"]["consistency"]["score"] > 0.0

    def test_missing_speed_fields_does_not_raise(self):
        m: dict[str, Any] = {"best_s": 60.0, "n_laps": 5, "cv_pct": 1.0, "best_to_median_s": 0.5}
        th: dict[str, Any] = {"best_s": 58.0}
        result = score_session(m, th)
        assert isinstance(result, dict)

    def test_missing_robustness_fields_does_not_raise(self):
        m: dict[str, Any] = {
            "best_s": 60.0, "n_laps": 10, "cv_pct": 1.0, "best_to_median_s": 0.5,
            "speed_mean_mps": 30.0,
            # early_mean_s and late_mean_s intentionally absent
        }
        th = _base_theoretical()
        result = score_session(m, th)
        assert isinstance(result, dict)
        assert 0.0 <= result["total_score"] <= TOTAL_MAX

    def test_none_confidence_defaults_to_full(self):
        """Absent confidence key should not penalise the score."""
        m  = _base_metrics()
        th = _base_theoretical()
        del th["confidence"]
        result = score_session(m, th)
        assert result["data_confidence"] == 1.0

    def test_nan_confidence_defaults_to_full(self):
        m  = _base_metrics()
        th = _base_theoretical(confidence=float("nan"))
        result = score_session(m, th)
        assert result["data_confidence"] == 1.0

    def test_negative_confidence_defaults_to_full(self):
        m  = _base_metrics()
        th = _base_theoretical(confidence=-0.5)
        result = score_session(m, th)
        assert result["data_confidence"] == 1.0


# ===========================================================================
# Type-checking — score_session() raises TypeError on bad inputs
# ===========================================================================


class TestScoreSessionTypeErrors:
    def test_raises_on_non_dict_metrics(self):
        with pytest.raises(TypeError):
            score_session(None, {})  # type: ignore[arg-type]

    def test_raises_on_non_dict_theoretical(self):
        with pytest.raises(TypeError):
            score_session({}, "not a dict")  # type: ignore[arg-type]

    def test_raises_on_list_metrics(self):
        with pytest.raises(TypeError):
            score_session([], {})  # type: ignore[arg-type]


# ===========================================================================
# Score structure contract
# ===========================================================================


class TestScoreSessionStructure:
    """score_session() result must always satisfy the documented contract."""

    def test_sub_scores_has_five_categories(self):
        result = score_session(_base_metrics(), _base_theoretical())
        assert set(result["sub_scores"].keys()) == {
            "pace", "consistency", "execution", "robustness", "adaptation"
        }

    def test_each_sub_score_has_required_keys(self):
        result = score_session(_base_metrics(), _base_theoretical())
        for cat, sub in result["sub_scores"].items():
            assert "score" in sub, f"{cat} missing 'score'"
            assert "max"   in sub, f"{cat} missing 'max'"
            assert "pct"   in sub, f"{cat} missing 'pct'"

    def test_sub_scores_non_negative(self):
        result = score_session(_base_metrics(), _base_theoretical())
        for cat, sub in result["sub_scores"].items():
            assert sub["score"] >= 0.0, f"{cat} score is negative: {sub['score']}"

    def test_sub_scores_do_not_exceed_max(self):
        result = score_session(_base_metrics(), _base_theoretical())
        for cat, sub in result["sub_scores"].items():
            assert sub["score"] <= sub["max"] + 1e-6, (
                f"{cat} score {sub['score']} exceeds max {sub['max']}"
            )

    def test_strengths_and_weaknesses_are_lists(self):
        result = score_session(_base_metrics(), _base_theoretical())
        assert isinstance(result["strengths"],  list)
        assert isinstance(result["weaknesses"], list)

    def test_session_type_preserved_in_result(self):
        result = score_session(_base_metrics(), _base_theoretical(), session_type="qualifying")
        assert result["session_type"] == "qualifying"

    def test_total_equals_sum_of_sub_scores(self):
        """total_score must match the sum of final sub-scores (within rounding)."""
        result = score_session(_base_metrics(), _base_theoretical())
        sub_total = sum(s["score"] for s in result["sub_scores"].values())
        # The total is clamped to [0, 100] and rounded; allow 0.01 tolerance.
        assert abs(result["total_score"] - sub_total) < 0.02, (
            f"total={result['total_score']}  sub_sum={sub_total}"
        )
