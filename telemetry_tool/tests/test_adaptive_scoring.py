"""Tests for adaptive scoring weights — suppression, track state, diminishing returns."""
import math
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestSessionCategoryConfig:
    """Verify _SESSION_CATEGORY_CONFIG structure and invariants."""

    def test_config_exists(self):
        from scoring.constants import _SESSION_CATEGORY_CONFIG
        assert isinstance(_SESSION_CATEGORY_CONFIG, dict)
        assert len(_SESSION_CATEGORY_CONFIG) >= 10

    def test_all_entries_have_suppressed_and_emphasis(self):
        from scoring.constants import _SESSION_CATEGORY_CONFIG
        valid_cats = {"pace", "consistency", "execution", "robustness", "adaptation"}
        for stype, cfg in _SESSION_CATEGORY_CONFIG.items():
            assert "suppressed" in cfg, f"{stype} missing 'suppressed'"
            assert "emphasis" in cfg, f"{stype} missing 'emphasis'"
            assert cfg["suppressed"].issubset(valid_cats), f"{stype} has invalid suppressed categories"
            assert set(cfg["emphasis"].keys()).issubset(valid_cats), f"{stype} has invalid emphasis categories"
            # Suppressed and emphasized must not overlap
            assert cfg["suppressed"].isdisjoint(set(cfg["emphasis"].keys())), (
                f"{stype} has overlap between suppressed and emphasis"
            )

    def test_qualifying_suppresses_consistency_robustness_adaptation(self):
        from scoring.constants import _SESSION_CATEGORY_CONFIG
        q = _SESSION_CATEGORY_CONFIG["qualifying"]
        assert q["suppressed"] == {"consistency", "robustness", "adaptation"}

    def test_practice_suppresses_robustness_emphasizes_adaptation(self):
        from scoring.constants import _SESSION_CATEGORY_CONFIG
        p = _SESSION_CATEGORY_CONFIG["practice"]
        assert "robustness" in p["suppressed"]
        assert p["emphasis"].get("adaptation", 0) > 1.0

    def test_endurance_suppresses_nothing(self):
        from scoring.constants import _SESSION_CATEGORY_CONFIG
        for key in ("endurance", "endurance_stint", "endurance_race"):
            if key in _SESSION_CATEGORY_CONFIG:
                assert len(_SESSION_CATEGORY_CONFIG[key]["suppressed"]) == 0


class TestTrackStateModifiers:
    """Verify _TRACK_STATE_MODIFIERS structure."""

    def test_modifiers_exist(self):
        from scoring.constants import _TRACK_STATE_MODIFIERS
        assert isinstance(_TRACK_STATE_MODIFIERS, dict)
        assert "dry" in _TRACK_STATE_MODIFIERS
        assert "wet" in _TRACK_STATE_MODIFIERS

    def test_dry_is_empty(self):
        from scoring.constants import _TRACK_STATE_MODIFIERS
        assert _TRACK_STATE_MODIFIERS["dry"] == {}

    def test_wet_boosts_adaptation_reduces_pace(self):
        from scoring.constants import _TRACK_STATE_MODIFIERS
        wet = _TRACK_STATE_MODIFIERS["wet"]
        assert wet.get("adaptation", 1.0) > 1.0
        assert wet.get("pace", 1.0) < 1.0


class TestDiminishingReturnsConstants:
    """Verify DR constants exist and have sane values."""

    def test_dr_constants_exist(self):
        from scoring.constants import (
            DR_EXP_K, DR_EXP_L0, DR_EXP_FLOOR,
            DR_SES_K, DR_SES_L0, DR_SES_FLOOR,
            DR_COMBINED_FLOOR,
        )
        assert 0 < DR_EXP_K < 0.1
        assert DR_EXP_L0 > 0
        assert 0.9 <= DR_EXP_FLOOR < 1.0
        assert 0 < DR_SES_K < 0.1
        assert DR_SES_L0 > 0
        assert 0.9 <= DR_SES_FLOOR < 1.0
        assert 0.85 <= DR_COMBINED_FLOOR < 1.0


