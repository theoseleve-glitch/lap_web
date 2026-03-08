"""Tests for the Corner Timeline event detection system."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import numpy as np
import pandas as pd
import pytest

from telemetry_tool.corner_analysis import CornerEvent, CornerTimeline


class TestCornerEventDataclass:
    def test_create_and_to_dict(self):
        ev = CornerEvent(
            event_type="BP",
            s_position=100.0,
            confidence=0.9,
            source_channel="accel_long",
            value=-3.5,
            available=True,
        )
        d = ev.to_dict()
        assert d["event_type"] == "BP"
        assert d["s_position"] == 100.0
        assert d["confidence"] == 0.9
        assert d["source_channel"] == "accel_long"
        assert d["value"] == -3.5
        assert d["available"] is True

    def test_unavailable_event(self):
        ev = CornerEvent(
            event_type="MRP",
            s_position=0.0,
            confidence=0.0,
            source_channel="yaw_rate",
            value=0.0,
            available=False,
        )
        assert ev.available is False
        assert ev.confidence == 0.0


class TestCornerTimelineDataclass:
    def test_create_and_to_dict(self):
        events = [
            CornerEvent("BP", 90.0, 0.95, "accel_long", -3.0, True),
            CornerEvent("EOB", 110.0, 0.90, "accel_long", -0.3, True),
            CornerEvent("MRP", 125.0, 0.85, "yaw_rate", 12.0, True),
            CornerEvent("MIN_SPEED", 130.0, 1.0, "speed", 15.5, True),
            CornerEvent("THROTTLE_ON", 140.0, 0.90, "accel_long", 0.8, True),
            CornerEvent("TRACK_OUT", 170.0, 0.50, "position", 0.0, True),
        ]
        tl = CornerTimeline(
            corner_id=1,
            events=events,
            segment_losses_s={},
            segment_confidences={},
            mistakes=[],
            mrp_strength=12.0,
            mrp_stability_std_m=0.0,
            event_stability={},
        )
        d = tl.to_dict()
        assert d["corner_id"] == 1
        assert len(d["events"]) == 6
        assert d["mrp_strength"] == 12.0

    def test_get_event(self):
        events = [
            CornerEvent("BP", 90.0, 0.95, "accel_long", -3.0, True),
            CornerEvent("MRP", 125.0, 0.85, "yaw_rate", 12.0, True),
        ]
        tl = CornerTimeline(
            corner_id=1, events=events,
            segment_losses_s={}, segment_confidences={},
            mistakes=[], mrp_strength=12.0,
            mrp_stability_std_m=0.0, event_stability={},
        )
        assert tl.get_event("BP") is not None
        assert tl.get_event("MRP").value == 12.0
        assert tl.get_event("APEX") is None
