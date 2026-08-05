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


def test_an_invalid_validity_is_rejected():
    """Validity must be one of the three valid types."""
    import driving_events as de

    with pytest.raises(ValueError, match="validity"):
        de.DrivingEvent(
            event_type="over_slowing", lap_number=1, corner_id=1,
            s_norm_start=0.0, s_norm_end=0.1, magnitude=None,
            magnitude_unit="", time_cost_s=None,
            validity="probably_fine", reason="invalid",
            n_samples_in_window=0, evidence={"n": 0},
        )


def test_validity_is_case_sensitive():
    """Case variants of validity strings must be rejected."""
    import driving_events as de

    with pytest.raises(ValueError, match="validity"):
        de.DrivingEvent(
            event_type="over_slowing", lap_number=1, corner_id=1,
            s_norm_start=0.0, s_norm_end=0.1, magnitude=None,
            magnitude_unit="", time_cost_s=None,
            validity="Measured", reason="case mismatch",
            n_samples_in_window=0, evidence={"n": 0},
        )


def test_a_non_measured_event_must_not_carry_time_cost():
    """A non-measured event with time_cost_s set must raise ValueError."""
    import driving_events as de

    with pytest.raises(ValueError, match="time_cost_s"):
        de.DrivingEvent(
            event_type="over_slowing", lap_number=1, corner_id=1,
            s_norm_start=0.25, s_norm_end=0.35, magnitude=None,
            magnitude_unit="m/s", time_cost_s=0.5,
            validity=de.VALIDITY_INSUFFICIENT_SAMPLES, reason="window too short",
            n_samples_in_window=2, evidence={"n": 2},
        )


def test_a_non_measured_event_with_neither_magnitude_nor_time_cost():
    """A non-measured event with both magnitude and time_cost_s as None must succeed."""
    import driving_events as de

    ev = de.DrivingEvent(
        event_type="over_slowing", lap_number=1, corner_id=1,
        s_norm_start=0.25, s_norm_end=0.35, magnitude=None,
        magnitude_unit="", time_cost_s=None,
        validity=de.VALIDITY_INSUFFICIENT_SAMPLES, reason="window too short",
        n_samples_in_window=2, evidence={"n": 2},
    )
    assert ev.magnitude is None
    assert ev.time_cost_s is None


def test_evidence_is_defensively_copied():
    """Post-construction mutation of the caller's dict must not affect the event."""
    import driving_events as de

    caller_dict = {"n": 42, "lap_id": 5}
    ev = de.DrivingEvent(
        event_type="over_slowing", lap_number=1, corner_id=1,
        s_norm_start=0.25, s_norm_end=0.35, magnitude=1.4,
        magnitude_unit="m/s", time_cost_s=0.31,
        validity=de.VALIDITY_MEASURED, reason=None,
        n_samples_in_window=42, evidence=caller_dict,
    )
    # Mutate the caller's dict after construction
    caller_dict["n"] = 999999
    caller_dict["new_key"] = "injected"
    # The event's evidence must remain unchanged
    assert ev.evidence == {"n": 42, "lap_id": 5}
    assert "new_key" not in ev.evidence


import numpy as np


def _window(**over):
    import driving_events as de
    base = dict(
        lap_number=1, corner_id=1, s_norm_start=0.25, s_norm_end=0.35,
        n_samples=40,
        speed_mps=np.full(40, 12.0), a_lat_mps2=np.full(40, 9.0),
        a_long_mps2=np.zeros(40), dist_m=np.linspace(250.0, 350.0, 40),
        apex_speed_mps=12.0, corner_time_s=8.0,
        reference={"apex_speed_mps": 13.5, "corner_time_s": 7.5,
                   "throttle_onset_m": 10.0},
        grip_anchor_pct=95.0,
    )
    base.update(over)
    return de.CornerWindow(**base)


@pytest.mark.xfail(reason="registry populated in Tasks 7-8", strict=True)
def test_registry_reports_not_triggered_separately_from_insufficient():
    """'Found nothing' and 'could not look' must never be the same answer."""
    import driving_events as de

    # A clean window: detectors can look, and (mostly) find nothing.
    clean = _window(apex_speed_mps=13.5, corner_time_s=7.5)
    _, cap = de.run_registry([clean])
    assert set(cap.values()) <= {"detected", "not_triggered", "insufficient"}
    assert cap["over_slowing"] == "not_triggered"

    # A window too short to judge.
    tiny = _window(n_samples=2, speed_mps=np.full(2, 12.0),
                   a_lat_mps2=np.full(2, 9.0), a_long_mps2=np.zeros(2),
                   dist_m=np.linspace(250.0, 260.0, 2))
    _, cap2 = de.run_registry([tiny])
    assert cap2["over_slowing"] == "insufficient"


@pytest.mark.xfail(reason="registry populated in Tasks 7-8", strict=True)
def test_registry_marks_a_detector_insufficient_when_its_channel_is_absent():
    import driving_events as de

    w = _window(a_long_mps2=None)
    _, cap = de.run_registry([w])
    assert cap["re_braking"] == "insufficient"


@pytest.mark.xfail(reason="registry populated in Tasks 7-8", strict=True)
def test_every_event_the_registry_emits_is_in_the_vocabulary():
    import driving_events as de

    events, _ = de.run_registry([_window(), _window(lap_number=2)])
    for e in events:
        assert e.event_type in de.EVENT_TYPES
        assert e.validity in de.VALIDITIES
