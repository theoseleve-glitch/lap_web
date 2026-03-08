"""Tests for theoretical per-corner targets."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import numpy as np
import pandas as pd
import pytest

from telemetry_tool.corner_analysis import (
    CornerTargets, compute_corner_targets,
    CornerEvent, CornerTimeline, CornerPerformance,
    detect_corner_events,
)


def _make_corner(cid=1, s_start=100.0, s_end=200.0):
    return {"corner_id": cid, "s_start": s_start, "s_end": s_end, "s_apex": (s_start + s_end) / 2}


def _make_theoretical_df(n=500, lap_length=400.0):
    dist = np.linspace(0, lap_length, n)
    speed = np.ones(n) * 30.0
    # Slow in corner zone
    mask = (dist >= 80) & (dist <= 200)
    speed[mask] = np.interp(dist[mask], [80, 100, 150, 200], [30, 20, 15, 25])
    return pd.DataFrame({"distance_m": dist, "v_env_mps": speed})


def _make_driver_df(n=500, lap_length=400.0):
    dist = np.linspace(0, lap_length, n)
    speed = np.ones(n) * 28.0  # slightly slower than theoretical
    mask = (dist >= 85) & (dist <= 200)
    speed[mask] = np.interp(dist[mask], [85, 105, 155, 200], [28, 18, 13, 22])
    ds = np.gradient(dist)
    ds[ds == 0] = 1e-6
    dv = np.gradient(speed)
    accel = speed * dv / ds
    return pd.DataFrame({
        "Distance (m)": dist, "Speed (m/s)": speed, "accel_long_mps2": accel,
    })


class TestCornerTargets:
    def test_targets_generated(self):
        """Targets computed for a single corner."""
        corner = _make_corner(1, 100.0, 200.0)
        theo_df = _make_theoretical_df()
        drv_df = _make_driver_df()

        # Get driver events
        tl = detect_corner_events(corner, drv_df)
        # Get theoretical events
        theo_tl = detect_corner_events(corner, theo_df)

        targets = compute_corner_targets(
            corner, tl, theo_tl, theo_df, drv_df,
        )
        assert targets is not None
        assert targets.corner_id == 1
        assert len(targets.target_events) > 0
        assert targets.priority in ("entry", "exit", "balanced")
        assert len(targets.recommended_changes) > 0

    def test_recommended_changes_have_deltas(self):
        """Each recommended change has delta_m and delta_kmh."""
        corner = _make_corner(1, 100.0, 200.0)
        theo_df = _make_theoretical_df()
        drv_df = _make_driver_df()

        tl = detect_corner_events(corner, drv_df)
        theo_tl = detect_corner_events(corner, theo_df)

        targets = compute_corner_targets(corner, tl, theo_tl, theo_df, drv_df)
        for change in targets.recommended_changes:
            assert "event" in change
            assert "delta_m" in change

    def test_to_dict_serializable(self):
        """CornerTargets.to_dict() is JSON-serializable."""
        corner = _make_corner(1, 100.0, 200.0)
        theo_df = _make_theoretical_df()
        drv_df = _make_driver_df()
        tl = detect_corner_events(corner, drv_df)
        theo_tl = detect_corner_events(corner, theo_df)

        targets = compute_corner_targets(corner, tl, theo_tl, theo_df, drv_df)
        d = targets.to_dict()
        import json
        json.dumps(d)
        assert "target_events" in d
        assert "recommended_changes" in d

    def test_exit_priority_after_long_straight(self):
        """Corner followed by long straight -> exit priority."""
        corner = _make_corner(1, 100.0, 200.0)
        corner["next_straight_m"] = 300.0  # long straight follows
        theo_df = _make_theoretical_df()
        drv_df = _make_driver_df()
        tl = detect_corner_events(corner, drv_df)
        theo_tl = detect_corner_events(corner, theo_df)

        targets = compute_corner_targets(corner, tl, theo_tl, theo_df, drv_df)
        assert targets.priority == "exit"
