"""Tests for the multi-criterion transition gate.

Covers:
  - Stable flat / stable banked / unstable regime classification
  - Each criterion fires independently
  - Hysteresis: entry/exit thresholds + dwell + padding control flicker
  - Reason codes are deterministic and accurate
  - Run-length diagnostics
  - End-to-end integration with the bucketing transition_mask contract
  - Coverage doesn't collapse on noisy-but-stable signals
"""
from __future__ import annotations

import numpy as np
import pytest

from track_surface.multi_criterion_transition_gate import (
    RegimeLabel,
    TransitionFeatures,
    TransitionGateConfig,
    TransitionGateResult,
    TransitionReason,
    apply_gate,
    apply_hysteresis,
    classify_regime,
    compute_transition_features,
    score_per_sample,
)


# ── Synthetic-signal builders ───────────────────────────────


def _flat_signals(n: int = 600, sample_rate_hz: float = 60.0) -> dict:
    """Stable flat-track signals: small noise, no transitions."""
    rng = np.random.default_rng(42)
    return {
        "bank_est": rng.normal(0.0, 0.001, n),
        "grade_est": rng.normal(0.0, 0.001, n),
        "yaw_rate": rng.normal(0.5, 0.02, n),  # gentle steady cornering
        "steer": rng.normal(0.1, 0.005, n),
        "a_lat": rng.normal(8.0, 0.05, n),     # steady ~0.8 g
        "road_quality": np.full(n, 0.9),
    }


def _banked_signals(n: int = 600) -> dict:
    """Stable banked: ~20° bank, no transitions, steady cornering."""
    rng = np.random.default_rng(7)
    return {
        "bank_est": np.full(n, 0.35) + rng.normal(0, 0.001, n),
        "grade_est": rng.normal(0, 0.001, n),
        "yaw_rate": rng.normal(0.6, 0.02, n),
        "steer": rng.normal(0.1, 0.005, n),
        "a_lat": rng.normal(15.0, 0.1, n),
        "road_quality": np.full(n, 0.85),
    }


def _bank_transition_signals(n: int = 600, transition_start: int = 200,
                              transition_len: int = 30) -> dict:
    """Flat → banking transition starting at index `transition_start`."""
    rng = np.random.default_rng(13)
    bank = np.zeros(n)
    bank[transition_start + transition_len:] = 0.35
    # Linear ramp during the transition
    ramp = np.linspace(0, 0.35, transition_len)
    bank[transition_start:transition_start + transition_len] = ramp
    bank += rng.normal(0, 0.001, n)
    a_lat = np.where(bank > 0.2, 15.0, 8.0) + rng.normal(0, 0.05, n)
    return {
        "bank_est": bank,
        "grade_est": rng.normal(0, 0.001, n),
        "yaw_rate": rng.normal(0.5, 0.02, n),
        "steer": rng.normal(0.1, 0.005, n),
        "a_lat": a_lat,
        "road_quality": np.full(n, 0.85),
    }


def _curb_hit_signals(n: int = 600, hit_at: int = 300) -> dict:
    """Flat track with a single curb hit (ride height + a_lat spike)."""
    base = _flat_signals(n)
    rh = np.full((n, 4), 0.05) + np.random.default_rng(99).normal(0, 0.0005, (n, 4))
    # Sharp wheel-unload at hit_at
    rh[hit_at:hit_at + 5, 1] += 0.05  # right-front extends
    rh[hit_at:hit_at + 5, 0] -= 0.02  # left-front compresses
    base["ride_heights"] = rh
    # a_lat blip
    base["a_lat"][hit_at:hit_at + 3] += 5.0
    return base


# ── compute_transition_features ─────────────────────────────


