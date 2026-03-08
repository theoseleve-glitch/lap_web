"""Tests for compound corner detection and metrics."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import numpy as np
import pandas as pd
import pytest

from telemetry_tool.corner_detection import detect_compound_corners, identify_setup_corners
from telemetry_tool.corner_analysis import CompoundCornerMetrics, compute_compound_metrics


class TestCompoundDetection:
    def test_close_corners_grouped(self):
        """Two corners with < 50m gap -> grouped as compound."""
        corners = [
            {"corner_id": 1, "s_start": 100.0, "s_end": 150.0, "s_apex": 125.0},
            {"corner_id": 2, "s_start": 175.0, "s_end": 230.0, "s_apex": 200.0},
        ]
        n = 500
        dist = np.linspace(0, 400, n)
        df = pd.DataFrame({"Distance (m)": dist, "Speed (m/s)": np.ones(n) * 20.0})

        compounds = detect_compound_corners(corners, df)
        assert len(compounds) == 1
        assert set(compounds[0]["corner_ids"]) == {1, 2}

    def test_far_corners_not_grouped(self):
        """Two corners with > 100m gap -> not grouped."""
        corners = [
            {"corner_id": 1, "s_start": 50.0, "s_end": 100.0, "s_apex": 75.0},
            {"corner_id": 2, "s_start": 250.0, "s_end": 300.0, "s_apex": 275.0},
        ]
        n = 500
        dist = np.linspace(0, 400, n)
        df = pd.DataFrame({"Distance (m)": dist, "Speed (m/s)": np.ones(n) * 20.0})

        compounds = detect_compound_corners(corners, df)
        assert len(compounds) == 0

    def test_three_corner_compound(self):
        """Three close corners -> single compound group."""
        corners = [
            {"corner_id": 1, "s_start": 100.0, "s_end": 130.0, "s_apex": 115.0},
            {"corner_id": 2, "s_start": 150.0, "s_end": 180.0, "s_apex": 165.0},
            {"corner_id": 3, "s_start": 200.0, "s_end": 240.0, "s_apex": 220.0},
        ]
        n = 500
        dist = np.linspace(0, 400, n)
        df = pd.DataFrame({"Distance (m)": dist, "Speed (m/s)": np.ones(n) * 20.0})

        compounds = detect_compound_corners(corners, df)
        assert len(compounds) == 1
        assert len(compounds[0]["corner_ids"]) == 3

    def test_compound_marks_corners(self):
        """Compound detection marks corners with compound_id."""
        corners = [
            {"corner_id": 1, "s_start": 100.0, "s_end": 130.0, "s_apex": 115.0},
            {"corner_id": 2, "s_start": 150.0, "s_end": 180.0, "s_apex": 165.0},
        ]
        n = 500
        dist = np.linspace(0, 400, n)
        df = pd.DataFrame({"Distance (m)": dist, "Speed (m/s)": np.ones(n) * 20.0})

        detect_compound_corners(corners, df)
        assert corners[0].get("compound_id") is not None
        assert corners[0]["compound_id"] == corners[1]["compound_id"]


class TestCompoundMetrics:
    def test_compute_compound_metrics(self):
        """Compound metrics computed with blame attribution."""
        corners = [
            {"corner_id": 1, "s_start": 100.0, "s_end": 130.0, "s_apex": 115.0},
            {"corner_id": 2, "s_start": 150.0, "s_end": 180.0, "s_apex": 165.0},
        ]
        compound = {"compound_id": 1, "corner_ids": [1, 2]}

        from telemetry_tool.corner_analysis import CornerPerformance
        perfs = [
            CornerPerformance(corner_id=1, s_start=100, s_end=130, time_loss_s=0.3),
            CornerPerformance(corner_id=2, s_start=150, s_end=180, time_loss_s=0.5),
        ]

        metrics = compute_compound_metrics(compound, perfs, corners)
        assert metrics is not None
        assert metrics.compound_id == 1
        assert len(metrics.corner_ids) == 2
        assert metrics.leverage_corner_id in [1, 2]
        assert sum(metrics.blame_attribution.values()) == pytest.approx(1.0, abs=0.01)


class TestSetupCorners:
    def test_kink_before_heavy_braking_is_setup(self):
        """Kink followed by heavy braking corner within 80m -> setup corner."""
        corners = [
            {"corner_id": 1, "s_start": 100.0, "s_end": 120.0, "s_apex": 110.0, "corner_type": "kink"},
            {"corner_id": 2, "s_start": 160.0, "s_end": 220.0, "s_apex": 190.0, "corner_type": "hairpin"},
        ]
        n = 500
        dist = np.linspace(0, 400, n)
        speed = np.ones(n) * 30.0
        # Kink: minimal speed loss
        kink_mask = (dist >= 100) & (dist <= 120)
        speed[kink_mask] = 28.0
        # Hairpin: heavy braking
        hp_mask = (dist >= 140) & (dist <= 160)
        speed[hp_mask] = np.interp(dist[hp_mask], [140, 160], [30, 10])
        hp_mid = (dist > 160) & (dist <= 220)
        speed[hp_mid] = 10.0

        ds = np.gradient(dist)
        ds[ds == 0] = 1e-6
        dv = np.gradient(speed)
        accel = speed * dv / ds

        df = pd.DataFrame({
            "Distance (m)": dist, "Speed (m/s)": speed,
            "accel_long_mps2": accel,
        })

        identify_setup_corners(corners, df)
        assert corners[0].get("corner_type") == "setup"
        assert corners[0].get("is_setup_corner") is True
        assert corners[0].get("target_corner_id") == 2

    def test_normal_corner_not_setup(self):
        """Normal medium corner not tagged as setup even near another corner."""
        corners = [
            {"corner_id": 1, "s_start": 100.0, "s_end": 160.0, "s_apex": 130.0, "corner_type": "medium"},
            {"corner_id": 2, "s_start": 200.0, "s_end": 260.0, "s_apex": 230.0, "corner_type": "medium"},
        ]
        n = 500
        dist = np.linspace(0, 400, n)
        df = pd.DataFrame({
            "Distance (m)": dist, "Speed (m/s)": np.ones(n) * 20.0,
            "accel_long_mps2": np.zeros(n),
        })

        identify_setup_corners(corners, df)
        assert corners[0].get("is_setup_corner", False) is False
        assert corners[0].get("corner_type") == "medium"

    def test_kink_far_from_braking_not_setup(self):
        """Kink with next corner > 100m away -> not setup."""
        corners = [
            {"corner_id": 1, "s_start": 50.0, "s_end": 70.0, "s_apex": 60.0, "corner_type": "kink"},
            {"corner_id": 2, "s_start": 250.0, "s_end": 310.0, "s_apex": 280.0, "corner_type": "hairpin"},
        ]
        n = 500
        dist = np.linspace(0, 400, n)
        df = pd.DataFrame({
            "Distance (m)": dist, "Speed (m/s)": np.ones(n) * 20.0,
            "accel_long_mps2": np.zeros(n),
        })

        identify_setup_corners(corners, df)
        assert corners[0].get("is_setup_corner", False) is False
