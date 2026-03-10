"""Tests for geometry + speed corner classification."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pytest
from corner_classifier import classify_corner, CornerClassification


def _make_curvature(length_m, peak_curvature, n_points=100):
    """Generate a single-peak curvature profile."""
    s = np.linspace(0, length_m, n_points)
    curv = peak_curvature * np.exp(-0.5 * ((s - length_m / 2) / (length_m / 6)) ** 2)
    return s, curv


def test_kink():
    """Short, low curvature, minimal speed drop -> kink."""
    s, curv = _make_curvature(30.0, 0.005)
    speeds = np.full_like(s, 30.0)
    speeds[len(s)//2] = 28.0  # 6% drop
    result = classify_corner(s, curv, speeds, direction_changes=0, directions=["L"])
    assert result.corner_type == "kink"


def test_hairpin():
    """Tight radius, large direction change -> hairpin."""
    s, curv = _make_curvature(60.0, 0.06)
    speeds = np.linspace(25, 8, len(s))
    result = classify_corner(s, curv, speeds, direction_changes=0,
                             directions=["R"], total_heading_change=140.0)
    assert result.corner_type == "hairpin"


def test_fast_sweeper():
    """Long, moderate curvature, high min speed -> fast sweeper."""
    s, curv = _make_curvature(120.0, 0.008)
    straight_speed = 40.0
    speeds = np.full_like(s, straight_speed * 0.8)
    result = classify_corner(s, curv, speeds, direction_changes=0,
                             directions=["L"], straight_speed_mps=straight_speed)
    assert result.corner_type == "fast_sweeper"


def test_simple_corner():
    """Standard single-peak corner."""
    s, curv = _make_curvature(80.0, 0.025)
    speeds = np.linspace(30, 18, len(s))
    result = classify_corner(s, curv, speeds, direction_changes=0,
                             directions=["R"], total_heading_change=80.0)
    assert result.corner_type == "simple"


def test_chicane():
    """Multiple peaks, alternating directions -> chicane."""
    s = np.linspace(0, 100, 200)
    curv = 0.02 * (np.exp(-((s - 30) / 8) ** 2) + np.exp(-((s - 70) / 8) ** 2))
    speeds = np.full_like(s, 20.0)
    result = classify_corner(s, curv, speeds, direction_changes=1,
                             directions=["L", "R"], n_peaks=2)
    assert result.corner_type == "chicane"


def test_double_apex():
    """Two peaks, same direction -> double apex."""
    s = np.linspace(0, 100, 200)
    curv = 0.02 * (np.exp(-((s - 30) / 8) ** 2) + np.exp(-((s - 70) / 8) ** 2))
    speeds = np.full_like(s, 20.0)
    result = classify_corner(s, curv, speeds, direction_changes=0,
                             directions=["L", "L"], n_peaks=2)
    assert result.corner_type == "double_apex"


def test_compound():
    """Multiple peaks, mixed directions but not simple chicane -> compound."""
    s = np.linspace(0, 150, 300)
    curv = 0.015 * (np.exp(-((s - 30) / 8) ** 2) +
                    np.exp(-((s - 70) / 8) ** 2) +
                    np.exp(-((s - 110) / 8) ** 2))
    speeds = np.full_like(s, 18.0)
    result = classify_corner(s, curv, speeds, direction_changes=2,
                             directions=["L", "R", "L"], n_peaks=3)
    assert result.corner_type == "compound"


def test_decreasing_radius():
    """Curvature increases through corner -> decreasing radius."""
    s = np.linspace(0, 80, 100)
    curv = 0.01 + 0.02 * (s / 80)
    speeds = np.linspace(25, 15, 100)
    result = classify_corner(s, curv, speeds, direction_changes=0,
                             directions=["R"], total_heading_change=70.0)
    assert result.corner_type == "decreasing_radius"


def test_classification_has_all_fields():
    """Output has all required fields."""
    s, curv = _make_curvature(80.0, 0.025)
    speeds = np.linspace(30, 18, len(s))
    result = classify_corner(s, curv, speeds, direction_changes=0,
                             directions=["R"], total_heading_change=80.0)
    assert hasattr(result, "corner_type")
    assert hasattr(result, "min_radius_m")
    assert hasattr(result, "arc_length_m")
    assert hasattr(result, "speed_ratio")
    assert hasattr(result, "confidence")
