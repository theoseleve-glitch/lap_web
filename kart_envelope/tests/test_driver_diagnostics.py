"""Tests for driver behavior diagnostics."""
from __future__ import annotations

import numpy as np
import pandas as pd

from kart_envelope.coaching.corner_coaching import detect_corners_from_curvature
from kart_envelope.coaching.driver_diagnostics import analyze_driver_dynamics
from kart_envelope.inference.session_scalars import SessionScalars
from kart_envelope.ingest.metadata import SessionMetadata


def _make_lap_df(
    distance: np.ndarray,
    curvature: np.ndarray,
    *,
    straight_speed: float,
    corner_speed: float,
    yaw_oscillation_dps: float = 0.0,
) -> pd.DataFrame:
    k_abs = np.abs(curvature)
    in_corner = k_abs > 1e-3
    speed = np.where(in_corner, corner_speed, straight_speed).astype(float)
    speed = np.maximum(speed, 2.0)
    # smooth transitions
    for _ in range(5):
        speed = 0.25 * np.roll(speed, 1) + 0.5 * speed + 0.25 * np.roll(speed, -1)

    ds = np.diff(distance, prepend=distance[0])
    dt = np.where(speed > 0.5, ds / speed, 0.05)
    time = np.cumsum(np.maximum(dt, 0.01))
    accel_long = np.gradient(speed, time, edge_order=1)
    accel_lat = (speed ** 2) * k_abs

    yaw = speed * curvature * (180.0 / np.pi)
    if yaw_oscillation_dps > 0.0:
        osc = np.sin(np.linspace(0.0, 20.0, len(yaw)))
        yaw = yaw + yaw_oscillation_dps * osc * (k_abs > 0.003)

    altitude = 2.0 * np.sin(np.linspace(0.0, 8.0 * np.pi, len(speed)))

    return pd.DataFrame({
        "time_s": time,
        "distance_m": distance,
        "speed_mps": speed,
        "accel_long_mps2": accel_long,
        "accel_lat_mps2": accel_lat,
        "yaw_rate_dps": yaw,
        "altitude_m": altitude,
    })


def test_driver_diagnostics_detects_underdriving(default_config, known_envelope, small_oval_geometry):
    corners = detect_corners_from_curvature(
        small_oval_geometry.curvature_1pm,
        small_oval_geometry.distance_m,
    )
    best = _make_lap_df(
        small_oval_geometry.distance_m,
        small_oval_geometry.curvature_1pm,
        straight_speed=9.0,
        corner_speed=6.0,
    )
    laps = {
        1: best.copy(),
        2: _make_lap_df(small_oval_geometry.distance_m, small_oval_geometry.curvature_1pm, straight_speed=9.5, corner_speed=6.2),
        3: _make_lap_df(small_oval_geometry.distance_m, small_oval_geometry.curvature_1pm, straight_speed=8.8, corner_speed=5.9),
    }

    report = analyze_driver_dynamics(
        resampled_laps=laps,
        best_lap_df=best,
        geometry=small_oval_geometry,
        envelope=known_envelope,
        scalars=SessionScalars(),
        metadata=SessionMetadata(session_file="synthetic.csv"),
        corners=corners,
        config=default_config,
    )
    codes = {f.code for f in report.findings}
    assert "underdriving" in codes


def test_driver_diagnostics_uses_yaw_for_countersteer_signal(
    default_config,
    known_envelope,
    small_oval_geometry,
):
    corners = detect_corners_from_curvature(
        small_oval_geometry.curvature_1pm,
        small_oval_geometry.distance_m,
    )
    best = _make_lap_df(
        small_oval_geometry.distance_m,
        small_oval_geometry.curvature_1pm,
        straight_speed=14.0,
        corner_speed=10.0,
        yaw_oscillation_dps=0.0,
    )
    laps = {
        1: _make_lap_df(small_oval_geometry.distance_m, small_oval_geometry.curvature_1pm, straight_speed=14.0, corner_speed=10.0, yaw_oscillation_dps=20.0),
        2: _make_lap_df(small_oval_geometry.distance_m, small_oval_geometry.curvature_1pm, straight_speed=14.2, corner_speed=10.1, yaw_oscillation_dps=22.0),
        3: _make_lap_df(small_oval_geometry.distance_m, small_oval_geometry.curvature_1pm, straight_speed=13.9, corner_speed=9.9, yaw_oscillation_dps=18.0),
    }

    report = analyze_driver_dynamics(
        resampled_laps=laps,
        best_lap_df=best,
        geometry=small_oval_geometry,
        envelope=known_envelope,
        scalars=SessionScalars(),
        metadata=SessionMetadata(session_file="synthetic.csv"),
        corners=corners,
        config=default_config,
    )
    codes = {f.code for f in report.findings}
    assert report.yaw_summary.get("yaw_available") is True
    assert "yaw_countersteer_instability" in codes
