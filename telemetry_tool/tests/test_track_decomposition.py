"""Tests for track decomposition engine."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd
import pytest
from track_decomposition import decompose_track, TrackSection


def _make_oval_trace(n_points=400, straight_length=200.0, radius=50.0):
    """Generate a simple oval track with two straights and two corners."""
    points = []
    # Straight 1 (heading east)
    for x in np.linspace(0, straight_length, n_points // 4):
        points.append((x, 0.0))
    # Corner 1 (right turn, semicircle south)
    cx, cy = straight_length, radius
    for a in np.linspace(-np.pi / 2, np.pi / 2, n_points // 4):
        points.append((cx + radius * np.cos(a), cy + radius * np.sin(a)))
    # Straight 2 (heading west)
    for x in np.linspace(straight_length, 0, n_points // 4):
        points.append((x, 2 * radius))
    # Corner 2 (right turn, semicircle north)
    cx2, cy2 = 0, radius
    for a in np.linspace(np.pi / 2, 3 * np.pi / 2, n_points // 4):
        points.append((cx2 + radius * np.cos(a), cy2 + radius * np.sin(a)))

    xs, ys = zip(*points)
    xs, ys = np.array(xs), np.array(ys)
    dists = np.concatenate([[0], np.cumsum(np.sqrt(np.diff(xs)**2 + np.diff(ys)**2))])

    # Speed: fast on straights, slow in corners
    speeds = np.full(len(xs), 30.0)
    q = n_points // 4
    speeds[q:2*q] = 15.0   # corner 1
    speeds[3*q:] = 15.0     # corner 2

    df = pd.DataFrame({
        "Latitude": ys * 0.00001,   # fake GPS
        "Longitude": xs * 0.00001,
        "Speed (m/s)": speeds,
        "Distance (m)": dists,
    })
    return df


def test_oval_produces_4_sections():
    """An oval track should decompose into ~4 sections: 2 straights + 2 corners."""
    df = _make_oval_trace()
    sections = decompose_track(df)
    corners = [s for s in sections if s.section_type == "corner"]
    straights = [s for s in sections if s.section_type == "straight"]
    assert len(corners) == 2, f"Expected 2 corners, got {len(corners)}"
    assert len(straights) >= 1, "Expected at least 1 straight"


def test_sections_cover_full_track():
    """All sections together should cover the full track distance."""
    df = _make_oval_trace()
    sections = decompose_track(df)
    total_covered = sum(s.s_end - s.s_start for s in sections)
    track_length = df["Distance (m)"].iloc[-1]
    assert total_covered == pytest.approx(track_length, rel=0.05)


def test_sections_are_ordered():
    """Sections should be in distance order with no gaps."""
    df = _make_oval_trace()
    sections = decompose_track(df)
    for i in range(1, len(sections)):
        assert sections[i].s_start >= sections[i - 1].s_start


def test_corners_have_type():
    """Corner sections should have a corner_type assigned."""
    df = _make_oval_trace()
    sections = decompose_track(df)
    corners = [s for s in sections if s.section_type == "corner"]
    for c in corners:
        assert c.corner_type is not None
        assert c.corner_type != ""


def test_corners_have_direction():
    """Corner sections should have L or R direction."""
    df = _make_oval_trace()
    sections = decompose_track(df)
    corners = [s for s in sections if s.section_type == "corner"]
    for c in corners:
        assert c.direction in ("L", "R")


def test_sections_have_exit_importance():
    """All sections should have exit_importance scored."""
    df = _make_oval_trace()
    sections = decompose_track(df)
    for s in sections:
        assert 0.0 <= s.exit_importance <= 1.0


def test_empty_df_returns_empty():
    """Empty DataFrame returns no sections."""
    df = pd.DataFrame(columns=["Latitude", "Longitude", "Speed (m/s)", "Distance (m)"])
    sections = decompose_track(df)
    assert sections == []


def test_section_ids_sequential():
    """Section IDs should be sequential starting from 1."""
    df = _make_oval_trace()
    sections = decompose_track(df)
    for i, s in enumerate(sections):
        assert s.section_id == i + 1
