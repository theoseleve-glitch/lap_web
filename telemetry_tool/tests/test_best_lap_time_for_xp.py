"""Personal-best XP needs a lap TIME, and ``select_best_lap`` returns pairs.

THE DEFECT THIS GUARDS (live in production until 2026-08-06).

``pipeline/orchestrator.py`` computed the session's best lap for the
gamification stage as ``min(valid_times)``, where ``valid_times`` comes from
``s08_metrics.select_best_lap`` and is documented as
``list[tuple[int, float]]`` -- ``(lap_key, time)`` pairs.

That is wrong twice: it yields a tuple (which ``gamification/xp.py:68``
then compares against a float, raising ``TypeError``, swallowed by the
orchestrator's "Gamification stage failed (non-fatal)" handler), and tuple
ordering is element-wise, so it ranks by LAP NUMBER before time.

The second point is why "just unwrap it" is not enough, and why the fastest
lap in these fixtures is deliberately never lap 1: a fix that returned
``min(valid_times)[1]`` would pass a test whose fastest lap happened to come
first, and still be wrong.
"""
import pytest

from pipeline.orchestrator import _best_lap_time


def test_returns_a_float_not_a_tuple():
    """The TypeError that silently killed the whole gamification stage."""
    result = _best_lap_time([(1, 62.5), (2, 60.1), (3, 61.0)])
    assert isinstance(result, float), f"expected a float, got {type(result).__name__}"
    # The comparison xp.py:68 performs. Under the old code this raised
    # TypeError: '<' not supported between instances of 'tuple' and 'float'.
    assert (result < 65.0) is True


def test_returns_the_fastest_time_not_the_earliest_lap():
    """Tuple ordering compares lap number first -- the fastest lap here is
    lap 3, while the lowest lap number is 1."""
    assert _best_lap_time([(1, 62.5), (2, 61.4), (3, 59.9)]) == 59.9


def test_lap_ordering_does_not_affect_the_answer():
    """Same laps, shuffled. A lap-number-ordered implementation would differ."""
    ascending = _best_lap_time([(1, 62.5), (2, 61.4), (3, 59.9)])
    shuffled = _best_lap_time([(3, 59.9), (1, 62.5), (2, 61.4)])
    assert ascending == shuffled == 59.9


def test_fastest_lap_is_not_the_first_entry():
    """Guards the fixture itself: if the fastest lap were also lap 1, every
    assertion above would pass under the original buggy expression."""
    laps = [(1, 62.5), (2, 61.4), (3, 59.9)]
    assert min(laps)[1] != _best_lap_time(laps), (
        "fixture is too weak -- min(pairs) happens to agree with the correct "
        "answer here, so it cannot distinguish the bug from the fix"
    )


def test_empty_and_none_give_none():
    """``award_session_xp`` treats None as 'no best lap' and skips the award."""
    assert _best_lap_time([]) is None
    assert _best_lap_time(None) is None


def test_single_lap():
    assert _best_lap_time([(7, 58.2)]) == 58.2


def test_matches_the_shape_select_best_lap_actually_returns():
    """Round-trip through the real producer rather than a hand-made list.

    If ``select_best_lap`` ever stops returning pairs, this fails and the
    helper needs revisiting -- rather than silently returning nonsense.
    """
    import numpy as np
    import pandas as pd

    from pipeline.stages import s08_metrics

    laps = {k: pd.DataFrame({"Distance (m)": np.linspace(0, 400, 50)})
            for k in (1, 2, 3)}
    lap_times = [62.5, 61.4, 59.9]

    _key, _df, valid_times = s08_metrics.select_best_lap(
        laps, lap_times, excluded_laps=set(), invalid_lap_set=set(),
    )
    assert valid_times, "producer returned nothing -- test would be vacuous"
    for item in valid_times:
        assert isinstance(item, tuple) and len(item) == 2, (
            f"select_best_lap no longer returns (lap, time) pairs: {item!r}"
        )
    assert _best_lap_time(valid_times) == pytest.approx(59.9)
