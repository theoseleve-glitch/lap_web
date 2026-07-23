"""Guard test: the throttle-lift path end to end.

This is the coverage gap that hid a two-bug interaction found in the
Phase-1 whole-branch review:

1. `s13_coaching_v3.run_coaching_analyzers` called `detect_throttle_lifts`
   with 3 positional args when the function requires 4
   (`vehicle_mass_kg`). The call sits inside a broad
   `except Exception: logger.debug(...)`, so the `TypeError` was silently
   swallowed -- `bundle["throttle_lifts"]` was ALWAYS empty in production,
   which meant `_resolve_cause`'s dangerous-lift branch never actually ran.
2. That branch itself (`corner_composer._resolve_cause`) read a field
   `ThrottleLiftEvent` has never had (`.throttle_drop_pct` instead of the
   real `.drop_pct`) -- an `AttributeError` that bug (1) was masking. Once
   (1) is fixed, any session with a real dangerous throttle lift would hit
   this `AttributeError`, which propagates out of `compose_session_coaching`
   and is swallowed by `run_enhanced_coaching`'s `except Exception` --
   silently dropping the ENTIRE session to the v2 fallback.

These two tests drive the previously-dead code paths directly so a
regression of either fix fails loudly instead of vanishing into a swallowed
exception again.
"""
import numpy as np
import pandas as pd

from coaching.composers.corner_composer import _resolve_cause
from coaching.models import ThrottleLiftEvent
from coaching.taxonomy.causes import CauseTaxonomy
from pipeline.stages.s13_coaching_v3 import run_coaching_analyzers


def _dangerous_lift(drop_pct=55.0):
    return ThrottleLiftEvent(
        corner_id=3, s_position=120.0,
        throttle_before_pct=95.0, throttle_after_pct=40.0,
        drop_pct=drop_pct, drop_duration_s=0.4,
        lateral_grip_at_lift_pct=70.0, weight_shift_estimate_kg=45.0,
        yaw_rate_change_dps=12.5, resulted_in_correction=True,
        severity="dangerous",
    )


def _neutral_corner_perf():
    """No braking-point delta, no trail-brake data, no time-loss phases --
    forces `_resolve_cause` past branches 1-3 down to the throttle-lift
    branch (branch 4)."""
    return {"corner_id": 3, "braking_point_delta_m": 0.0, "time_loss_s": 0.1}


def test_resolve_cause_dangerous_lift_uses_real_drop_pct_field():
    """Finding 1's guard: a real ThrottleLiftEvent must resolve via
    `.drop_pct`, not the fictitious `.throttle_drop_pct` -- reverting the fix
    regresses this with an `AttributeError` instead of the expected tuple."""
    cause_id, delta_value = _resolve_cause(
        _neutral_corner_perf(), symptoms=None, trail_brake=None,
        throttle_lifts=[_dangerous_lift(drop_pct=55.0)],
        taxonomy=CauseTaxonomy(),
    )
    assert (cause_id, delta_value) == ("mid_corner_lift", 55.0)


def _make_lift_lap(drop_pct=60, lat_grip_pct=75):
    # Exact copy of tests/coaching/test_throttle_lift.py::_make_lift_lap --
    # kept local (rather than imported) because that module lives in the
    # `tests.coaching` package and this file needs the identical
    # dangerous-lift-shaped fixture without a cross-package import.
    n = 100
    dist = np.linspace(100, 200, n)
    throttle = np.full(n, 70.0)
    throttle[50:53] = [70, 30, 10]  # abrupt lift at midpoint
    throttle[53:60] = np.linspace(10, 70, 7)  # recover
    lat_accel = np.full(n, lat_grip_pct / 100 * 10)
    return pd.DataFrame({
        "Distance (m)": dist, "Speed (m/s)": np.full(n, 25.0),
        "Throttle (%)": throttle,
        "Lateral acceleration (m/s2)": lat_accel,
        "Time (s)": np.linspace(0, 4, n),
    })


def test_run_coaching_analyzers_populates_throttle_lifts_for_real_lift():
    """Finding 2's guard: `detect_throttle_lifts` must be called with the
    correct arity (including `vehicle_mass_kg`) -- the previous 3-arg call
    raised `TypeError` inside a swallowed `except Exception`, so
    `throttle_lifts` was ALWAYS empty regardless of input."""
    corner = {"corner_id": 1, "s_start": 100.0, "s_end": 200.0, "vehicle_class": "kart"}
    lap = _make_lift_lap(drop_pct=60, lat_grip_pct=75)

    bundle = run_coaching_analyzers(
        corner_perfs=[corner], best_lap_df=lap,
        theoretical_result=None, friction_model=None,
        resampled_laps={0: lap}, available_columns=set(lap.columns),
    )

    assert bundle["throttle_lifts"], "throttle_lifts must not be empty for a real lift"
    assert any(tl.severity == "dangerous" for tl in bundle["throttle_lifts"])
