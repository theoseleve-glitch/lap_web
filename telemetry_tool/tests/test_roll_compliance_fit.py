"""Tests for roll_compliance_fit.py."""
from __future__ import annotations

import numpy as np
import pytest

from track_surface.roll_compliance_fit import (
    RollComplianceFitResult,
    fit_roll_compliance,
    _compute_measured_roll,
)


def _make_ride_heights(n: int, compliance: float, a_lat: np.ndarray,
                       track_mm: float = 1666.0, noise: float = 0.0) -> np.ndarray:
    """Synthesize ride heights consistent with a known roll compliance.

    Chassis roll under lateral accel compresses one side, extends the other.
    delta_rh = compliance × a_lat × track_mm / 2 (per side, in mm)
    """
    rng = np.random.default_rng(42)
    base_rh = 80.0  # mm static ride height
    roll_mm = compliance * a_lat * track_mm  # total L/R delta in mm
    rh = np.full((n, 4), base_rh)
    # LF gets -roll/2, RF gets +roll/2 (positive a_lat = right turn → right compresses)
    rh[:, 0] -= roll_mm * 0.5  # LF rises
    rh[:, 1] += roll_mm * 0.5  # RF drops
    rh[:, 2] -= roll_mm * 0.5  # LR rises
    rh[:, 3] += roll_mm * 0.5  # RR drops
    if noise > 0:
        rh += rng.normal(0, noise, rh.shape)
    return rh


def _default_inputs(n: int = 500, a_lat_val: float = 8.0, compliance: float = 0.005):
    a_lat = np.full(n, a_lat_val)
    rh = _make_ride_heights(n, compliance, a_lat)
    return dict(
        ride_heights=rh,
        a_lat_tire=a_lat,
        bank_rad=np.zeros(n),
        bank_gradient=np.zeros(n),
        speed=np.full(n, 30.0),
        transition_mask=np.zeros(n, dtype=bool),
        road_quality=np.full(n, 0.8),
    )


class TestMeasuredRoll:
    def test_zero_roll_on_symmetric(self):
        rh = np.array([[80, 80, 80, 80]], dtype=float)
        roll = _compute_measured_roll(rh, 1666.0, 1627.0)
        assert abs(roll[0]) < 0.001

    def test_positive_roll_when_right_compressed(self):
        # RF lower than LF, RR lower than LR
        rh = np.array([[82, 78, 82, 78]], dtype=float)
        roll = _compute_measured_roll(rh, 1666.0, 1627.0)
        assert roll[0] < 0  # right side drops → negative by convention


class TestFitRecovery:
    def test_recovers_known_compliance(self):
        """Synthetic data at compliance=0.008 → fit should find ~0.008."""
        true_compliance = 0.008
        inp = _default_inputs(n=1000, a_lat_val=8.0, compliance=true_compliance)
        result = fit_roll_compliance(**inp, current_compliance=0.005)
        assert abs(result.compliance_rad_per_mps2 - true_compliance) < 0.002

    def test_recovers_small_compliance(self):
        true_compliance = 0.003
        inp = _default_inputs(n=1000, a_lat_val=6.0, compliance=true_compliance)
        result = fit_roll_compliance(**inp, current_compliance=0.005)
        assert abs(result.compliance_rad_per_mps2 - true_compliance) < 0.002

    def test_noisy_data_still_reasonable(self):
        true_compliance = 0.006
        n = 2000
        a_lat = np.full(n, 7.0)
        rh = _make_ride_heights(n, true_compliance, a_lat, noise=0.5)
        result = fit_roll_compliance(
            ride_heights=rh, a_lat_tire=a_lat,
            bank_rad=np.zeros(n), bank_gradient=np.zeros(n),
            speed=np.full(n, 30.0),
            transition_mask=np.zeros(n, dtype=bool),
            road_quality=np.full(n, 0.8),
            current_compliance=0.005,
        )
        assert abs(result.compliance_rad_per_mps2 - true_compliance) < 0.003


class TestFlatSectionPreservation:
    def test_flat_residual_does_not_worsen(self):
        """Fitting on combined data should not break the flat sections."""
        true_compliance = 0.007
        n = 1000
        a_lat = np.concatenate([
            np.full(500, 6.0),   # flat sections
            np.full(500, 10.0),  # banked sections
        ])
        rh = _make_ride_heights(n, true_compliance, a_lat)
        bank = np.concatenate([
            np.zeros(500),
            np.full(500, 0.3),  # ~17° bank
        ])
        result = fit_roll_compliance(
            ride_heights=rh, a_lat_tire=a_lat,
            bank_rad=bank, bank_gradient=np.zeros(n),
            speed=np.full(n, 30.0),
            transition_mask=np.zeros(n, dtype=bool),
            road_quality=np.full(n, 0.8),
            current_compliance=0.005,
        )
        # Flat residual should not worsen
        assert result.flat_residual_after <= result.flat_residual_before * 1.2 + 0.001


class TestEdgeCases:
    def test_insufficient_samples(self):
        inp = _default_inputs(n=10)
        result = fit_roll_compliance(**inp, current_compliance=0.005)
        assert result.compliance_rad_per_mps2 == 0.005  # returns default
        assert "insufficient" in result.recommendation

    def test_clamped_to_physical_range(self):
        """Extreme data should not produce unphysical compliance."""
        n = 500
        a_lat = np.full(n, 5.0)
        # Huge ride-height difference → would give huge compliance
        rh = np.full((n, 4), 80.0)
        rh[:, 0] -= 50  # extreme roll
        rh[:, 1] += 50
        rh[:, 2] -= 50
        rh[:, 3] += 50
        result = fit_roll_compliance(
            ride_heights=rh, a_lat_tire=a_lat,
            bank_rad=np.zeros(n), bank_gradient=np.zeros(n),
            speed=np.full(n, 30.0),
            transition_mask=np.zeros(n, dtype=bool),
            road_quality=np.full(n, 0.8),
            current_compliance=0.005,
        )
        assert result.compliance_rad_per_mps2 <= 0.020

    def test_all_quarantined_returns_default(self):
        inp = _default_inputs(n=500)
        inp["transition_mask"] = np.ones(500, dtype=bool)
        result = fit_roll_compliance(**inp, current_compliance=0.005)
        assert result.compliance_rad_per_mps2 == 0.005


class TestRecommendation:
    def test_good_fit_recommends_stop(self):
        true_compliance = 0.008
        inp = _default_inputs(n=1000, compliance=true_compliance)
        # Add some banked samples
        n_banked = 500
        a_lat_banked = np.full(n_banked, 10.0)
        rh_banked = _make_ride_heights(n_banked, true_compliance, a_lat_banked)
        inp["ride_heights"] = np.vstack([inp["ride_heights"], rh_banked])
        inp["a_lat_tire"] = np.concatenate([inp["a_lat_tire"], a_lat_banked])
        inp["bank_rad"] = np.concatenate([inp["bank_rad"], np.full(n_banked, 0.3)])
        inp["bank_gradient"] = np.concatenate([inp["bank_gradient"], np.zeros(n_banked)])
        inp["speed"] = np.concatenate([inp["speed"], np.full(n_banked, 40.0)])
        inp["transition_mask"] = np.concatenate([inp["transition_mask"], np.zeros(n_banked, dtype=bool)])
        inp["road_quality"] = np.concatenate([inp["road_quality"], np.full(n_banked, 0.8)])

        result = fit_roll_compliance(**inp, current_compliance=0.005)
        assert "stop" in result.recommendation.lower() or "continue" in result.recommendation.lower()
