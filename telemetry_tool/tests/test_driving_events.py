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
        apex_speed_mps=12.0, apex_idx=20, s_norm_apex=0.30,
        corner_time_s=8.0, throttle_onset_m=9.0,
        reference={"apex_speed_mps": 13.5, "corner_time_s": 7.5,
                   "throttle_onset_m": 10.0},
        grip_anchor_pct=95.0,
    )
    base.update(over)
    return de.CornerWindow(**base)


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


def test_every_event_the_registry_emits_is_in_the_vocabulary():
    """Not xfail like its two neighbours: with REGISTRY still empty this is
    vacuously true (zero events trivially satisfy the loop below), so it
    passes for real today rather than failing on a missing detector name.
    Marking it xfail(strict=True) anyway would XPASS-fail the suite the
    moment it's collected -- confirmed by running with --runxfail. It stays
    unmarked and becomes a genuine check the moment Tasks 7-8 add detectors
    that actually emit events; no unmark step needed for this one."""
    import driving_events as de

    events, _ = de.run_registry([_window(), _window(lap_number=2)])
    for e in events:
        assert e.event_type in de.EVENT_TYPES
        assert e.validity in de.VALIDITIES


# ── run_registry must be total: never raise, for any input ────────────────
#
# REGISTRY ships empty in production today, so these use monkeypatch to
# install small fake detectors for the duration of a single test (auto-
# restored after) -- that's how a window missing attributes, or a detector
# whose detect() raises, gets exercised before Tasks 7-8 exist for real.

class _NeverFires:
    """A detector with no requirements that always looks and finds nothing."""
    name = "probe"
    requires = frozenset()
    min_samples = 5

    def detect(self, w):
        return None


class _AlwaysRaises:
    name = "explodes"
    requires = frozenset()
    min_samples = 5

    def detect(self, w):
        raise RuntimeError("boom")


def _assert_total_result(result):
    """The invariant that must hold for every fuzz vector below: a 2-tuple
    whose capability values are all drawn from the closed set."""
    events, cap = result
    assert isinstance(events, list)
    assert isinstance(cap, dict)
    assert set(cap.values()) <= {"detected", "not_triggered", "insufficient"}
    return events, cap


def test_run_registry_handles_none_as_the_windows_argument(monkeypatch):
    import driving_events as de

    monkeypatch.setattr(de, "REGISTRY", (_NeverFires(),))
    events, cap = _assert_total_result(de.run_registry(None))
    assert events == []
    assert cap["probe"] == "insufficient"


def test_run_registry_handles_an_empty_iterable(monkeypatch):
    """Isolated with a fake REGISTRY (like its fuzz-suite siblings) rather
    than asserting `cap == {}` against whatever real detectors happen to be
    registered: with zero windows, every REGISTERED detector still gets a
    capability entry ('insufficient' -- no window could be looked at), so
    the real cap is non-empty now that over_slowing/late_throttle exist."""
    import driving_events as de

    monkeypatch.setattr(de, "REGISTRY", (_NeverFires(),))
    events, cap = _assert_total_result(de.run_registry([]))
    assert events == []
    assert cap == {"probe": "insufficient"}


def test_run_registry_handles_a_none_window_in_the_list(monkeypatch):
    import driving_events as de

    monkeypatch.setattr(de, "REGISTRY", (_NeverFires(),))
    events, cap = _assert_total_result(de.run_registry([None]))
    assert events == []
    assert cap["probe"] == "insufficient"


def test_run_registry_handles_a_window_missing_attributes(monkeypatch):
    import driving_events as de

    class Bare:
        """Not a CornerWindow at all -- no n_samples, no anything."""

    monkeypatch.setattr(de, "REGISTRY", (_NeverFires(),))
    events, cap = _assert_total_result(de.run_registry([Bare()]))
    assert events == []
    assert cap["probe"] == "insufficient"


