"""Tests for the theoretical-lap plausibility guard (s10_theoretical).

A theoretical / "optimal" lap must never be presented to a customer as slower
than a lap they actually drove — that is physically impossible (they already
beat it) and poisons the ideal-lap gap and the score. These tests pin the guard
that rejects an implausible optimum and falls through to the data-driven
percentile envelope.
"""
import math

import numpy as np
import pandas as pd
import pytest

from pipeline.stages import s10_theoretical as S10


# ── pure helpers ────────────────────────────────────────────────────────────
def test_is_optimal_plausible_accepts_faster():
    assert S10.is_optimal_plausible(59.0, 61.0) is True


def test_is_optimal_plausible_rejects_slower():
    # 71s optimal vs 61.7s achieved — the real SLK_FP2 failure mode
    assert S10.is_optimal_plausible(71.0, 61.7) is False


def test_is_optimal_plausible_within_tolerance():
    # marginally slower (<2%) is accepted as measurement noise, not rejected
    assert S10.is_optimal_plausible(61.0 * 1.015, 61.0) is True


def test_is_optimal_plausible_no_reference_accepts():
    assert S10.is_optimal_plausible(90.0, float("inf")) is True
    assert S10.is_optimal_plausible(90.0, None) is True


def test_is_optimal_plausible_missing_theo_time_accepts():
    # don't reject on missing/garbage data — only on a real slower-than-driver lap
    assert S10.is_optimal_plausible(float("nan"), 61.0) is True
    assert S10.is_optimal_plausible(0.0, 61.0) is True


def test_theoretical_lap_time_prefers_sim_result():
    class _R:
        lap_time_s = 62.5
    assert S10.theoretical_lap_time_s(None, _R()) == pytest.approx(62.5)


def test_theoretical_lap_time_from_df_when_no_sim_result():
    df = pd.DataFrame({"Time (s)": np.linspace(0.0, 60.0, 100)})
    assert S10.theoretical_lap_time_s(df, None) == pytest.approx(60.0)


# ── cascade fall-through ─────────────────────────────────────────────────────
class _FakeSimResult:
    def __init__(self, t):
        self.lap_time_s = t
        self.method = "hybrid_calibrated"
        self.max_speed_mps = 30.0


class _FakeSimModule:
    """Stands in for lap_simulation: returns an IMPLAUSIBLE optimum."""
    def simulate_with_fallback(self, *a, **k):
        return _FakeSimResult(71.0)

    def result_to_theoretical_df(self, result):
        return pd.DataFrame({"Time (s)": np.linspace(0.0, result.lap_time_s, 50)})


class _FakePercentileModule:
    """Stands in for theoretical_engine: a plausible envelope from real laps."""
    def build_theoretical_lap(self, laps_for_theo, **k):
        return pd.DataFrame({"Time (s)": np.linspace(0.0, 60.0, 50)})


def test_run_theoretical_rejects_implausible_sim_and_falls_through(monkeypatch):
    """Hybrid sim says 71s but the driver did 61s → the guard must reject it and
    return the plausible percentile envelope instead."""
    fake_sim = _FakeSimModule()
    fake_pct = _FakePercentileModule()

    def _fake_lazy_import(name):
        if name == "theoretical_adapter":
            return None            # P0 unavailable → skip kart solver
        if name == "lap_simulation":
            return fake_sim        # P1 returns implausible 71s
        if name == "theoretical_engine":
            return fake_pct        # P2 plausible envelope
        return None

    monkeypatch.setattr(S10, "lazy_import", _fake_lazy_import)

    laps = {1: pd.DataFrame({"distance_m": np.linspace(0, 500, 20),
                             "speed_mps": np.full(20, 22.0)})}
    result = S10.run_theoretical(
        laps, None, object(), None, None,
        valid_times=[(1, 61.0), (2, 62.0)],
        channel_discovery=None, phases_df=None,
    )
    theo_df, sim_method, sim_result, *_ = result
    # Fell through to the percentile envelope, not the implausible 71s sim
    assert sim_method == "percentile_envelope"
    assert S10.theoretical_lap_time_s(theo_df, sim_result) == pytest.approx(60.0, abs=0.5)


# ── the fallback must accept raw RaceChrono-named laps ───────────────────────
def test_build_theoretical_lap_accepts_racechrono_columns():
    """The percentile-envelope fallback (what the guard routes to) must work on
    distance-resampled laps that still carry raw RaceChrono headers, not only
    snake_case feature columns."""
    from theoretical_engine import build_theoretical_lap

    rng = np.random.default_rng(7)
    laps = []
    for _ in range(4):
        dist = np.linspace(0.0, 500.0, 200)
        speed = 20.0 + 5.0 * np.sin(2 * np.pi * dist / 500.0) + rng.normal(0, 0.3, 200)
        laps.append(pd.DataFrame({
            "Distance (m)": dist,
            "Speed (m/s)": speed,
            "Longitudinal acceleration (G) *calc": rng.normal(0, 0.2, 200),
        }))

    theo = build_theoretical_lap(laps, n_points=100)
    assert theo is not None and len(theo) > 0
    assert "v_env_mps" in theo.columns
    assert theo["v_env_mps"].notna().any()
