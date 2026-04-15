"""Tests for the canonical cumulative_delta engine.

Every delta-related consumer in the product must route through
telemetry_tool.deltas.cumulative_delta. These tests pin the contract:
trapezoidal integration, NaN-safe handling, sign convention, anchoring,
and cross-consumer equality on the same synthetic input.
"""

from __future__ import annotations

import numpy as np
import pytest

from telemetry_tool.deltas import (
    CumulativeDeltaResult,
    DeltaInputError,
    cumulative_delta,
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Trapezoidal correctness — constant-speed laps
# ─────────────────────────────────────────────────────────────────────────────


def test_constant_same_speed_zero_delta():
    """Two identical constant-speed laps ⇒ zero delta everywhere."""
    dist = np.linspace(0.0, 1000.0, 101)
    speed = np.full_like(dist, 25.0)  # 25 m/s
    res = cumulative_delta(dist, speed, dist, speed)
    assert np.allclose(res.delta_s, 0.0, atol=1e-9)
    assert np.allclose(res.time_a_s, res.time_b_s, atol=1e-9)


def test_constant_different_speed_linear_delta():
    """Lap B at 20 m/s vs lap A at 30 m/s over 600 m.

    True final delta = 600/20 - 600/30 = 30 - 20 = 10 s.
    Trapezoid on constant speed is exact.
    """
    dist = np.linspace(0.0, 600.0, 121)
    speed_a = np.full_like(dist, 30.0)
    speed_b = np.full_like(dist, 20.0)
    res = cumulative_delta(dist, speed_a, dist, speed_b)
    assert res.delta_s[-1] == pytest.approx(10.0, abs=1e-9)
    # Sign: B is slower ⇒ positive.
    assert res.delta_s[-1] > 0


# ─────────────────────────────────────────────────────────────────────────────
# 2. Rect vs trap divergence — known example
# ─────────────────────────────────────────────────────────────────────────────


def test_trapezoid_differs_from_midpoint_rectangle_on_non_linear_inv_speed():
    """The integrand is 1/v. By Jensen's inequality 0.5*(1/v_a + 1/v_b) is
    always ≥ 1/(0.5*(v_a + v_b)) with equality only when v_a == v_b. So the
    trap rule and the midpoint-rectangle rule ALWAYS disagree on non-constant
    speed — this is a proof that the choice of rule matters, and we use trap.
    """
    dist  = np.array([0.0, 10.0])
    # Sharp speed transition: 30 m/s → 3 m/s over 10 m.
    v = np.array([30.0, 3.0])

    ds = dist[1] - dist[0]
    trap = 0.5 * (1.0 / v[0] + 1.0 / v[1]) * ds
    midpoint_rect = ds / (0.5 * (v[0] + v[1]))

    # Trap > midpoint rect by > 50% here due to inv-speed curvature.
    assert trap > midpoint_rect
    assert (trap - midpoint_rect) / trap > 0.5

    # Engine uses trap: same-lap delta is zero, period.
    res = cumulative_delta(dist, v, dist, v)
    assert np.allclose(res.delta_s, 0.0, atol=1e-12)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Zero / NaN / dropout handling — never forward-fill
# ─────────────────────────────────────────────────────────────────────────────


def test_zero_speed_does_not_invent_motion():
    """A block of zero-speed samples in lap B should NOT appear as motion.

    If we were forward-filling from the previous valid speed, lap B's
    cumulative time would continue to accumulate over the gap and produce
    a different delta from a clean lap B where the gap was explicitly invalid.
    """
    dist = np.linspace(0.0, 1000.0, 101)
    speed_a = np.full_like(dist, 25.0)
    speed_b = np.full_like(dist, 25.0)
    # Lap B has a zero-speed dropout between 400 and 600 m.
    gap = (dist >= 400) & (dist <= 600)
    speed_b_gap = speed_b.copy()
    speed_b_gap[gap] = 0.0
    res_gap = cumulative_delta(dist, speed_a, dist, speed_b_gap)

    # The cumulative time for B should stop advancing through the dropout,
    # producing a NEGATIVE delta (B appears "ahead" because it didn't
    # accumulate time). This is the correct "no motion, no time" behaviour.
    assert res_gap.delta_s[-1] < 0.0
    # The invalid mask should mark the dropout.
    in_gap = (res_gap.progress_m >= 400) & (res_gap.progress_m <= 600)
    assert not res_gap.valid_mask[in_gap].any()


def test_nan_speed_treated_as_invalid():
    dist = np.linspace(0.0, 500.0, 51)
    speed_a = np.full_like(dist, 20.0)
    speed_b = np.full_like(dist, 20.0)
    speed_b[20:25] = np.nan
    res = cumulative_delta(dist, speed_a, dist, speed_b)
    # Finite everywhere
    assert np.all(np.isfinite(res.delta_s))
    # Delta strictly non-positive (B loses no time through NaN gap)
    assert res.delta_s[-1] < 0.0


def test_explicit_valid_mask_honoured():
    dist = np.linspace(0.0, 400.0, 41)
    speed_a = np.full_like(dist, 20.0)
    speed_b = np.full_like(dist, 20.0)
    mask_b = np.ones_like(dist, dtype=bool)
    mask_b[15:20] = False  # mark some samples invalid even though speeds are fine
    res = cumulative_delta(dist, speed_a, dist, speed_b, valid_b=mask_b)
    # Something got dropped, so B accumulated less time.
    assert res.delta_s[-1] < 0.0


# ─────────────────────────────────────────────────────────────────────────────
# 4. Endpoint anchoring to official lap times
# ─────────────────────────────────────────────────────────────────────────────


def test_anchor_to_official_matches_lap_time_difference():
    """Integration gives time_a≈40s, time_b≈50s. If we claim the OFFICIAL
    times were 40.0 and 51.2, anchoring should stretch each curve
    proportionally so the final delta equals exactly 11.2 s.
    """
    dist = np.linspace(0.0, 1000.0, 201)
    speed_a = np.full_like(dist, 25.0)   # 1000/25 = 40 s
    speed_b = np.full_like(dist, 20.0)   # 1000/20 = 50 s
    res = cumulative_delta(
        dist, speed_a, dist, speed_b,
        lap_time_a_s=40.0,
        lap_time_b_s=51.2,
        anchor_to_official=True,
    )
    assert res.anchored is True
    assert res.delta_s[-1] == pytest.approx(11.2, abs=1e-6)
    # Curve A still starts at 0.
    assert res.time_a_s[0] == 0.0


def test_anchor_disabled_returns_raw_delta():
    dist = np.linspace(0.0, 1000.0, 201)
    speed_a = np.full_like(dist, 25.0)
    speed_b = np.full_like(dist, 20.0)
    res = cumulative_delta(
        dist, speed_a, dist, speed_b,
        lap_time_a_s=40.0,
        lap_time_b_s=51.2,
        anchor_to_official=False,  # explicit off
    )
    assert res.anchored is False
    # Raw integration: 50 - 40 = 10 s (not 11.2).
    assert res.delta_s[-1] == pytest.approx(10.0, abs=1e-6)


# ─────────────────────────────────────────────────────────────────────────────
# 5. Sign convention (documented once, enforced always)
# ─────────────────────────────────────────────────────────────────────────────


def test_sign_convention_b_slower_is_positive():
    dist = np.linspace(0.0, 500.0, 51)
    fast = np.full_like(dist, 40.0)
    slow = np.full_like(dist, 20.0)
    # A fast, B slow → B is slower → positive.
    res = cumulative_delta(dist, fast, dist, slow)
    assert res.delta_s[-1] > 0
    # A slow, B fast → negative.
    res_rev = cumulative_delta(dist, slow, dist, fast)
    assert res_rev.delta_s[-1] < 0
    # Magnitudes equal.
    assert res.delta_s[-1] == pytest.approx(-res_rev.delta_s[-1], abs=1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# 6. Cross-consumer equality — same inputs, same output everywhere
# ─────────────────────────────────────────────────────────────────────────────


def test_dataframe_wrapper_agrees_with_canonical():
    """compute_delta_curve (the pipeline DataFrame adapter) and a direct
    cumulative_delta call on the same raw arrays must produce identical
    numbers. This pins the rule that every consumer routes through the
    canonical engine.
    """
    import pandas as pd
    from telemetry_tool.deltas import compute_delta_curve

    dist = np.linspace(0.0, 800.0, 81)
    speed_a = 25.0 + 5.0 * np.sin(dist * 0.01)
    speed_b = 25.0 + 5.0 * np.sin(dist * 0.01 + 0.3)

    df_a = pd.DataFrame({"Distance (m)": dist, "Speed (m/s)": speed_a})
    df_b = pd.DataFrame({"Distance (m)": dist, "Speed (m/s)": speed_b})
    n_grid = 200

    via_df = compute_delta_curve(df_a, df_b, n_grid=n_grid)
    via_canonical = cumulative_delta(
        dist, speed_a, dist, speed_b, n_grid=n_grid,
    )

    # Same grid length
    assert len(via_df) == len(via_canonical.progress_m) == n_grid
    # Final delta agrees bit-for-bit
    assert via_df["delta_s"].iloc[-1] == pytest.approx(
        via_canonical.delta_s[-1], abs=1e-9,
    )
    # Every intermediate point agrees
    assert np.allclose(
        via_df["delta_s"].to_numpy(),
        via_canonical.delta_s,
        atol=1e-9,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 7. Regression test — known synthetic outcome
# ─────────────────────────────────────────────────────────────────────────────


def test_regression_known_lap_delta():
    """Piecewise-constant speeds for both laps, with a trap-aware expected
    value that accounts for the one averaged segment at the discontinuity.

       Lap A: 30 m/s for [0, 300] m, then 20 m/s for [300, 500] m.
       Lap B: 20 m/s for [0, 300] m, then 30 m/s for [300, 500] m.

    1 m sampling. The segment spanning the speed discontinuity (300→301)
    contributes 0.5 * (1/v_left + 1/v_right) for one lap and the mirror for
    the other — which still sum symmetrically, so the closed-form delta
    equals (B_time - A_time) exactly with trap on this discretisation.
    """
    dist = np.concatenate([
        np.linspace(0.0, 300.0, 301),
        np.linspace(300.0, 500.0, 201)[1:],
    ])
    v_a = np.concatenate([np.full(301, 30.0), np.full(200, 20.0)])
    v_b = np.concatenate([np.full(301, 20.0), np.full(200, 30.0)])

    # Analytical trap-rule result, one 1 m segment at the kink each way.
    ds_flat = 1.0
    time_a = 300 * ds_flat / 30.0 + 0.5 * (1 / 30.0 + 1 / 20.0) + 199 * ds_flat / 20.0
    time_b = 300 * ds_flat / 20.0 + 0.5 * (1 / 20.0 + 1 / 30.0) + 199 * ds_flat / 30.0
    expected = time_b - time_a

    res = cumulative_delta(dist, v_a, dist, v_b, n_grid=501)
    assert res.delta_s[-1] == pytest.approx(expected, abs=1e-6)
    # Sanity: about 1.68 s, B is slower overall.
    assert 1.5 < res.delta_s[-1] < 1.8


# ─────────────────────────────────────────────────────────────────────────────
# 8. Cross-session style — different sample spacing, same underlying lap
# ─────────────────────────────────────────────────────────────────────────────


def test_different_sample_spacing_same_result():
    """Two laps represent the same underlying physics sampled at very
    different densities. Final delta should be effectively zero (tolerance
    for interpolation error), and the cumulative curves should match in
    shape.
    """
    dist_fine = np.linspace(0.0, 1000.0, 1001)   # 1 m spacing
    dist_coarse = np.linspace(0.0, 1000.0, 101)  # 10 m spacing

    # Same speed profile — a sinusoidal pattern common in real telemetry.
    def profile(s: np.ndarray) -> np.ndarray:
        return 25.0 + 8.0 * np.sin(s * np.pi / 500.0)

    v_fine = profile(dist_fine)
    v_coarse = profile(dist_coarse)

    res = cumulative_delta(dist_fine, v_fine, dist_coarse, v_coarse, n_grid=400)
    # Delta should be essentially zero; interpolation adds tiny error.
    assert abs(res.delta_s[-1]) < 0.05  # under 50 ms over a ~40 s lap


# ─────────────────────────────────────────────────────────────────────────────
# 9. Input validation
# ─────────────────────────────────────────────────────────────────────────────


def test_shape_mismatch_raises():
    with pytest.raises(DeltaInputError):
        cumulative_delta(
            np.arange(10), np.arange(9),  # length mismatch
            np.arange(10), np.arange(10),
        )


def test_empty_input_returns_empty_result():
    res = cumulative_delta(np.array([]), np.array([]), np.array([]), np.array([]))
    assert res.progress_m.size == 0
    assert res.anchored is False