def test_run_registry_handles_a_generator_that_raises_partway_through(monkeypatch):
    import driving_events as de

    def bad_gen():
        yield _window()          # one good window before the blow-up
        raise RuntimeError("corrupt lap")
        yield _window()          # pragma: no cover -- never reached

    monkeypatch.setattr(de, "REGISTRY", (_NeverFires(),))
    events, cap = _assert_total_result(de.run_registry(bad_gen()))
    assert events == []
    # The window yielded before the raise was still usable.
    assert cap["probe"] == "not_triggered"


def test_run_registry_swallows_a_raising_detector(monkeypatch):
    import driving_events as de

    monkeypatch.setattr(de, "REGISTRY", (_AlwaysRaises(),))
    events, cap = _assert_total_result(de.run_registry([_window()]))
    assert events == []
    assert cap["explodes"] == "insufficient"


# ── over_slowing / late_throttle ───────────────────────────────────────────

def test_over_slowing_measures_the_apex_deficit_against_the_reference():
    import driving_events as de

    w = _window(apex_speed_mps=12.0, corner_time_s=8.0,
                reference={"apex_speed_mps": 13.5, "corner_time_s": 7.5,
                           "throttle_onset_m": 10.0})
    ev = de.OVER_SLOWING.detect(w)

    assert ev is not None
    assert ev.event_type == "over_slowing"
    assert ev.magnitude == pytest.approx(1.5)        # 13.5 - 12.0
    assert ev.magnitude_unit == "m/s"
    assert ev.time_cost_s == pytest.approx(0.5)      # 8.0 - 7.5
    assert ev.validity == de.VALIDITY_MEASURED
    # The claim must be reconstructible from stored numbers.
    assert ev.evidence["apex_speed_mps"] == pytest.approx(12.0)
    assert ev.evidence["reference_apex_speed_mps"] == pytest.approx(13.5)


def test_over_slowing_is_silent_when_this_lap_IS_the_reference():
    import driving_events as de

    w = _window(apex_speed_mps=13.5, corner_time_s=7.5,
                reference={"apex_speed_mps": 13.5, "corner_time_s": 7.5,
                           "throttle_onset_m": 10.0})
    assert de.OVER_SLOWING.detect(w) is None


def test_over_slowing_refuses_rather_than_guessing_without_a_reference():
    """Tightened from the brief's `ev is None or ev.validity != MEASURED`:
    that shape passes under two different detector behaviours. This detector
    always refuses by returning None when the reference is incomplete --
    assert that one behaviour exactly, not either of the two."""
    import driving_events as de

    w = _window(reference={})
    assert de.OVER_SLOWING.detect(w) is None


def test_late_throttle_measures_metres_later_than_the_reference():
    import driving_events as de

    w = _window(
        throttle_onset_m=24.0,
        reference={"apex_speed_mps": 12.0, "corner_time_s": 8.0,
                   "throttle_onset_m": 10.0},
    )
    ev = de.LATE_THROTTLE.detect(w)

    assert ev is not None
    assert ev.event_type == "late_throttle"
    assert ev.magnitude == pytest.approx(14.0)      # 24.0 - 10.0
    assert ev.magnitude_unit == "m"
    # The evidence must name the proxy, because this is NOT a throttle channel.
    assert "proxy" in " ".join(str(v) for v in ev.evidence.values()).lower() \
        or ev.evidence.get("source") == "speed_derivative_proxy"


def test_late_throttle_refuses_when_this_lap_has_no_onset():
    """No onset was found -- refuse, do not invent one.

    Tightened from the brief's `ev is None or ev.validity != MEASURED` to
    the one behaviour this detector actually has: return None."""
    import driving_events as de

    w = _window(
        throttle_onset_m=None,
        reference={"apex_speed_mps": 12.0, "corner_time_s": 8.0,
                   "throttle_onset_m": 10.0},
    )
    assert de.LATE_THROTTLE.detect(w) is None


# ── fix round 1: NaN must never fabricate a "measured" claim ──────────────
#
# `is None` alone does not catch NaN (`float("nan") is None` is False), and
# every comparison against NaN -- including an emit-floor check like
# `deficit <= FLOOR` -- is False. Both detectors' finiteness guard, and
# `DrivingEvent.__post_init__`'s independent second layer, are bite-checked
# here.

