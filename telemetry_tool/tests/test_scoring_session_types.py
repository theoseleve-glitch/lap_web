"""Test scoring system differentiates by session type."""
import pytest


class TestScoringSessionTypes:
    def test_weight_normalization(self):
        """All session-type weights should normalize properly."""
        from scoring import _SESSION_WEIGHT_OVERRIDES
        for stype, weights in _SESSION_WEIGHT_OVERRIDES.items():
            total = sum(weights.values())
            assert 3.0 < total < 7.0, f"{stype} weights sum to {total}"

    def test_qualifying_prioritizes_pace(self):
        from scoring import _SESSION_WEIGHT_OVERRIDES
        w = _SESSION_WEIGHT_OVERRIDES.get("qualifying", {})
        assert w.get("pace", 0) > w.get("robustness", 0)

    def test_race_prioritizes_robustness(self):
        from scoring import _SESSION_WEIGHT_OVERRIDES
        w = _SESSION_WEIGHT_OVERRIDES.get("race", {})
        assert w.get("robustness", 0) > w.get("pace", 0)

    def test_endurance_high_robustness(self):
        from scoring import _SESSION_WEIGHT_OVERRIDES
        for key in ("endurance_stint", "endurance_race"):
            if key in _SESSION_WEIGHT_OVERRIDES:
                w = _SESSION_WEIGHT_OVERRIDES[key]
                assert w.get("robustness", 0) >= 1.4

    def test_all_types_have_five_keys(self):
        from scoring import _SESSION_WEIGHT_OVERRIDES
        for stype, weights in _SESSION_WEIGHT_OVERRIDES.items():
            assert set(weights.keys()) == {"pace", "consistency", "execution", "robustness", "adaptation"}
