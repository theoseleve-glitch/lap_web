"""Tests for vehicle-class profiles + demonstrated-envelope resolver."""
from __future__ import annotations

import numpy as np
import pytest

from telemetry_tool.lap_oracle.config import VehicleParams
from track_surface.vehicle_profile import CLASS_PROFILES, ParamProvenance


_ALL_CLASSES = ["kart", "gt3", "gt4", "formula", "lmp", "touring", "road", "generic"]


def test_every_class_has_a_finite_bounded_profile():
    for cls in _ALL_CLASSES:
        vp = CLASS_PROFILES[cls]
        assert isinstance(vp, VehicleParams)
        assert 100.0 <= vp.mass_kg <= 2000.0
        assert 0.5 <= vp.wheelbase_m <= 3.5
        assert 0.0 <= vp.cla <= 5.0
        assert vp.max_power_w > 0
        assert vp.max_brake_decel > 0
        assert vp.tyre_lat.D == pytest.approx(1.0)
        assert vp.tyre_long.D == pytest.approx(1.0)


def test_kart_profile_is_light_and_downforce_free():
    kart = CLASS_PROFILES["kart"]
    assert kart.mass_kg < 250.0
    assert kart.cla == 0.0
    assert kart.wheelbase_m < 1.3


def test_aero_classes_have_downforce():
    for cls in ("gt3", "formula", "lmp"):
        assert CLASS_PROFILES[cls].cla > 0.0


def test_param_provenance_fields():
    p = ParamProvenance(vehicle_class="kart", lateral_source="grip_grid",
                        longitudinal_source="demonstrated", mass_source="class_default",
                        envelope_reliable=True)
    assert p.vehicle_class == "kart"
    assert p.longitudinal_source == "demonstrated"


# ---------------------------------------------------------------------------
# Task 2 — _envelope_to_caps
# ---------------------------------------------------------------------------
from telemetry_tool.friction_envelope import FrictionEnvelope, FrictionBin, _G
from track_surface.vehicle_profile import _envelope_to_caps


def _bin(speed, accel_g, brake_g, n=20):
    return FrictionBin(speed_center_mps=speed, combined_g_p95=1.5,
                       lat_max_g=1.4, accel_max_g=accel_g, brake_max_g=brake_g,
                       sample_count=n, confidence=1.0)


def _reliable_env(bins):
    return FrictionEnvelope(speed_bins=np.array([b.speed_center_mps for b in bins]),
                            friction_bins=bins, global_combined_g=1.5,
                            is_reliable=True, warning=None)


def test_envelope_to_caps_converts_g_to_mps2_over_reliable_bins():
    env = _reliable_env([_bin(10.0, 0.5, 1.2), _bin(20.0, 0.4, 1.3), _bin(30.0, 0.3, 1.1)])
    caps = _envelope_to_caps(env)
    assert caps is not None
    assert caps["v_grid"] == pytest.approx([10.0, 20.0, 30.0])
    assert caps["ax_drive_max"] == pytest.approx([0.5 * _G, 0.4 * _G, 0.3 * _G])
    assert caps["ax_brake_max"] == pytest.approx([1.2 * _G, 1.3 * _G, 1.1 * _G])


def test_envelope_to_caps_drops_low_sample_bins():
    env = _reliable_env([_bin(10.0, 0.5, 1.2, n=20), _bin(20.0, 0.4, 1.3, n=3),
                         _bin(30.0, 0.3, 1.1, n=20)])
    caps = _envelope_to_caps(env)
    assert caps["v_grid"] == pytest.approx([10.0, 30.0])


def test_envelope_to_caps_none_when_unreliable():
    env = FrictionEnvelope(speed_bins=np.array([]), friction_bins=[],
                           global_combined_g=1.0, is_reliable=False, warning="sparse")
    assert _envelope_to_caps(env) is None


def test_envelope_to_caps_none_with_fewer_than_two_bins():
    env = _reliable_env([_bin(10.0, 0.5, 1.2)])
    assert _envelope_to_caps(env) is None


# ---------------------------------------------------------------------------
# Task 3 — resolve_vehicle_params (3 tiers)
# ---------------------------------------------------------------------------
import pandas as pd
from track_surface.vehicle_profile import resolve_vehicle_params


def _accel_lap(*, n=400, v_lo=12.0, v_hi=38.0, a_lat_g=0.8):
    """A realistic lap: accelerate v_lo->v_hi (accel_long>0), then brake
    v_hi->v_lo (accel_long<0). Each speed bin in [v_lo,v_hi] sees BOTH an
    accel and a brake sample, so the friction envelope's bins have both axes.

    dt is chosen so the demonstrated longitudinal limit lands in a physically
    plausible band (~0.5 g) — within the _envelope_to_caps plausibility guard
    so these Tier-A bins are correctly accepted as demonstrated."""
    half = n // 2
    v_up = np.linspace(v_lo, v_hi, half)
    v_dn = np.linspace(v_hi, v_lo, n - half)
    v = np.concatenate([v_up, v_dn])
    # accel_long = dv/dt along travel; uniform dt=0.025s (40 Hz) -> ~0.5 g peak.
    dt = 0.025
    accel_long = np.gradient(v) / dt
    return pd.DataFrame({
        "Speed (m/s)": v,
        "accel_lat_mps2": np.full(n, a_lat_g * 9.80665),
        "accel_long_mps2": accel_long,
    })


