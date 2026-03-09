"""Tests for the theoretical_adapter module.

Validates the adapter layer that bridges the kart_envelope solver
to the telemetry_tool pipeline contract.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Ensure project root is on path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from telemetry_tool.theoretical_adapter import (
    AdapterResult,
    _map_columns_to_canonical,
    compute_theoretical_via_envelope,
)

# ---------------------------------------------------------------------------
# Synthetic data helpers
# ---------------------------------------------------------------------------

_G = 9.80665


def _make_oval_lap(
    lap_num: int,
    n_points: int = 200,
    lap_length_m: float = 500.0,
    v_mean: float = 10.0,
    v_amp: float = 2.0,
) -> pd.DataFrame:
    """Generate a single synthetic lap on a 500 m oval.

    Speed oscillates sinusoidally (braking into turns, accelerating out).
    Accel is the analytical gradient of speed w.r.t. distance.
    """
    dist = np.linspace(0, lap_length_m, n_points, endpoint=False)
    # Two turns per oval -> 2 periods of sinusoid
    speed = v_mean + v_amp * np.sin(2 * np.pi * 2 * dist / lap_length_m)
    speed = np.maximum(speed, 1.0)  # floor at 1 m/s

    # Time from trapezoidal integration of 1/v
    dt = np.diff(dist) / (0.5 * (speed[:-1] + speed[1:]))
    time = np.concatenate([[0.0], np.cumsum(dt)])

    # Longitudinal accel = dv/dt ~ (dv/ds) * v
    dv_ds = np.gradient(speed, dist)
    accel_long = dv_ds * speed

    # Lateral accel ~ v^2 * curvature (sinusoidal curvature)
    kappa = 0.02 * np.abs(np.sin(2 * np.pi * 2 * dist / lap_length_m))
    accel_lat = speed**2 * kappa

    return pd.DataFrame({
        "distance_m": dist,
        "speed_mps": speed,
        "time_s": time,
        "lap_number": lap_num,
        "accel_long_mps2": accel_long,
        "accel_lat_mps2": accel_lat,
    })


def _make_resampled_laps(
    n_laps: int = 5,
    n_points: int = 200,
    lap_length_m: float = 500.0,
) -> dict[int, pd.DataFrame]:
    """Build a dict of resampled laps for the adapter."""
    laps = {}
    for i in range(1, n_laps + 1):
        # Slight speed variation per lap
        laps[i] = _make_oval_lap(
            lap_num=i,
            n_points=n_points,
            lap_length_m=lap_length_m,
            v_mean=10.0 + 0.2 * (i - 1),
            v_amp=2.0,
        )
    return laps


def _make_curvature_profile(
    n_points: int = 200,
    lap_length_m: float = 500.0,
) -> pd.DataFrame:
    """Build a sinusoidal curvature profile with integrated XY.

    Two corners per oval (two sinusoidal bumps).
    """
    dist = np.linspace(0, lap_length_m, n_points, endpoint=False)
    # Curvature: two bumps per lap (oval with two turns)
    kappa = 0.02 * np.abs(np.sin(2 * np.pi * 2 * dist / lap_length_m))

    # Integrate heading: heading = integral of curvature w.r.t. distance
    ds = np.diff(dist)
    heading = np.zeros(n_points)
    for i in range(1, n_points):
        heading[i] = heading[i - 1] + kappa[i - 1] * ds[i - 1]

    # Integrate XY from heading
    x = np.zeros(n_points)
    y = np.zeros(n_points)
    for i in range(1, n_points):
        x[i] = x[i - 1] + ds[i - 1] * np.cos(heading[i - 1])
        y[i] = y[i - 1] + ds[i - 1] * np.sin(heading[i - 1])

    return pd.DataFrame({
        "distance_m": dist,
        "curvature": kappa,
        "heading_rad": heading,
        "x_m": x,
        "y_m": y,
    })


# ---------------------------------------------------------------------------
# Test: _map_columns_to_canonical
# ---------------------------------------------------------------------------

class TestMapColumnsToCanonical:
    """Tests for the column mapping function."""

    def test_racechrono_columns(self):
        """RaceChrono raw column names are mapped to canonical."""
        df = pd.DataFrame({
            "Distance (m)": [0.0, 1.0],
            "Speed (m/s)": [10.0, 11.0],
            "Time (s)": [0.0, 0.1],
            "Lap #": [1, 1],
        })
        mapped = _map_columns_to_canonical(df)
        assert "distance_m" in mapped.columns
        assert "speed_mps" in mapped.columns
        assert "time_s" in mapped.columns
        assert "lap_number" in mapped.columns

    def test_calc_variant_preferred(self):
        """Speed (m/s) *calc is preferred over Speed (m/s)."""
        df = pd.DataFrame({
            "Speed (m/s) *calc": [10.0, 11.0],
            "Speed (m/s)": [9.0, 10.0],
            "Distance (m)": [0.0, 1.0],
        })
        mapped = _map_columns_to_canonical(df)
        assert "speed_mps" in mapped.columns
        # *calc values should be used
        np.testing.assert_array_almost_equal(mapped["speed_mps"].values, [10.0, 11.0])

    def test_already_canonical_passthrough(self):
        """Columns that are already canonical pass through unchanged."""
        df = pd.DataFrame({
            "distance_m": [0.0, 1.0],
            "speed_mps": [10.0, 11.0],
            "time_s": [0.0, 0.1],
            "lap_number": [1, 1],
        })
        mapped = _map_columns_to_canonical(df)
        assert "distance_m" in mapped.columns
        assert "speed_mps" in mapped.columns
        np.testing.assert_array_almost_equal(mapped["speed_mps"].values, [10.0, 11.0])

    def test_g_unit_conversion_long(self):
        """Longitudinal G-force columns are converted to m/s^2."""
        df = pd.DataFrame({
            "Longitudinal acceleration (G) *calc": [1.0, -0.5],
            "Distance (m)": [0.0, 1.0],
        })
        mapped = _map_columns_to_canonical(df)
        assert "accel_long_mps2" in mapped.columns
        np.testing.assert_array_almost_equal(
            mapped["accel_long_mps2"].values,
            [1.0 * _G, -0.5 * _G],
            decimal=3,
        )

    def test_g_unit_conversion_lat(self):
        """Lateral G-force columns are converted to m/s^2."""
        df = pd.DataFrame({
            "Lateral acceleration (G)": [0.8, 1.2],
            "Distance (m)": [0.0, 1.0],
        })
        mapped = _map_columns_to_canonical(df)
        assert "accel_lat_mps2" in mapped.columns
        np.testing.assert_array_almost_equal(
            mapped["accel_lat_mps2"].values,
            [0.8 * _G, 1.2 * _G],
            decimal=3,
        )

    def test_mps2_columns_no_g_conversion(self):
        """Acceleration already in m/s^2 should NOT be re-converted."""
        df = pd.DataFrame({
            "Longitudinal acceleration (m/s\u00b2)": [5.0, -3.0],
            "Lateral acceleration (m/s\u00b2)": [4.0, 6.0],
            "Distance (m)": [0.0, 1.0],
        })
        mapped = _map_columns_to_canonical(df)
        assert "accel_long_mps2" in mapped.columns
        assert "accel_lat_mps2" in mapped.columns
        # Values should stay the same (no G conversion)
        np.testing.assert_array_almost_equal(
            mapped["accel_long_mps2"].values, [5.0, -3.0], decimal=3)
        np.testing.assert_array_almost_equal(
            mapped["accel_lat_mps2"].values, [4.0, 6.0], decimal=3)

    def test_no_duplicate_canonical_names(self):
        """First match wins -- no duplicate canonical columns."""
        df = pd.DataFrame({
            "Speed (m/s) *calc": [10.0],
            "Speed (m/s)": [9.0],
            "Distance (m)": [0.0],
        })
        mapped = _map_columns_to_canonical(df)
        speed_cols = [c for c in mapped.columns if c == "speed_mps"]
        assert len(speed_cols) == 1

    def test_unknown_columns_preserved(self):
        """Columns that don't match any mapping are kept as-is."""
        df = pd.DataFrame({
            "Distance (m)": [0.0, 1.0],
            "my_custom_col": [42, 43],
        })
        mapped = _map_columns_to_canonical(df)
        assert "my_custom_col" in mapped.columns


