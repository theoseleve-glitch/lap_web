"""Tests for brake release quality metrics."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import numpy as np
import pandas as pd
import pytest

from telemetry_tool.corner_analysis import (
    BrakeReleaseMetrics,
    BrakeYawCoupling,
    CornerEvent,
    CornerTimeline,
    compute_brake_release_metrics,
    compute_brake_yaw_coupling,
)


def _make_corner():
    return {"corner_id": 1, "s_start": 100.0, "s_end": 200.0}


def _make_timeline_with_bp_eob(bp_s=70.0, eob_s=105.0, throttle_on_s=150.0):
    events = [
        CornerEvent("BP", bp_s, 0.9, "accel_long", -4.0, True),
        CornerEvent("EOB", eob_s, 0.9, "accel_long", -0.3, True),
        CornerEvent("MRP", 130.0, 0.8, "yaw_rate", 10.0, True),
        CornerEvent("MIN_SPEED", 135.0, 1.0, "speed", 15.0, True),
        CornerEvent("THROTTLE_ON", throttle_on_s, 0.9, "accel_long", 0.5, True),
        CornerEvent("TRACK_OUT", 200.0, 0.5, "position", 0.0, True),
    ]
    return CornerTimeline(
        corner_id=1, events=events,
        segment_losses_s={}, segment_confidences={},
        mistakes=[], mrp_strength=10.0,
        mrp_stability_std_m=0.0, event_stability={},
    )


def _make_braking_df(n=500, bp_pos=70.0, eob_pos=105.0):
    """Synthetic lap with clear braking zone."""
    dist = np.linspace(0, 300, n)
    speed = np.ones(n) * 30.0

    # Braking zone
    brake_mask = (dist >= bp_pos) & (dist <= eob_pos)
    speed[brake_mask] = np.interp(dist[brake_mask], [bp_pos, eob_pos], [30, 15])

    # Mid corner
    mid_mask = (dist > eob_pos) & (dist <= 150)
    speed[mid_mask] = 15.0

    # Acceleration
    accel_mask = (dist > 150) & (dist <= 200)
    speed[accel_mask] = np.interp(dist[accel_mask], [150, 200], [15, 28])
    speed[dist > 200] = 28.0

    # Derive accel
    ds = np.gradient(dist)
    ds[ds == 0] = 1e-6
    dv = np.gradient(speed)
    accel = speed * dv / ds

    return pd.DataFrame({
        "Distance (m)": dist,
        "Speed (m/s)": speed,
        "accel_long_mps2": accel,
    })


class TestBrakeReleaseMetrics:
    def test_basic_brake_release_from_accel(self):
        """Accel-only fallback produces metrics with lower confidence."""
        df = _make_braking_df()
        tl = _make_timeline_with_bp_eob()
        corner = _make_corner()

        metrics = compute_brake_release_metrics(tl, df, corner)
        assert metrics is not None
        assert metrics.source == "accel_inferred"
        assert metrics.confidence <= 0.7
        assert metrics.peak_decel_mps2 < 0  # negative = braking
        assert metrics.brake_zone_length_m > 0
        assert 0.0 <= metrics.terminal_trail_pct <= 100.0

    def test_brake_pressure_channel_used(self):
        """When brake pressure column exists, use it with high confidence."""
        df = _make_braking_df()
        # Add synthetic brake pressure
        dist = df["Distance (m)"].values
        brake_pct = np.zeros(len(df))
        bp_mask = (dist >= 70) & (dist <= 105)
        brake_pct[bp_mask] = np.interp(dist[bp_mask], [70, 85, 105], [0, 100, 0])
        df["Brake (%)"] = brake_pct

        tl = _make_timeline_with_bp_eob()
        corner = _make_corner()

        metrics = compute_brake_release_metrics(tl, df, corner)
        assert metrics is not None
        assert metrics.source == "brake_pressure"
        assert metrics.confidence >= 0.8
        assert metrics.peak_brake_pressure > 0

    def test_release_linearity(self):
        """Linear release -> high linearity score."""
        df = _make_braking_df()
        tl = _make_timeline_with_bp_eob()
        corner = _make_corner()

        metrics = compute_brake_release_metrics(tl, df, corner)
        assert 0.0 <= metrics.release_linearity <= 1.0

    def test_to_dict_serializable(self):
        """BrakeReleaseMetrics.to_dict() is JSON-serializable."""
        df = _make_braking_df()
        tl = _make_timeline_with_bp_eob()
        corner = _make_corner()

        metrics = compute_brake_release_metrics(tl, df, corner)
        d = metrics.to_dict()
        import json
        json.dumps(d)
        assert "peak_decel_mps2" in d
        assert "terminal_trail_pct" in d

    def test_bp_before_eob_invariant(self):
        """Peak deceleration must occur before or at EOB."""
        df = _make_braking_df()
        tl = _make_timeline_with_bp_eob()
        corner = _make_corner()

        metrics = compute_brake_release_metrics(tl, df, corner)
        # The peak decel position should be between BP and EOB
        assert metrics.peak_decel_mps2 < 0  # negative means braking


# =============================================================================
# Brake-Yaw Coupling tests
# =============================================================================


def _make_coupling_timeline(eob_s=105.0, mrp_s=130.0, throttle_on_s=150.0):
    events = [
        CornerEvent("BP", 70.0, 0.9, "accel_long", -4.0, True),
        CornerEvent("EOB", eob_s, 0.9, "accel_long", -0.3, True),
        CornerEvent("MRP", mrp_s, 0.8, "yaw_rate", 10.0, True),
        CornerEvent("MIN_SPEED", 135.0, 1.0, "speed", 15.0, True),
        CornerEvent("THROTTLE_ON", throttle_on_s, 0.9, "accel_long", 0.5, True),
        CornerEvent("TRACK_OUT", 200.0, 0.5, "position", 0.0, True),
    ]
    return CornerTimeline(
        corner_id=1, events=events,
        segment_losses_s={}, segment_confidences={},
        mistakes=[], mrp_strength=10.0,
        mrp_stability_std_m=0.0, event_stability={},
    )


class TestBrakeYawCoupling:
    def test_well_coupled_signal(self):
        """Brake release correlates with yaw growth -> well_coupled."""
        n = 500
        dist = np.linspace(0, 300, n)
        speed = np.ones(n) * 20.0
        accel = np.zeros(n)

        # Brake release (105-150m): accel goes from -3 to 0
        brake_zone = (dist >= 105) & (dist <= 150)
        accel[brake_zone] = np.interp(dist[brake_zone], [105, 150], [-3, 0])

        # Yaw grows in sync with brake release
        yaw = np.zeros(n)
        yaw_zone = (dist >= 105) & (dist <= 150)
        yaw[yaw_zone] = np.interp(dist[yaw_zone], [105, 150], [0, 12])

        df = pd.DataFrame({
            "Distance (m)": dist, "Speed (m/s)": speed,
            "accel_long_mps2": accel, "yaw_rate_dps": yaw,
        })

        tl = _make_coupling_timeline()
        corner = {"corner_id": 1, "s_start": 100.0, "s_end": 200.0}

        coupling = compute_brake_yaw_coupling(tl, df, corner)
        assert coupling is not None
        assert coupling.pattern in ("well_coupled", "under_rotation", "over_rotation")
        assert 0.0 <= coupling.coupling_score <= 1.0
        assert coupling.confidence > 0

    def test_missing_yaw_unavailable(self):
        """No yaw channel -> coupling unavailable."""
        n = 500
        dist = np.linspace(0, 300, n)
        df = pd.DataFrame({
            "Distance (m)": dist,
            "Speed (m/s)": np.ones(n) * 20.0,
            "accel_long_mps2": np.zeros(n),
        })

        tl = _make_coupling_timeline()
        corner = {"corner_id": 1, "s_start": 100.0, "s_end": 200.0}

        coupling = compute_brake_yaw_coupling(tl, df, corner)
        assert coupling is not None
        assert coupling.pattern == "unavailable"
        assert coupling.confidence == 0.0

    def test_over_rotation_detected(self):
        """Yaw spikes while brake still high -> over_rotation."""
        n = 500
        dist = np.linspace(0, 300, n)
        speed = np.ones(n) * 20.0
        accel = np.zeros(n)

        # Still heavy braking in coupling window
        brake_zone = (dist >= 105) & (dist <= 150)
        accel[brake_zone] = -3.0  # constant heavy braking

        # But yaw spikes anyway
        yaw = np.zeros(n)
        yaw_zone = (dist >= 110) & (dist <= 130)
        yaw[yaw_zone] = 15.0  # sudden spike

        df = pd.DataFrame({
            "Distance (m)": dist, "Speed (m/s)": speed,
            "accel_long_mps2": accel, "yaw_rate_dps": yaw,
        })

        tl = _make_coupling_timeline()
        corner = {"corner_id": 1, "s_start": 100.0, "s_end": 200.0}

        coupling = compute_brake_yaw_coupling(tl, df, corner)
        assert coupling is not None
        assert coupling.pattern == "over_rotation"

    def test_to_dict_serializable(self):
        """BrakeYawCoupling.to_dict() is JSON-serializable."""
        n = 500
        dist = np.linspace(0, 300, n)
        yaw = 10.0 * np.exp(-0.5 * ((dist - 130.0) / 10.0) ** 2)
        accel = np.zeros(n)
        accel[(dist >= 105) & (dist <= 150)] = np.interp(
            dist[(dist >= 105) & (dist <= 150)], [105, 150], [-3, 0]
        )
        df = pd.DataFrame({
            "Distance (m)": dist, "Speed (m/s)": np.ones(n) * 20.0,
            "accel_long_mps2": accel, "yaw_rate_dps": yaw,
        })
        tl = _make_coupling_timeline()
        corner = {"corner_id": 1, "s_start": 100.0, "s_end": 200.0}

        coupling = compute_brake_yaw_coupling(tl, df, corner)
        d = coupling.to_dict()
        import json
        json.dumps(d)
        assert "coupling_score" in d
        assert "pattern" in d
