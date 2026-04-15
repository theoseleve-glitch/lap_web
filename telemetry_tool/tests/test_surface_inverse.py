"""Tests for surface_inverse_solver.py — lambda estimation from observed vs predicted forces."""
from __future__ import annotations

import numpy as np
import pytest

from track_surface.surface_inverse_solver import (
    ExcitationConfig,
    SurfaceEstimate,
    aggregate_wheel_lambdas,
    solve_lambda_surface,
)
from track_surface.tire_model import TireInputs, TireParams, predict_tire_forces


def _default_params() -> TireParams:
    return TireParams.gt4_default()


def _make_tire_input(**kwargs) -> TireInputs:
    defaults = dict(alpha=0.06, kappa=None, fz=4000.0, camber=0.0, vx=30.0, state=None)
    defaults.update(kwargs)
    return TireInputs(**defaults)


# ── Core inverse problem ─────────────────────────────────────


class TestLambdaRecovery:
    """Given Fx/Fy = lambda × TireModel prediction, recover lambda."""

    def test_lambda_one_on_perfect_match(self):
        """If observed forces exactly match prediction, lambda ≈ 1.0."""
        params = _default_params()
        inp = _make_tire_input(alpha=0.06)
        pred = predict_tire_forces(inp, params)

        est = solve_lambda_surface(
            fx_obs=pred.fx, fy_obs=pred.fy,
            tire_input=inp, tire_params=params,
        )
        assert est.lambda_surface is not None
        assert abs(est.lambda_surface - 1.0) < 0.05

    def test_lambda_recovers_scaled_surface(self):
        """If surface is 20% grippier, lambda should be ~1.2."""
        params = _default_params()
        inp = _make_tire_input(alpha=0.08)
        pred = predict_tire_forces(inp, params)

        # Observed = 1.2 × predicted
        est = solve_lambda_surface(
            fx_obs=pred.fx * 1.2, fy_obs=pred.fy * 1.2,
            tire_input=inp, tire_params=params,
        )
        assert est.lambda_surface is not None
        assert abs(est.lambda_surface - 1.2) < 0.05

    def test_lambda_recovers_low_grip(self):
        """If surface offers 80% of expected, lambda ≈ 0.8."""
        params = _default_params()
        inp = _make_tire_input(alpha=0.07, kappa=-0.03)
        pred = predict_tire_forces(inp, params)

        est = solve_lambda_surface(
            fx_obs=pred.fx * 0.8, fy_obs=pred.fy * 0.8,
            tire_input=inp, tire_params=params,
        )
        assert est.lambda_surface is not None
        assert abs(est.lambda_surface - 0.8) < 0.05

    def test_lambda_correct_under_combined_slip(self):
        """Lambda recovery should work under combined braking + cornering."""
        params = _default_params()
        inp = _make_tire_input(alpha=0.06, kappa=-0.05, fz=5000.0)
        pred = predict_tire_forces(inp, params)

        target_lambda = 1.15
        est = solve_lambda_surface(
            fx_obs=pred.fx * target_lambda,
            fy_obs=pred.fy * target_lambda,
            tire_input=inp, tire_params=params,
        )
        assert est.lambda_surface is not None
        assert abs(est.lambda_surface - target_lambda) < 0.05


# ── Excitation gating ────────────────────────────────────────


class TestExcitationGating:
    """Low-excitation samples should be rejected (lambda = None)."""

    def test_low_speed_rejected(self):
        est = solve_lambda_surface(
            fx_obs=500.0, fy_obs=2000.0,
            tire_input=_make_tire_input(vx=3.0),
            tire_params=_default_params(),
        )
        assert est.lambda_surface is None
        assert est.flags.get("low_speed") is True

    def test_low_fz_rejected(self):
        est = solve_lambda_surface(
            fx_obs=100.0, fy_obs=500.0,
            tire_input=_make_tire_input(fz=200.0),
            tire_params=_default_params(),
        )
        assert est.lambda_surface is None
        assert est.flags.get("low_fz") is True

    def test_low_demand_rejected(self):
        """Cruising at low lateral demand — no information about peak grip."""
        est = solve_lambda_surface(
            fx_obs=50.0, fy_obs=100.0,  # very low forces
            tire_input=_make_tire_input(alpha=0.005, fz=4000.0),
            tire_params=_default_params(),
        )
        assert est.lambda_surface is None
        assert "low" in str(est.flags.get("reject_reasons", []))

    def test_high_excitation_accepted(self):
        """Hard cornering should be accepted."""
        params = _default_params()
        inp = _make_tire_input(alpha=0.08, fz=5000.0, vx=40.0)
        pred = predict_tire_forces(inp, params)

        est = solve_lambda_surface(
            fx_obs=pred.fx * 1.1, fy_obs=pred.fy * 1.1,
            tire_input=inp, tire_params=params,
        )
        assert est.lambda_surface is not None
        assert est.confidence > 0.2
        assert est.flags.get("rejected") is False

    def test_excitation_score_increases_with_demand(self):
        params = _default_params()
        inp_low = _make_tire_input(alpha=0.02, fz=4000.0)
        inp_high = _make_tire_input(alpha=0.10, fz=4000.0)
        pred_low = predict_tire_forces(inp_low, params)
        pred_high = predict_tire_forces(inp_high, params)

        est_low = solve_lambda_surface(
            fx_obs=pred_low.fx, fy_obs=pred_low.fy,
            tire_input=inp_low, tire_params=params,
        )
        est_high = solve_lambda_surface(
            fx_obs=pred_high.fx, fy_obs=pred_high.fy,
            tire_input=inp_high, tire_params=params,
        )
        # The high-demand sample should have higher excitation
        assert est_high.excitation >= est_low.excitation


