"""``run_coaching_v2`` must hand the coaching modules OBJECTS, not dicts.

THE DEFECT THIS GUARDS (live in production until 2026-08-06).

``run_mrp_detection_v2`` serialises every ``CornerEvents`` with ``.to_dict()``
so its result can sit in the JSON summary, and ``run_handling_analysis_v2``
does the same with ``e.__dict__``. The orchestrator then feeds both straight
into ``run_coaching_v2`` (orchestrator.py:1304-1306), which passed them
unchanged to ``generate_basic_coaching`` / ``generate_advanced_coaching``.

Those do ATTRIBUTE access -- ``corner_events.mrp_m`` (coaching_basic.py:127),
``ev.cause`` / ``ev.severity`` (coaching_advanced.py:58-60) -- so every
section raised ``AttributeError`` inside the per-section ``except Exception``
at coaching_basic.py:423, which substituted ``_empty_coaching``.

The result: every corner of every session that had MRP events reported
"No data available for this section." with all four time losses 0.0, while
the stage reported success. Measured on a synthetic single-corner lap, the
object path produces "Apex speed 43 km/h vs 108 km/h potential -- lost 1.30s"
and 10 populated fields; the dict path produced 6, all of them zeros and
placeholders.

WHY THESE TESTS GO THROUGH ``run_coaching_v2`` AND NOT THE COACHING MODULES:
the coaching functions were never wrong -- they were handed the wrong types.
A test that calls ``generate_basic_coaching`` with properly-built
``CornerEvents`` passes both before and after the fix and proves nothing.
The contract that broke is the one at the stage boundary, so that is where
these assert.
"""
import logging

import numpy as np
import pandas as pd
import pytest

import mrp_detector
import track_decomposition as td
from pipeline.stages import s10b_corners

# The marker _empty_coaching writes into every field it cannot fill.
NO_DATA = "No data available for this section."


def _lap(lap_len_m: float = 400.0, n: int = 800) -> pd.DataFrame:
    """One corner mid-lap: fast straights either side, a clear speed minimum.

    The speed dip has to be deep and smooth enough for the MRP detector to
    find a rotation point -- a flat or noisy trace yields no events, and then
    every assertion below would pass vacuously on an empty dict.
    """
    dist = np.linspace(0.0, lap_len_m, n)
    frac = dist / lap_len_m
    speed = 32.0 - 20.0 * np.exp(-((frac - 0.5) ** 2) / (2 * 0.06 ** 2))
    return pd.DataFrame({
        "Distance (m)": dist,
        "Speed (m/s)": speed,
        "speed_mps": speed,
    })


def _section_dicts() -> list[dict]:
    """Sections in the dict form the orchestrator passes between stages."""
    return [{
        "section_id": 1,
        "section_type": "corner",
        "corner_type": "medium",
        "s_start": 140.0,
        "s_end": 260.0,
        "direction": "left",
        "geometric_apex": 200.0,
        "exit_importance": 0.8,
        "sub_corners": None,
    }]


def _section_objs() -> list:
    return [td.TrackSection(
        section_id=1, section_type="corner", corner_type="medium",
        s_start=140.0, s_end=260.0, direction="left",
        geometric_apex=200.0, exit_importance=0.8,
    )]


@pytest.fixture
def serialised_events() -> dict:
    """Exactly what ``run_mrp_detection_v2`` returns: section_id -> dict."""
    events = mrp_detector.detect_all_mrp(_section_objs(), _lap())
    assert events, (
        "fixture produced no MRP events, so every assertion below would be "
        "vacuous -- the corner needs a deeper or smoother speed minimum"
    )
    return {sid: ev.to_dict() for sid, ev in events.items()}


def test_the_fixture_really_is_dicts(serialised_events):
    """Pins the premise. If the stage stopped serialising, these tests would
    silently start testing nothing."""
    assert serialised_events
    for sid, ev in serialised_events.items():
        assert isinstance(ev, dict), f"section {sid}: expected a dict, got {type(ev).__name__}"
        assert "mrp_m" in ev