class TestApplyAdaptiveWeights:
    """Test the new _apply_adaptive_weights function."""

    def _make_raw_scores(self, pace=20.0, cons=20.0, exe=16.0, rob=12.0, adapt=11.25):
        """Helper: reasonable raw sub-scores (80% of each max)."""
        return {
            "pace": pace,
            "consistency": cons,
            "execution": exe,
            "robustness": rob,
            "adaptation": adapt,
        }

    def test_qualifying_suppresses_three_categories(self):
        from scoring.scorer import _apply_adaptive_weights
        raw = self._make_raw_scores()
        result, maxes = _apply_adaptive_weights(raw, "qualifying")
        assert result["consistency"] == 0.0
        assert result["robustness"] == 0.0
        assert result["adaptation"] == 0.0
        assert maxes["consistency"] == 0.0
        assert maxes["robustness"] == 0.0
        # Remaining categories should sum to 100
        assert abs(sum(maxes.values()) - 100.0) < 0.01

    def test_practice_suppresses_robustness(self):
        from scoring.scorer import _apply_adaptive_weights
        raw = self._make_raw_scores()
        result, maxes = _apply_adaptive_weights(raw, "practice")
        assert result["robustness"] == 0.0
        assert maxes["robustness"] == 0.0
        assert abs(sum(maxes.values()) - 100.0) < 0.01

    def test_practice_emphasizes_adaptation(self):
        from scoring.scorer import _apply_adaptive_weights
        raw = self._make_raw_scores()
        _, maxes_practice = _apply_adaptive_weights(raw, "practice")
        _, maxes_race = _apply_adaptive_weights(raw, "race")
        adapt_frac_practice = maxes_practice["adaptation"] / sum(maxes_practice.values())
        adapt_frac_race = maxes_race["adaptation"] / sum(maxes_race.values())
        assert adapt_frac_practice > adapt_frac_race

    def test_endurance_nothing_suppressed(self):
        from scoring.scorer import _apply_adaptive_weights
        raw = self._make_raw_scores()
        result, maxes = _apply_adaptive_weights(raw, "endurance")
        for cat in raw:
            assert result[cat] > 0
            assert maxes[cat] > 0
        assert abs(sum(maxes.values()) - 100.0) < 0.01

    def test_unknown_session_type_uses_base_weights(self):
        from scoring.scorer import _apply_adaptive_weights
        raw = self._make_raw_scores()
        result, maxes = _apply_adaptive_weights(raw, "unknown_xyz")
        assert abs(sum(maxes.values()) - 100.0) < 0.01
        for cat in raw:
            assert result[cat] > 0

    def test_track_state_wet_boosts_adaptation(self):
        from scoring.scorer import _apply_adaptive_weights
        raw = self._make_raw_scores()
        _, maxes_dry = _apply_adaptive_weights(raw, "race", track_state="dry")
        _, maxes_wet = _apply_adaptive_weights(raw, "race", track_state="wet")
        dry_adapt_frac = maxes_dry["adaptation"] / sum(maxes_dry.values())
        wet_adapt_frac = maxes_wet["adaptation"] / sum(maxes_wet.values())
        assert wet_adapt_frac > dry_adapt_frac

    def test_track_state_modifier_only_on_surviving(self):
        """Track-state modifier on a suppressed category has no effect."""
        from scoring.scorer import _apply_adaptive_weights
        raw = self._make_raw_scores()
        result_dry, _ = _apply_adaptive_weights(raw, "qualifying", track_state="dry")
        result_wet, _ = _apply_adaptive_weights(raw, "qualifying", track_state="wet")
        assert result_dry["consistency"] == 0.0
        assert result_wet["consistency"] == 0.0

    def test_total_maxes_always_sum_to_100(self):
        from scoring.scorer import _apply_adaptive_weights
        raw = self._make_raw_scores()
        for stype in ("qualifying", "race", "practice", "warmup", "test",
                       "endurance", "heat", "final", "sprint"):
            for ts in ("dry", "wet", "damp", "full_wet", "drying", "greasy"):
                _, maxes = _apply_adaptive_weights(raw, stype, track_state=ts)
                assert abs(sum(maxes.values()) - 100.0) < 0.01, (
                    f"{stype}/{ts}: maxes sum to {sum(maxes.values())}"
                )


