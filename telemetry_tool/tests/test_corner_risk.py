"""Tests for corner risk scoring."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import numpy as np
import pandas as pd
import pytest

from telemetry_tool.corner_analysis import (
    CornerRiskScore, compute_corner_risk,
    CornerEvent, CornerTimeline,
)


def _make_corner():
    return {"corner_id": 1, "s_start": 100.0, "s_end": 200.0}


def _make_timeline(mrp_strength=10.0, event_stability=None):
    events = [
        CornerEvent("BP", 70.0, 0.9, "accel_long", -4.0, True),
        CornerEvent("EOB", 105.0, 0.9, "accel_long", -0.3, True),
        CornerEvent("MRP", 130.0, 0.8, "yaw_rate", 10.0, True),
        CornerEvent("MIN_SPEED", 135.0, 1.0, "speed", 15.0, True),
        CornerEvent("THROTTLE_ON", 150.0, 0.9, "accel_long", 0.5, True),
        CornerEvent("TRACK_OUT", 200.0, 0.5, "position", 0.0, True),
    ]
    return CornerTimeline(
        corner_id=1, events=events,
        segment_losses_s={}, segment_confidences={},
        mistakes=[], mrp_strength=mrp_strength,
        mrp_stability_std_m=0.0,
        event_stability=event_stability or {},
    )


def _make_lap_df(n=500):
    dist = np.linspace(0, 300, n)
    speed = np.ones(n) * 20.0
    accel = np.zeros(n)
    yaw = 10.0 * np.exp(-0.5 * ((dist - 130.0) / 10.0) ** 2)
    return pd.DataFrame({
        "Distance (m)": dist, "Speed (m/s)": speed,
        "accel_long_mps2": accel, "yaw_rate_dps": yaw,
    })


class TestCornerRiskScore:
    def test_clean_corner_low_risk(self):
        """Stable corner with strong MRP -> low risk index."""
        tl = _make_timeline(mrp_strength=10.0)
        df = _make_lap_df()
        corner = _make_corner()

        risk = compute_corner_risk(tl, [df, df, df, df], corner)
        assert risk is not None
        assert 0.0 <= risk.risk_index <= 1.0
        assert risk.risk_index < 0.5  # clean corner should be low risk

    def test_noisy_yaw_increases_risk(self):
        """Yaw noise across laps -> higher yaw_spike_risk."""
        tl = _make_timeline(mrp_strength=3.0)  # weak MRP

        # Create laps with varying yaw peaks
        laps = []
        for peak in [8, 15, 5, 20, 3]:
            n = 500
            dist = np.linspace(0, 300, n)
            yaw = float(peak) * np.exp(-0.5 * ((dist - 130.0) / 10.0) ** 2)
            laps.append(pd.DataFrame({
                "Distance (m)": dist, "Speed (m/s)": np.ones(n) * 20.0,
                "accel_long_mps2": np.zeros(n), "yaw_rate_dps": yaw,
            }))

        corner = _make_corner()
        risk = compute_corner_risk(tl, laps, corner)
        assert risk.yaw_spike_risk > 0.1  # should show some yaw instability

    def test_mrp_plateau_increases_risk(self):
        """Weak MRP (low prominence) -> higher mrp_plateau_risk."""
        tl = _make_timeline(mrp_strength=0.3)  # very weak
        df = _make_lap_df()
        corner = _make_corner()

        risk = compute_corner_risk(tl, [df], corner)
        assert risk.mrp_plateau_risk > 0.5

    def test_to_dict_serializable(self):
        """CornerRiskScore.to_dict() is JSON-serializable."""
        tl = _make_timeline()
        df = _make_lap_df()
        corner = _make_corner()

        risk = compute_corner_risk(tl, [df], corner)
        d = risk.to_dict()
        import json
        json.dumps(d)
        assert "risk_index" in d
        assert "yaw_spike_risk" in d

    def test_few_laps_low_confidence(self):
        """< 3 laps -> low confidence on stability-based risks."""
        tl = _make_timeline()
        df = _make_lap_df()
        corner = _make_corner()

        risk = compute_corner_risk(tl, [df], corner)
        assert risk.confidence < 0.5
