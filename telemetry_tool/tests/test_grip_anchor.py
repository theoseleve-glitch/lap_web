"""Phase 1 grip anchor — tier vocabulary and the pure decision function.

The anchor answers "you used X% of the available grip here" and ALWAYS says
what "available" was measured against. Fail-safe: any doubt degrades toward
the lower tier; an unknown signal never yields a physics tier.
"""
import numpy as np
import pytest


def test_tier_vocabulary_is_closed():
    import grip_anchor as ga

    assert ga.TIERS == frozenset({
        ga.TIER_PHYSICS_ELLIPSE_FITTED,
        ga.TIER_PHYSICS_ELLIPSE_DEFAULT_P2,
        ga.TIER_DRIVER_BEST_SESSION,
        ga.TIER_REFUSED,
    })
    # Cross-session tier must NOT exist yet — corner identity is not stable
    # across sessions, so a driver_best_track value would be a promise we
    # cannot keep. Phase 2 adds it as a NEW value, not a redefinition.
    assert not hasattr(ga, "TIER_DRIVER_BEST_TRACK")


def test_only_physics_tiers_are_quotable_as_physics():
    import grip_anchor as ga

    assert ga.is_quotable_as_physics(ga.TIER_PHYSICS_ELLIPSE_FITTED) is True
    assert ga.is_quotable_as_physics(ga.TIER_PHYSICS_ELLIPSE_DEFAULT_P2) is True
    assert ga.is_quotable_as_physics(ga.TIER_DRIVER_BEST_SESSION) is False
    assert ga.is_quotable_as_physics(ga.TIER_REFUSED) is False
    assert ga.is_quotable_as_physics(None) is False
    assert ga.is_quotable_as_physics("something_invented") is False


def test_reserved_reasons_exist_for_phase_2_prerequisites():
    """Reserving these now forces Phase 2 to handle them deliberately."""
    import grip_anchor as ga

    assert ga.REASON_CONDITION_UNKNOWN == "condition_unknown"
    assert ga.REASON_CORNER_IDENTITY_UNSTABLE == "corner_identity_unstable"
