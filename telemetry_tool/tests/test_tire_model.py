"""Tests for tire_model.py — quasi-steady combined-slip v1.

All must pass before wiring to surface_inverse_solver.py.
"""
from __future__ import annotations

import numpy as np
import pytest

from track_surface.tire_model import (
    TireInputs,
    TireOutputs,
    TireParams,
    TireState,
    peak_mu_vs_load,
    predict_tire_forces,
)


def _default_params() -> TireParams:
    return TireParams.gt4_default()


def _make_input(
    alpha=0.0, kappa=None, fz=4000.0, camber=0.0, vx=30.0, state=None,
) -> TireInputs:
    return TireInputs(alpha=alpha, kappa=kappa, fz=fz, camber=camber, vx=vx, state=state)


# ── Physics sanity ───────────────────────────────────────────


class TestPureSlipSymmetry:
    """Fy(alpha) and Fx(kappa) must be odd-symmetric around zero."""

    def test_fy_odd_symmetric(self):
        p = _default_params()
        out_pos = predict_tire_forces(_make_input(alpha=0.05), p)
        out_neg = predict_tire_forces(_make_input(alpha=-0.05), p)
        assert abs(out_pos.fy + out_neg.fy) < 1.0  # should be opposite signs

    def test_fx_odd_symmetric(self):
        p = _default_params()
        out_pos = predict_tire_forces(_make_input(kappa=0.05), p)
        out_neg = predict_tire_forces(_make_input(kappa=-0.05), p)
        assert abs(out_pos.fx + out_neg.fx) < 1.0

    def test_zero_alpha_zero_fy(self):
        p = _default_params()
        out = predict_tire_forces(_make_input(alpha=0.0), p)
        assert abs(out.fy) < 1.0

    def test_zero_kappa_zero_fx(self):
        p = _default_params()
        out = predict_tire_forces(_make_input(alpha=0.05, kappa=0.0), p)
        assert abs(out.fx) < 1.0


class TestLoadSensitivity:
    """Peak friction coefficient must decrease with increasing Fz."""

    def test_mu_decreases_with_load(self):
        p = _default_params()
        fz_range = np.array([2000, 4000, 6000, 8000, 10000], dtype=float)
        mu_lat, mu_long = peak_mu_vs_load(fz_range, p)

        # mu should be monotonically decreasing
        for i in range(len(mu_lat) - 1):
            assert mu_lat[i] > mu_lat[i + 1], f"mu_lat not decreasing at Fz={fz_range[i+1]}"
            assert mu_long[i] > mu_long[i + 1], f"mu_long not decreasing at Fz={fz_range[i+1]}"

    def test_mu_at_low_load_higher_than_high_load(self):
        p = _default_params()
        fz_low, fz_high = np.array([2000.0]), np.array([8000.0])
        mu_low, _ = peak_mu_vs_load(fz_low, p)
        mu_high, _ = peak_mu_vs_load(fz_high, p)
        assert mu_low[0] > mu_high[0]

    def test_mu_at_typical_load_in_physical_range(self):
        """At 4000 N (typical GT4 corner), peak mu should be 1.2-1.6."""
        p = _default_params()
        fz = np.array([4000.0])
        mu_lat, _ = peak_mu_vs_load(fz, p)
        assert 1.1 < mu_lat[0] < 1.7


class TestCombinedSlip:
    """Combined slip reduces available lateral force when longitudinal demand rises."""

    def test_combined_reduces_lateral(self):
        p = _default_params()
        # Pure cornering
        out_pure = predict_tire_forces(_make_input(alpha=0.06, kappa=None), p)
        # Combined: same alpha but also braking
        out_combined = predict_tire_forces(_make_input(alpha=0.06, kappa=-0.05), p)
        # Lateral force should be reduced under combined slip
        assert abs(out_combined.fy) < abs(out_pure.fy)

    def test_combined_reduces_longitudinal(self):
        p = _default_params()
        out_pure = predict_tire_forces(_make_input(alpha=0.0, kappa=0.08), p)
        out_combined = predict_tire_forces(_make_input(alpha=0.06, kappa=0.08), p)
        assert abs(out_combined.fx) < abs(out_pure.fx)

    def test_utilization_increases_with_demand(self):
        p = _default_params()
        out_low = predict_tire_forces(_make_input(alpha=0.02), p)
        out_high = predict_tire_forces(_make_input(alpha=0.10), p)
        assert out_high.combined_utilization > out_low.combined_utilization


