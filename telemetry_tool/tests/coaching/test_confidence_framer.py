"""Tests for confidence framer — strength rewriting."""
import pytest
from coaching.composers.confidence_framer import reframe_strengths


class TestConfidenceFramer:
    def test_reframes_confidence_weakness(self):
        strengths, weaknesses = reframe_strengths(
            strengths_raw=["Good pace"],
            weaknesses_raw=["Braking too early"],
            root_causes=["confidence"],
            corner_names=["Turn 3"],
        )
        assert len(weaknesses) == 1
        assert "Turn 3" in weaknesses[0]
        assert len(strengths) >= 2  # original + encouragement

    def test_reframes_technique_weakness(self):
        strengths, weaknesses = reframe_strengths(
            strengths_raw=["Consistent"],
            weaknesses_raw=["No trail braking"],
            root_causes=["technique"],
            corner_names=["Turn 5"],
        )
        assert "Turn 5" in weaknesses[0]

    def test_preserves_original_strengths(self):
        strengths, _ = reframe_strengths(
            strengths_raw=["Fast", "Smooth"],
            weaknesses_raw=["Late braking"],
            root_causes=["aggression"],
        )
        assert "Fast" in strengths
        assert "Smooth" in strengths

    def test_unknown_root_cause_falls_back(self):
        _, weaknesses = reframe_strengths(
            strengths_raw=[],
            weaknesses_raw=["Something odd"],
            root_causes=["unknown_root"],
        )
        assert len(weaknesses) == 1

    def test_empty_input(self):
        strengths, weaknesses = reframe_strengths([], [], [])
        assert strengths == []
        assert weaknesses == []
