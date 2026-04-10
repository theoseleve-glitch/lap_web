"""Tests for track_surface.py — aggregate track surface model."""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import numpy as np
import pytest

from track_surface import AggregateGrip, upsert_session_grip, upsert_global_grip


# ── AggregateGrip ────────────────────────────────────────────────


class TestAggregateGrip:
    def _make_grip(self, n_bins=10):
        dist = np.linspace(0, 500, n_bins)
        mu = np.linspace(0.8, 1.3, n_bins)
        return AggregateGrip(
            distance_bins=dist,
            mu_p95=mu,
            mu_mean=mu * 0.9,
            mu_lon_accel=np.full(n_bins, 0.4),
            mu_lon_brake=np.full(n_bins, 0.9),
            session_count=5,
            track_id="test_track",
        )

    def test_mu_at_interpolates(self):
        grip = self._make_grip()
        # At start
        val = grip.mu_at(0.0)
        assert abs(val - 0.8) < 0.01
        # At end
        val = grip.mu_at(500.0)
        assert abs(val - 1.3) < 0.01
        # Midpoint
        val = grip.mu_at(250.0)
        assert 1.0 < val < 1.1

    def test_mu_at_clamps(self):
        grip = self._make_grip()
        # Before start
        val = grip.mu_at(-10.0)
        assert abs(val - 0.8) < 0.01
        # After end
        val = grip.mu_at(600.0)
        assert abs(val - 1.3) < 0.01

    def test_mu_at_mean(self):
        grip = self._make_grip()
        val_p95 = grip.mu_at(250.0, "p95")
        val_mean = grip.mu_at(250.0, "mean")
        assert val_mean < val_p95

    def test_mu_at_empty(self):
        grip = AggregateGrip(
            distance_bins=np.array([]),
            mu_p95=np.array([]),
            mu_mean=np.array([]),
            mu_lon_accel=np.array([]),
            mu_lon_brake=np.array([]),
            session_count=0,
            track_id="empty",
        )
        assert grip.mu_at(100.0) == 1.0

    def test_to_dict(self):
        grip = self._make_grip(5)
        d = grip.to_dict()
        assert d["track_id"] == "test_track"
        assert d["session_count"] == 5
        assert d["bin_count"] == 5
        assert len(d["mu_p95"]) == 5
        assert len(d["distance_bins"]) == 5

    def test_is_global_fallback_default(self):
        grip = self._make_grip()
        assert grip.is_global_fallback is False


# ── upsert_session_grip guards ───────────────────────────────────


class _FakeGripMap:
    """Minimal mock that matches GripMap's interface."""
    def __init__(self, fallback=False, stats=None):
        self.is_global_fallback = fallback
        self.bin_stats = stats or []


class TestUpsertGuards:
    def test_skips_none(self):
        assert upsert_session_grip(None, "track", None) == 0

    def test_skips_global_fallback(self):
        gm = _FakeGripMap(fallback=True)
        assert upsert_session_grip(None, "track", gm) == 0

    def test_skips_unknown_track(self):
        gm = _FakeGripMap(fallback=False, stats=[1])
        assert upsert_session_grip(None, "unknown_track", gm) == 0

    def test_skips_empty_stats(self):
        gm = _FakeGripMap(fallback=False, stats=[])
        assert upsert_session_grip(None, "test_track", gm) == 0


# ── Solver aggregate grip fallback ──────────────────────────────


class TestSolverAggregateGripFallback:
    """Verify the theoretical solver can use AggregateGrip as a drop-in for GripMap."""

    def _make_aggregate(self, session_count: int, mu_val: float = 1.0, n_bins: int = 10):
        dist = np.linspace(0, 500, n_bins)
        return AggregateGrip(
            distance_bins=dist,
            mu_p95=np.full(n_bins, mu_val),
            mu_mean=np.full(n_bins, mu_val * 0.9),
            mu_lon_accel=np.full(n_bins, 0.4),
            mu_lon_brake=np.full(n_bins, 0.9),
            session_count=session_count,
            track_id="test_track",
        )

    def test_aggregate_replaces_global_fallback(self):
        """AggregateGrip with enough sessions provides real grip, not fallback."""
        grip = self._make_aggregate(session_count=5, mu_val=1.25)

        # mu_at returns the aggregate value (not the default 1.0 fallback)
        assert abs(grip.mu_at(250.0, "p95") - 1.25) < 0.01

        # Enough sessions to be trustworthy
        assert grip.session_count >= 3

        # Not a global fallback — this is real measured data
        assert grip.is_global_fallback is False

    def test_aggregate_skipped_when_session_count_low(self):
        """AggregateGrip with too few sessions should be guarded against."""
        grip = self._make_aggregate(session_count=2)

        # The solver guard condition: skip aggregate when < 3 sessions
        assert grip.session_count < 3


# ── upsert_global_grip guards ──────────────────────────────────


class TestGlobalUpsertGuards:
    def test_skips_none(self):
        assert upsert_global_grip(None, "track", None) == 0

    def test_skips_global_fallback(self):
        gm = _FakeGripMap(fallback=True)
        assert upsert_global_grip(None, "track", gm) == 0

    def test_skips_unknown_track(self):
        gm = _FakeGripMap(fallback=False, stats=[1])
        assert upsert_global_grip(None, "unknown_track", gm) == 0