# ── Edge cases ───────────────────────────────────────────────


class TestEdgeCases:
    def test_zero_prediction_returns_none(self):
        """If the tire model predicts zero force, lambda is undefined."""
        est = solve_lambda_surface(
            fx_obs=500.0, fy_obs=2000.0,
            tire_input=_make_tire_input(alpha=0.0, kappa=0.0),  # zero slip → zero force
            tire_params=_default_params(),
        )
        # Should reject due to low prediction or low excitation
        assert est.lambda_surface is None or est.confidence < 0.1

    def test_opposite_direction_forces_low_confidence(self):
        """If observed and predicted forces point opposite, lambda should be
        negative → clamped, low confidence."""
        params = _default_params()
        inp = _make_tire_input(alpha=0.06, fz=4000.0)
        pred = predict_tire_forces(inp, params)

        est = solve_lambda_surface(
            fx_obs=-pred.fx, fy_obs=-pred.fy,  # opposite direction
            tire_input=inp, tire_params=params,
        )
        # Lambda would be negative → clamped to min_lambda
        if est.lambda_surface is not None:
            assert est.lambda_surface <= 0.3  # clamped to min
            assert est.confidence < 0.3  # direction mismatch penalty

    def test_extreme_lambda_gets_clamped(self):
        """Lambda > max_lambda should be clamped with reduced confidence."""
        params = _default_params()
        inp = _make_tire_input(alpha=0.08, fz=4000.0)
        pred = predict_tire_forces(inp, params)

        est = solve_lambda_surface(
            fx_obs=pred.fx * 3.0, fy_obs=pred.fy * 3.0,  # 3x → beyond max_lambda
            tire_input=inp, tire_params=params,
        )
        if est.lambda_surface is not None:
            assert est.lambda_surface <= 2.0  # clamped
            assert est.flags.get("lambda_clamped") is True


# ── Multi-wheel aggregation ──────────────────────────────────


class TestAggregation:
    def test_four_valid_wheels_average(self):
        estimates = (
            SurfaceEstimate(lambda_surface=1.1, confidence=0.8, excitation=0.8, flags={}),
            SurfaceEstimate(lambda_surface=1.2, confidence=0.7, excitation=0.7, flags={}),
            SurfaceEstimate(lambda_surface=1.0, confidence=0.9, excitation=0.9, flags={}),
            SurfaceEstimate(lambda_surface=1.15, confidence=0.6, excitation=0.6, flags={}),
        )
        lam, conf = aggregate_wheel_lambdas(estimates)
        assert lam is not None
        # Confidence-weighted mean: should be between 1.0 and 1.2
        assert 1.0 < lam < 1.2
        assert conf > 0.5

    def test_some_wheels_none(self):
        """Aggregation should work even if some wheels have no estimate."""
        estimates = (
            SurfaceEstimate(lambda_surface=1.1, confidence=0.8, excitation=0.8, flags={}),
            SurfaceEstimate(lambda_surface=None, confidence=0.0, excitation=0.1, flags={}),
            SurfaceEstimate(lambda_surface=None, confidence=0.0, excitation=0.2, flags={}),
            SurfaceEstimate(lambda_surface=1.05, confidence=0.7, excitation=0.7, flags={}),
        )
        lam, conf = aggregate_wheel_lambdas(estimates)
        assert lam is not None
        assert 1.0 < lam < 1.15

    def test_all_none_returns_none(self):
        estimates = tuple(
            SurfaceEstimate(lambda_surface=None, confidence=0.0, excitation=0.0, flags={})
            for _ in range(4)
        )
        lam, conf = aggregate_wheel_lambdas(estimates)
        assert lam is None
        assert conf == 0.0


# ── Integration: full pipeline ───────────────────────────────


class TestIntegration:
    def test_round_trip_with_known_surface(self):
        """Generate forces at lambda=1.15, then recover lambda from the inverse."""
        params = _default_params()
        true_lambda = 1.15

        # Simulate: tire produces forces, road scales them
        inp = _make_tire_input(alpha=0.07, kappa=-0.04, fz=4500.0, vx=35.0)
        pred = predict_tire_forces(inp, params)
        fx_obs = pred.fx * true_lambda
        fy_obs = pred.fy * true_lambda

        est = solve_lambda_surface(
            fx_obs=fx_obs, fy_obs=fy_obs,
            tire_input=inp, tire_params=params,
        )
        assert est.lambda_surface is not None
        assert abs(est.lambda_surface - true_lambda) < 0.03
        assert est.confidence > 0.3

    def test_different_loads_same_lambda(self):
        """Same surface at different loads should give similar lambda."""
        params = _default_params()
        true_lambda = 1.10

        lambdas = []
        for fz in [3000.0, 4500.0, 6000.0]:
            inp = _make_tire_input(alpha=0.06, fz=fz, vx=30.0)
            pred = predict_tire_forces(inp, params)
            est = solve_lambda_surface(
                fx_obs=pred.fx * true_lambda,
                fy_obs=pred.fy * true_lambda,
                tire_input=inp, tire_params=params,
            )
            if est.lambda_surface is not None:
                lambdas.append(est.lambda_surface)

        assert len(lambdas) >= 2
        # All recovered lambdas should be within 10% of each other
        assert max(lambdas) - min(lambdas) < 0.15
