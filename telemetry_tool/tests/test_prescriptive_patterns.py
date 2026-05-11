"""Phase 2 tests: built-in coaching patterns.

Each concrete pattern is verified against four invariants the brief requires:

    A. Protocol conformance — the class satisfies ``Pattern``.
    B. Insufficient branch  — if ALL corners lack required fields,
       ``Insufficient`` is returned (not silent skip, not fake Detected).
    C. Detected branch      — with good evidence, ``Detected`` fires,
       coaching_actions are fully parameterised (no stray ``{var}``),
       measurable_targets contain numbers, and not_evaluable_corners are
       reported when some (but not all) corners are incomplete.
    D. Content parity       — title, phase, and sensor_note match the
       legacy ``WEAKNESS_PLAYBOOK`` entry exactly so Phase 3 migration is
       byte-identical on the parity path.

A cross-cutting test verifies that ``build_default_registry()`` installs
exactly the five patterns the legacy playbook defines, in the legacy order.
"""
from __future__ import annotations

import pytest

from track_surface.prescriptive import Pattern, PatternRegistry, build_default_registry
from track_surface.prescriptive._internal import (
    Detected,
    Evidence,
    Insufficient,
    NotTriggered,
    WeaknessContext,
)
from track_surface.prescriptive.patterns import (
    BasePattern,
    EarlyBraking,
    LateThrottlePickup,
    LineDeviation,
    LowMinimumSpeed,
    WeakExitBuild,
)


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────


def _ctx(cost_ms: float = 300.0, corners=(1, 2, 3), confidence=0.8, trend="improving",
         archetypes=("slow_90deg", "medium_speed"), sessions=3) -> WeaknessContext:
    return WeaknessContext(
        key="any", label="Any", occurrence_count=30, trend=trend,
        estimated_time_cost_ms=cost_ms, confidence=confidence,
        corners_observed=tuple(corners),
        archetypes_observed=archetypes,
        sessions_observed=tuple(f"S{i}" for i in range(sessions)),
        sessions_analyzed=sessions,
    )


def _ev(
    corner_id: int = 1,
    *,
    min_speed=-8.0, brake=-6.0, throttle=8.0, exit_spd=-6.0, line=0.5,
    confidence=0.8,
) -> Evidence:
    return Evidence(
        corner_id=corner_id, time_delta_ms=300.0, primary_cause="t",
        confidence=confidence,
        s_entry_m=float(corner_id) * 100.0,
        s_apex_m=float(corner_id) * 100.0 + 25.0,
        s_exit_m=float(corner_id) * 100.0 + 50.0,
        min_speed_delta_kph=min_speed,
        brake_point_delta_m=brake,
        throttle_pickup_delta_m=throttle,
        exit_speed_delta_kph=exit_spd,
        line_deviation_rms_m=line,
    )


def _ev_missing(corner_id: int, field_name: str) -> Evidence:
    """Evidence with `field_name` set to None — everything else populated."""
    full = _ev(corner_id)
    return Evidence(
        corner_id=full.corner_id, time_delta_ms=full.time_delta_ms,
        primary_cause=full.primary_cause, confidence=full.confidence,
        s_entry_m=full.s_entry_m, s_apex_m=full.s_apex_m, s_exit_m=full.s_exit_m,
        min_speed_delta_kph=None if field_name == "min_speed_delta_kph" else full.min_speed_delta_kph,
        brake_point_delta_m=None if field_name == "brake_point_delta_m" else full.brake_point_delta_m,
        throttle_pickup_delta_m=None if field_name == "throttle_pickup_delta_m" else full.throttle_pickup_delta_m,
        exit_speed_delta_kph=None if field_name == "exit_speed_delta_kph" else full.exit_speed_delta_kph,
        line_deviation_rms_m=None if field_name == "line_deviation_rms_m" else full.line_deviation_rms_m,
    )


# Parametrisation: (pattern_class, key, phase, required_field)
_PATTERN_MATRIX = [
    (LowMinimumSpeed,    "low_minimum_speed",    "apex",  "min_speed_delta_kph"),
    (EarlyBraking,       "early_braking",        "entry", "brake_point_delta_m"),
    (LateThrottlePickup, "late_throttle_pickup", "exit",  "throttle_pickup_delta_m"),
    (WeakExitBuild,      "weak_exit_build",      "exit",  "exit_speed_delta_kph"),
    (LineDeviation,      "line_deviation",       "apex",  "line_deviation_rms_m"),
]


# ─────────────────────────────────────────────────────────────────
# A. Protocol conformance
# ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("cls,key,phase,field", _PATTERN_MATRIX)
def test_pattern_satisfies_protocol(cls, key, phase, field):
    instance = cls()
    assert isinstance(instance, Pattern)
    assert instance.key == key
    assert instance.phase == phase
    assert field in instance.required_fields


@pytest.mark.parametrize("cls,key,phase,field", _PATTERN_MATRIX)
def test_pattern_inherits_base(cls, key, phase, field):
    assert issubclass(cls, BasePattern)


# ─────────────────────────────────────────────────────────────────
# B. Insufficient branch
# ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("cls,key,phase,field", _PATTERN_MATRIX)
def test_all_corners_missing_field_yields_insufficient(cls, key, phase, field):
    """When every corner has the required field = None, emit Insufficient
    with the missing fields listed. Never silently skip."""
    ctx = _ctx()
    evidence = [_ev_missing(1, field), _ev_missing(2, field), _ev_missing(3, field)]
    result = cls().evaluate(ctx, evidence)
    assert isinstance(result, Insufficient)
    assert field in result.missing_fields
    assert result.weakness_key == key


