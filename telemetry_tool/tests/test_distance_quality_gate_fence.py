"""Fence: the distance-quality gate is currently DEAD and must stay that way
until repairing it is a deliberate, separately-reviewed decision.

orchestrator.py stores distance_quality as a dict (.to_dict()) while every
consumer checks hasattr(dq, "gate_advanced").  hasattr on a dict is False, so
degraded sessions are never gated.  Repairing this would start suppressing
theoretical laps and coaching on sessions that currently emit them.
"""


def test_hasattr_gate_is_false_for_a_dict():
    """Documents the mechanism, so the fence below is understandable."""
    dq = {"gate_advanced": True, "monotonic_ratio": 0.4}
    assert hasattr(dq, "gate_advanced") is False


def test_consumers_still_use_hasattr_not_dict_access():
    """If this fails, someone repaired the gate. That may be correct - but it
    is a behaviour change that must ship on its own branch with its own
    review, not inside a coordinate-frame fix."""
    import inspect
    from pipeline.stages import s10_theoretical

    src = inspect.getsource(s10_theoretical)
    assert 'hasattr(' in src and 'gate_advanced' in src, (
        "the distance-quality gate appears to have been changed - see the "
        "module docstring in this file before accepting"
    )