def test_tier_c_nothing_is_pure_class_profile():
    vp, caps, prov = resolve_vehicle_params("kart")
    assert vp.mass_kg == CLASS_PROFILES["kart"].mass_kg
    assert caps is None
    assert prov.longitudinal_source == "class_default"
    assert prov.mass_source == "class_default"
    assert prov.envelope_reliable is False


def test_tier_b_weight_and_power_overrides():
    vp, caps, prov = resolve_vehicle_params("kart", weight_kg=175.0, power_w=30_000.0)
    assert vp.mass_kg == pytest.approx(175.0)
    assert vp.max_power_w == pytest.approx(30_000.0)
    assert caps is None
    assert prov.mass_source == "user_weight"
    assert prov.longitudinal_source == "user_power"


def test_tier_a_demonstrated_envelope_from_laps():
    laps = {i: _accel_lap() for i in range(8)}
    vp, caps, prov = resolve_vehicle_params("kart", laps=laps)
    assert caps is not None
    assert "v_grid" in caps and "ax_drive_max" in caps and "ax_brake_max" in caps
    assert prov.longitudinal_source == "demonstrated"
    assert prov.envelope_reliable is True


def test_sparse_laps_fall_back_to_class_default():
    laps = {0: _accel_lap(n=5)}
    vp, caps, prov = resolve_vehicle_params("kart", laps=laps)
    assert caps is None
    assert prov.longitudinal_source == "class_default"


def test_unknown_class_uses_generic():
    vp, caps, prov = resolve_vehicle_params("spaceship")
    assert vp.mass_kg == CLASS_PROFILES["generic"].mass_kg
    assert prov.vehicle_class == "spaceship"


def test_user_power_takes_precedence_over_demonstrated():
    laps = {i: _accel_lap() for i in range(8)}
    vp, caps, prov = resolve_vehicle_params("kart", laps=laps, power_w=30_000.0)
    assert vp.max_power_w == pytest.approx(30_000.0)
    assert caps is not None
    assert prov.longitudinal_source == "user_power"


def test_caps_never_emit_zero_limits():
    """Regression: a bin passing the filter must have BOTH axes demonstrated,
    so no cap is ever 0.0 (a 0.0 brake/drive cap cripples the solver)."""
    laps = {i: _accel_lap() for i in range(8)}
    _, caps, _ = resolve_vehicle_params("kart", laps=laps)
    assert caps is not None
    assert all(d > 0.0 for d in caps["ax_drive_max"])
    assert all(b > 0.0 for b in caps["ax_brake_max"])


def test_envelope_to_caps_none_on_non_monotonic_grid():
    """A non-strictly-increasing v_grid would crash ca.interpolant at solve
    time; _envelope_to_caps must fail soft to class scalars instead."""
    env = _reliable_env([_bin(20.0, 0.5, 1.2), _bin(20.0, 0.4, 1.3), _bin(10.0, 0.3, 1.1)])
    assert _envelope_to_caps(env) is None


def test_resolver_degrades_when_envelope_raises(monkeypatch):
    """If friction-envelope estimation raises, the resolver must still return a
    usable class-default vp (envelope is an optional enhancement)."""
    import track_surface.vehicle_profile as vpmod
    def boom(*a, **k):
        raise ValueError("synthetic envelope failure")
    monkeypatch.setattr(vpmod, "compute_friction_envelope", boom)
    laps = {i: _accel_lap() for i in range(8)}
    vp, caps, prov = resolve_vehicle_params("kart", laps=laps)
    assert caps is None
    assert prov.longitudinal_source == "class_default"
    assert prov.envelope_reliable is False
    assert vp.mass_kg == CLASS_PROFILES["kart"].mass_kg


def test_envelope_to_caps_rejects_implausibly_weak_limits():
    """A ~30x-underscaled envelope (e.g. accel_long differentiated at the wrong
    dt) must NOT pass as demonstrated — fall back to class default."""
    env = _reliable_env([_bin(10.0, 0.01, 0.01), _bin(20.0, 0.012, 0.011),
                         _bin(30.0, 0.009, 0.013)])   # ~0.01 g -> absurd
    assert _envelope_to_caps(env) is None


def test_envelope_to_caps_accepts_plausible_limits():
    env = _reliable_env([_bin(10.0, 0.4, 1.2), _bin(20.0, 0.5, 1.3), _bin(30.0, 0.45, 1.1)])
    caps = _envelope_to_caps(env)
    assert caps is not None    # ~1.2 g brake is plausible


def test_envelope_to_caps_rejects_asymmetric_near_zero_drive():
    """Plausible brake but near-zero drive (one axis not really demonstrated)
    must be rejected -- a tiny drive cap would over-constrain the solver."""
    env = _reliable_env([_bin(10.0, 0.04, 1.2), _bin(20.0, 0.05, 1.3),
                         _bin(30.0, 0.03, 1.1)])   # brake ~1.2g OK, drive ~0.04g absurd
    assert _envelope_to_caps(env) is None