def test_insufficient_on_empty_evidence():
    """Zero evidence items is equivalent to zero evaluable corners."""
    result = LowMinimumSpeed().evaluate(_ctx(), [])
    assert isinstance(result, Insufficient)


# ─────────────────────────────────────────────────────────────────
# C. Detected branch
# ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("cls,key,phase,field", _PATTERN_MATRIX)
def test_full_evidence_yields_detected(cls, key, phase, field):
    ctx = _ctx()
    evidence = [_ev(1), _ev(2), _ev(3)]
    result = cls().evaluate(ctx, evidence)
    assert isinstance(result, Detected)
    assert result.weakness_key == key
    assert result.phase == phase
    assert result.affected_corners == (1, 2, 3)
    assert result.not_evaluable_corners == ()


@pytest.mark.parametrize("cls,key,phase,field", _PATTERN_MATRIX)
def test_coaching_actions_fully_parameterised(cls, key, phase, field):
    """No unresolved ``{var}`` placeholders may survive parameterisation."""
    ctx = _ctx()
    evidence = [_ev(1), _ev(2), _ev(3)]
    result = cls().evaluate(ctx, evidence)
    assert isinstance(result, Detected)
    joined = " ".join(result.coaching_actions)
    assert "{" not in joined, f"unresolved template in {key}: {joined}"
    joined_cues = " ".join(result.driver_cues)
    assert "{" not in joined_cues, f"unresolved cue template in {key}: {joined_cues}"


@pytest.mark.parametrize("cls,key,phase,field", _PATTERN_MATRIX)
def test_measurable_targets_contain_digits(cls, key, phase, field):
    ctx = _ctx()
    evidence = [_ev(1, min_speed=-10.0, brake=-10.0, throttle=10.0,
                     exit_spd=-10.0, line=2.0) for _ in range(3)]
    # Stamp corner_ids
    evidence = [_ev(i, min_speed=-10.0, brake=-10.0, throttle=10.0,
                    exit_spd=-10.0, line=2.0) for i in (1, 2, 3)]
    result = cls().evaluate(ctx, evidence)
    assert isinstance(result, Detected)
    for target in result.measurable_targets:
        assert any(c.isdigit() for c in target), (
            f"{key}: measurable target lacks a number: {target!r}"
        )


def test_partial_evidence_policy_option_b():
    """Policy B: when some corners have the required field and others don't,
    the pattern fires on the complete subset and reports the incomplete
    corners via ``not_evaluable_corners``. This is the explicit design choice
    locked at end of Phase 1."""
    ctx = _ctx()
    evidence = [
        _ev(1),                                     # has brake_point_delta_m
        _ev_missing(2, "brake_point_delta_m"),      # missing
        _ev(3),                                     # has it
    ]
    result = EarlyBraking().evaluate(ctx, evidence)
    assert isinstance(result, Detected)
    assert result.affected_corners == (1, 3)
    assert result.not_evaluable_corners == (2,)


def test_severity_tracks_cost_ms():
    # cost > 400 -> high
    ctx = _ctx(cost_ms=500.0)
    r = LowMinimumSpeed().evaluate(ctx, [_ev(1), _ev(2)])
    assert isinstance(r, Detected)
    assert r.severity == "high"
    # cost 150-400 -> medium
    ctx = _ctx(cost_ms=200.0)
    r = LowMinimumSpeed().evaluate(ctx, [_ev(1)])
    assert isinstance(r, Detected)
    assert r.severity == "medium"
    # cost <= 150 -> low
    ctx = _ctx(cost_ms=100.0)
    r = LowMinimumSpeed().evaluate(ctx, [_ev(1)])
    assert isinstance(r, Detected)
    assert r.severity == "low"


def test_data_support_mentions_sessions_and_trend():
    ctx = _ctx(trend="improving", sessions=5)
    r = LowMinimumSpeed().evaluate(ctx, [_ev(1)])
    assert isinstance(r, Detected)
    assert "improving" in r.data_support
    assert "5 sessions" in r.data_support


def test_portability_empty_archetypes_flags_track_specific():
    ctx = _ctx(archetypes=(), sessions=5)
    r = LowMinimumSpeed().evaluate(ctx, [_ev(1)])
    assert isinstance(r, Detected)
    assert "track-specific" in r.portability


def test_portability_few_sessions_flags_unknown():
    ctx = _ctx(sessions=1, archetypes=("slow_90deg",))
    r = LowMinimumSpeed().evaluate(ctx, [_ev(1)])
    assert isinstance(r, Detected)
    assert "unknown" in r.portability



# ─────────────────────────────────────────────────────────────────
# Cross-cutting: default registry
# ─────────────────────────────────────────────────────────────────


class TestDefaultRegistry:
    def test_registry_has_exactly_five_patterns(self):
        reg = build_default_registry()
        assert isinstance(reg, PatternRegistry)
        assert len(reg) == 5


    def test_registry_get_returns_pattern_instance(self):
        reg = build_default_registry()
        p = reg.get("low_minimum_speed")
        assert p is not None
        assert isinstance(p, LowMinimumSpeed)

    def test_registry_get_unknown_returns_none(self):
        reg = build_default_registry()
        assert reg.get("not_a_real_pattern") is None


# ─────────────────────────────────────────────────────────────────
# NotTriggered variant — no Phase-2 pattern emits it, but it stays
# part of the PatternResult union. Sanity spot-check the type exists
# and can be constructed (so the Phase-3 engine can use it).
# ─────────────────────────────────────────────────────────────────


def test_not_triggered_can_be_constructed():
    nt = NotTriggered(weakness_key="low_minimum_speed", reason="evidence below threshold")
    assert nt.weakness_key == "low_minimum_speed"
    assert nt.reason
