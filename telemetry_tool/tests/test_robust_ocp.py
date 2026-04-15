"""Tests for robust_ocp.py — uncertainty-aware OCP grip policy."""
from __future__ import annotations

import numpy as np
import pytest

from track_surface.condition_bucketing import (
    BucketKey,
    BucketedSurfaceField,
    BucketQueryResult,
    TRANSITION_BUCKET,
)
from track_surface.robust_ocp import (
    GripPolicyPoint,
    ModeDiagnostics,
    PlannerMode,
    RobustGripConfig,
    build_grip_map_for_ocp,
    compare_modes,
    compute_mu_eff_single,
)
from track_surface.surface_field import SurfaceFieldConfig


def _make_query(mean=1.1, std=0.1, conf=0.5, depth=0) -> BucketQueryResult:
    return BucketQueryResult(
        mean=mean, std=std, confidence=conf,
        bucket_used=BucketKey("flat", "mid"),
        fallback_depth=depth, evidence_count=100,
    )


def _default_config() -> RobustGripConfig:
    return RobustGripConfig()


# ── Mode semantics ───────────────────────────────────────────


class TestNominalMode:
    def test_returns_mean(self):
        q = _make_query(mean=1.2)
        p = compute_mu_eff_single(q, PlannerMode.NOMINAL, _default_config())
        assert abs(p.mu_eff - 1.2) < 0.001
        assert p.mode_applied == "nominal"

    def test_floors_at_minimum(self):
        q = _make_query(mean=0.3)
        p = compute_mu_eff_single(q, PlannerMode.NOMINAL, _default_config())
        assert p.mu_eff >= 0.5  # mu_floor

    def test_always_trusted(self):
        q = _make_query(conf=0.01)
        p = compute_mu_eff_single(q, PlannerMode.NOMINAL, _default_config())
        assert p.is_trusted is True


class TestRobustMode:
    def test_less_than_nominal_with_uncertainty(self):
        q = _make_query(mean=1.1, std=0.15)
        nom = compute_mu_eff_single(q, PlannerMode.NOMINAL, _default_config())
        rob = compute_mu_eff_single(q, PlannerMode.ROBUST, _default_config())
        assert rob.mu_eff < nom.mu_eff

    def test_equals_nominal_with_zero_uncertainty(self):
        q = _make_query(mean=1.1, std=0.0, conf=0.9, depth=0)
        nom = compute_mu_eff_single(q, PlannerMode.NOMINAL, _default_config())
        rob = compute_mu_eff_single(q, PlannerMode.ROBUST, _default_config())
        assert abs(rob.mu_eff - nom.mu_eff) < 0.01

    def test_fallback_depth_increases_penalty(self):
        q0 = _make_query(mean=1.1, std=0.1, depth=0)
        q2 = _make_query(mean=1.1, std=0.1, depth=2)
        r0 = compute_mu_eff_single(q0, PlannerMode.ROBUST, _default_config())
        r2 = compute_mu_eff_single(q2, PlannerMode.ROBUST, _default_config())
        assert r2.mu_eff < r0.mu_eff  # deeper fallback = more conservative

    def test_floors_at_minimum(self):
        q = _make_query(mean=0.6, std=0.5)
        r = compute_mu_eff_single(q, PlannerMode.ROBUST, _default_config())
        assert r.mu_eff >= 0.5

    def test_boundary_tightened_for_deep_fallback(self):
        q = _make_query(conf=0.05, depth=2)
        r = compute_mu_eff_single(q, PlannerMode.ROBUST, _default_config())
        assert r.boundary_scale < 1.0

    def test_not_trusted(self):
        q = _make_query()
        r = compute_mu_eff_single(q, PlannerMode.ROBUST, _default_config())
        assert r.is_trusted is False


class TestExploitableMode:
    def test_trusted_when_conditions_met(self):
        q = _make_query(mean=1.15, std=0.05, conf=0.8, depth=0)
        e = compute_mu_eff_single(q, PlannerMode.EXPLOITABLE, _default_config())
        assert e.is_trusted is True
        assert e.mode_applied == "exploitable_trusted"
        assert abs(e.mu_eff - 1.15) < 0.01

    def test_degrades_when_low_confidence(self):
        q = _make_query(mean=1.15, std=0.05, conf=0.1, depth=0)
        e = compute_mu_eff_single(q, PlannerMode.EXPLOITABLE, _default_config())
        assert e.is_trusted is False
        assert e.mode_applied == "exploitable_degraded"
        assert e.mu_eff < 1.15  # some penalty applied

    def test_degrades_when_high_std(self):
        q = _make_query(mean=1.15, std=0.3, conf=0.8, depth=0)
        e = compute_mu_eff_single(q, PlannerMode.EXPLOITABLE, _default_config())
        assert e.is_trusted is False

    def test_degrades_when_deep_fallback(self):
        q = _make_query(mean=1.15, std=0.05, conf=0.8, depth=1)
        e = compute_mu_eff_single(q, PlannerMode.EXPLOITABLE, _default_config())
        assert e.is_trusted is False

    def test_never_exceeds_mean(self):
        """Exploitable must NEVER produce mu_eff > mu_mean."""
        q = _make_query(mean=1.2, std=0.05, conf=0.95, depth=0)
        e = compute_mu_eff_single(q, PlannerMode.EXPLOITABLE, _default_config())
        assert e.mu_eff <= q.mean + 0.001


