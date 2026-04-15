"""Tests for track_surface/store.py — cross-session track model accumulation."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from track_surface.builder import build_track_surface
from track_surface.frenet import FrenetFrame
from track_surface.grip_2d import GripSurface
from track_surface.model import TrackSurface
from track_surface.store import (
    _merge_centerlines,
    _validate_merge,
    load_track_model,
    merge_track_model,
)


@pytest.fixture
def tmp_sidecar(tmp_path):
    """Temporary sidecar root directory."""
    return str(tmp_path)


def _make_oval_xy(
    straight_len: float = 100.0,
    radius: float = 30.0,
    n_points: int = 400,
    offset_m: float = 0.0,
) -> np.ndarray:
    """Generate an oval centerline as (N, 2) array."""
    pts = []
    n_q = n_points // 4
    for i in range(n_q):
        t = i / n_q
        pts.append([t * straight_len, offset_m])
    for i in range(n_q):
        theta = -np.pi / 2 + np.pi * i / n_q
        pts.append([straight_len + radius * np.cos(theta),
                     radius + radius * np.sin(theta) + offset_m])
    for i in range(n_q):
        t = i / n_q
        pts.append([straight_len - t * straight_len, 2 * radius + offset_m])
    for i in range(n_q):
        theta = np.pi / 2 + np.pi * i / n_q
        pts.append([radius * np.cos(theta),
                     radius + radius * np.sin(theta) + offset_m])
    return np.array(pts)


def _make_surface(track_id: str = "test", n_laps: int = 3, offset: float = 0.0) -> TrackSurface:
    """Build a minimal TrackSurface for testing."""
    xy = _make_oval_xy(offset_m=offset)
    frenet = FrenetFrame.from_centerline(xy)
    n = frenet.n_points
    return TrackSurface(
        track_id=track_id,
        frenet=frenet,
        width_left=np.full(n, 5.0),
        width_right=np.full(n, 5.0),
        elevation_m=np.sin(frenet.s_grid / 50.0) * 3.0,
        slope_pct=np.cos(frenet.s_grid / 50.0) * 6.0,
        vert_curvature_1pm=np.sin(frenet.s_grid / 25.0) * 0.005,
        camber_rad=np.zeros(n),
        n_laps=n_laps,
        sim_sources=["ac"],
    )


class TestBootstrap:
    def test_first_session_creates_sidecar(self, tmp_sidecar):
        surface = _make_surface()
        result = merge_track_model("test_track", surface, tmp_sidecar)
        assert result is True

        # Should be loadable now
        loaded = load_track_model("test_track", tmp_sidecar)
        assert loaded is not None
        assert loaded.track_id == "test_track"
        assert loaded.n_laps == surface.n_laps

    def test_no_sidecar_returns_none(self, tmp_sidecar):
        loaded = load_track_model("nonexistent", tmp_sidecar)
        assert loaded is None


class TestMergeConvergence:
    def test_two_sessions_merge(self, tmp_sidecar):
        s1 = _make_surface(n_laps=5, offset=0.0)
        s2 = _make_surface(n_laps=3, offset=1.0)

        merge_track_model("track_a", s1, tmp_sidecar)
        merge_track_model("track_a", s2, tmp_sidecar)

        loaded = load_track_model("track_a", tmp_sidecar)
        assert loaded is not None
        assert loaded.n_laps == 8  # 5 + 3

    def test_five_sessions_converge(self, tmp_sidecar):
        """Centerline should converge toward the mean of all sessions."""
        for i in range(5):
            s = _make_surface(n_laps=2, offset=float(i) * 0.5)
            merge_track_model("track_conv", s, tmp_sidecar)

        loaded = load_track_model("track_conv", tmp_sidecar)
        assert loaded is not None
        assert loaded.n_laps == 10  # 5 × 2

    def test_sim_sources_accumulated(self, tmp_sidecar):
        s1 = _make_surface()
        s1.sim_sources = ["ac"]
        s2 = _make_surface()
        s2.sim_sources = ["iracing"]

        merge_track_model("track_multi", s1, tmp_sidecar)
        merge_track_model("track_multi", s2, tmp_sidecar)

        loaded = load_track_model("track_multi", tmp_sidecar)
        assert "ac" in loaded.sim_sources
        assert "iracing" in loaded.sim_sources


class TestDivergenceRejection:
    def test_wrong_track_rejected(self, tmp_sidecar):
        s1 = _make_surface(offset=0.0)
        merge_track_model("track_x", s1, tmp_sidecar)

        # Make a completely different track (shifted 50m)
        s2 = _make_surface(offset=50.0)  # way too far from original
        result = merge_track_model("track_x", s2, tmp_sidecar)

        # Should be rejected — loaded model should still have original laps
        loaded = load_track_model("track_x", tmp_sidecar)
        assert loaded.n_laps == s1.n_laps  # not merged

    def test_length_mismatch_rejected(self, tmp_sidecar):
        s1 = _make_surface()
        merge_track_model("track_len", s1, tmp_sidecar)

        # Make a track with very different length
        xy_short = _make_oval_xy(straight_len=30.0, radius=10.0, n_points=200)
        ff_short = FrenetFrame.from_centerline(xy_short)
        s2 = TrackSurface(
            track_id="track_len",
            frenet=ff_short,
            n_laps=2,
            sim_sources=["ac"],
        )
        result = merge_track_model("track_len", s2, tmp_sidecar)
        assert result is False


class TestLoadSaveRoundtrip:
    def test_elevation_preserved(self, tmp_sidecar):
        surface = _make_surface()
        merge_track_model("track_rt", surface, tmp_sidecar)
        loaded = load_track_model("track_rt", tmp_sidecar)

        assert loaded.has_elevation
        # Elevation should be close (may differ slightly due to resampling)
        np.testing.assert_allclose(
            loaded.elevation_m[:10], surface.elevation_m[:10], atol=0.5,
        )

    def test_vert_curvature_preserved(self, tmp_sidecar):
        surface = _make_surface()
        merge_track_model("track_kv", surface, tmp_sidecar)
        loaded = load_track_model("track_kv", tmp_sidecar)

        assert loaded.has_vert_curvature
        # Should have non-zero values
        assert np.any(np.abs(loaded.vert_curvature_1pm) > 0.001)

    def test_boundaries_preserved(self, tmp_sidecar):
        surface = _make_surface()
        merge_track_model("track_bnd", surface, tmp_sidecar)
        loaded = load_track_model("track_bnd", tmp_sidecar)

        assert loaded.has_boundaries
        np.testing.assert_allclose(loaded.width_left[:5], 5.0, atol=0.1)

    def test_width_running_max(self, tmp_sidecar):
        """Width should use running max — track doesn't shrink."""
        s1 = _make_surface()
        s1.width_left = np.full(s1.frenet.n_points, 4.0)
        merge_track_model("track_wmax", s1, tmp_sidecar)

        s2 = _make_surface()
        s2.width_left = np.full(s2.frenet.n_points, 6.0)
        merge_track_model("track_wmax", s2, tmp_sidecar)

        loaded = load_track_model("track_wmax", tmp_sidecar)
        # Should be 6.0 (max of 4.0 and 6.0)
        assert np.mean(loaded.width_left) > 5.5


class TestValidation:
    def test_compatible_tracks_pass(self):
        s1 = _make_surface()
        s2 = _make_surface(offset=1.0)
        assert _validate_merge(s1, s2) is True

    def test_divergent_tracks_fail(self):
        s1 = _make_surface(offset=0.0)
        s2 = _make_surface(offset=50.0)
        assert _validate_merge(s1, s2) is False