class TestFeatureComputation:
    def test_flat_signals_low_features(self):
        sig = _flat_signals()
        f = compute_transition_features(**sig)
        assert (f.bank_grad < 0.005).all()
        assert (f.steer_rate < 1.0).all()
        # No ride_heights provided → has_ride_height=False, rates are 0
        assert f.has_ride_height is False
        assert (f.ride_height_rate_max == 0).all()

    def test_bank_transition_spikes_bank_grad(self):
        sig = _bank_transition_signals()
        f = compute_transition_features(**sig)
        # The bank_grad should peak during the transition window
        max_grad_idx = f.bank_grad.argmax()
        assert 200 <= max_grad_idx <= 250

    def test_ride_height_provided(self):
        sig = _curb_hit_signals()
        f = compute_transition_features(**sig)
        assert f.has_ride_height is True
        # The max ride height rate should peak around the hit
        peak_idx = f.ride_height_rate_max.argmax()
        assert 295 <= peak_idx <= 315

    def test_nan_input_safe(self):
        sig = _flat_signals(n=100)
        sig["bank_est"][50] = np.nan
        f = compute_transition_features(**sig)
        # Gradient should still be finite everywhere (NaN-guarded)
        assert np.isfinite(f.bank_grad).all()


# ── score_per_sample ────────────────────────────────────────


class TestScoring:
    def test_flat_signals_score_zero(self):
        f = compute_transition_features(**_flat_signals())
        score, reasons = score_per_sample(f, TransitionGateConfig())
        assert (score == 0).all()
        assert all(r == [] for r in reasons)

    def test_bank_transition_scores_positive(self):
        f = compute_transition_features(**_bank_transition_signals())
        score, reasons = score_per_sample(f, TransitionGateConfig())
        # Some samples in the ramp should fire
        assert score.max() >= 1
        # The peaks should include BANK_TRANSITION reason
        peak_idx = f.bank_grad.argmax()
        assert TransitionReason.BANK_TRANSITION in reasons[peak_idx]

    def test_road_quality_drop_fires(self):
        sig = _flat_signals()
        sig["road_quality"][100:120] = 0.05  # below the default 0.10 threshold
        f = compute_transition_features(**sig)
        score, reasons = score_per_sample(f, TransitionGateConfig())
        # All those samples should have ROAD_QUALITY_DROP
        for i in range(100, 120):
            assert TransitionReason.ROAD_QUALITY_DROP in reasons[i]

    def test_steering_spike_fires(self):
        sig = _flat_signals()
        # Inject a sharp steering correction: 0.5 rad change in 1 sample at 60Hz = 30 rad/s
        sig["steer"][300] += 0.5
        f = compute_transition_features(**sig)
        score, reasons = score_per_sample(f, TransitionGateConfig())
        nearby = reasons[299] + reasons[300] + reasons[301]
        assert TransitionReason.STEERING_SPIKE in nearby


# ── apply_hysteresis ────────────────────────────────────────


class TestHysteresis:
    def test_no_unstable_when_score_below_entry(self):
        score = np.zeros(100, dtype=int)
        score[50] = 1   # below entry_score=2
        cfg = TransitionGateConfig(entry_score=2, exit_score=0,
                                   min_dwell_samples=5,
                                   pre_padding_samples=0,
                                   post_padding_samples=0)
        unstable, _, _ = apply_hysteresis(score, cfg)
        assert not unstable.any()

    def test_dwell_extends_unstable(self):
        score = np.zeros(100, dtype=int)
        score[50:55] = 3  # entry above 2
        cfg = TransitionGateConfig(entry_score=2, exit_score=0,
                                   min_dwell_samples=20,
                                   pre_padding_samples=0,
                                   post_padding_samples=0)
        unstable, dwell, _ = apply_hysteresis(score, cfg)
        # min_dwell=20 keeps it unstable until at least index 70
        assert unstable[55:70].all()
        # Some of those will be by-dwell (score is 0 there)
        assert dwell[60:70].any()

    def test_padding_extends_around_unstable_run(self):
        score = np.zeros(100, dtype=int)
        score[50:55] = 3
        cfg = TransitionGateConfig(entry_score=2, exit_score=0,
                                   min_dwell_samples=5,
                                   pre_padding_samples=3,
                                   post_padding_samples=3)
        unstable, _, padding = apply_hysteresis(score, cfg)
        # Pre-padding should cover ~indexes 47-49
        assert unstable[47:50].all()
        assert padding[47:50].all()
        # Post-padding should cover a few samples after exit

    def test_no_flicker_with_isolated_spikes(self):
        """An isolated spike of score=1 should NOT cause a transition."""
        score = np.zeros(100, dtype=int)
        score[10] = 1   # one criterion fires briefly
        score[50] = 1
        cfg = TransitionGateConfig(entry_score=2)
        unstable, _, _ = apply_hysteresis(score, cfg)
        assert not unstable.any()

    def test_two_criteria_simultaneously_triggers(self):
        score = np.zeros(100, dtype=int)
        score[50] = 2
        cfg = TransitionGateConfig(entry_score=2, exit_score=0,
                                   min_dwell_samples=1,
                                   pre_padding_samples=0,
                                   post_padding_samples=0)
        unstable, _, _ = apply_hysteresis(score, cfg)
        assert unstable[50]

    def test_empty_input(self):
        unstable, dwell, padding = apply_hysteresis(np.zeros(0, dtype=int),
                                                     TransitionGateConfig())
        assert unstable.size == 0