def test_coaching_is_not_empty_when_events_arrive_as_dicts(serialised_events):
    """The regression: dicts in must still produce real coaching out."""
    result = s10b_corners.run_coaching_v2(
        _section_dicts(), serialised_events, {}, _lap(),
    )
    assert result, "run_coaching_v2 returned nothing"

    for sc in result:
        hints = sc.get("coaching_hints") or []
        assert NO_DATA not in hints, (
            f"section {sc.get('section_id')} fell back to _empty_coaching: "
            f"{hints}. The stage handed the coaching module a dict where it "
            "does attribute access, and the per-section `except Exception` "
            "swallowed the AttributeError."
        )
        assert sc.get("primary_focus") != NO_DATA


def test_dict_events_produce_the_same_coaching_as_objects():
    """The strongest form: serialising must not change the OUTPUT at all.

    Asserting merely "not empty" would still pass if the fix produced
    different-but-nonempty coaching. Round-tripping through ``to_dict`` is
    supposed to be lossless, so the two runs must agree.
    """
    lap = _lap()
    events_objs = mrp_detector.detect_all_mrp(_section_objs(), lap)
    assert events_objs, "no MRP events -- comparison would be vacuous"
    events_dicts = {sid: ev.to_dict() for sid, ev in events_objs.items()}

    from_objects = s10b_corners.run_coaching_v2(_section_dicts(), events_objs, {}, lap)
    from_dicts = s10b_corners.run_coaching_v2(_section_dicts(), events_dicts, {}, lap)

    assert from_objects and from_dicts
    assert len(from_objects) == len(from_dicts)
    for a, b in zip(from_objects, from_dicts):
        assert a.get("coaching_hints") == b.get("coaching_hints")
        assert a.get("primary_focus") == b.get("primary_focus")
        assert a.get("time_loss_total_s") == b.get("time_loss_total_s")


def test_time_losses_are_not_all_zero(serialised_events):
    """_empty_coaching zeroes every time loss, which reads as a perfect lap.

    On this fixture the driver is far off the optimal apex speed, so a real
    computation must report a non-zero total.
    """
    result = s10b_corners.run_coaching_v2(
        _section_dicts(), serialised_events, {}, _lap(),
    )
    totals = [sc.get("time_loss_total_s") for sc in result]
    assert any(t for t in totals if t), (
        f"every section reported zero time loss ({totals}) -- the signature "
        "of _empty_coaching, not of a driver who nailed every corner"
    )


def test_handling_events_as_dicts_do_not_break_coaching(serialised_events):
    """``run_handling_analysis_v2`` serialises handling events with
    ``e.__dict__``; coaching_advanced.py:58-60 reads ``.cause``/``.severity``
    off them. Same contract, same failure mode."""
    handling_dicts = {1: [{
        "corner_id": 1,
        "event_type": "understeer",
        "severity": "moderate",
        "s_start": 150.0,
        "s_end": 200.0,
        "duration_s": 1.2,
        "magnitude": 0.5,
        "cause": "entry_speed",
        "cause_detail": "carried too much speed to the apex",
        "time_cost_s": 0.3,
        "corner_phase": "entry",
    }]}
    result = s10b_corners.run_coaching_v2(
        _section_dicts(), serialised_events, handling_dicts, _lap(),
    )
    assert result
    for sc in result:
        assert NO_DATA not in (sc.get("coaching_hints") or [])


def test_no_exception_is_swallowed_during_coaching(serialised_events, caplog):
    """The bug was invisible because the handler logged and carried on.

    Assert on the log too: if a future change reintroduces a swallowed
    AttributeError, the content assertions above might still pass by luck,
    but this will not.
    """
    with caplog.at_level(logging.ERROR):
        s10b_corners.run_coaching_v2(
            _section_dicts(), serialised_events, {}, _lap(),
        )
    swallowed = [r for r in caplog.records if "Coaching failed for section" in r.getMessage()]
    assert not swallowed, (
        f"{len(swallowed)} section(s) raised inside the coaching try/except: "
        f"{[r.getMessage() for r in swallowed]}"
    )
