"""Tests for condition_bucketing.py."""
from __future__ import annotations

import numpy as np
import pytest

from track_surface.condition_bucketing import (
    ACTIVE_BUCKETS,
    TRANSITION_BUCKET,
    BucketKey,
    BucketQueryResult,
    BucketedSurfaceField,
    assign_bucket_keys,
    classify_section_regime,
    classify_stint_phase,
)


# ── Regime classification ────────────────────────────────────


class TestSectionRegime:
    def test_flat_below_threshold(self):
        bank = np.array([0.01, -0.02, 0.04])
        trans = np.zeros(3, dtype=bool)
        regime = classify_section_regime(bank, trans)
        assert all(r == "flat" for r in regime)

    def test_banked_above_threshold(self):
        bank = np.array([0.3, -0.2, 0.5])
        trans = np.zeros(3, dtype=bool)
        regime = classify_section_regime(bank, trans)
        assert all(r == "banked" for r in regime)

    def test_transition_overrides(self):
        bank = np.array([0.01, 0.5])  # first flat, second banked
        trans = np.array([True, True])
        regime = classify_section_regime(bank, trans)
        assert all(r == "transition" for r in regime)

    def test_mixed(self):
        bank = np.array([0.01, 0.3, 0.05])
        trans = np.array([False, False, True])
        regime = classify_section_regime(bank, trans)
        assert regime[0] == "flat"
        assert regime[1] == "banked"
        assert regime[2] == "transition"


class TestStintPhase:
    def test_early_laps(self):
        laps = np.array([1, 2, 3, 4, 5])
        phase = classify_stint_phase(laps)
        assert all(p == "early" for p in phase)

    def test_mid_laps(self):
        laps = np.array([10, 20, 30])
        phase = classify_stint_phase(laps)
        assert all(p == "mid" for p in phase)

    def test_late_laps(self):
        laps = np.array([51, 60, 70])
        phase = classify_stint_phase(laps)
        assert all(p == "late" for p in phase)


class TestBucketKeyAssignment:
    def test_assigns_correct_keys(self):
        bank = np.array([0.01, 0.3, 0.01])
        trans = np.zeros(3, dtype=bool)
        laps = np.array([3, 25, 55])
        keys = assign_bucket_keys(bank, trans, laps)
        assert keys[0] == BucketKey("flat", "early")
        assert keys[1] == BucketKey("banked", "mid")
        assert keys[2] == BucketKey("flat", "late")

    def test_transition_gets_special_key(self):
        bank = np.array([0.01])
        trans = np.array([True])
        laps = np.array([10])
        keys = assign_bucket_keys(bank, trans, laps)
        assert keys[0] == TRANSITION_BUCKET


# ── Bucketed field ───────────────────────────────────────────


def _make_field(M=20, K=10, ds=10.0, dn=2.0) -> BucketedSurfaceField:
    s_bins = np.arange(0, M * ds + ds, ds)
    n_bins = np.arange(-K * dn / 2, K * dn / 2 + dn, dn)
    return BucketedSurfaceField(s_bins, n_bins)


class TestUpdate:
    def test_updates_only_correct_bucket(self):
        bf = _make_field()
        N = 100
        s = np.full(N, 50.0)
        n = np.full(N, 0.0)
        lam = np.full(N, 1.1)
        conf = np.full(N, 0.8)
        keys = np.array([BucketKey("flat", "mid")] * N, dtype=object)

        counts = bf.update(s, n, lam, conf, keys)
        assert counts[BucketKey("flat", "mid")] > 0
        assert counts[BucketKey("banked", "mid")] == 0
        assert counts[BucketKey("flat", "early")] == 0

    def test_transition_samples_dropped(self):
        bf = _make_field()
        N = 50
        keys = np.array([TRANSITION_BUCKET] * N, dtype=object)
        counts = bf.update(
            np.full(N, 50.0), np.full(N, 0.0),
            np.full(N, 1.2), np.full(N, 0.8), keys,
        )
        # No active bucket should get updates
        for key in ACTIVE_BUCKETS:
            assert counts[key] == 0

    def test_mixed_buckets_routed_correctly(self):
        bf = _make_field()
        s = np.array([50.0, 50.0, 50.0])
        n = np.array([0.0, 0.0, 0.0])
        lam = np.array([1.1, 1.2, 1.3])
        conf = np.array([0.8, 0.8, 0.8])
        keys = np.array([
            BucketKey("flat", "mid"),
            BucketKey("banked", "mid"),
            BucketKey("flat", "early"),
        ], dtype=object)

        counts = bf.update(s, n, lam, conf, keys)
        assert counts[BucketKey("flat", "mid")] == 1
        assert counts[BucketKey("banked", "mid")] == 1
        assert counts[BucketKey("flat", "early")] == 1


