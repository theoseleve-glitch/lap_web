"""Tests for MRP (Maximum Rotation Point) detector."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from track_decomposition import TrackSection
from mrp_detector import CornerEvents, detect_mrp, detect_all_mrp


def _make_section(s_start=0.0, s_end=100.0, geometric_apex=None, section_id=1):
    """Helper to build a TrackSection for testing."""
    if geometric_apex is None:
        geometric_apex = (s_start + s_end) / 2.0
    return TrackSection(
        section_id=section_id,
        section_type="corner",
        corner_type="hairpin",
        s_start=s_start,
        s_end=s_end,
        direction="R",
        geometric_apex=geometric_apex,
        exit_importance=0.8,
    )


def _make_arrays(s_start, s_end, n=200, peak_yaw_frac=0.55):
    """Build synthetic corner arrays with a known peak yaw rate location.

    Returns (distances, speeds, headings, accel_long, accel_lat).
    The heading profile has its steepest change at peak_yaw_frac through
    the corner, giving a clear yaw-rate peak there.
    """
    distances = np.linspace(s_start, s_end, n)
    corner_len = s_end - s_start

    # Speed: V-shaped, minimum at 50% of corner
    min_frac = 0.5
    speed_entry = 30.0
    speed_min = 15.0
    speed_exit = 28.0
    t = np.linspace(0, 1, n)
    speeds = np.where(
        t < min_frac,
        speed_entry - (speed_entry - speed_min) * (t / min_frac),
        speed_min + (speed_exit - speed_min) * ((t - min_frac) / (1 - min_frac)),
    )

    # Heading: sigmoid-like, steepest change at peak_yaw_frac
    # Use a logistic function centered at peak_yaw_frac
    k = 20.0  # steepness
    heading_total = np.radians(90)  # 90 degree corner
    headings = heading_total / (1 + np.exp(-k * (t - peak_yaw_frac)))

    # Longitudinal acceleration: braking before mid, acceleration after
    accel_long = np.zeros(n)
    brake_end_frac = 0.35
    throttle_start_frac = 0.65
    for i, ti in enumerate(t):
        if ti < 0.1:
            accel_long[i] = 0.0  # coasting before brake
        elif ti < brake_end_frac:
            accel_long[i] = -3.0  # braking
        elif ti < 0.45:
            accel_long[i] = -0.3  # trail brake tapering
        elif ti < throttle_start_frac:
            accel_long[i] = 0.0  # neutral
        else:
            accel_long[i] = 2.0  # throttle

    # Lateral acceleration: peaks in middle of corner
    accel_lat = 5.0 * np.exp(-((t - 0.5) ** 2) / (2 * 0.15**2))

    return distances, speeds, headings, accel_long, accel_lat


class TestMRPDetector:
    """Tests for MRP detection and corner event timeline."""

    def test_mrp_at_peak_yaw_rate(self):
        """MRP should be at the point of maximum yaw rate."""
        section = _make_section(s_start=0.0, s_end=100.0)
        peak_frac = 0.55
        distances, speeds, headings, accel_long, accel_lat = _make_arrays(
            0.0, 100.0, n=200, peak_yaw_frac=peak_frac,
        )

        result = detect_mrp(section, distances, speeds, headings=headings)
        expected_mrp = 0.0 + 100.0 * peak_frac  # 55.0
        assert abs(result.mrp_m - expected_mrp) < 5.0, (
            f"MRP at {result.mrp_m}, expected near {expected_mrp}"
        )

    def test_mrp_fallback_to_min_speed(self):
        """When yaw rate unavailable, MRP falls back to minimum speed point."""
        section = _make_section(s_start=0.0, s_end=100.0)
        distances, speeds, headings, _, _ = _make_arrays(0.0, 100.0, n=200)

        # No headings → should use speed minimum
        result = detect_mrp(section, distances, speeds, headings=None)
        # Speed minimum is at 50% of corner = 50.0
        assert abs(result.mrp_m - 50.0) < 5.0, (
            f"MRP at {result.mrp_m}, expected near 50.0 (min speed)"
        )

    def test_mrp_clamped_to_corner(self):
        """MRP must fall between s_start and s_end."""
        section = _make_section(s_start=20.0, s_end=80.0, geometric_apex=50.0)
        n = 200
        # Create data spanning wider range but with peak yaw rate outside bounds
        distances = np.linspace(0.0, 100.0, n)
        speeds = np.full(n, 20.0)
        # Heading with steepest change at distance=10 (before s_start)
        t = np.linspace(0, 1, n)
        headings = np.radians(90) / (1 + np.exp(-30 * (t - 0.1)))

        result = detect_mrp(section, distances, speeds, headings=headings)
        assert result.mrp_m >= section.s_start, (
            f"MRP {result.mrp_m} < s_start {section.s_start}"
        )
        assert result.mrp_m <= section.s_end, (
            f"MRP {result.mrp_m} > s_end {section.s_end}"
        )

    def test_corner_events_ordered(self):
        """Events timeline: brake < turn_in < mrp < throttle < track_out."""
        section = _make_section(s_start=0.0, s_end=100.0)
        distances, speeds, headings, accel_long, accel_lat = _make_arrays(
            0.0, 100.0, n=200,
        )

        result = detect_mrp(
            section, distances, speeds,
            headings=headings, accel_long=accel_long, accel_lat=accel_lat,
        )

        events = []
        if result.brake_point_m is not None:
            events.append(("brake", result.brake_point_m))
        events.append(("turn_in", result.turn_in_m))
        events.append(("mrp", result.mrp_m))
        if result.throttle_application_m is not None:
            events.append(("throttle", result.throttle_application_m))
        events.append(("track_out", result.track_out_m))

        for i in range(len(events) - 1):
            assert events[i][1] <= events[i + 1][1], (
                f"{events[i][0]}({events[i][1]:.1f}) > "
                f"{events[i + 1][0]}({events[i + 1][1]:.1f})"
            )

    def test_mrp_apex_delta(self):
        """mrp_apex_delta_m = mrp_m - geometric_apex_m."""
        geometric_apex = 45.0
        section = _make_section(s_start=0.0, s_end=100.0, geometric_apex=geometric_apex)
        distances, speeds, headings, _, _ = _make_arrays(
            0.0, 100.0, n=200, peak_yaw_frac=0.55,
        )

        result = detect_mrp(section, distances, speeds, headings=headings)
        expected_delta = result.mrp_m - geometric_apex
        assert abs(result.mrp_apex_delta_m - expected_delta) < 0.01, (
            f"Delta {result.mrp_apex_delta_m}, expected {expected_delta}"
        )

    def test_brake_point_detected(self):
        """Brake initiation found where accel_long drops below -1.0."""
        section = _make_section(s_start=0.0, s_end=100.0)
        distances, speeds, headings, accel_long, accel_lat = _make_arrays(
            0.0, 100.0, n=200,
        )

        result = detect_mrp(
            section, distances, speeds,
            headings=headings, accel_long=accel_long,
        )
        assert result.brake_point_m is not None, "Brake point should be detected"
        # Braking starts at ~10% of corner in our synthetic data
        assert result.brake_point_m < 30.0, (
            f"Brake point at {result.brake_point_m}, expected < 30"
        )

    def test_throttle_application_detected(self):
        """Throttle onset found where accel_long rises above +0.5."""
        section = _make_section(s_start=0.0, s_end=100.0)
        distances, speeds, headings, accel_long, accel_lat = _make_arrays(
            0.0, 100.0, n=200,
        )

        result = detect_mrp(
            section, distances, speeds,
            headings=headings, accel_long=accel_long,
        )
        assert result.throttle_application_m is not None, (
            "Throttle application should be detected"
        )
        # Throttle starts at ~65% of corner in our synthetic data
        assert result.throttle_application_m > 50.0, (
            f"Throttle at {result.throttle_application_m}, expected > 50"
        )


class TestDetectAllMRP:
    """Tests for batch processing."""

    def test_detect_all_mrp_processes_corners_only(self):
        """detect_all_mrp should process corner sections and skip straights."""
        corner = _make_section(s_start=50.0, s_end=150.0, section_id=1)
        straight = TrackSection(
            section_id=2, section_type="straight", corner_type=None,
            s_start=150.0, s_end=250.0, direction=None,
            geometric_apex=None, exit_importance=0.3,
        )
        sections = [corner, straight]

        n = 500
        df = pd.DataFrame({
            "Distance (m)": np.linspace(0, 300, n),
            "Speed (m/s)": np.concatenate([
                np.linspace(30, 15, n // 2),
                np.linspace(15, 30, n - n // 2),
            ]),
        })

        results = detect_all_mrp(sections, df)
        assert 1 in results, "Corner section should be in results"
        assert 2 not in results, "Straight section should not be in results"
        assert isinstance(results[1], CornerEvents)
