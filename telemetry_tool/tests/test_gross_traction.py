"""VehicleModel.gross_traction_accel recovers gross capability from the NET envelope.

The traction envelope is trained from measured net accel (drag + rolling
resistance already removed). The forward integrator subtracts resistance once,
so the envelope must be converted back to gross first — otherwise resistance is
double-counted and the simulated lap crawls (optimal slower than the driver).
See docs/theoretical-lap-grip-underestimation-diagnosis.md.
"""
import numpy as np
import pytest

from lap_simulation import VehicleModel, _G


def _vm(**kw):
    v = np.array([5.0, 10.0, 20.0, 30.0])
    params = dict(
        v_knots=v,
        traction_force_per_kg=np.array([3.0, 3.0, 3.0, 3.0]),   # NET ~0.31 g
        braking_force_per_kg=np.array([6.0, 6.0, 6.0, 6.0]),
        power_envelope_w_per_kg=np.array([1e4, 1e4, 1e4, 1e4]),  # power not binding
        estimated_peak_power_w_per_kg=1e4,
        aero_drag_coeff=0.002,
        rolling_resistance=0.015,
    )
    params.update(kw)
    return VehicleModel(**params)


def test_gross_adds_resistance_back_when_net():
    vm = _vm()
    v = 20.0
    rr = 0.015 * _G
    drag = 0.002 * v * v
    assert vm.gross_traction_accel(v) == pytest.approx(3.0 + rr + drag, rel=1e-9)


def test_gross_greater_than_net():
    vm = _vm()
    for v in (5.0, 10.0, 20.0, 30.0):
        assert vm.gross_traction_accel(v) > vm.traction_accel(v)


def test_gross_capped_by_gross_power():
    # gross power = P/v = 40/20 = 2.0 < net+resistance (~3.95) -> capped at 2.0
    vm = _vm(power_envelope_w_per_kg=np.array([40.0, 40.0, 40.0, 40.0]),
             estimated_peak_power_w_per_kg=40.0)
    assert vm.gross_traction_accel(20.0) == pytest.approx(2.0, rel=1e-9)


def test_gross_no_add_when_already_gross():
    vm = _vm(traction_is_net=False)
    # envelope already gross -> nothing added (power not binding here)
    assert vm.gross_traction_accel(20.0) == pytest.approx(3.0, rel=1e-9)


def test_net_minus_resistance_recovers_observed_accel():
    """The whole point: gross_traction - resistance == the observed NET accel."""
    vm = _vm()
    v = 20.0
    a_resist = vm.resistance_accel(v, 0.0)   # rr + drag (no grade)
    a_net = vm.gross_traction_accel(v) - a_resist
    assert a_net == pytest.approx(3.0, rel=1e-9)   # back to the trained net value


def _vm_dip(**kw):
    """Envelope that dips at low speed (the corner-exit sampling artifact)."""
    v = np.array([8.0, 12.0, 16.0, 20.0, 24.0])
    params = dict(
        v_knots=v,
        traction_force_per_kg=np.array([1.5, 2.0, 3.0, 3.2, 2.8]),  # NET, dips at low v
        braking_force_per_kg=np.array([6.0] * 5),
        power_envelope_w_per_kg=np.array([1e6] * 5),  # power not binding
        estimated_peak_power_w_per_kg=1e6,
        aero_drag_coeff=0.0, rolling_resistance=0.0,  # isolate the grip term
        aero_downforce_coeff=0.0,
    )
    params.update(kw)
    return VehicleModel(**params)


def test_no_lowspeed_collapse_without_downforce():
    vm = _vm_dip()
    # at 8 m/s the raw envelope dips to 1.5 but peak is 3.2 -> lifted to peak
    assert vm.gross_traction_accel(8.0) == pytest.approx(3.2, rel=1e-9)
    assert vm.gross_traction_accel(12.0) == pytest.approx(3.2, rel=1e-9)
    assert vm.gross_traction_accel(20.0) == pytest.approx(3.2, rel=1e-9)


def test_downforce_keeps_lowspeed_dependence():
    vm = _vm_dip(aero_downforce_coeff=0.001)  # has downforce -> low-speed grip is real
    assert vm.gross_traction_accel(8.0) == pytest.approx(1.5, rel=1e-9)


def test_power_ceiling_uses_peak_not_binned():
    # binned power collapses at low speed; P_peak/v must be used instead
    v = np.array([8.0, 12.0, 20.0, 30.0])
    vm = VehicleModel(
        v_knots=v,
        traction_force_per_kg=np.array([5.0, 5.0, 5.0, 5.0]),   # grip floored to peak 5
        braking_force_per_kg=np.array([6.0] * 4),
        power_envelope_w_per_kg=np.array([40.0, 48.0, 1500.0, 3000.0]),  # collapses low; peak 3000
        estimated_peak_power_w_per_kg=3000.0,
        aero_drag_coeff=0.0, rolling_resistance=0.0, aero_downforce_coeff=0.0,
    )
    # binned would give 48/12 = 4.0 (wrongly power-limited); P_peak/v = 3000/12 = 250 -> grip 5 binds
    assert vm.gross_traction_accel(12.0) == pytest.approx(5.0, rel=1e-9)