# ── classify_regime ─────────────────────────────────────────


class TestRegime:
    def test_flat_classified_as_stable_flat(self):
        bank = np.zeros(50)
        unstable = np.zeros(50, dtype=bool)
        regimes = classify_regime(bank, unstable, TransitionGateConfig())
        assert all(r == RegimeLabel.STABLE_FLAT for r in regimes)

    def test_banked_classified_as_stable_banked(self):
        bank = np.full(50, 0.20)  # well above 0.08 threshold
        unstable = np.zeros(50, dtype=bool)
        regimes = classify_regime(bank, unstable, TransitionGateConfig())
        assert all(r == RegimeLabel.STABLE_BANKED for r in regimes)

    def test_unstable_overrides_banking(self):
        bank = np.full(50, 0.20)
        unstable = np.ones(50, dtype=bool)
        regimes = classify_regime(bank, unstable, TransitionGateConfig())
        assert all(r == RegimeLabel.UNSTABLE for r in regimes)


# ── End-to-end apply_gate ───────────────────────────────────


class TestApplyGateE2E:
    def test_flat_session_keeps_almost_everything(self):
        result = apply_gate(**_flat_signals(n=600))
        assert result.diagnostics.accept_pct > 95.0
        # Regime: nearly all STABLE_FLAT
        assert result.diagnostics.regime_counts["stable_flat"] > 570

    def test_banked_session_keeps_almost_everything(self):
        result = apply_gate(**_banked_signals(n=600))
        assert result.diagnostics.accept_pct > 95.0
        assert result.diagnostics.regime_counts["stable_banked"] > 570

    def test_bank_transition_rejects_window(self):
        result = apply_gate(**_bank_transition_signals(n=600,
                                                       transition_start=200,
                                                       transition_len=30))
        # The transition window (~200-230) should be rejected by the gate
        # plus padding on either side
        rejected_in_window = (~result.accept_mask[195:240]).sum()
        assert rejected_in_window >= 20
        # Outside the window, things should still be stable
        assert result.accept_mask[:150].all()
        assert result.accept_mask[300:].all()

    def test_curb_hit_rejected(self):
        result = apply_gate(**_curb_hit_signals(n=600, hit_at=300))
        # The hit window is rejected
        assert not result.accept_mask[295:310].all()
        # And reason codes include RIDE_HEIGHT_SPIKE somewhere in that range
        any_rh_spike = any(
            TransitionReason.RIDE_HEIGHT_SPIKE in result.reasons_per_sample[i]
            for i in range(295, 315)
        )
        assert any_rh_spike

    def test_diagnostics_consistent(self):
        result = apply_gate(**_bank_transition_signals())
        d = result.diagnostics
        assert d.n_total == 600
        assert d.n_accepted + d.n_rejected == d.n_total
        assert abs(d.accept_pct + d.reject_pct - 100.0) < 0.001

    def test_reason_counts_match_per_sample(self):
        result = apply_gate(**_bank_transition_signals())
        # Sum reason hits across samples
        manual_counts: dict[str, int] = {}
        for sample_reasons in result.reasons_per_sample:
            for r in sample_reasons:
                manual_counts[r.value] = manual_counts.get(r.value, 0) + 1
        assert manual_counts == result.diagnostics.reason_counts

    def test_run_length_diagnostics(self):
        result = apply_gate(**_bank_transition_signals(n=600,
                                                       transition_start=200,
                                                       transition_len=30))
        # Should be exactly one unstable run (the transition window)
        # plus padding either side
        d = result.diagnostics
        assert d.n_unstable_runs >= 1
        assert d.longest_unstable_run >= 20

    def test_deterministic_across_runs(self):
        sig = _bank_transition_signals()
        r1 = apply_gate(**sig)
        r2 = apply_gate(**sig)
        np.testing.assert_array_equal(r1.accept_mask, r2.accept_mask)
        assert r1.diagnostics.reason_counts == r2.diagnostics.reason_counts


