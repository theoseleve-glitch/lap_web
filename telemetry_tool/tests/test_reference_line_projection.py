"""Tests for the equirectangular GPS projection's polar-latitude guard."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from reference_line import _latlon_to_local_xy, _local_xy_to_latlon


class TestPolarLatitudeGuard:
    def test_normal_track_latitude_does_not_raise(self):
        """A real track (e.g. ~45N) must be unaffected."""
        lat = np.array([45.0, 45.001, 45.002, 45.001])
        lon = np.array([7.0, 7.001, 7.002, 7.001])
        x, y = _latlon_to_local_xy(lat, lon)
        assert x.shape == lat.shape

    def test_raises_above_85_degrees_north(self):
        lat = np.array([89.0, 89.001, 89.002])
        lon = np.array([7.0, 7.001, 7.002])
        with pytest.raises(ValueError, match=r"outside the supported range"):
            _latlon_to_local_xy(lat, lon)

    def test_raises_below_minus_85_degrees_south(self):
        lat = np.array([-89.0, -89.001, -89.002])
        lon = np.array([7.0, 7.001, 7.002])
        with pytest.raises(ValueError, match=r"outside the supported range"):
            _latlon_to_local_xy(lat, lon)

    def test_boundary_at_exactly_85_degrees_does_not_raise(self):
        lat = np.array([85.0, 85.0, 85.0])
        lon = np.array([7.0, 7.001, 7.002])
        x, y = _latlon_to_local_xy(lat, lon)
        assert x.shape == lat.shape

    def test_inverse_transform_also_raises_near_pole(self):
        with pytest.raises(ValueError, match=r"outside the supported range"):
            _local_xy_to_latlon(
                np.array([10.0, 20.0]), np.array([5.0, 6.0]),
                lat_ref_rad=np.radians(89.5), lon_ref_rad=np.radians(7.0),
            )
