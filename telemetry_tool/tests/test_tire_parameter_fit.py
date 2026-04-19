"""Tests for tire_parameter_fit.py — lateral D scale fitting."""
from __future__ import annotations

import numpy as np
import pytest

from track_surface.tire_parameter_fit import (
    CurationConfig,
    CurationResult,
    curate_calibration_set,
    fit_lateral_d_scale,
    apply_d_scale,
)


def _make_curate_inputs(n: int = 500, **overrides):
    defaults = dict(
        bank_rad=np.zeros(n),
        bank_gradient=np.zeros(n),
        a_lat_tire=np.full(n, 5.0),
        speed=np.full(n, 30.0),
        beta_quality=np.full(n, 0.5),
        road_quality=np.full(n, 0.8),
        fz_per_wheel=np.full((n, 4), 3000.0),
        alpha_per_wheel=np.full((n, 4), 0.06),
        transition_mask=np.zeros(n, dtype=bool),
    )
    defaults.update(overrides)
    return defaults


class TestCuration:
    def test_all_good_samples_pass(self):
        inputs = _make_curate_inputs()
        result = curate_calibration_set(**inputs)
        assert result.n_selected == result.n_total

    def test_high_bank_excluded(self):
        inputs = _make_curate_inputs(bank_rad=np.full(500, 0.3))
        result = curate_calibration_set(**inputs)
        assert result.n_selected == 0
        assert result.exclusion_reasons.get("high_bank", 0) > 0

    def test_low_excitation_excluded(self):
        inputs = _make_curate_inputs(a_lat_tire=np.full(500, 1.0))
        result = curate_calibration_set(**inputs)
        assert result.n_selected == 0

    def test_quarantined_excluded(self):
        inputs = _make_curate_inputs(transition_mask=np.ones(500, dtype=bool))
        result = curate_calibration_set(**inputs)
        assert result.n_selected == 0

    def test_mixed_quality(self):
        """Some good, some bad → only good pass."""
        n = 200
        bank = np.concatenate([np.zeros(100), np.full(100, 0.4)])  # first half flat
        inputs = _make_curate_inputs(n=n, bank_rad=bank)
        result = curate_calibration_set(**inputs)
        assert result.n_selected == 100  # only flat half passes

    def test_reason_codes_populated(self):
        inputs = _make_curate_inputs(speed=np.full(500, 5.0))  # too slow
        result = curate_calibration_set(**inputs)
        assert "low_speed" in result.exclusion_reasons


class TestFitting:
    def test_fit_recovers_known_scale(self):
        """If lambda_raw clusters at 1.3, k_lat should be ~1.3."""
        n = 1000
        rng = np.random.default_rng(42)
        lam = 1.3 + rng.normal(0, 0.1, n)
        conf = np.full(n, 0.8)
        mask = np.ones(n, dtype=bool)
        laps = np.arange(n) % 20 + 1

        result = fit_lateral_d_scale(
            lambda_raw=lam, confidence=conf,
            curation_mask=mask, lap_numbers=laps,
        )
        assert abs(result.k_lat - 1.3) < 0.1
        assert result.train_median_lambda_after < 1.15  # closer to 1.0

    def test_fit_near_one_when_lambda_is_one(self):
        """If lambda already at 1.0, k_lat ≈ 1.0."""
        n = 500
        rng = np.random.default_rng(42)
        lam = 1.0 + rng.normal(0, 0.05, n)
        conf = np.full(n, 0.9)
        mask = np.ones(n, dtype=bool)
        laps = np.arange(n) % 10 + 1

        result = fit_lateral_d_scale(
            lambda_raw=lam, confidence=conf,
            curation_mask=mask, lap_numbers=laps,
        )
        assert abs(result.k_lat - 1.0) < 0.1

    def test_validation_not_overfit(self):
        """Train and validation medians should be similar."""
        n = 2000
        rng = np.random.default_rng(42)
        lam = 1.5 + rng.normal(0, 0.15, n)
        conf = np.full(n, 0.7)
        mask = np.ones(n, dtype=bool)
        laps = np.arange(n) % 30 + 1

        result = fit_lateral_d_scale(
            lambda_raw=lam, confidence=conf,
            curation_mask=mask, lap_numbers=laps,
        )
        # Train and val should agree within 10%
        assert abs(result.train_median_lambda_after - result.validation_median_lambda_after) < 0.15

    def test_robust_to_outliers(self):
        """Outliers should not dominate the fit."""
        n = 500
        rng = np.random.default_rng(42)
        lam = np.concatenate([
            1.2 + rng.normal(0, 0.08, 400),  # core
            5.0 + rng.normal(0, 0.5, 100),    # outliers
        ])
        conf = np.full(n, 0.7)
        mask = np.ones(n, dtype=bool)
        laps = np.arange(n) % 10 + 1

        result = fit_lateral_d_scale(
            lambda_raw=lam, confidence=conf,
            curation_mask=mask, lap_numbers=laps,
        )
        # Should fit to the core (~1.2), not the outliers
        assert abs(result.k_lat - 1.2) < 0.2

    def test_insufficient_samples_returns_safe_default(self):
        lam = np.array([1.3, 1.2])
        conf = np.array([0.8, 0.8])
        mask = np.array([True, True])
        laps = np.array([1, 2])

        result = fit_lateral_d_scale(
            lambda_raw=lam, confidence=conf,
            curation_mask=mask, lap_numbers=laps,
        )
        # Should return something safe, not crash
        assert result.k_lat > 0

    def test_residual_after_less_than_before(self):
        n = 1000
        rng = np.random.default_rng(42)
        lam = 1.4 + rng.normal(0, 0.12, n)
        conf = np.full(n, 0.8)
        mask = np.ones(n, dtype=bool)
        laps = np.arange(n) % 15 + 1

        result = fit_lateral_d_scale(
            lambda_raw=lam, confidence=conf,
            curation_mask=mask, lap_numbers=laps,
        )
        assert result.residual_after < result.residual_before


class TestApplyScale:
    def test_apply_d_scale(self):
        assert abs(apply_d_scale(2.8, 1.3) - 3.64) < 0.01

    def test_identity(self):
        assert abs(apply_d_scale(2.8, 1.0) - 2.8) < 0.001