class TestCamber:
    """Camber changes lateral-force bias in the correct direction."""

    def test_negative_camber_produces_lateral_force(self):
        """Negative camber (top of tire inward) should produce force toward
        the center of the car — which for the front-left wheel is rightward."""
        p = _default_params()
        # No slip angle, just camber
        out = predict_tire_forces(
            _make_input(alpha=0.0, camber=-0.07, kappa=0.0), p  # -4 degrees
        )
        # Camber thrust should produce a non-zero Fy
        assert abs(out.fy) > 10.0  # should be measurable

    def test_opposite_camber_opposite_force(self):
        p = _default_params()
        out_neg = predict_tire_forces(_make_input(alpha=0.0, camber=-0.07, kappa=0.0), p)
        out_pos = predict_tire_forces(_make_input(alpha=0.0, camber=+0.07, kappa=0.0), p)
        # Forces should be opposite sign
        assert out_neg.fy * out_pos.fy < 0


# ── Numerical sanity ─────────────────────────────────────────


class TestNumericalSanity:
    def test_bounded_at_small_vx(self):
        p = _default_params()
        out = predict_tire_forces(_make_input(alpha=0.1, kappa=0.1, vx=0.5), p)
        assert np.isfinite(out.fx)
        assert np.isfinite(out.fy)
        assert abs(out.fx) < 100000
        assert abs(out.fy) < 100000

    def test_no_blowup_near_kappa_zero(self):
        p = _default_params()
        for k in [0.0, 0.001, -0.001, 1e-8, -1e-8]:
            out = predict_tire_forces(_make_input(alpha=0.05, kappa=k), p)
            assert np.isfinite(out.fx)
            assert np.isfinite(out.fy)

    def test_graceful_with_kappa_none(self):
        p = _default_params()
        out = predict_tire_forces(_make_input(alpha=0.05, kappa=None), p)
        assert np.isfinite(out.fy)
        assert out.flags.get("kappa_available") is False
        # Fx should be ~0 when kappa is None (treated as 0)
        assert abs(out.fx) < 1.0

    def test_very_high_fz_no_crash(self):
        p = _default_params()
        out = predict_tire_forces(_make_input(fz=20000.0, alpha=0.05), p)
        assert np.isfinite(out.fy)

    def test_zero_fz_no_crash(self):
        p = _default_params()
        out = predict_tire_forces(_make_input(fz=0.0, alpha=0.05), p)
        assert np.isfinite(out.fy)
        assert abs(out.fy) < 1.0  # no force at zero load


# ── API sanity ───────────────────────────────────────────────


class TestAPISanity:
    def test_road_scaling_not_in_params(self):
        """TireParams should NOT contain a lambda_surface field."""
        p = _default_params()
        assert not hasattr(p, "lambda_surface")
        assert not hasattr(p, "road_scale")

    def test_tire_state_optional(self):
        """Model should work with and without tire state."""
        p = _default_params()
        out_no_state = predict_tire_forces(_make_input(alpha=0.05, state=None), p)
        out_with_state = predict_tire_forces(
            _make_input(alpha=0.05, state=TireState(temp_surface_c=90.0, wear_pct=95.0)), p
        )
        # Both should produce valid output
        assert np.isfinite(out_no_state.fy)
        assert np.isfinite(out_with_state.fy)
        assert out_no_state.flags.get("tire_state_applied") is False
        assert out_with_state.flags.get("tire_state_applied") is True

    def test_outputs_include_capacity(self):
        p = _default_params()
        out = predict_tire_forces(_make_input(alpha=0.05, kappa=0.03), p)
        assert out.fx_capacity > 0
        assert out.fy_capacity > 0
        assert out.combined_utilization is not None
        assert 0 <= out.combined_utilization <= 1.0

    def test_quality_monotone_with_inputs(self):
        p = _default_params()
        out_minimal = predict_tire_forces(_make_input(alpha=0.05, kappa=None, vx=5.0), p)
        out_full = predict_tire_forces(
            _make_input(alpha=0.05, kappa=0.02, vx=30.0, state=TireState(temp_surface_c=85.0)), p
        )
        assert out_full.quality > out_minimal.quality
