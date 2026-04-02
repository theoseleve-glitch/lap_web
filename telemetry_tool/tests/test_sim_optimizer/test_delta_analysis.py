"""Tests for distance-aligned delta analysis."""
import numpy as np
import pytest

from telemetry_tool.sim_optimizer.analysis.delta import LapDelta, compute_lap_delta

# ---------------------------------------------------------------------------
# Helpers — synthetic data
# ---------------------------------------------------------------------------

def _make_traces(
    n: int = 501,
    ds: float = 1.0,
    theo_speed: float = 20.0,
    actual_speed: float | None = None,
):
    """Return kwargs for compute_lap_delta with uniform traces."""
    if actual_speed is None:
        actual_speed = theo_speed
    distance = np.arange(0, n * ds, ds)
    zeros = np.zeros(n)
    return dict(
        actual_distance_m=distance,
        actual_speed_mps=np.full(n, actual_speed),
        actual_throttle=zeros,
        actual_brake=zeros,
        actual_steering_deg=zeros,
        theoretical_distance_m=distance,
        theoretical_speed_mps=np.full(n, theo_speed),
        theoretical_throttle=zeros,
        theoretical_brake=zeros,
        theoretical_steering_deg=zeros,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestLapDelta:
    def test_identical_laps_zero_delta(self):
        """Actual == theoretical -> time_delta ~0, total_loss ~0."""
        delta = compute_lap_delta(**_make_traces(theo_speed=20.0, actual_speed=20.0))
        assert abs(delta.total_time_loss_s) < 1e-9
        np.testing.assert_allclose(delta.time_delta_s, 0.0, atol=1e-9)

    def test_slower_actual_positive_delta(self):
        """Actual 10 % slower -> positive total_time_loss."""
        delta = compute_lap_delta(**_make_traces(theo_speed=20.0, actual_speed=18.0))
        assert delta.total_time_loss_s > 0.0
        # Rough check: 500 m at 18 vs 20 m/s => ~2.78 s loss
        assert delta.total_time_loss_s > 2.0

    def test_faster_actual_negative_delta(self):
        """Actual 10 % faster -> negative total_time_loss."""
        delta = compute_lap_delta(**_make_traces(theo_speed=20.0, actual_speed=22.0))
        assert delta.total_time_loss_s < 0.0

    def test_speed_delta_sign(self):
        """When actual is slower, speed_delta (theo - actual) > 0."""
        delta = compute_lap_delta(**_make_traces(theo_speed=20.0, actual_speed=18.0))
        assert np.all(delta.speed_delta_mps > 0.0)

    def test_arrays_same_length(self):
        """All output arrays must share the same length."""
        delta = compute_lap_delta(**_make_traces(theo_speed=20.0, actual_speed=18.0))
        n = len(delta.distance_m)
        assert len(delta.time_delta_s) == n
        assert len(delta.speed_delta_mps) == n
        assert len(delta.throttle_delta_pct) == n
        assert len(delta.brake_delta_pct) == n
        assert len(delta.steering_delta_deg) == n
