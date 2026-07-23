"""Tests for template coverage — every cause×severity×vehicle must have a template."""
import pytest
from coaching.taxonomy.causes import CauseTaxonomy
from coaching.templates.corner_tips import CORNER_TIPS
from coaching.templates.drills import DRILL_LIBRARY
from coaching.templates.narratives import SESSION_NARRATIVES
from coaching.templates.confidence_frames import CONFIDENCE_FRAMES
from coaching.templates.mental_imagery import MENTAL_IMAGERY


class TestCornerTipCoverage:
    def test_all_combinations_covered(self):
        tax = CauseTaxonomy()
        missing = []
        for cat_name, causes in tax.categories.items():
            for cause_id in causes:
                for severity in ("mild", "moderate", "severe"):
                    for vehicle in ("kart", "car"):
                        key = (cause_id, severity, vehicle)
                        if key not in CORNER_TIPS:
                            missing.append(key)
        assert missing == [], f"Missing templates: {missing}"

    def test_each_template_has_required_keys(self):
        for key, template in CORNER_TIPS.items():
            assert "tip" in template, f"{key} missing 'tip'"
            assert "progressive_steps" in template, f"{key} missing 'progressive_steps'"
            assert "symptom_check" in template, f"{key} missing 'symptom_check'"
            assert len(template["progressive_steps"]) == 3, f"{key} needs 3 progressive steps"

    def test_placeholder_formatting_doesnt_crash(self):
        """Fill a template with dummy values to verify no KeyError."""
        sample_key = list(CORNER_TIPS.keys())[0]
        template = CORNER_TIPS[sample_key]
        dummy = {
            "corner_name": "Turn 3", "delta_m": 10.0, "variance_m": 2.5,
            "step_m": 5.0, "current_m": 200.0, "step1_m": 195.0,
            "step2_m": 190.0, "target_delta_m": 3.0, "time_loss_s": 0.25,
            "exit_speed_loss_kmh": 4.0, "cascade_time_s": 0.18,
            "pct_increase": 12.0, "throttle_drop_pct": 60.0,
            "lift_duration_s": 0.15, "grip_pct": 75.0,
            "weight_shift_kg": 45.0, "yaw_spike": 8.5,
        }
        # Should not raise
        template["tip"].format(**dummy)


class TestDrillLibrary:
    def test_at_least_20_drill_types(self):
        assert len(DRILL_LIBRARY) >= 20

    def test_each_drill_has_three_difficulty_levels(self):
        for drill_id, drill in DRILL_LIBRARY.items():
            assert "title" in drill
            assert "difficulty_levels" in drill
            levels = drill["difficulty_levels"]
            for level in ("beginner", "intermediate", "advanced"):
                assert level in levels, f"{drill_id} missing {level}"
                assert "description" in levels[level]
                assert "success_criteria" in levels[level]
                assert "lap_count" in levels[level]

    def test_each_drill_has_applicable_causes(self):
        for drill_id, drill in DRILL_LIBRARY.items():
            assert "applicable_causes" in drill
            assert len(drill["applicable_causes"]) >= 1


class TestSessionNarratives:
    def test_coverage(self):
        """At least one narrative per grade band."""
        grade_bands = set()
        for key in SESSION_NARRATIVES:
            grade_bands.add(key[0])
        assert "S-A" in grade_bands
        assert "B-C" in grade_bands
        assert "D-F" in grade_bands

    def test_each_is_list_of_variants(self):
        for key, variants in SESSION_NARRATIVES.items():
            assert isinstance(variants, list)
            assert len(variants) >= 1


class TestMentalImagery:
    def test_has_entries(self):
        assert len(MENTAL_IMAGERY) >= 5

    def test_each_has_pre_session(self):
        for key, entry in MENTAL_IMAGERY.items():
            assert "pre_session" in entry
            assert len(entry["pre_session"]) > 50  # substantive text