class TestDiminishingReturns:
    """Test the diminishing-returns multiplier."""

    def test_compute_dr_multiplier_new_driver(self):
        from scoring.scorer import _compute_dr_multiplier
        m = _compute_dr_multiplier(total_laps=0, session_laps=10)
        assert 0.99 < m <= 1.0

    def test_compute_dr_multiplier_veteran(self):
        from scoring.scorer import _compute_dr_multiplier
        m = _compute_dr_multiplier(total_laps=10000, session_laps=100)
        assert 0.92 <= m < 0.99

    def test_compute_dr_multiplier_extreme_near_floor(self):
        from scoring.scorer import _compute_dr_multiplier
        m = _compute_dr_multiplier(total_laps=1_000_000, session_laps=10_000)
        # Product of two per-factor floors (0.96 * 0.96 = 0.9216) but
        # with these constants the raw values don't quite hit per-factor
        # floors, so combined stays above DR_COMBINED_FLOOR.
        assert 0.92 <= m < 0.96

    def test_compute_dr_multiplier_no_laps_is_neutral(self):
        from scoring.scorer import _compute_dr_multiplier
        m = _compute_dr_multiplier(total_laps=0, session_laps=0)
        assert m == 1.0

    def test_veteran_scores_lower_than_newcomer(self):
        """Identical raw metrics, veteran gets slightly lower total."""
        from scoring import score_session
        metrics = {
            "best_s": 60.0, "n_laps": 15, "cv_pct": 1.0,
            "best_to_median_s": 0.5, "speed_mean_mps": 30.0,
            "accel_max_mps2": 10.0, "braking_max_mps2": 12.0,
            "early_mean_s": 61.0, "late_mean_s": 61.5,
            "early_yaw_var": 0.01, "late_yaw_var": 0.012,
        }
        theo = {
            "best_s": 58.0, "speed_mean_mps": 32.0,
            "accel_max_mps2": 12.0, "braking_max_mps2": 14.0,
        }
        newcomer = score_session(metrics, theo, "practice",
                                  driver_total_laps=50)
        veteran = score_session(metrics, theo, "practice",
                                 driver_total_laps=20000)
        assert newcomer["total_score"] > veteran["total_score"]

    def test_long_session_scores_lower_than_short(self):
        """200-lap session scores slightly lower than 15-lap with same metrics."""
        from scoring import score_session
        base_metrics = {
            "best_s": 60.0, "cv_pct": 1.0,
            "best_to_median_s": 0.5, "speed_mean_mps": 30.0,
            "accel_max_mps2": 10.0, "braking_max_mps2": 12.0,
            "early_mean_s": 61.0, "late_mean_s": 61.5,
            "early_yaw_var": 0.01, "late_yaw_var": 0.012,
        }
        theo = {
            "best_s": 58.0, "speed_mean_mps": 32.0,
            "accel_max_mps2": 12.0, "braking_max_mps2": 14.0,
        }
        short = score_session({**base_metrics, "n_laps": 15}, theo, "practice")
        long = score_session({**base_metrics, "n_laps": 200}, theo, "practice")
        assert short["total_score"] > long["total_score"]


class TestScoreSessionAdaptive:
    """Integration: score_session uses adaptive weights end-to-end."""

    def test_qualifying_sub_scores_suppressed(self):
        from scoring import score_session
        metrics = {
            "best_s": 60.0, "n_laps": 5, "cv_pct": 1.0,
            "best_to_median_s": 0.5, "speed_mean_mps": 30.0,
            "accel_max_mps2": 10.0, "braking_max_mps2": 12.0,
            "early_mean_s": 61.0, "late_mean_s": 61.5,
            "early_yaw_var": 0.01, "late_yaw_var": 0.012,
        }
        theo = {
            "best_s": 58.0, "speed_mean_mps": 32.0,
            "accel_max_mps2": 12.0, "braking_max_mps2": 14.0,
        }
        result = score_session(metrics, theo, "qualifying")
        assert result["sub_scores"]["consistency"]["score"] == 0.0
        assert result["sub_scores"]["consistency"]["max"] == 0.0
        assert result["sub_scores"]["robustness"]["score"] == 0.0
        assert result["sub_scores"]["adaptation"]["score"] == 0.0
        # Pace and execution should have all the budget
        pace_max = result["sub_scores"]["pace"]["max"]
        exec_max = result["sub_scores"]["execution"]["max"]
        assert abs(pace_max + exec_max - 100.0) < 0.01

    def test_track_state_passed_through(self):
        from scoring import score_session
        metrics = {
            "best_s": 60.0, "n_laps": 15, "cv_pct": 1.0,
            "best_to_median_s": 0.5, "speed_mean_mps": 30.0,
            "accel_max_mps2": 10.0, "braking_max_mps2": 12.0,
            "early_mean_s": 61.0, "late_mean_s": 61.5,
            "early_yaw_var": 0.01, "late_yaw_var": 0.012,
        }
        theo = {
            "best_s": 58.0, "speed_mean_mps": 32.0,
            "accel_max_mps2": 12.0, "braking_max_mps2": 14.0,
        }
        dry = score_session(metrics, theo, "race", track_state="dry")
        wet = score_session(metrics, theo, "race", track_state="wet")
        dry_adapt = dry["sub_scores"]["adaptation"]["max"]
        wet_adapt = wet["sub_scores"]["adaptation"]["max"]
        assert wet_adapt > dry_adapt


class TestReExports:
    """Verify new symbols are accessible from the scoring package."""

    def test_session_category_config_importable(self):
        from scoring import _SESSION_CATEGORY_CONFIG
        assert isinstance(_SESSION_CATEGORY_CONFIG, dict)

    def test_track_state_modifiers_importable(self):
        from scoring import _TRACK_STATE_MODIFIERS
        assert isinstance(_TRACK_STATE_MODIFIERS, dict)

    def test_apply_adaptive_weights_importable(self):
        from scoring import _apply_adaptive_weights
        assert callable(_apply_adaptive_weights)

    def test_backward_compat_weight_overrides_still_importable(self):
        from scoring import _SESSION_WEIGHT_OVERRIDES
        assert isinstance(_SESSION_WEIGHT_OVERRIDES, dict)
        assert "qualifying" in _SESSION_WEIGHT_OVERRIDES

    def test_backward_compat_apply_session_weights_still_importable(self):
        from scoring import _apply_session_weights
        assert callable(_apply_session_weights)
