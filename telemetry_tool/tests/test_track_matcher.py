"""Tests for track_surface.track_matcher — cross-sim track matching."""
from __future__ import annotations

import numpy as np
import pytest

from track_surface.track_matcher import (
    TrackMatch,
    compute_track_fingerprint,
    find_matching_tracks,
    match_tracks,
)
from track_surface.frenet import FrenetFrame


def _make_circle_frenet(radius=100.0, n_points=400):
    """Build a circular track FrenetFrame."""
    theta = np.linspace(0, 2 * np.pi, n_points, endpoint=False)
    xy = np.column_stack([radius * np.cos(theta), radius * np.sin(theta)])
    return FrenetFrame.from_centerline(xy)


def _make_oval_frenet(a=100.0, b=50.0, n_points=400):
    """Build an oval track FrenetFrame (ellipse)."""
    theta = np.linspace(0, 2 * np.pi, n_points, endpoint=False)
    xy = np.column_stack([a * np.cos(theta), b * np.sin(theta)])
    return FrenetFrame.from_centerline(xy)


def _make_offset_circle_frenet(radius=100.0, n_points=400, offset_x=500.0, offset_y=300.0):
    """Same shape as circle but translated — should produce same fingerprint."""
    theta = np.linspace(0, 2 * np.pi, n_points, endpoint=False)
    xy = np.column_stack([
        radius * np.cos(theta) + offset_x,
        radius * np.sin(theta) + offset_y,
    ])
    return FrenetFrame.from_centerline(xy)


def _make_rotated_circle_frenet(radius=100.0, n_points=400, start_offset=100):
    """Same circle but with different start/finish position."""
    theta = np.linspace(0, 2 * np.pi, n_points, endpoint=False)
    # Rotate the start index
    theta = np.roll(theta, start_offset)
    xy = np.column_stack([radius * np.cos(theta), radius * np.sin(theta)])
    return FrenetFrame.from_centerline(xy)


class TestTrackMatch:
    def test_to_dict_fields(self):
        m = TrackMatch(
            track_id_a="monza_ac", track_id_b="monza_iracing",
            sim_a="AC", sim_b="iRacing",
            similarity=0.9567, length_diff_pct=1.234,
            shape_correlation=0.9432,
        )
        d = m.to_dict()
        assert d["track_id_a"] == "monza_ac"
        assert d["similarity"] == 0.9567
        assert d["length_diff_pct"] == 1.23
        assert d["shape_correlation"] == 0.9432


class TestComputeFingerprint:
    def test_fingerprint_length(self):
        """Fingerprint should always be length 200."""
        frenet = _make_circle_frenet()
        fp = compute_track_fingerprint(frenet)
        assert fp.shape == (200,)

    def test_translation_invariance(self):
        """Translated track should produce the same fingerprint."""
        fp_origin = compute_track_fingerprint(_make_circle_frenet())
        fp_offset = compute_track_fingerprint(_make_offset_circle_frenet())
        corr = np.corrcoef(fp_origin, fp_offset)[0, 1]
        assert corr > 0.99, f"Correlation {corr} too low for translated track"

    def test_different_shapes_differ(self):
        """Circle vs oval should produce different fingerprints."""
        fp_circle = compute_track_fingerprint(_make_circle_frenet())
        fp_oval = compute_track_fingerprint(_make_oval_frenet())
        corr = np.corrcoef(fp_circle, fp_oval)[0, 1]
        assert corr < 0.95, f"Correlation {corr} too high for different shapes"

    def test_tiny_track_returns_zeros(self):
        """Track with < 3 points should return zeros."""
        xy = np.array([[0, 0], [1, 0]])
        # Can't build a FrenetFrame with < 3 points, so test the guard
        # by making a minimal frenet manually
        frenet = FrenetFrame(
            centerline_xy=xy,
            s_grid=np.array([0.0, 1.0]),
            heading_rad=np.array([0.0, 0.0]),
            curvature_1pm=np.array([0.0, 0.0]),
            total_length_m=1.0,
        )
        fp = compute_track_fingerprint(frenet)
        assert fp.shape == (200,)
        assert np.all(fp == 0)


class TestMatchTracks:
    def test_identical_tracks(self):
        """Same fingerprint should give similarity ~1.0."""
        fp = compute_track_fingerprint(_make_circle_frenet(radius=100))
        sim = match_tracks(fp, fp, 628.0, 628.0)
        assert sim > 0.99

    def test_different_shapes_low_similarity(self):
        """Very different shapes with same length should give low similarity."""
        fp_circle = compute_track_fingerprint(_make_circle_frenet(radius=100))
        # Make a very different shape: figure-8 style
        t = np.linspace(0, 2 * np.pi, 400, endpoint=False)
        xy = np.column_stack([100 * np.sin(t), 50 * np.sin(2 * t)])
        frenet_fig8 = FrenetFrame.from_centerline(xy)
        fp_fig8 = compute_track_fingerprint(frenet_fig8)
        sim = match_tracks(fp_circle, fp_fig8, 628.0, 628.0, max_length_diff_pct=100)
        assert sim < 0.9

    def test_length_mismatch_returns_zero(self):
        """Tracks with length diff > threshold should return 0."""
        fp = compute_track_fingerprint(_make_circle_frenet())
        sim = match_tracks(fp, fp, 1000.0, 500.0, max_length_diff_pct=5.0)
        assert sim == 0.0

    def test_zero_length_returns_zero(self):
        """Zero-length track should return 0."""
        fp = np.zeros(200)
        sim = match_tracks(fp, fp, 0.0, 100.0)
        assert sim == 0.0

    def test_both_straight_tracks(self):
        """Two straight tracks (zero curvature) should match perfectly."""
        fp_a = np.zeros(200)
        fp_b = np.zeros(200)
        sim = match_tracks(fp_a, fp_b, 500.0, 500.0)
        assert sim == 1.0


class TestFindMatchingTracks:
    def test_finds_matching_track(self):
        """Should find a matching track in the known set."""
        target = _make_circle_frenet(radius=100)
        # Same shape, slightly translated
        known_circle = _make_offset_circle_frenet(radius=100)
        # Different shape
        known_oval = _make_oval_frenet(a=100, b=50)

        known = {
            "circle_iracing": (known_circle, "iRacing"),
            "oval_ac": (known_oval, "AC"),
        }
        matches = find_matching_tracks(target, known, min_similarity=0.85)
        # The circle should match; the oval may or may not
        circle_matches = [m for m in matches if m.track_id_b == "circle_iracing"]
        assert len(circle_matches) == 1
        assert circle_matches[0].similarity > 0.85

    def test_empty_known_set(self):
        """Empty known set should return empty list."""
        target = _make_circle_frenet()
        matches = find_matching_tracks(target, {})
        assert matches == []

    def test_sorted_by_similarity(self):
        """Matches should be sorted by similarity descending."""
        target = _make_circle_frenet(radius=100)
        known = {
            f"track_{i}": (_make_circle_frenet(radius=100 + i * 0.1), f"sim_{i}")
            for i in range(5)
        }
        matches = find_matching_tracks(target, known, min_similarity=0.5)
        for i in range(len(matches) - 1):
            assert matches[i].similarity >= matches[i + 1].similarity