class TestOrderingInvariant:
    """robust_mu <= nominal_mu for all uncertainty > 0."""

    def test_robust_le_nominal(self):
        for std in [0.05, 0.1, 0.2, 0.3]:
            for depth in [0, 1, 2]:
                q = _make_query(mean=1.1, std=std, conf=0.5, depth=depth)
                nom = compute_mu_eff_single(q, PlannerMode.NOMINAL, _default_config())
                rob = compute_mu_eff_single(q, PlannerMode.ROBUST, _default_config())
                assert rob.mu_eff <= nom.mu_eff + 0.001, (
                    f"Robust ({rob.mu_eff:.3f}) > Nominal ({nom.mu_eff:.3f}) "
                    f"at std={std}, depth={depth}"
                )

    def test_exploitable_le_nominal(self):
        """Exploitable never exceeds nominal."""
        for conf in [0.1, 0.5, 0.9]:
            q = _make_query(mean=1.1, std=0.1, conf=conf, depth=0)
            nom = compute_mu_eff_single(q, PlannerMode.NOMINAL, _default_config())
            exp = compute_mu_eff_single(q, PlannerMode.EXPLOITABLE, _default_config())
            assert exp.mu_eff <= nom.mu_eff + 0.001


# ── Local uncertainty response ───────────────────────────────


class TestLocalResponse:
    def test_uncertain_sector_penalised_more(self):
        q_certain = _make_query(mean=1.1, std=0.05, conf=0.9, depth=0)
        q_uncertain = _make_query(mean=1.1, std=0.25, conf=0.1, depth=2)
        r_certain = compute_mu_eff_single(q_certain, PlannerMode.ROBUST, _default_config())
        r_uncertain = compute_mu_eff_single(q_uncertain, PlannerMode.ROBUST, _default_config())
        assert r_uncertain.mu_eff < r_certain.mu_eff


# ── Transition exclusion ─────────────────────────────────────


class TestTransitionExclusion:
    def test_transition_gets_floor(self):
        bf = _make_bucketed_field()
        s_grid = np.array([50.0])
        keys = np.array([TRANSITION_BUCKET], dtype=object)
        mu, bnd, details = build_grip_map_for_ocp(
            bucketed_field=bf, s_grid=s_grid,
            bucket_keys_per_s=keys, mode=PlannerMode.NOMINAL,
        )
        assert mu[0] == 0.5  # floor
        assert details[0].mode_applied == "transition_excluded"
        assert details[0].is_trusted is False


# ── Batch integration ────────────────────────────────────────


def _make_bucketed_field() -> BucketedSurfaceField:
    s_bins = np.arange(0, 210, 10.0)
    n_bins = np.arange(-5, 6, 1.0)
    bf = BucketedSurfaceField(s_bins, n_bins)
    # Feed some data into flat/mid bucket
    N = 200
    keys = np.array([BucketKey("flat", "mid")] * N, dtype=object)
    bf.update(
        np.linspace(10, 190, N), np.zeros(N),
        np.full(N, 1.15), np.full(N, 0.8), keys,
    )
    bf.apply_spatial_smoothing()
    return bf


class TestBatchBuild:
    def test_produces_valid_array(self):
        bf = _make_bucketed_field()
        s_grid = np.linspace(10, 190, 20)
        keys = np.array([BucketKey("flat", "mid")] * 20, dtype=object)
        mu, bnd, details = build_grip_map_for_ocp(
            bucketed_field=bf, s_grid=s_grid,
            bucket_keys_per_s=keys, mode=PlannerMode.NOMINAL,
        )
        assert len(mu) == 20
        assert all(np.isfinite(mu))
        assert all(m >= 0.5 for m in mu)

    def test_robust_produces_lower_mu(self):
        bf = _make_bucketed_field()
        s_grid = np.linspace(10, 190, 20)
        keys = np.array([BucketKey("flat", "mid")] * 20, dtype=object)
        nom_mu, _, _ = build_grip_map_for_ocp(
            bucketed_field=bf, s_grid=s_grid,
            bucket_keys_per_s=keys, mode=PlannerMode.NOMINAL,
        )
        rob_mu, _, _ = build_grip_map_for_ocp(
            bucketed_field=bf, s_grid=s_grid,
            bucket_keys_per_s=keys, mode=PlannerMode.ROBUST,
        )
        assert rob_mu.mean() <= nom_mu.mean()


class TestCompareModes:
    def test_diagnostics_structure(self):
        bf = _make_bucketed_field()
        s_grid = np.linspace(10, 190, 20)
        keys = np.array([BucketKey("flat", "mid")] * 20, dtype=object)
        diag = compare_modes(bf, s_grid, keys)
        assert isinstance(diag, ModeDiagnostics)
        assert diag.nominal_mean_mu >= diag.robust_mean_mu
        assert diag.n_transition_excluded == 0  # no transitions in this test
