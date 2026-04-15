"""Tests for surface_field.py — Bayesian spatial lambda field."""
from __future__ import annotations

import numpy as np
import pytest

from track_surface.surface_field import SurfaceField, SurfaceFieldConfig


def _make_field(M: int = 50, K: int = 20, ds: float = 10.0, dn: float = 1.0) -> SurfaceField:
    s_bins = np.arange(0, M * ds + ds, ds)
    n_bins = np.arange(-K * dn / 2, K * dn / 2 + dn, dn)
    return SurfaceField(s_bins, n_bins)


# ── Prior initialization ─────────────────────────────────────


class TestPrior:
    def test_initial_mean_is_prior(self):
        f = _make_field()
        assert np.allclose(f.mean, 1.0)

    def test_initial_confidence_is_zero(self):
        f = _make_field()
        # No observations → variance = prior_std² → confidence ≈ 0
        assert np.allclose(f.confidence_map, 0.0, atol=0.01)

    def test_initial_n_obs_is_zero(self):
        f = _make_field()
        assert np.all(f.n_obs == 0)


# ── Single-cell Kalman update ────────────────────────────────


class TestCellUpdate:
    def test_single_observation_shifts_mean(self):
        f = _make_field()
        f.update_cell(s=50.0, n=0.0, lambda_obs=1.3, obs_variance=0.04,
                       confidence=0.8)
        si, ni = f._cell_index(50.0, 0.0)
        # Mean should shift toward 1.3 from prior of 1.0
        assert f.mean[si, ni] > 1.0
        assert f.mean[si, ni] < 1.3  # not fully — blended with prior

    def test_multiple_observations_converge(self):
        f = _make_field()
        for _ in range(20):
            f.update_cell(s=50.0, n=0.0, lambda_obs=1.2, obs_variance=0.04,
                           confidence=0.9)
        si, ni = f._cell_index(50.0, 0.0)
        # After many observations, should converge close to 1.2
        assert abs(f.mean[si, ni] - 1.2) < 0.05

    def test_variance_shrinks_with_observations(self):
        f = _make_field()
        si, ni = f._cell_index(50.0, 0.0)
        var_before = f.variance[si, ni]
        f.update_cell(s=50.0, n=0.0, lambda_obs=1.1, obs_variance=0.04,
                       confidence=0.8)
        assert f.variance[si, ni] < var_before

    def test_low_confidence_has_little_effect(self):
        f = _make_field()
        si, ni = f._cell_index(50.0, 0.0)
        mean_before = f.mean[si, ni]
        f.update_cell(s=50.0, n=0.0, lambda_obs=1.5, obs_variance=0.04,
                       confidence=0.05)  # below threshold
        # Should not have changed (below min_confidence)
        assert f.mean[si, ni] == mean_before

    def test_high_confidence_large_shift(self):
        f = _make_field()
        si, ni = f._cell_index(50.0, 0.0)
        f.update_cell(s=50.0, n=0.0, lambda_obs=1.3, obs_variance=0.01,
                       confidence=1.0)
        # High confidence + low obs_variance → large shift toward 1.3
        assert f.mean[si, ni] > 1.15


# ── Batch update ─────────────────────────────────────────────


class TestBatchUpdate:
    def test_batch_updates_multiple_cells(self):
        f = _make_field()
        s = np.array([50.0, 100.0, 150.0])
        n = np.array([0.0, 2.0, -1.0])
        lam = np.array([1.1, 1.2, 1.3])
        conf = np.array([0.8, 0.7, 0.9])
        updated = f.update_batch(s, n, lam, conf)
        assert updated == 3
        assert f.n_obs.sum() == 3

    def test_batch_skips_nan_lambda(self):
        f = _make_field()
        s = np.array([50.0, 100.0])
        n = np.array([0.0, 0.0])
        lam = np.array([1.1, np.nan])
        conf = np.array([0.8, 0.8])
        updated = f.update_batch(s, n, lam, conf)
        assert updated == 1

    def test_batch_skips_low_confidence(self):
        f = _make_field()
        s = np.array([50.0, 100.0])
        n = np.array([0.0, 0.0])
        lam = np.array([1.1, 1.2])
        conf = np.array([0.8, 0.05])  # second below threshold
        updated = f.update_batch(s, n, lam, conf)
        assert updated == 1