# ---------------------------------------------------------------------------
# Test: AdapterResult
# ---------------------------------------------------------------------------

class TestAdapterResult:
    """Tests for the AdapterResult dataclass."""

    def test_fields_exist(self):
        """All specified fields are accessible."""
        result = AdapterResult(
            theoretical_df=pd.DataFrame(),
            theoretical_result=None,
            method="test_method",
        )
        assert result.theoretical_df is not None
        assert result.theoretical_result is None
        assert result.method == "test_method"
        assert result.corner_coaching is None
        assert result.delta_map is None
        assert result.session_scalars is None

    def test_defaults_correct(self):
        """Optional fields default to None."""
        result = AdapterResult(
            theoretical_df=pd.DataFrame({"a": [1]}),
            theoretical_result="dummy",
            method="kart_envelope_qss",
        )
        assert result.corner_coaching is None
        assert result.delta_map is None
        assert result.session_scalars is None

    def test_all_fields_settable(self):
        """All fields can be set explicitly."""
        df = pd.DataFrame({"x": [1]})
        delta = pd.DataFrame({"d": [2]})
        result = AdapterResult(
            theoretical_df=df,
            theoretical_result="result_obj",
            method="kart_envelope_qss",
            corner_coaching=[{"corner_id": 1}],
            delta_map=delta,
            session_scalars="scalars_obj",
        )
        assert result.corner_coaching == [{"corner_id": 1}]
        assert result.delta_map is delta
        assert result.session_scalars == "scalars_obj"


