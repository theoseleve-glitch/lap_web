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
