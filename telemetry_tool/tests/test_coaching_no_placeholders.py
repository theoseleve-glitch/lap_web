"""Guard test: coaching payloads must never leak unrendered template tokens
or hardcoded 0.0% magnitudes masquerading as real measurements.

Regression coverage for the customer-visible bug where `_pick_narrative`
returned the raw (un-.format'ed) narrative template, and `_build_placeholders`
hardcoded several per-corner magnitudes to 0.0 regardless of real analyzer
output.
"""
import json
import re

from coaching.composers.corner_composer import _build_placeholders
from coaching.composers.session_composer import compose_session_coaching
from coaching.models import ThrottleLiftEvent
from coaching.taxonomy.causes import CauseTaxonomy

# Magnitude tokens that `_build_placeholders` previously hardcoded to 0.0
# and now sources from real throttle-lift analyzer output (or omits entirely).
_LIFT_MAGNITUDE_KEYS = ("throttle_drop_pct", "lift_duration_s", "weight_shift_kg", "yaw_spike")

# NOTE: `tests.coaching.test_session_composer._corner_perfs` cannot be imported
# by dotted path here — this worktree's pytest.ini rootdir sits one level above
# `telemetry_tool/`, and that parent also has its own top-level `tests/`
# package, so `import tests.coaching` resolves to the wrong `tests` package
# under regular (non-pytest-collection) import machinery. Per the brief's
# fallback ("construct inline the same way"), this is an exact copy of the
# real fixture body from tests/coaching/test_session_composer.py::_corner_perfs.
def _corner_perfs(n=5):
    return [
        {"corner_id": i, "s_start": i * 100, "s_end": i * 100 + 50,
         "theoretical_entry_speed_mps": 25.0, "actual_entry_speed_mps": 22.0,
         "theoretical_apex_speed_mps": 18.0, "actual_apex_speed_mps": 16.0,
         "theoretical_exit_speed_mps": 23.0, "actual_exit_speed_mps": 20.0,
         "braking_point_delta_m": 10.0,
         "time_loss_s": 0.3, "time_loss_braking_s": 0.1,
         "time_loss_apex_speed_s": 0.12, "time_loss_exit_s": 0.08,
         "grip_utilisation_pct": 65.0}
        for i in range(1, n + 1)
    ]


def test_payload_has_no_unrendered_placeholders_or_fake_zero_pct():
    result = compose_session_coaching(
        corner_perfs=_corner_perfs(), coaching_v2={}, scores={"grade": "B"},
        lap_metrics=[], driving_style={}, analyzer_results={},
        taxonomy=CauseTaxonomy(), vehicle_class="kart",
        driver_history=None, previous_goals=None,
    )
    blob = json.dumps(result.to_dict())
    # Broadened vs. the brief's literal regex to also catch format-spec tokens
    # like "{std_dev_s:.2f}" (the actual template that fires for this fixture:
    # grade "B" + an "early_braking_confidence"/"confidence" focus area picks
    # the ("B-C", "consistency") narrative variant, which only uses a
    # format-spec token — the plain r"\{[a-z_]+\}" pattern from the brief
    # would miss it and pass even with the un-rendered-narrative bug live).
    assert not re.search(r"\{[a-z_]+(?::[^}]*)?\}", blob), (
        f"unrendered token in payload: {blob[:400]}"
    )
    assert "0.0%" not in blob, "fabricated 0.0% magnitude leaked to payload"
    assert "Unknown cause" not in blob


# ---------------------------------------------------------------------------
# Direct guard for the `_build_placeholders` real-magnitude fix.
#
# The payload-level test above does NOT actually exercise the magnitude path:
# its fixture (all corners braking_point_delta_m=10.0, analyzer_results={})
# only ever resolves to `early_braking_confidence`, whose templates use
# {delta_m}/{time_loss_s} and never the {throttle_drop_pct}/{weight_shift_kg}/
# {lift_duration_s}/{yaw_spike} tokens — so reverting `_build_placeholders` to
# the hardcoded-0.0 version still passes it. These two tests call
# `_build_placeholders` directly so a revert of that fix FAILS.
# ---------------------------------------------------------------------------

def _corner_perf():
    # Minimal corner_perf shaped like the real _corner_perf fixture; the
    # magnitude tokens under test come from the throttle-lift arg, not here.
    return {"corner_id": 3, "braking_point_delta_m": 12.0, "time_loss_s": 0.35,
            "grip_utilisation_pct": 68.0}


def _dangerous_lift():
    return ThrottleLiftEvent(
        corner_id=3, s_position=120.0,
        throttle_before_pct=95.0, throttle_after_pct=35.0,
        drop_pct=60.0, drop_duration_s=0.35,
        lateral_grip_at_lift_pct=70.0, weight_shift_estimate_kg=45.0,
        yaw_rate_change_dps=12.5, resulted_in_correction=True,
        severity="dangerous",
    )


def test_build_placeholders_threads_real_throttle_lift_magnitudes():
    """A real ThrottleLiftEvent's magnitudes must reach the placeholders,
    NOT the old hardcoded 0.0 — reverting the fix regresses these equalities."""
    placeholders = _build_placeholders(
        _corner_perf(), "T3", exit_cascade=None, throttle_lifts=[_dangerous_lift()],
    )
    assert placeholders["throttle_drop_pct"] == 60.0
    assert placeholders["lift_duration_s"] == 0.35
    assert placeholders["weight_shift_kg"] == 45.0
    assert placeholders["yaw_spike"] == 12.5
    # None of the real magnitudes should read as the fabricated zero default.
    for key in _LIFT_MAGNITUDE_KEYS:
        assert placeholders[key] != 0.0


def test_build_placeholders_omits_magnitudes_when_no_analyzer_data():
    """With no throttle-lift data, the magnitude tokens must be OMITTED, not
    fabricated as 0.0 — reverting to the hardcoded version (which always sets
    them to 0.0) regresses this. `pct_increase` has no analyzer source at all
    and must never appear."""
    placeholders = _build_placeholders(
        _corner_perf(), "T3", exit_cascade=None, throttle_lifts=None,
    )
    for key in _LIFT_MAGNITUDE_KEYS:
        assert key not in placeholders, f"{key} fabricated with no analyzer data"
    assert "pct_increase" not in placeholders
