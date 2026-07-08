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
