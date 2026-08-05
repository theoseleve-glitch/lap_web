"""Driving events — the record and its vocabularies.

Every event is a checkable claim: what this lap did, what the reference lap
did, which lap that was, and how many samples the window held. There is
deliberately no confidence float -- see the spec's section 5.5.
"""
import pytest


def test_vocabularies_are_closed():
    import driving_events as de

    assert de.VALIDITIES == frozenset({
        de.VALIDITY_MEASURED,
        de.VALIDITY_INSUFFICIENT_SAMPLES,
        de.VALIDITY_NOT_MEASURABLE,
    })
    assert de.EVENT_TYPES == frozenset({
        "over_slowing", "late_throttle", "re_braking", "envelope_under_use",
    })


def test_there_is_no_confidence_field():
    """A probability nobody can calibrate is worse than no number at all."""
    import dataclasses
    import driving_events as de

    names = {f.name for f in dataclasses.fields(de.DrivingEvent)}
    assert "confidence" not in names
    assert "evidence" in names
    assert "n_samples_in_window" in names


def test_a_measured_event_must_carry_evidence():
    import driving_events as de

    with pytest.raises(ValueError, match="evidence"):
        de.DrivingEvent(
            event_type="over_slowing", lap_number=1, corner_id=1,
            s_norm_start=0.25, s_norm_end=0.35, magnitude=1.4,
            magnitude_unit="m/s", time_cost_s=0.31,
            validity=de.VALIDITY_MEASURED, reason=None,
            n_samples_in_window=42, evidence={},
        )


def test_a_non_measured_event_must_not_carry_a_magnitude():
    """Refusing with a number attached is the failure this layer prevents."""
    import driving_events as de

    with pytest.raises(ValueError, match="magnitude"):
        de.DrivingEvent(
            event_type="over_slowing", lap_number=1, corner_id=1,
            s_norm_start=0.25, s_norm_end=0.35, magnitude=1.4,
            magnitude_unit="m/s", time_cost_s=None,
            validity=de.VALIDITY_INSUFFICIENT_SAMPLES, reason="window too short",
            n_samples_in_window=2, evidence={"n": 2},
        )


def test_an_unknown_event_type_is_rejected():
    import driving_events as de

    with pytest.raises(ValueError, match="event_type"):
        de.DrivingEvent(
            event_type="invented_thing", lap_number=1, corner_id=1,
            s_norm_start=0.0, s_norm_end=0.1, magnitude=None,
            magnitude_unit="", time_cost_s=None,
            validity=de.VALIDITY_NOT_MEASURABLE, reason="x",
            n_samples_in_window=0, evidence={"n": 0},
        )
