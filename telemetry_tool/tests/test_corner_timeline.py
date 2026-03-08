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


# ── detect_corner_events tests ──────────────────────────────────────────────

from telemetry_tool.corner_analysis import detect_corner_events


def _make_corner(cid=1, s_start=100.0, s_end=200.0):
    return {"corner_id": cid, "s_start": s_start, "s_end": s_end}


def _make_braking_lap_df(n=500, corner_s_start=100.0, corner_s_end=200.0):
    """Synthetic lap with clear braking, min-speed, and acceleration zones."""
    dist = np.linspace(0, 300, n)
    speed = np.ones(n) * 30.0

    brake_mask = (dist >= 70) & (dist <= 100)
    speed[brake_mask] = np.interp(dist[brake_mask], [70, 100], [30, 15])
    mid_mask = (dist > 100) & (dist <= 150)
    speed[mid_mask] = 15.0
    accel_mask = (dist > 150) & (dist <= 200)
    speed[accel_mask] = np.interp(dist[accel_mask], [150, 200], [15, 28])
    post_mask = dist > 200
    speed[post_mask] = 28.0

    ds = np.gradient(dist)
    ds[ds == 0] = 1e-6
    dv = np.gradient(speed)
    accel_long = speed * dv / ds

    return pd.DataFrame({
        "Distance (m)": dist,
        "Speed (m/s)": speed,
        "accel_long_mps2": accel_long,
    })


class TestDetectCornerEvents:
    def test_braking_signal_detects_bp_eob(self):
        df = _make_braking_lap_df()
        corner = _make_corner(1, 100.0, 200.0)
        tl = detect_corner_events(corner, df)
        bp = tl.get_event("BP")
        eob = tl.get_event("EOB")
        assert bp is not None and bp.available
        assert eob is not None and eob.available
        assert 60.0 <= bp.s_position <= 100.0
        assert eob.s_position > bp.s_position

    def test_min_speed_detected(self):
        df = _make_braking_lap_df()
        corner = _make_corner(1, 100.0, 200.0)
        tl = detect_corner_events(corner, df)
        ms = tl.get_event("MIN_SPEED")
        assert ms is not None and ms.available
        assert 95.0 <= ms.s_position <= 155.0
        assert ms.value == pytest.approx(15.0, abs=1.0)

    def test_throttle_on_detected(self):
        df = _make_braking_lap_df()
        corner = _make_corner(1, 100.0, 200.0)
        tl = detect_corner_events(corner, df)
        to = tl.get_event("THROTTLE_ON")
        ms = tl.get_event("MIN_SPEED")
        assert to is not None and to.available
        assert ms is not None
        assert to.s_position >= ms.s_position

    def test_track_out_fallback_to_s_end(self):
        df = _make_braking_lap_df()
        corner = _make_corner(1, 100.0, 200.0)
        tl = detect_corner_events(corner, df)
        tout = tl.get_event("TRACK_OUT")
        assert tout is not None
        assert tout.s_position == pytest.approx(200.0, abs=1.0)

    def test_events_ordered_by_s_position(self):
        df = _make_braking_lap_df()
        corner = _make_corner(1, 100.0, 200.0)
        tl = detect_corner_events(corner, df)
        positions = [e.s_position for e in tl.events if e.available]
        assert positions == sorted(positions)