def test_over_slowing_refuses_a_nan_apex_speed():
    import driving_events as de

    w = _window(apex_speed_mps=float("nan"), corner_time_s=8.0,
                reference={"apex_speed_mps": 13.5, "corner_time_s": 7.5,
                           "throttle_onset_m": 10.0})
    assert de.OVER_SLOWING.detect(w) is None


def test_over_slowing_refuses_a_nan_reference_apex_speed():
    import driving_events as de

    w = _window(apex_speed_mps=12.0, corner_time_s=8.0,
                reference={"apex_speed_mps": float("nan"), "corner_time_s": 7.5,
                           "throttle_onset_m": 10.0})
    assert de.OVER_SLOWING.detect(w) is None


def test_late_throttle_refuses_a_nan_onset():
    import driving_events as de

    w = _window(
        throttle_onset_m=float("nan"),
        reference={"apex_speed_mps": 12.0, "corner_time_s": 8.0,
                   "throttle_onset_m": 10.0},
    )
    assert de.LATE_THROTTLE.detect(w) is None


def test_late_throttle_refuses_a_nan_reference_onset():
    import driving_events as de

    w = _window(
        throttle_onset_m=24.0,
        reference={"apex_speed_mps": 12.0, "corner_time_s": 8.0,
                   "throttle_onset_m": float("nan")},
    )
    assert de.LATE_THROTTLE.detect(w) is None


def test_a_measured_event_must_have_a_finite_magnitude():
    """Layer 2 defence: even if a future detector's own NaN guard has a bug,
    the record itself refuses to carry a non-finite 'measured' magnitude --
    `json.dumps` would otherwise emit an invalid-JSON bare `NaN` token at
    Task 10's persistence layer."""
    import driving_events as de

    with pytest.raises(ValueError, match="magnitude"):
        de.DrivingEvent(
            event_type="over_slowing", lap_number=1, corner_id=1,
            s_norm_start=0.25, s_norm_end=0.35, magnitude=float("nan"),
            magnitude_unit="m/s", time_cost_s=0.5,
            validity=de.VALIDITY_MEASURED, reason=None,
            n_samples_in_window=42, evidence={"n": 42},
        )


def test_a_measured_event_must_have_a_finite_time_cost():
    """Same layer-2 defence, covering +-inf (not just NaN) and the other
    numeric field."""
    import driving_events as de

    with pytest.raises(ValueError, match="time_cost_s"):
        de.DrivingEvent(
            event_type="over_slowing", lap_number=1, corner_id=1,
            s_norm_start=0.25, s_norm_end=0.35, magnitude=1.5,
            magnitude_unit="m/s", time_cost_s=float("inf"),
            validity=de.VALIDITY_MEASURED, reason=None,
            n_samples_in_window=42, evidence={"n": 42},
        )


# ── fix round 1: late_throttle was never routed through run_registry ──────

def test_registry_reports_late_throttle_capability_too():
    """cap["over_slowing"] is asserted elsewhere in this file; nothing
    previously routed late_throttle through run_registry, so a mutation to
    its `requires` or `min_samples` could have passed the whole suite
    silently. Mirrors test_registry_reports_not_triggered_separately_from_
    insufficient's clean/tiny pair, for late_throttle specifically."""
    import driving_events as de

    # A clean window: matches the reference throttle onset -> not_triggered.
    clean = _window(throttle_onset_m=10.0)
    _, cap = de.run_registry([clean])
    assert cap["late_throttle"] == "not_triggered"

    # A window too short to judge.
    tiny = _window(n_samples=2, speed_mps=np.full(2, 12.0),
                   a_lat_mps2=np.full(2, 9.0), a_long_mps2=np.zeros(2),
                   dist_m=np.linspace(250.0, 260.0, 2))
    _, cap2 = de.run_registry([tiny])
    assert cap2["late_throttle"] == "insufficient"
