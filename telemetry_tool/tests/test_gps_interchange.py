"""Tests for the shared GPS-interchange helpers."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from telemetry_tool.adapters._gps_interchange import (
    finalize_gps_frame,
    haversine_m,
    initial_bearing_deg,
)


def test_haversine_known_distance():
    # 0.001 deg latitude ~= 111.19 m
    d = float(haversine_m(np.array([0.0]), np.array([0.0]),
                          np.array([0.001]), np.array([0.0]))[0])
    assert d == pytest.approx(111.19, abs=1.0)


def test_initial_bearing_due_north():
    b = float(initial_bearing_deg(np.array([0.0]), np.array([0.0]),
                                  np.array([0.001]), np.array([0.0]))[0])
    assert b == pytest.approx(0.0, abs=1.0)


def test_finalize_derives_speed_distance_heading():
    # Two points 1 s apart, ~111 m north -> ~111 m/s, distance 111 m, heading ~0.
    df = pd.DataFrame({
        "time_s": [0.0, 1.0],
        "lat_deg": [0.0, 0.001],
        "lon_deg": [0.0, 0.0],
    })
    out = finalize_gps_frame(df, source="test")
    assert {"speed_mps", "distance_m", "heading_deg"} <= set(out.columns)
    assert out["distance_m"].iloc[-1] == pytest.approx(111.19, abs=1.0)
    assert out["speed_mps"].iloc[-1] == pytest.approx(111.19, abs=1.0)
    assert out["heading_deg"].iloc[-1] == pytest.approx(0.0, abs=1.0)


def test_finalize_preserves_supplied_speed():
    df = pd.DataFrame({
        "time_s": [0.0, 1.0],
        "lat_deg": [0.0, 0.001],
        "lon_deg": [0.0, 0.0],
        "speed_mps": [10.0, 12.0],
    })
    out = finalize_gps_frame(df, source="test")
    assert out["speed_mps"].tolist() == [10.0, 12.0]


def test_finalize_requires_position():
    df = pd.DataFrame({"time_s": [0.0, 1.0]})
    with pytest.raises(ValueError):
        finalize_gps_frame(df, source="test")