class TestNoiseRobustness:
    """The gate must not collapse coverage on noisy-but-stable signals."""

    def test_noisy_flat_still_keeps_most_samples(self):
        rng = np.random.default_rng(2026)
        n = 600
        sig = {
            "bank_est": rng.normal(0.0, 0.003, n),    # mild bank noise
            "grade_est": rng.normal(0.0, 0.003, n),
            "yaw_rate": rng.normal(0.5, 0.05, n),     # noisy yaw
            "steer": rng.normal(0.1, 0.02, n),
            "a_lat": rng.normal(8.0, 0.5, n),         # noisy a_lat
            "road_quality": np.full(n, 0.5),
        }
        result = apply_gate(**sig)
        # Even with mild noise, accept_pct should stay high (noise alone shouldn't
        # cause two criteria to fire simultaneously)
        assert result.diagnostics.accept_pct > 80.0


class TestConfigurability:
    def test_strict_config_rejects_more(self):
        sig = _bank_transition_signals(n=600)
        loose = apply_gate(**sig)
        strict = apply_gate(
            **sig,
            config=TransitionGateConfig(
                bank_grad_thresh_rad_per_sample=0.001,  # very strict
                pre_padding_samples=20, post_padding_samples=20,
                min_dwell_samples=30,
            ),
        )
        assert strict.diagnostics.n_rejected > loose.diagnostics.n_rejected

    def test_old_gate_equivalent_isolated(self):
        """Replicate the old single-axis gate: bank_grad > 0.008 with no
        hysteresis. We simulate this by using a config that effectively
        disables every other criterion + entry_score=1, no dwell, no padding."""
        sig = _bank_transition_signals(n=600)
        # Disable all OTHER criteria by setting their thresholds extremely high
        cfg = TransitionGateConfig(
            bank_grad_thresh_rad_per_sample=0.008,
            grade_grad_thresh_rad_per_sample=1e9,
            steer_rate_thresh_rad_per_s=1e9,
            yaw_jerk_thresh_rad_per_s2=1e9,
            a_lat_jerk_thresh_m_per_s3=1e9,
            ride_height_rate_thresh_m_per_s=1e9,
            road_quality_thresh=-1.0,
            entry_score=1, exit_score=0,
            min_dwell_samples=1,
            pre_padding_samples=0,
            post_padding_samples=0,
        )
        old_like = apply_gate(**sig, config=cfg)
        # Should reject ~30 samples (the transition window) — close to manual count
        # Manual: bank_grad > 0.008 over a 30-sample ramp from 0 → 0.35
        # Per-sample step is 0.35/30 ≈ 0.0117, so all 30 fire
        assert old_like.diagnostics.n_rejected >= 25
        assert old_like.diagnostics.n_rejected <= 50
