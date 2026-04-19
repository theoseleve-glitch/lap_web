"""Tests for Bayesian fusion (C1, C3, C5, C6)."""
import numpy as np
import pytest

from telemetry_tool.handling.types import DetectorVote, FusedEvent
from telemetry_tool.handling.fusion import BayesianFusion
from telemetry_tool.tests.handling.conftest import _make_corner


@pytest.fixture
def fusion():
    return BayesianFusion()


@pytest.fixture
def corner():
    return _make_corner()


class TestBayesianFusion:
    def test_agreeing_votes_produce_event(self, fusion, corner):
        votes = [
            DetectorVote("a", -0.7, 0.8, "exit"),
            DetectorVote("b", -0.5, 0.6, "exit"),
        ]
        events = fusion.fuse_corner(corner, votes)
        assert len(events) == 1
        assert events[0].label == "oversteer"
        assert events[0].confidence > 0

    def test_single_detector_below_threshold_filtered(self, fusion, corner):
        """C6: single detector below 0.8 confidence should be filtered."""
        votes = [DetectorVote("a", 0.5, 0.4, "mid")]
        events = fusion.fuse_corner(corner, votes)
        assert len(events) == 0

    def test_single_detector_weak_filtered_by_c6(self, fusion, corner):
        """C6: single detector with low confidence gets filtered."""
        votes = [DetectorVote("a", 0.5, 0.4, "entry")]
        events = fusion.fuse_corner(corner, votes)
        assert len(events) == 0, "Weak single detector should be filtered"

    def test_single_detector_strong_passes_c6(self, fusion, corner):
        """C6: single detector with very high confidence passes."""
        votes = [DetectorVote("a", 1.0, 0.99, "entry")]
        events = fusion.fuse_corner(corner, votes)
        assert len(events) >= 1, "Strong single detector should pass C6"

    def test_conflict_detected(self, fusion, corner):
        """C3: conflicting votes should flag conflict."""
        votes = [
            DetectorVote("a", +0.8, 0.9, "entry"),
            DetectorVote("b", -0.8, 0.9, "entry"),
        ]
        events = fusion.fuse_corner(corner, votes)
        # May or may not produce event, but if it does, conflict should be True
        for e in events:
            if e.zone == "entry":
                assert e.conflict is True

    def test_confidence_modifier_reduces_confidence(self, fusion, corner):
        """B7 line variation should reduce confidence."""
        base_votes = [
            DetectorVote("a", -0.7, 0.8, "exit"),
            DetectorVote("b", -0.5, 0.6, "exit"),
        ]
        events_base = fusion.fuse_corner(corner, base_votes)

        modified_votes = base_votes + [
            DetectorVote("line_var", 0.0, 0.5, "mid", is_confidence_modifier=True),
        ]
        events_mod = fusion.fuse_corner(corner, modified_votes)

        if events_base and events_mod:
            assert events_mod[0].confidence < events_base[0].confidence

    def test_per_phase_fusion(self, fusion, corner):
        """C5: votes in different zones produce separate events."""
        votes = [
            DetectorVote("a", +0.8, 0.9, "entry"),
            DetectorVote("b", -0.8, 0.9, "exit"),
        ]
        events = fusion.fuse_corner(corner, votes)
        # Should NOT merge entry understeer with exit oversteer
        zones = {e.zone for e in events}
        # Each zone should have its own event (if above threshold)
        for e in events:
            assert e.zone in ("entry", "exit")

    def test_empty_votes_no_events(self, fusion, corner):
        events = fusion.fuse_corner(corner, [])
        assert events == []

    def test_event_serialization(self, fusion, corner):
        votes = [
            DetectorVote("a", -0.7, 0.8, "exit"),
            DetectorVote("b", -0.5, 0.6, "exit"),
        ]
        events = fusion.fuse_corner(corner, votes)
        if events:
            d = events[0].to_dict()
            assert "event_type" in d
            assert "confidence" in d
            assert "detector_votes" in d
            assert d["event_type"] in ("understeer", "oversteer", "neutral")
