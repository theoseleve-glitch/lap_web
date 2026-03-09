"""Test data factories for generating realistic telemetry objects.

Usage::

    from tests.factories import make_session, make_lap_times, make_gps_trace

    session = make_session(n_laps=10, best_time=58.5)
    laps = make_lap_times(n=10, base=60.0, spread=0.5)
    gps = make_gps_trace(n_points=200, lap_length_m=1000)
"""
from __future__ import annotations

import math
import uuid
from typing import Any


def make_session(
    *,
    session_id: str | None = None,
    driver_id: int = 1,
    track_id: str = "t1",
    n_laps: int = 10,
    best_time: float = 60.0,
    session_type: str = "practice",
    track_state: str = "dry",
    date: str = "2024-01-01",
) -> dict[str, Any]:
    """Create a session dict suitable for DB insertion or test assertions."""
    return {
        "session_id": session_id or uuid.uuid4().hex[:12],
        "csv_filename": f"session_{date}.csv",
        "driver_id": driver_id,
        "track_id": track_id,
        "session_type": session_type,
        "track_state": track_state,
        "session_date": date,
        "n_laps": n_laps,
        "best_lap_time_s": best_time,
        "mean_lap_time_s": best_time + 1.5,
        "total_score": 75.0,
        "grade": "B",
    }


def make_lap_times(
    n: int = 10,
    base: float = 60.0,
    spread: float = 0.5,
    *,
    outlier_lap: int | None = None,
    outlier_delta: float = 5.0,
) -> list[float]:
    """Generate realistic lap times with optional outlier.

    Times increase slightly (simulating tire deg), with a sine wobble
    for natural variation.
    """
    times = []
    for i in range(n):
        t = base + i * 0.1 + spread * math.sin(i * 0.7)
        if outlier_lap is not None and i == outlier_lap:
            t += outlier_delta
        times.append(round(t, 3))
    return times


def make_gps_trace(
    n_points: int = 200,
    lap_length_m: float = 1000.0,
    *,
    center_lat: float = 45.0,
    center_lon: float = 7.0,
) -> dict[str, list[float]]:
    """Generate a synthetic oval GPS trace.

    Returns dict with keys: latitudes, longitudes, distances, speeds,
    accel_lat, accel_long.
    """
    distances = [i * lap_length_m / n_points for i in range(n_points)]
    speeds = [20.0 + 5.0 * math.sin(2 * math.pi * d / lap_length_m) for d in distances]
    lats = [center_lat + 0.001 * math.cos(2 * math.pi * d / lap_length_m) for d in distances]
    lons = [center_lon + 0.002 * math.sin(2 * math.pi * d / lap_length_m) for d in distances]
    accel_lat = [1.5 * math.sin(4 * math.pi * d / lap_length_m) for d in distances]
    accel_long = [0.8 * math.cos(4 * math.pi * d / lap_length_m) for d in distances]
    return {
        "latitudes": lats,
        "longitudes": lons,
        "distances": distances,
        "speeds": speeds,
        "accel_lat": accel_lat,
        "accel_long": accel_long,
    }


def make_corners(
    n: int = 3,
    lap_length_m: float = 1000.0,
) -> list[dict[str, Any]]:
    """Generate evenly-spaced corner definitions."""
    corners = []
    spacing = lap_length_m / (n + 1)
    directions = ["left", "right"]
    for i in range(1, n + 1):
        s_center = spacing * i
        corners.append({
            "corner_id": i,
            "corner_name": f"T{i}",
            "s_start": s_center - 50,
            "s_end": s_center + 50,
            "s_apex": s_center,
            "direction": directions[i % 2],
        })
    return corners


def make_score_details(
    *,
    pace: int = 18,
    consistency: int = 15,
    execution: int = 20,
    robustness: int = 22,
    max_per: int = 25,
) -> dict[str, int]:
    """Create a score_details dict."""
    return {
        "pace_score": pace,
        "pace_max": max_per,
        "consistency_score": consistency,
        "consistency_max": max_per,
        "execution_score": execution,
        "execution_max": max_per,
        "robustness_score": robustness,
        "robustness_max": max_per,
    }


def make_corner_metrics(
    n_laps: int = 5,
    n_corners: int = 4,
) -> dict[int, list[dict[str, Any]]]:
    """Generate synthetic per-lap corner metrics."""
    metrics: dict[int, list[dict[str, Any]]] = {}
    for lap in range(1, n_laps + 1):
        lap_metrics = []
        for corner in range(1, n_corners + 1):
            lap_metrics.append({
                "corner_id": corner,
                "brake_point_m": 50.0 + corner * 10 + (lap % 3) * 0.5,
                "brake_intensity": 0.8 + corner * 0.05,
                "entry_speed_mps": 25.0 - corner * 2,
                "apex_speed_mps": 18.0 - corner * 1.5,
                "exit_speed_mps": 22.0 - corner * 1.5,
                "throttle_onset_m": 10.0 + corner * 2 + (lap % 2) * 0.3,
                "exit_accel_mps2": 5.0 + corner * 0.5,
                "grip_utilization": 0.85 + corner * 0.02,
                "time_loss_ms": 20 + corner * 10 + lap * 2,
            })
        metrics[lap] = lap_metrics
    return metrics


def make_consistency_metrics(
    *,
    cv_pct: float = 0.43,
    std_dev_s: float = 0.195,
) -> dict[str, float]:
    """Create consistency metrics dict."""
    return {
        "cv_pct": cv_pct,
        "std_dev_s": std_dev_s,
        "best_to_median_delta_s": 0.015,
    }
