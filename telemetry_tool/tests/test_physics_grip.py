"""Tests for track_surface/physics_grip.py — rigid-body load + force + mu."""
from __future__ import annotations

import numpy as np
import pytest

from track_surface.physics_grip import (
    VehicleGeometry,
    build_physics_grip_grid,
    build_vehicle_geometry,
    compute_mu_per_wheel,
    compute_per_wheel_normal_loads,
    compute_per_wheel_tangential_forces,
)

_G = 9.80665


def _default_geom() -> VehicleGeometry:
    return build_vehicle_geometry(None)


def _make_arrays(n, a_long=0.0, a_lat=0.0, speed=30.0, roll=0.0, pitch=0.0):
    return {
        "speed_mps": np.full(n, speed),
        "a_long_body": np.full(n, a_long),
        "a_lat_body": np.full(n, a_lat),
        "roll_rad": np.full(n, roll),
        "pitch_rad": np.full(n, pitch),
    }


class TestPerWheelNormalLoads:
    def test_static_balance_all_four_wheels(self):
        """Zero accel/roll/pitch, no aero → load matches static distribution."""
        geom = _default_geom()
        mass = 1300.0
        n = 5
        args = _make_arrays(n)
        loads = compute_per_wheel_normal_loads(
            mass_kg=mass, aero_cla=0.0, air_density=1.225, geom=geom, **args,
        )
        # Each row must sum to mass * g
        total = loads.fz.sum(axis=1)
        np.testing.assert_allclose(total, mass * _G, rtol=1e-6)
        # Left vs right symmetric
        np.testing.assert_allclose(loads.fz[:, 0], loads.fz[:, 1], rtol=1e-6)
        np.testing.assert_allclose(loads.fz[:, 2], loads.fz[:, 3], rtol=1e-6)

    def test_braking_transfers_to_front(self):
        """Negative a_long shifts load from rear to front."""
        geom = _default_geom()
        mass = 1300.0
        n = 5
        args_static = _make_arrays(n, a_long=0.0)
        args_brake = _make_arrays(n, a_long=-10.0)
        loads_s = compute_per_wheel_normal_loads(
            mass_kg=mass, aero_cla=0.0, air_density=1.225, geom=geom, **args_static,
        )
        loads_b = compute_per_wheel_normal_loads(
            mass_kg=mass, aero_cla=0.0, air_density=1.225, geom=geom, **args_brake,
        )
        # Under braking, front load > static front load
        assert loads_b.fz[0, 0] > loads_s.fz[0, 0]
        assert loads_b.fz[0, 1] > loads_s.fz[0, 1]
        # Rear load decreases
        assert loads_b.fz[0, 2] < loads_s.fz[0, 2]
        assert loads_b.fz[0, 3] < loads_s.fz[0, 3]
        # Total still conserved
        np.testing.assert_allclose(loads_b.fz.sum(axis=1), mass * _G, rtol=1e-6)

    def test_right_turn_loads_right_side(self):
        """+a_lat (right turn) transfers load from left to right wheels."""
        geom = _default_geom()
        mass = 1300.0
        n = 3
        args = _make_arrays(n, a_lat=15.0)  # hard right
        loads = compute_per_wheel_normal_loads(
            mass_kg=mass, aero_cla=0.0, air_density=1.225, geom=geom, **args,
        )
        # Right wheels carry more load than left
        assert loads.fz[0, 1] > loads.fz[0, 0]  # RF > LF
        assert loads.fz[0, 3] > loads.fz[0, 2]  # RR > LR
        # Total conserved
        np.testing.assert_allclose(loads.fz.sum(axis=1), mass * _G, rtol=1e-6)

    def test_aero_increases_total_load(self):
        """High CLA at speed increases total normal force."""
        geom = _default_geom()
        mass = 1300.0
        n = 3
        args = _make_arrays(n, speed=60.0)
        loads_no_aero = compute_per_wheel_normal_loads(
            mass_kg=mass, aero_cla=0.0, air_density=1.225, geom=geom, **args,
        )
        loads_aero = compute_per_wheel_normal_loads(
            mass_kg=mass, aero_cla=2.0, air_density=1.225, geom=geom, **args,
        )
        # With aero, total Fz should be higher
        assert loads_aero.fz.sum(axis=1).mean() > loads_no_aero.fz.sum(axis=1).mean()

    def test_wheel_lift_clipped_to_zero(self):
        """Extreme lateral should not produce negative Fz."""
        geom = _default_geom()
        mass = 1300.0
        n = 3
        # Extreme lateral > possible in reality
        args = _make_arrays(n, a_lat=50.0, speed=30.0)
        loads = compute_per_wheel_normal_loads(
            mass_kg=mass, aero_cla=0.0, air_density=1.225, geom=geom, **args,
        )
        # No negative loads (wheel lift clipped)
        assert np.all(loads.fz >= 0)