# ── Variance decay ───────────────────────────────────────────


class TestVarianceDecay:
    def test_decay_increases_variance(self):
        f = _make_field()
        si, ni = f._cell_index(50.0, 0.0)
        # First observe to reduce variance
        f.update_cell(s=50.0, n=0.0, lambda_obs=1.1, obs_variance=0.04,
                       confidence=0.8)
        var_after_obs = f.variance[si, ni]
        # Decay
        f.decay_variance(n_samples_elapsed=1000)
        assert f.variance[si, ni] > var_after_obs

    def test_decay_does_not_exceed_prior(self):
        f = _make_field()
        prior_var = f.config.prior_std ** 2
        f.decay_variance(n_samples_elapsed=100000)
        assert np.all(f.variance <= prior_var + 1e-9)


# ── Spatial smoothing ────────────────────────────────────────


class TestSpatialSmoothing:
    def test_smoothing_spreads_information(self):
        f = _make_field(M=20, K=10)
        # Observe one cell strongly
        for _ in range(10):
            f.update_cell(s=50.0, n=0.0, lambda_obs=1.3, obs_variance=0.02,
                           confidence=0.9)

        si, ni = f._cell_index(50.0, 0.0)
        neighbor_si = min(si + 1, f.M - 1)

        mean_before_smooth = f.mean[neighbor_si, ni]
        f.apply_spatial_smoothing()
        mean_after_smooth = f.mean[neighbor_si, ni]

        # Neighbor should have shifted toward the observed cell's value
        assert mean_after_smooth > mean_before_smooth

    def test_well_observed_cell_not_diluted(self):
        f = _make_field(M=20, K=10)
        # Heavily observe one cell
        for _ in range(50):
            f.update_cell(s=50.0, n=0.0, lambda_obs=1.25, obs_variance=0.02,
                           confidence=0.95)

        si, ni = f._cell_index(50.0, 0.0)
        mean_before = f.mean[si, ni]
        f.apply_spatial_smoothing()
        mean_after = f.mean[si, ni]

        # Well-observed cell should barely change
        assert abs(mean_after - mean_before) < 0.03


# ── Query ────────────────────────────────────────────────────


class TestQuery:
    def test_query_returns_prior_when_unobserved(self):
        f = _make_field()
        mean, std, conf = f.query(50.0, 0.0)
        assert abs(mean - 1.0) < 0.01
        assert std > 0.2
        assert conf < 0.05

    def test_query_reflects_observation(self):
        f = _make_field()
        for _ in range(10):
            f.update_cell(s=50.0, n=0.0, lambda_obs=1.15, obs_variance=0.03,
                           confidence=0.8)
        mean, std, conf = f.query(50.0, 0.0)
        assert abs(mean - 1.15) < 0.10
        assert std < 0.2  # lower than prior
        assert conf > 0.3

    def test_batch_query(self):
        f = _make_field()
        s = np.array([10.0, 50.0, 100.0])
        n = np.array([0.0, 0.0, 0.0])
        means, stds, confs = f.query_batch(s, n)
        assert len(means) == 3
        assert all(np.isfinite(means))


# ── Export ───────────────────────────────────────────────────


class TestExport:
    def test_export_has_required_keys(self):
        f = _make_field(M=10, K=5)
        d = f.to_export_dict()
        assert "mean" in d
        assert "std" in d
        assert "confidence" in d
        assert "summary" in d
        assert d["summary"]["cells_total"] == 10 * 5

    def test_summary_after_observations(self):
        f = _make_field(M=10, K=5)
        f.update_cell(s=5.0, n=0.0, lambda_obs=1.1, obs_variance=0.04, confidence=0.8)
        f.update_cell(s=15.0, n=1.0, lambda_obs=1.2, obs_variance=0.04, confidence=0.7)
        s = f.summary()
        assert s["cells_observed"] == 2
        assert s["coverage_pct"] > 0
