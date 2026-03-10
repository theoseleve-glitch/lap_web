"""Test scoring system differentiates by session type."""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestScoringSessionTypes:
    def test_weight_normalization(self):
        """Backward-compat _SESSION_WEIGHT_OVERRIDES should still exist."""
        from scoring import _SESSION_WEIGHT_OVERRIDES
        assert len(_SESSION_WEIGHT_OVERRIDES) >= 10

    def test_session_category_config_complete(self):
        """New config should cover all session types."""
        from scoring import _SESSION_CATEGORY_CONFIG
        required = {"qualifying", "race", "practice", "warmup", "test",
                     "endurance", "heat", "final", "sprint"}
        assert required.issubset(set(_SESSION_CATEGORY_CONFIG.keys()))

    def test_qualifying_suppresses_consistency(self):
        from scoring import _SESSION_CATEGORY_CONFIG
        q = _SESSION_CATEGORY_CONFIG["qualifying"]
        assert "consistency" in q["suppressed"]

    def test_race_prioritizes_robustness(self):
        from scoring import _SESSION_CATEGORY_CONFIG
        r = _SESSION_CATEGORY_CONFIG["race"]
        assert r["emphasis"].get("robustness", 0) > 1.0

    def test_endurance_high_robustness(self):
        from scoring import _SESSION_CATEGORY_CONFIG
        for key in ("endurance", "endurance_stint", "endurance_race"):
            if key in _SESSION_CATEGORY_CONFIG:
                e = _SESSION_CATEGORY_CONFIG[key]
                assert e["emphasis"].get("robustness", 0) >= 1.4

    def test_practice_emphasizes_adaptation(self):
        from scoring import _SESSION_CATEGORY_CONFIG
        p = _SESSION_CATEGORY_CONFIG["practice"]
        assert p["emphasis"].get("adaptation", 0) > 1.0

    def test_no_overlap_suppressed_emphasis(self):
        from scoring import _SESSION_CATEGORY_CONFIG
        for stype, cfg in _SESSION_CATEGORY_CONFIG.items():
            overlap = cfg["suppressed"] & set(cfg["emphasis"].keys())
            assert not overlap, f"{stype} has overlap: {overlap}"