class TestNoContamination:
    def test_flat_banked_independent(self):
        """Data in flat bucket must not appear in banked bucket."""
        bf = _make_field()
        N = 200
        s = np.full(N, 50.0)
        n = np.full(N, 0.0)

        # Put lambda=1.5 into flat/mid
        flat_keys = np.array([BucketKey("flat", "mid")] * N, dtype=object)
        bf.update(s, n, np.full(N, 1.5), np.full(N, 0.9), flat_keys)

        # Query banked/mid at same location — should be at prior (1.0), not 1.5
        result = bf.query(50.0, 0.0, BucketKey("banked", "mid"))
        assert result.mean < 1.2  # should be near prior, not near 1.5


# ── Fallback hierarchy ───────────────────────────────────────


class TestFallback:
    def test_exact_hit_depth_zero(self):
        bf = _make_field()
        N = 100
        s = np.full(N, 50.0)
        n = np.full(N, 0.0)
        keys = np.array([BucketKey("flat", "mid")] * N, dtype=object)
        bf.update(s, n, np.full(N, 1.15), np.full(N, 0.9), keys)
        bf.apply_spatial_smoothing()

        result = bf.query(50.0, 0.0, BucketKey("flat", "mid"))
        assert result.fallback_depth == 0
        assert result.confidence > 0.01

    def test_section_fallback_depth_one(self):
        bf = _make_field()
        N = 100
        s = np.full(N, 50.0)
        n = np.full(N, 0.0)
        # Only mid data, query early (same section)
        keys = np.array([BucketKey("flat", "mid")] * N, dtype=object)
        bf.update(s, n, np.full(N, 1.2), np.full(N, 0.9), keys)
        bf.apply_spatial_smoothing()

        result = bf.query(50.0, 0.0, BucketKey("flat", "early"))
        # Should fall back to section-merged (depth 1)
        assert result.fallback_depth <= 1
        assert result.bucket_used.stint_phase in ("merged", "mid", "early")

    def test_global_fallback_depth_two(self):
        bf = _make_field()
        # No updates at all
        result = bf.query(50.0, 0.0, BucketKey("banked", "late"))
        assert result.fallback_depth == 2
        assert result.confidence == 0.0
        assert abs(result.mean - 1.0) < 0.01  # global prior

    def test_fallback_reports_bucket_used(self):
        bf = _make_field()
        result = bf.query(50.0, 0.0, BucketKey("flat", "mid"))
        assert result.bucket_used is not None
        assert isinstance(result.bucket_used, BucketKey)


# ── Sparse-data behavior ────────────────────────────────────


class TestSparseBehavior:
    def test_sparse_bucket_low_confidence(self):
        bf = _make_field()
        # Feed only 2 samples — not enough for real confidence
        keys = np.array([BucketKey("flat", "mid")] * 2, dtype=object)
        bf.update(
            np.array([50.0, 60.0]), np.array([0.0, 0.0]),
            np.array([1.3, 1.2]), np.array([0.3, 0.3]), keys,
        )
        result = bf.query(50.0, 0.0, BucketKey("flat", "mid"))
        # Should have low confidence due to sparse data
        assert result.confidence < 0.5

    def test_well_observed_bucket_high_confidence(self):
        bf = _make_field()
        N = 500
        keys = np.array([BucketKey("flat", "mid")] * N, dtype=object)
        bf.update(
            np.full(N, 50.0), np.full(N, 0.0),
            np.full(N, 1.1), np.full(N, 0.9), keys,
        )
        bf.apply_spatial_smoothing()
        result = bf.query(50.0, 0.0, BucketKey("flat", "mid"))
        assert result.confidence > 0.05  # well-observed cell should have nonzero confidence
        assert result.fallback_depth == 0  # exact hit, not fallback


# ── Diagnostics ──────────────────────────────────────────────


class TestDiagnostics:
    def test_summary_has_all_buckets(self):
        bf = _make_field()
        s = bf.summary()
        for key in ACTIVE_BUCKETS:
            assert str(key) in s

    def test_diagnostics_empty_when_no_data(self):
        bf = _make_field()
        d = bf.diagnostics()
        for key in ACTIVE_BUCKETS:
            assert d[str(key)]["n_cells"] == 0

    def test_diagnostics_reflect_updates(self):
        bf = _make_field()
        N = 100
        keys = np.array([BucketKey("flat", "mid")] * N, dtype=object)
        bf.update(
            np.full(N, 50.0), np.full(N, 0.0),
            np.full(N, 1.15), np.full(N, 0.9), keys,
        )
        d = bf.diagnostics()
        assert d["flat/mid"]["n_cells"] > 0
        assert d["flat/mid"]["lambda_mean"] is not None