# ---------------------------------------------------------------------------
# Test: compute_theoretical_via_envelope (integration)
# ---------------------------------------------------------------------------

class TestComputeTheoreticalViaEnvelope:
    """Integration tests for the main adapter function."""

    @pytest.fixture
    def resampled_laps(self):
        return _make_resampled_laps(n_laps=5, n_points=200, lap_length_m=500.0)

    @pytest.fixture
    def curvature_profile(self):
        return _make_curvature_profile(n_points=200, lap_length_m=500.0)

    def test_returns_adapter_result(self, resampled_laps, curvature_profile):
        """Main function returns an AdapterResult."""
        result = compute_theoretical_via_envelope(
            resampled_laps=resampled_laps,
            curvature_profile=curvature_profile,
            vehicle_params=None,
            data_quality_rpt=None,
        )
        assert isinstance(result, AdapterResult)

    def test_method_name(self, resampled_laps, curvature_profile):
        """Method name indicates kart_envelope origin."""
        result = compute_theoretical_via_envelope(
            resampled_laps=resampled_laps,
            curvature_profile=curvature_profile,
            vehicle_params=None,
            data_quality_rpt=None,
        )
        assert "kart_envelope" in result.method

    def test_df_has_required_columns(self, resampled_laps, curvature_profile):
        """Theoretical DataFrame has pipeline-expected columns."""
        result = compute_theoretical_via_envelope(
            resampled_laps=resampled_laps,
            curvature_profile=curvature_profile,
            vehicle_params=None,
            data_quality_rpt=None,
        )
        df = result.theoretical_df
        required = {"distance_m", "v_env_mps", "accel_max_mps2", "brake_max_mps2"}
        assert required.issubset(set(df.columns)), (
            f"Missing columns: {required - set(df.columns)}"
        )

    def test_df_not_empty(self, resampled_laps, curvature_profile):
        """Theoretical DataFrame has rows."""
        result = compute_theoretical_via_envelope(
            resampled_laps=resampled_laps,
            curvature_profile=curvature_profile,
            vehicle_params=None,
            data_quality_rpt=None,
        )
        assert len(result.theoretical_df) > 0

    def test_lap_time_positive(self, resampled_laps, curvature_profile):
        """TheoreticalResult has a positive lap time."""
        result = compute_theoretical_via_envelope(
            resampled_laps=resampled_laps,
            curvature_profile=curvature_profile,
            vehicle_params=None,
            data_quality_rpt=None,
        )
        assert result.theoretical_result is not None
        assert result.theoretical_result.lap_time_s > 0
        assert math.isfinite(result.theoretical_result.lap_time_s)

    def test_session_scalars_not_none(self, resampled_laps, curvature_profile):
        """Session scalars should be inferred."""
        result = compute_theoretical_via_envelope(
            resampled_laps=resampled_laps,
            curvature_profile=curvature_profile,
            vehicle_params=None,
            data_quality_rpt=None,
        )
        assert result.session_scalars is not None

    def test_raises_on_none_curvature(self, resampled_laps):
        """ValueError raised when curvature_profile is None."""
        with pytest.raises(ValueError, match="curvature"):
            compute_theoretical_via_envelope(
                resampled_laps=resampled_laps,
                curvature_profile=None,
                vehicle_params=None,
                data_quality_rpt=None,
            )

    def test_speed_profile_reasonable(self, resampled_laps, curvature_profile):
        """Speed profile values should be physically reasonable."""
        result = compute_theoretical_via_envelope(
            resampled_laps=resampled_laps,
            curvature_profile=curvature_profile,
            vehicle_params=None,
            data_quality_rpt=None,
        )
        df = result.theoretical_df
        speeds = df["v_env_mps"].values
        assert np.all(speeds > 0), "All speeds should be positive"
        assert np.all(speeds < 50), "All speeds should be under 50 m/s for karts"
        assert np.all(np.isfinite(speeds)), "All speeds should be finite"

    def test_distance_monotonic(self, resampled_laps, curvature_profile):
        """Distance column should be monotonically increasing."""
        result = compute_theoretical_via_envelope(
            resampled_laps=resampled_laps,
            curvature_profile=curvature_profile,
            vehicle_params=None,
            data_quality_rpt=None,
        )
        df = result.theoretical_df
        diffs = np.diff(df["distance_m"].values)
        assert np.all(diffs >= 0), "Distance should be monotonically increasing"

    def test_accel_brake_positive(self, resampled_laps, curvature_profile):
        """Accel and brake limits should be positive magnitudes."""
        result = compute_theoretical_via_envelope(
            resampled_laps=resampled_laps,
            curvature_profile=curvature_profile,
            vehicle_params=None,
            data_quality_rpt=None,
        )
        df = result.theoretical_df
        assert np.all(df["accel_max_mps2"].values >= 0), "Accel max should be >= 0"
        assert np.all(df["brake_max_mps2"].values >= 0), "Brake max should be >= 0"

    def test_racechrono_columns_handled(self, curvature_profile):
        """Laps with RaceChrono column names are handled correctly."""
        laps = {}
        for i in range(1, 4):
            n = 200
            dist = np.linspace(0, 500, n, endpoint=False)
            speed = 10.0 + 2.0 * np.sin(2 * np.pi * 2 * dist / 500)
            speed = np.maximum(speed, 1.0)
            dt = np.diff(dist) / (0.5 * (speed[:-1] + speed[1:]))
            time = np.concatenate([[0.0], np.cumsum(dt)])
            dv_ds = np.gradient(speed, dist)
            accel_long_g = (dv_ds * speed) / _G  # in G
            kappa = 0.02 * np.abs(np.sin(2 * np.pi * 2 * dist / 500))
            accel_lat_g = (speed**2 * kappa) / _G  # in G

            laps[i] = pd.DataFrame({
                "Distance (m)": dist,
                "Speed (m/s)": speed,
                "Time (s)": time,
                "Lap #": i,
                "Longitudinal acceleration (G) *calc": accel_long_g,
                "Lateral acceleration (G) *calc": accel_lat_g,
            })

        result = compute_theoretical_via_envelope(
            resampled_laps=laps,
            curvature_profile=curvature_profile,
            vehicle_params=None,
            data_quality_rpt=None,
        )
        assert isinstance(result, AdapterResult)
        assert len(result.theoretical_df) > 0

    def test_curvature_1pm_column_accepted(self, resampled_laps):
        """Curvature profile with 'curvature_1pm' column name works."""
        dist = np.linspace(0, 500, 200, endpoint=False)
        kappa = 0.02 * np.abs(np.sin(2 * np.pi * 2 * dist / 500))
        curv = pd.DataFrame({
            "distance_m": dist,
            "curvature_1pm": kappa,
        })
        result = compute_theoretical_via_envelope(
            resampled_laps=resampled_laps,
            curvature_profile=curv,
            vehicle_params=None,
            data_quality_rpt=None,
        )
        assert isinstance(result, AdapterResult)
        assert len(result.theoretical_df) > 0

    def test_best_driver_time_kwarg(self, resampled_laps, curvature_profile):
        """best_driver_time_s kwarg is accepted without error."""
        result = compute_theoretical_via_envelope(
            resampled_laps=resampled_laps,
            curvature_profile=curvature_profile,
            vehicle_params=None,
            data_quality_rpt=None,
            best_driver_time_s=42.0,
        )
        assert isinstance(result, AdapterResult)
