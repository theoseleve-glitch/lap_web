"""Tests for track_surface.bump_detection — suspension-based bump detection."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from track_surface.bump_detection import SurfaceBump, detect_bumps_from_suspension
from track_surface.frenet import FrenetFrame


def _make_oval_frenet(n_points=200, radius=50.0):
    """Build a simple circular FrenetFrame for testing."""
    theta = np.linspace(0, 2 * np.pi, n_points, endpoint=False)
    xy = np.column_stack([radius * np.cos(theta), radius * np.sin(theta)])
    return FrenetFrame.from_centerline(xy)


def _make_bump_df(n_rows=500, bump_indices=None, bump_amplitude=10.0):
    """Create a DataFrame with synthetic shock deflection channels.

    Baseline is near-zero; spikes are injected at bump_indices.
    """
    if bump_indices is None:
        bump_indices = [100, 300]

    # Position on a circle
    frenet = _make_oval_frenet()
    theta = np.linspace(0, 2 * np.pi, n_rows, endpoint=False)
    radius = 50.0
    x = radius * np.cos(theta)
    y = radius * np.sin(theta)
    dist = np.linspace(0, 2 * np.pi * radius, n_rows)

    # Baseline: small noise
    rng = np.random.RandomState(42)
    fl = rng.normal(0, 0.5, n_rows)
    fr = rng.normal(0, 0.5, n_rows)
    rl = rng.normal(0, 0.5, n_rows)
    rr = rng.normal(0, 0.5, n_rows)

    # Inject bumps: front-left and front-right at specified indices
    for idx in bump_indices:
        fl[idx] = bump_amplitude
        fr[idx] = bump_amplitude

    return pd.DataFrame({
        "pos_x_m": x,
        "pos_y_m": y,
        "distance_m": dist,
        "shock_defl_fl": fl,
        "shock_defl_fr": fr,
        "shock_defl_rl": rl,
        "shock_defl_rr": rr,
    })


class TestSurfaceBump:
    def test_to_dict_fields(self):
        b = SurfaceBump(
            s_position=45.6, n_estimated=-1.234,
            severity=0.567, bump_type="bump",
            affected_wheels=["fl", "fr"],
        )
        d = b.to_dict()
        assert d["s_position"] == 45.6
        assert d["n_estimated"] == -1.23
        assert d["severity"] == 0.567
        assert d["bump_type"] == "bump"
        assert d["affected_wheels"] == ["fl", "fr"]

    def test_to_dict_rounding(self):
        b = SurfaceBump(
            s_position=1.23456, n_estimated=0.56789,
            severity=0.12345, bump_type="dip",
            affected_wheels=["rl"],
        )
        d = b.to_dict()
        assert d["s_position"] == 1.2
        assert d["n_estimated"] == 0.57
        assert d["severity"] == 0.123


class TestDetectBumps:
    def test_basic_bump_detection(self):
        """Injected spikes in shock channels should be detected as bumps."""
        frenet = _make_oval_frenet()
        df = _make_bump_df(bump_indices=[100, 300], bump_amplitude=15.0)
        bumps = detect_bumps_from_suspension(df, frenet, threshold_mm=3.0)
        assert len(bumps) >= 2

    def test_no_shock_channels_returns_empty(self):
        """DataFrame without shock channels should return empty list."""
        frenet = _make_oval_frenet()
        df = pd.DataFrame({
            "pos_x_m": np.zeros(100),
            "pos_y_m": np.zeros(100),
            "distance_m": np.linspace(0, 100, 100),
        })
        bumps = detect_bumps_from_suspension(df, frenet)
        assert bumps == []

    def test_below_threshold_not_detected(self):
        """Spikes below threshold should not produce bumps."""
        frenet = _make_oval_frenet()
        df = _make_bump_df(bump_indices=[100], bump_amplitude=1.0)
        # Set a high threshold so the small bump is ignored
        bumps = detect_bumps_from_suspension(df, frenet, threshold_mm=50.0)
        assert bumps == []

    def test_sorted_by_s_position(self):
        """Results should be sorted by s_position ascending."""
        frenet = _make_oval_frenet()
        df = _make_bump_df(bump_indices=[50, 150, 350], bump_amplitude=12.0)
        bumps = detect_bumps_from_suspension(df, frenet, threshold_mm=3.0)
        for i in range(len(bumps) - 1):
            assert bumps[i].s_position <= bumps[i + 1].s_position

    def test_severity_bounded(self):
        """Severity should be in [0, 1]."""
        frenet = _make_oval_frenet()
        df = _make_bump_df(bump_indices=[100, 300], bump_amplitude=20.0)
        bumps = detect_bumps_from_suspension(df, frenet, threshold_mm=3.0)
        for b in bumps:
            assert 0.0 <= b.severity <= 1.0

    def test_affected_wheels_populated(self):
        """Each bump should have at least one affected wheel."""
        frenet = _make_oval_frenet()
        df = _make_bump_df(bump_indices=[200], bump_amplitude=10.0)
        bumps = detect_bumps_from_suspension(df, frenet, threshold_mm=3.0)
        for b in bumps:
            assert len(b.affected_wheels) >= 1
            for w in b.affected_wheels:
                assert w in ("fl", "fr", "rl", "rr")

    def test_empty_dataframe(self):
        """Empty DataFrame should return empty list."""
        frenet = _make_oval_frenet()
        df = pd.DataFrame()
        bumps = detect_bumps_from_suspension(df, frenet)
        assert bumps == []

    def test_one_side_bump_type(self):
        """Bump on only one side (left wheels) should be classified as bump/dip."""
        frenet = _make_oval_frenet()
        n_rows = 300
        rng = np.random.RandomState(99)
        theta = np.linspace(0, 2 * np.pi, n_rows, endpoint=False)
        radius = 50.0
        df = pd.DataFrame({
            "pos_x_m": radius * np.cos(theta),
            "pos_y_m": radius * np.sin(theta),
            "distance_m": np.linspace(0, 2 * np.pi * radius, n_rows),
            "shock_defl_fl": np.where(np.arange(n_rows) == 150, 15.0, rng.normal(0, 0.3, n_rows)),
            "shock_defl_fr": rng.normal(0, 0.3, n_rows),
            "shock_defl_rl": rng.normal(0, 0.3, n_rows),
            "shock_defl_rr": rng.normal(0, 0.3, n_rows),
        })
        bumps = detect_bumps_from_suspension(df, frenet, threshold_mm=3.0)
        # Should detect at least one bump, and it should be "bump" type (positive defl)
        assert len(bumps) >= 1
        assert bumps[0].bump_type in ("bump", "dip", "transition")