class TestTangentialForces:
    def test_braking_force_sum_equals_total(self):
        geom = _default_geom()
        mass = 1300.0
        n = 3
        args = _make_arrays(n, a_long=-10.0)
        loads = compute_per_wheel_normal_loads(
            mass_kg=mass, aero_cla=0.0, air_density=1.225, geom=geom, **args,
        )
        f_tang = compute_per_wheel_tangential_forces(
            mass_kg=mass,
            fz_per_wheel=loads.fz,
            a_long_body=args["a_long_body"],
            a_lat_body=args["a_lat_body"],
            brake_line_press=None,
            brake_bias_front=0.60,
            drive_rear_only=True,
        )
        # Sum of tangential = mass * |a_long| (all force is longitudinal)
        total = f_tang.sum(axis=1)
        np.testing.assert_allclose(total, mass * 10.0, rtol=1e-5)

    def test_traction_splits_to_rear_only(self):
        geom = _default_geom()
        mass = 1300.0
        n = 3
        args = _make_arrays(n, a_long=5.0)  # accelerating
        loads = compute_per_wheel_normal_loads(
            mass_kg=mass, aero_cla=0.0, air_density=1.225, geom=geom, **args,
        )
        f_tang = compute_per_wheel_tangential_forces(
            mass_kg=mass,
            fz_per_wheel=loads.fz,
            a_long_body=args["a_long_body"],
            a_lat_body=args["a_lat_body"],
            brake_line_press=None,
            brake_bias_front=0.60,
            drive_rear_only=True,
        )
        # Front wheels should have no longitudinal force during traction
        # so only the lateral split contributes (zero here)
        assert np.all(f_tang[:, 0] < 0.01)  # LF
        assert np.all(f_tang[:, 1] < 0.01)  # RF
        # Rear wheels carry all the tractive force
        assert f_tang[0, 2] > 100
        assert f_tang[0, 3] > 100


class TestMuPerWheel:
    def test_wheel_lift_gives_nan(self):
        fz = np.array([[100.0, 5000.0, 5000.0, 5000.0]])  # LF under 800 threshold
        f_tang = np.array([[50.0, 3000.0, 3000.0, 3000.0]])
        mu = compute_mu_per_wheel(fz, f_tang, fz_min_n=800.0)
        assert np.isnan(mu[0, 0])
        assert np.isfinite(mu[0, 1])

    def test_mu_clamped_at_cap(self):
        # Construct a case where F_t / Fz > 2.5 → should become NaN
        fz = np.array([[1000.0, 1000.0, 1000.0, 1000.0]])
        f_tang = np.array([[3000.0, 3000.0, 3000.0, 3000.0]])  # mu=3.0 > cap
        mu = compute_mu_per_wheel(fz, f_tang, mu_absolute_cap=2.5)
        assert np.all(np.isnan(mu))

    def test_straight_braking_mu_matches_body_frame(self):
        """Straight-line braking on symmetric tires: max mu ≈ a/g (ignoring aero)."""
        geom = _default_geom()
        mass = 1300.0
        n = 1
        args = _make_arrays(n, a_long=-10.0, speed=30.0)
        loads = compute_per_wheel_normal_loads(
            mass_kg=mass, aero_cla=0.0, air_density=1.225, geom=geom, **args,
        )
        f_tang = compute_per_wheel_tangential_forces(
            mass_kg=mass,
            fz_per_wheel=loads.fz,
            a_long_body=args["a_long_body"],
            a_lat_body=args["a_lat_body"],
            brake_line_press=None,
            brake_bias_front=0.50,
            drive_rear_only=True,
        )
        mu = compute_mu_per_wheel(loads.fz, f_tang, fz_min_n=100)
        max_mu = np.nanmax(mu)
        # With 50/50 brake bias but rear-biased static distribution (46% front)
        # plus forward load transfer from braking, the front wheel utilisation
        # is slightly higher than a/g=1.02 because it gets 50% of F_long
        # over ~50% of Fz after transfer. Expect 1.0-1.3 range.
        assert 0.90 < max_mu < 1.35


class TestGridBuild:
    def test_grid_with_single_cell_data(self):
        # 10 samples all hitting cell (5, 10) at high util
        n = 10
        s_proj = np.full(n, 50.0)
        n_proj = np.full(n, 5.0)
        # Mu per wheel: the max is 1.3
        mu_per_wheel = np.full((n, 4), 1.3)
        a_body_mag = np.full(n, 15.0)   # above threshold * 9.81
        g_eff = np.full(n, 9.81)
        s_bins = np.arange(0, 200, 10.0)
        n_bins = np.arange(-15, 16, 1.0)
        grid = build_physics_grip_grid(
            s_proj=s_proj,
            n_proj=n_proj,
            mu_per_wheel=mu_per_wheel,
            a_body_mag=a_body_mag,
            g_eff=g_eff,
            s_bins=s_bins,
            n_bins=n_bins,
            util_threshold=0.55,
            percentile=95.0,
        )
        # Expect one filled cell at s=50, n=5
        filled = np.where(np.isfinite(grid))
        assert len(filled[0]) >= 1
        # Value ≈ 1.3
        valid_vals = grid[~np.isnan(grid)]
        assert valid_vals.min() > 1.2
        assert valid_vals.max() < 1.4
