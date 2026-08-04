"""Fence: the distance-quality gate is currently DEAD and must stay that way
until repairing it is a deliberate, separately-reviewed decision.

orchestrator.py stores distance_quality as a dict (.to_dict()) while every
consumer checks hasattr(dq, "gate_advanced").  hasattr on a dict is False, so
degraded sessions are never gated.  Repairing this would start suppressing
theoretical laps and coaching on sessions that currently emit them.

The gate is checked at FOUR call sites, and this fence pins the exact literal
expression at each one (not just the bare tokens "hasattr(" / "gate_advanced",
which recur elsewhere in these modules for unrelated optional-attribute
checks, so a bare-token substring check cannot discriminate a real repair
from an untouched file):

  orchestrator.py:1043        hasattr(_dq, "gate_advanced")                x1
  s10_theoretical.py:84       hasattr(distance_quality, "gate_advanced")   x1
  s13_scoring.py:142,170      hasattr(distance_quality, "gate_advanced")   x2

orchestrator.py:1444 and :1457 reuse the `_dq_gated` boolean computed once at
:1043 rather than re-calling hasattr(), so :1043 is the only hasattr call
site in that module for this gate.

A genuine behavioural fence (call the real function, pass a dict, assert the
gate does not engage) was tried first and rejected for all four sites:
  - run_theoretical() needs a full session's worth of real resampled laps,
    curvature profile, vehicle params etc. to reach the gate at all, and if
    the gate incorrectly fails to engage it walks into real solver-selection
    code rather than returning cleanly - not callable without substantial
    fake scaffolding.
  - run_coaching_guide() is a documented permanent no-op (see its own
    docstring): it returns None whether or not the gate engages, so it
    cannot discriminate gated from ungated behaviour at all.
  - run_coaching_v2() only diverges once corner_analysis's real
    generate_coaching_v2() is actually exercised, which needs realistically
    shaped corner data or mocking of module internals - itself heavy
    scaffolding, and the exact failure mode (both branches falling through
    to the same `return None`) mirrors the false-pass this fence replaces.
  - orchestrator.py:1043 lives inside the main pipeline orchestration
    function, reachable only with a full session's upstream state.

So this fence asserts on the precise source text instead: the exact literal
call expression, per file, with an exact occurrence count. Changing any site
to a dict-style access (e.g. distance_quality.get("gate_advanced")) removes
that literal and the corresponding count assertion goes red.
"""
import inspect


def test_hasattr_gate_is_false_for_a_dict():
    """Documents the mechanism, so the fence below is understandable."""
    dq = {"gate_advanced": True, "monotonic_ratio": 0.4}
    assert hasattr(dq, "gate_advanced") is False


def test_consumers_still_use_hasattr_not_dict_access():
    """If any of these counts fail, someone changed a gate call site. That
    may be correct - but it is a behaviour change that must ship on its own
    branch with its own review, not inside a coordinate-frame fix.

    Each assertion matches the exact literal call expression, not the bare
    tokens `hasattr(` or `gate_advanced` - those bare tokens recur elsewhere
    in these modules for unrelated optional-attribute checks and would not
    go red if only the gate's own call were rewritten."""
    from pipeline import orchestrator
    from pipeline.stages import s10_theoretical, s13_scoring

    orch_src = inspect.getsource(orchestrator)
    s10_src = inspect.getsource(s10_theoretical)
    s13_src = inspect.getsource(s13_scoring)

    assert orch_src.count('hasattr(_dq, "gate_advanced")') == 1, (
        "orchestrator.py:1043 no longer contains the exact gate expression - "
        "see the module docstring in this file before accepting"
    )
    assert s10_src.count('hasattr(distance_quality, "gate_advanced")') == 1, (
        "s10_theoretical.py:84 no longer contains the exact gate expression - "
        "see the module docstring in this file before accepting"
    )
    assert s13_src.count('hasattr(distance_quality, "gate_advanced")') == 2, (
        "s13_scoring.py:142/170 no longer contain the exact gate expression - "
        "see the module docstring in this file before accepting"
    )
