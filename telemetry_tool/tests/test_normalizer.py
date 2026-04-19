"""Tests for track_surface/normalizer.py — coordinate normalization."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from track_surface.normalizer import (
    detect_coordinate_system,
    normalize_positions,
)


class TestDetectCoordinateSystem:
    def test_gps_formats(self):
        for fmt in ("iracing", "iracing_ibt", "racechrono", "racebox", "vbox", "qstarz"):
            assert detect_coordinate_system(fmt) == "gps"

    def test_cartesian_y_up_formats(self):
        for fmt in ("ac", "acc", "lmu", "motec"):
            assert detect_coordinate_system(fmt) == "cartesian_y_up"

    def test_cartesian_z_up_formats(self):
        assert detect_coordinate_system("f1_game") == "cartesian_z_up"

    def test_unknown_defaults_to_gps(self):
        assert detect_coordinate_system("some_unknown_format") == "gps"


class TestGPSNormalization:
    def _monza_df(self) -> pd.DataFrame:
        """Synthetic GPS data near Monza (45.62N, 9.28E)."""
        n = 100
        lat = np.linspace(45.620, 45.622, n)
        lon = np.linspace(9.280, 9.282, n)
        alt = np.linspace(160.0, 165.0, n)
        return pd.DataFrame({"lat_deg": lat, "lon_deg": lon, "altitude_m": alt})

    def test_output_shapes(self):
        df = self._monza_df()
        x, y, z, meta = normalize_positions(df, "gps")
        assert len(x) == 100
        assert len(y) == 100
        assert len(z) == 100

    def test_center_near_zero(self):
        df = self._monza_df()
        x, y, z, meta = normalize_positions(df, "gps")
        # Mean should be near zero since projection is centered on mean
        assert abs(np.mean(x)) < 1.0
        assert abs(np.mean(y)) < 1.0

    def test_altitude_preserved(self):
        df = self._monza_df()
        x, y, z, meta = normalize_positions(df, "gps")
        np.testing.assert_allclose(z, df["altitude_m"].to_numpy(), atol=0.01)

    def test_metadata_has_refs(self):
        df = self._monza_df()
        _, _, _, meta = normalize_positions(df, "gps")
        assert "lat_ref_rad" in meta
        assert "lon_ref_rad" in meta

    def test_scale_reasonable(self):
        """0.002 degrees lat ≈ 222m at Monza latitude."""
        df = self._monza_df()
        x, y, z, meta = normalize_positions(df, "gps")
        y_range = np.max(y) - np.min(y)
        assert 200 < y_range < 250

    def test_missing_columns_returns_zeros(self):
        df = pd.DataFrame({"some_col": [1, 2, 3]})
        x, y, z, meta = normalize_positions(df, "gps")
        np.testing.assert_array_equal(x, np.zeros(3))


class TestCartesianYUp:
    def test_remap_axes(self):
        """Sim X/Z horizontal, Y vertical -> our x/y horizontal, z vertical."""
        df = pd.DataFrame({
            "pos_x_m": [10.0, 20.0],
            "pos_y_m": [30.0, 40.0],  # sim Z (horizontal) -> our y
            "pos_z_m": [5.0, 6.0],    # sim Y (vertical) -> our z
        })
        x, y, z, meta = normalize_positions(df, "cartesian_y_up")
        np.testing.assert_allclose(x, [10.0, 20.0])
        np.testing.assert_allclose(y, [30.0, 40.0])
        np.testing.assert_allclose(z, [5.0, 6.0])

    def test_missing_columns_gives_zeros(self):
        df = pd.DataFrame({"unrelated": [1, 2]})
        x, y, z, _ = normalize_positions(df, "cartesian_y_up")
        assert len(x) == 2
        np.testing.assert_array_equal(x, np.zeros(2))


class TestCartesianZUp:
    def test_passthrough(self):
        df = pd.DataFrame({
            "pos_x_m": [1.0, 2.0],
            "pos_y_m": [3.0, 4.0],
            "pos_z_m": [5.0, 6.0],
        })
        x, y, z, _ = normalize_positions(df, "cartesian_z_up")
        np.testing.assert_allclose(x, [1.0, 2.0])
        np.testing.assert_allclose(y, [3.0, 4.0])
        np.testing.assert_allclose(z, [5.0, 6.0])


class TestUnknownSystem:
    def test_returns_zeros(self):
        df = pd.DataFrame({"a": [1, 2, 3]})
        x, y, z, meta = normalize_positions(df, "unsupported")
        np.testing.assert_array_equal(x, np.zeros(3))
