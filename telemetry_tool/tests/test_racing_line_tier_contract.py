"""Consumer contract (spec C, Task 7).

The public guarantee every racing-line consumer (Race Brief Lanes 3-4, the
webapp, any renderer) relies on: the tier vocabulary is closed at exactly
three values, and ONLY ``optimal_line`` may be drawn as a racing line. This
test is the executable contract — if it breaks, a consumer somewhere is about
to render a line it must not.
"""
from track_surface.honesty import (
    TIER_OPTIMAL_LINE,
    TIER_REFUSED,
    TIER_SPEED_PROFILE_ONLY,
    TIERS,
    is_drawable_as_line,
)


def test_tier_vocabulary_is_closed_at_three():
    assert set(TIERS) == {TIER_OPTIMAL_LINE, TIER_SPEED_PROFILE_ONLY, TIER_REFUSED}


def test_only_optimal_line_is_drawable():
    assert is_drawable_as_line(TIER_OPTIMAL_LINE) is True
    # Everything else — including a speed profile, a refusal, an unknown tier,
    # or None — must NOT be drawn as a racing line.
    for tier in (TIER_SPEED_PROFILE_ONLY, TIER_REFUSED, None, "", "optimal", "garbage"):
        assert is_drawable_as_line(tier) is False


def test_speed_profile_is_explicitly_undrawable():
    # The single most important guarantee: a speed_profile_only is a speed
    # overlay, never a line. This is the failure mode the honesty layer exists
    # to prevent.
    assert is_drawable_as_line(TIER_SPEED_PROFILE_ONLY) is False
