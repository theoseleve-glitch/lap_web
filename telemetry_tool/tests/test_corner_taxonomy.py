"""Tests for corner type classification."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import numpy as np
import pandas as pd
import pytest

from telemetry_tool.corner_detection import classify_corner_type, classify_corner_types


def _make_lap_df(n=1000, lap_length=500.0):
    dist = np.linspace(0, lap_length, n)
    speed = np.ones(n) * 25.0
    return pd.DataFrame({"Distance (m)": dist, "Speed (m/s)": speed})


class TestCornerTaxonomy:
    def test_hairpin(self):
        """High curvature, short, low min speed -> hairpin."""
        corner = {"corner_id": 1, "s_start": 100.0, "s_end": 140.0, "s_apex": 120.0}
        # Hairpin: short (40m), slow
        df = _make_lap_df()
        # Set low speed in corner
        mask = (df["Distance (m)"] >= 100) & (df["Distance (m)"] <= 140)
        df.loc[mask, "Speed (m/s)"] = 8.0  # ~29 km/h
        # Add high curvature
        yaw = np.zeros(len(df))
        cmask = (df["Distance (m)"].values >= 100) & (df["Distance (m)"].values <= 140)
        yaw[cmask] = 25.0  # high yaw rate
        df["yaw_rate_dps"] = yaw

        result = classify_corner_type(corner, df)
        assert result == "hairpin"

    def test_fast_corner(self):
        """Low curvature, long, high min speed -> fast."""
        corner = {"corner_id": 2, "s_start": 100.0, "s_end": 250.0, "s_apex": 175.0}
        df = _make_lap_df(n=1000, lap_length=500.0)
        mask = (df["Distance (m)"] >= 100) & (df["Distance (m)"] <= 250)
        df.loc[mask, "Speed (m/s)"] = 25.0  # ~90 km/h, minimal speed loss
        yaw = np.zeros(len(df))
        cmask = (df["Distance (m)"].values >= 100) & (df["Distance (m)"].values <= 250)
        yaw[cmask] = 3.0  # low yaw rate
        df["yaw_rate_dps"] = yaw

        result = classify_corner_type(corner, df)
        assert result == "fast"

    def test_kink(self):
        """Very low curvature, very short, almost no speed loss -> kink."""
        corner = {"corner_id": 3, "s_start": 200.0, "s_end": 225.0, "s_apex": 212.0}
        df = _make_lap_df()
        # Almost no speed loss
        mask = (df["Distance (m)"] >= 200) & (df["Distance (m)"] <= 225)
        df.loc[mask, "Speed (m/s)"] = 24.0  # 96% of baseline 25
        yaw = np.zeros(len(df))
        cmask = (df["Distance (m)"].values >= 200) & (df["Distance (m)"].values <= 225)
        yaw[cmask] = 2.0
        df["yaw_rate_dps"] = yaw

        result = classify_corner_type(corner, df)
        assert result == "kink"

    def test_medium_corner(self):
        """Moderate curvature and length -> medium."""
        corner = {"corner_id": 4, "s_start": 100.0, "s_end": 180.0, "s_apex": 140.0}
        df = _make_lap_df()
        mask = (df["Distance (m)"] >= 100) & (df["Distance (m)"] <= 180)
        df.loc[mask, "Speed (m/s)"] = 15.0  # ~54 km/h
        yaw = np.zeros(len(df))
        cmask = (df["Distance (m)"].values >= 100) & (df["Distance (m)"].values <= 180)
        yaw[cmask] = 10.0
        df["yaw_rate_dps"] = yaw

        result = classify_corner_type(corner, df)
        assert result == "medium"

    def test_classify_corner_types_batch(self):
        """classify_corner_types processes multiple corners."""
        corners = [
            {"corner_id": 1, "s_start": 50.0, "s_end": 90.0, "s_apex": 70.0},
            {"corner_id": 2, "s_start": 200.0, "s_end": 350.0, "s_apex": 275.0},
        ]
        df = _make_lap_df()
        mask1 = (df["Distance (m)"] >= 50) & (df["Distance (m)"] <= 90)
        df.loc[mask1, "Speed (m/s)"] = 8.0
        yaw = np.zeros(len(df))
        cmask1 = (df["Distance (m)"].values >= 50) & (df["Distance (m)"].values <= 90)
        yaw[cmask1] = 25.0
        df["yaw_rate_dps"] = yaw

        classify_corner_types(corners, df)
        assert corners[0].get("corner_type") is not None
        assert corners[1].get("corner_type") is not None
