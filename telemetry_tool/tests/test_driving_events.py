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
    assert de.ONSET_STATUSES == frozenset({
        de.ONSET_MEASURED,
        de.ONSET_NO_SPEED_CROSSING,
        de.ONSET_NO_SESSION_THRESHOLD,
        de.ONSET_NO_APEX,
        de.ONSET_NO_SEARCH_WINDOW,
        de.ONSET_NO_REFERENCE_FRAME,
        de.ONSET_NO_MEASUREMENT,
    })
    # "measured" is a status, never a refusal reason -- an event whose
    # `reason` said "measured" would be nonsense.
    assert de.ONSET_MEASURED not in de.ONSET_REFUSAL_REASONS
    assert de.ONSET_REFUSAL_REASONS == de.ONSET_STATUSES - {de.ONSET_MEASURED}


def test_the_anchor_and_unit_vocabularies_are_closed():
    """Final review, IMPORTANT 1a + a deferred minor.

    `anchor_tier` is spec SS5.1's mandatory provenance field; `magnitude_unit`
    was the one vocabulary that accepted any string, in the field where a typo
    is a UNIT error rather than a label error.
    """
    import grip_anchor as ga
    import driving_events as de

    # Phase 1's tiers verbatim, plus exactly one addition.
    assert de.ANCHOR_TIERS == frozenset(ga.TIERS) | {"absolute_measurement"}
    assert de.ANCHOR_TIERS - frozenset(ga.TIERS) == {de.ANCHOR_ABSOLUTE_MEASUREMENT}
    assert de.MAGNITUDE_UNITS == frozenset({"m/s", "m", "m/s2", "pct"})
    assert set(de.TIME_COST_ATTRIBUTION) == de.EVENT_TYPES
    assert set(de.TIME_COST_ATTRIBUTION.values()) <= de.ATTRIBUTIONS


def test_an_unknown_anchor_tier_is_rejected():
    """A provenance claim nobody can check is worse than no claim."""
    import driving_events as de

    with pytest.raises(ValueError, match="anchor_tier"):
        de.DrivingEvent(
            event_type="over_slowing", lap_number=1, corner_id=1,
            s_norm_start=0.25, s_norm_end=0.35, magnitude=1.4,
            magnitude_unit=de.MAGNITUDE_UNIT_MPS, time_cost_s=0.31,
            validity=de.VALIDITY_MEASURED, reason=None,
            anchor_tier="physics", n_samples_in_window=42,
            evidence={"n": 1},
        )


def test_an_unknown_magnitude_unit_is_rejected():
    """Spec SS8 names a 9.8x unit error as a top risk for this subsystem."""
    import driving_events as de

    with pytest.raises(ValueError, match="magnitude_unit"):
        de.DrivingEvent(
            event_type="over_slowing", lap_number=1, corner_id=1,
            s_norm_start=0.25, s_norm_end=0.35, magnitude=1.4,
            magnitude_unit="kph", time_cost_s=0.31,
            validity=de.VALIDITY_MEASURED, reason=None,
            anchor_tier=de.ANCHOR_DRIVER_BEST_SESSION, n_samples_in_window=42,
            evidence={"n": 1},
        )


def test_anchor_tier_has_no_default_so_every_site_must_state_it():
    """Spec SS5.1: mandatory on every event. A default would let a new
    construction site inherit a plausible-looking provenance it never
    checked -- which is how the field came to be dropped in the first
    place."""
    import dataclasses
    import driving_events as de

    f = {x.name: x for x in dataclasses.fields(de.DrivingEvent)}["anchor_tier"]
    assert f.default is dataclasses.MISSING
    assert f.default_factory is dataclasses.MISSING


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
            anchor_tier=de.ANCHOR_DRIVER_BEST_SESSION,
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
            anchor_tier=de.ANCHOR_DRIVER_BEST_SESSION,
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
            anchor_tier=de.ANCHOR_DRIVER_BEST_SESSION,
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
            anchor_tier=de.ANCHOR_DRIVER_BEST_SESSION,
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
            anchor_tier=de.ANCHOR_DRIVER_BEST_SESSION,
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
            anchor_tier=de.ANCHOR_DRIVER_BEST_SESSION,
            n_samples_in_window=2, evidence={"n": 2},
        )


def test_a_non_measured_event_with_neither_magnitude_nor_time_cost():
    """A non-measured event with both magnitude and time_cost_s as None must succeed."""
    import driving_events as de

    ev = de.DrivingEvent(
        event_type="over_slowing", lap_number=1, corner_id=1,
        s_norm_start=0.25, s_norm_end=0.35, magnitude=None,
        magnitude_unit=de.MAGNITUDE_UNIT_MPS, time_cost_s=None,
        validity=de.VALIDITY_INSUFFICIENT_SAMPLES, reason="window too short",
        anchor_tier=de.ANCHOR_DRIVER_BEST_SESSION,
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
        anchor_tier=de.ANCHOR_DRIVER_BEST_SESSION,
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
        corner_time_s=8.0, throttle_onset_m=9.0, throttle_onset_norm=0.0075,
        throttle_onset_status=de.ONSET_MEASURED,
        reference={"apex_speed_mps": 13.5, "corner_time_s": 7.5,
                   "throttle_onset_m": 10.0},
        grip_anchor_pct=95.0,
        # Tier 1 by default: a quotable session-envelope anchor, so
        # `envelope_under_use` exercises its MEASURED path. Tests that care
        # about provenance override it.
        anchor_tier=de.ANCHOR_SESSION_ENVELOPE_FITTED,
        anchor_reason=None,
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


# ── the onset scan looked and found nothing: say so, do not vanish ───────
#
# Task 12. `throttle_onset_m is None` used to mean the window was skipped
# entirely (it was in `requires`), so a corner-lap whose onset scan came back
# empty simply disappeared from the output -- indistinguishable from a
# corner-lap that was never analysed, and silently removed from the pool the
# per-corner reference is a minimum over.

def _late_throttle_via_registry(**over):
    """Drive the refusal through `run_registry`, NOT `detect` directly.

    Bite-check finding: a direct `LATE_THROTTLE.detect(w)` call cannot see
    `requires`, so every assertion below still passed against a build whose
    `requires` gated on `throttle_onset_m` -- the exact build in which the
    refusal event never reaches a caller at all. Routing through the
    registry is what makes these tests bite.
    """
    import driving_events as de

    events, cap = de.run_registry([_window(**over)])
    lt = [e for e in events if e.event_type == "late_throttle"]
    return (lt[0] if lt else None), cap


def test_late_throttle_emits_not_measurable_when_the_scan_found_no_crossing():
    import driving_events as de

    w_kwargs = dict(throttle_onset_m=None,
                    throttle_onset_status=de.ONSET_NO_SPEED_CROSSING)
    ev, cap = _late_throttle_via_registry(**w_kwargs)

    assert ev is not None, "the corner-lap vanished instead of being reported"
    assert cap["late_throttle"] == "detected", cap
    assert ev.validity == de.VALIDITY_NOT_MEASURABLE
    assert ev.reason == de.ONSET_NO_SPEED_CROSSING
    # A refusal carries no numbers -- DrivingEvent.__post_init__ enforces
    # this too, but assert it here so the intent is on the page.
    assert ev.magnitude is None
    assert ev.time_cost_s is None
    # Still located: Phase 3 has to be able to draw it.
    reference = _window(**w_kwargs)
    assert ev.s_norm_start == reference.s_norm_start
    assert ev.s_norm_end == reference.s_norm_end


def test_every_onset_refusal_reason_reaches_the_event_unchanged():
    """The reason is the whole product of a not_measurable event. If any
    member of the vocabulary were dropped or remapped on the way out, the
    customer would be told the wrong cause."""
    import driving_events as de

    for status in sorted(de.ONSET_REFUSAL_REASONS):
        ev, _ = _late_throttle_via_registry(
            throttle_onset_m=None, throttle_onset_status=status)
        assert ev is not None and ev.reason == status, status


def test_an_unrecognised_onset_status_is_clamped_to_the_closed_vocabulary():
    """An upstream typo must not become a customer-visible reason string."""
    import driving_events as de

    ev, _ = _late_throttle_via_registry(
        throttle_onset_m=None, throttle_onset_status="typo_from_10b")
    assert ev is not None
    assert ev.reason == de.ONSET_NO_MEASUREMENT
    assert ev.reason in de.ONSET_REFUSAL_REASONS


def test_an_onset_derivation_that_never_ran_reads_insufficient_not_measurable():
    """"Could not look" and "looked and found nothing" must stay different
    answers. A metric dict that never went through the onset pass carries no
    status at all -- that is NOT a refusal we can name, so it must gate the
    detector out rather than produce a not_measurable event with an invented
    cause."""
    import driving_events as de

    w = _window(throttle_onset_m=None, throttle_onset_status=None)
    events, cap = de.run_registry([w])

    assert cap["late_throttle"] == "insufficient", cap
    assert not [e for e in events if e.event_type == "late_throttle"]


def test_a_refused_onset_still_lets_the_other_three_detectors_evaluate():
    """The onset refusal is scoped to late_throttle. If it ever starved the
    reference-free detectors the way the corner-wide skip did in fix round 1,
    a session with a hard exit would lose its re_braking evidence too."""
    import driving_events as de

    a_long = np.zeros(40)
    a_long[25:31] = -3.0                # a genuine post-apex re-brake
    w = _window(throttle_onset_m=None,
                throttle_onset_status=de.ONSET_NO_SPEED_CROSSING,
                a_long_mps2=a_long, grip_anchor_pct=70.0)
    _, cap = de.run_registry([w])

    assert cap["late_throttle"] == "detected"
    assert cap["re_braking"] == "detected"
    assert cap["envelope_under_use"] == "detected"


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


# ── Final review, CRITICAL 2: the impossible-but-finite class ────────────
#
# `corner_analysis.py:731` substitutes `actual_apex_speed_mps=0.0` when its
# corner slice is empty or all-NaN. 0.0 is FINITE, so `_all_finite` accepts
# it and `over_slowing` emitted a `validity="measured"` event with magnitude
# 17.82 m/s against an apex speed that was never measured. Reachable because
# `apex_speed_mps` comes from an ABSOLUTE-metre mask while the other half of
# `requires` (`corner_time_s`) comes from a NORMALISED one, and the two
# disagree on 35 of 72 real corner-laps.


def test_over_slowing_refuses_a_substituted_zero_apex_speed():
    import driving_events as de

    w = _window(apex_speed_mps=0.0, corner_time_s=8.0,
                reference={"apex_speed_mps": 17.82, "corner_time_s": 7.5,
                           "throttle_onset_m": 10.0})
    assert de.OVER_SLOWING.detect(w) is None, (
        "a 0.0 apex speed is a substitution, not a measurement -- emitting "
        "against it tells the driver they were 17.8 m/s slow at an apex "
        "nobody measured")


def test_a_substituted_zero_never_becomes_the_corners_best_time():
    """The reference side, tested where it can actually discriminate.

    A 0.0 apex speed can never win the reference MAX, so guarding it there is
    unfalsifiable -- the emit floor rejects the negative deficit anyway. A 0.0
    corner TIME is the opposite: it always wins the reference MIN, becomes
    "the driver's best pass through this corner", and poisons every other
    lap's `time_cost_s` at that corner. That is the case worth pinning.
    """
    from pipeline.stages import s10d3_driving_events as s10d3

    metrics = [
        {"lap_number": 1, "corner_id": 3, "corner_time_s": 8.2,
         "apex_speed_mps": 12.0},
        {"lap_number": 2, "corner_id": 3, "corner_time_s": 0.0,
         "apex_speed_mps": 0.0},          # the substituted pair
        {"lap_number": 3, "corner_id": 3, "corner_time_s": 7.9,
         "apex_speed_mps": 13.1},
    ]
    refs = s10d3._build_references(metrics, frozenset())

    assert refs[3]["corner_time_s"] == 7.9, (
        "a substituted 0.0 corner time became the corner's reference best, "
        "so every other lap is now measured against an impossible lap")
    assert refs[3]["apex_speed_mps"] == 13.1


def test_over_slowing_refuses_a_zero_corner_time():
    """The other half: `time_cost_s` is a corner-time gap, and a 0 s pass
    through a corner is the same impossible-but-finite substitution."""
    import driving_events as de

    assert de.OVER_SLOWING.detect(_window(
        apex_speed_mps=12.0, corner_time_s=0.0,
        reference={"apex_speed_mps": 13.5, "corner_time_s": 7.5,
                   "throttle_onset_m": 10.0})) is None
    assert de.OVER_SLOWING.detect(_window(
        apex_speed_mps=12.0, corner_time_s=8.0,
        reference={"apex_speed_mps": 13.5, "corner_time_s": 0.0,
                   "throttle_onset_m": 10.0})) is None


def test_late_throttle_refuses_a_zero_corner_time():
    import driving_events as de

    assert de.LATE_THROTTLE.detect(_window(
        throttle_onset_m=24.0, corner_time_s=0.0,
        reference={"apex_speed_mps": 12.0, "corner_time_s": 7.5,
                   "throttle_onset_m": 10.0})) is None


def test_a_zero_apex_speed_reads_insufficient_not_not_triggered():
    """The distinction that matters. A window the stage built from a
    substituted 0.0 must make `over_slowing` report "could not look", not
    "looked and found nothing" -- the collapse CAPABILITIES exists to stop.
    """
    import driving_events as de
    from pipeline.stages import s10d3_driving_events as s10d3

    assert s10d3._positive_float(0.0) is None
    assert s10d3._positive_float(-1.0) is None
    assert s10d3._positive_float(12.0) == 12.0
    # ... while the plain finite coercion still lets a legitimate zero
    # through, which is why the two are separate helpers.
    assert s10d3._finite_float(0.0) == 0.0

    stripped = _window(apex_speed_mps=None, corner_time_s=8.0)
    _, cap = de.run_registry([stripped])
    assert cap["over_slowing"] == de.CAPABILITY_INSUFFICIENT


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
            anchor_tier=de.ANCHOR_DRIVER_BEST_SESSION,
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
            anchor_tier=de.ANCHOR_DRIVER_BEST_SESSION,
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


# ── re_braking / envelope_under_use ────────────────────────────────────────

def test_re_braking_needs_a_sustained_run_not_a_single_sample():
    import driving_events as de

    a = np.zeros(40)
    a[20] = -2.0                       # one isolated sample
    assert de.RE_BRAKING.detect(_window(a_long_mps2=a)) is None

    a2 = np.zeros(40)
    a2[20:23] = -2.0                   # three consecutive
    ev = de.RE_BRAKING.detect(_window(a_long_mps2=a2))
    assert ev is not None
    assert ev.event_type == "re_braking"
    assert ev.validity == de.VALIDITY_MEASURED


def test_re_braking_refuses_when_the_channel_is_absent():
    import driving_events as de

    ev = de.RE_BRAKING.detect(_window(a_long_mps2=None))
    assert ev is None or ev.validity != de.VALIDITY_MEASURED


# ── re_braking: fix round 1 -- the magnitude floor pins the measured rate ──
#
# The run-length gate (>= 3 consecutive samples) alone measured 35.6% on
# real post-apex a_long from data/raw/OK_R4.csv -- 5x the cited 7%. Only
# adding the -0.5 m/s^2 magnitude floor back reproduces 6.8% (~7%). This
# test pins that floor's actual effect: a sustained (3-sample) run shallower
# than -0.5 must NOT fire, and one deeper than -0.5 must.

def test_re_braking_floor_rejects_shallow_decel_and_fires_on_deep_decel():
    import driving_events as de

    shallow = np.zeros(40)
    shallow[20:23] = -0.3               # sustained, but shallower than -0.5
    assert de.RE_BRAKING.detect(_window(a_long_mps2=shallow)) is None

    deep = np.zeros(40)
    deep[20:23] = -0.8                  # sustained AND deeper than -0.5
    ev = de.RE_BRAKING.detect(_window(a_long_mps2=deep))
    assert ev is not None
    assert ev.event_type == "re_braking"
    assert ev.magnitude == pytest.approx(0.8)


def test_envelope_under_use_fires_below_the_floor_and_is_silent_above():
    import driving_events as de

    low = de.ENVELOPE_UNDER_USE.detect(_window(grip_anchor_pct=62.0))
    assert low is not None
    assert low.magnitude == pytest.approx(62.0)
    assert low.magnitude_unit == "pct"
    # The number now says what it was measured against.
    assert low.anchor_tier == de.ANCHOR_SESSION_ENVELOPE_FITTED
    assert low.evidence["grip_anchor_tier"] == de.ANCHOR_SESSION_ENVELOPE_FITTED

    assert de.ENVELOPE_UNDER_USE.detect(_window(grip_anchor_pct=101.5)) is None


def test_envelope_under_use_refuses_without_a_phase_1_number():
    import driving_events as de

    ev = de.ENVELOPE_UNDER_USE.detect(_window(grip_anchor_pct=None))
    assert ev is None or ev.validity != de.VALIDITY_MEASURED


# ── Final review, IMPORTANT 1b: the tier-2 bound is TAUTOLOGICAL ─────────
#
# On `driver_best_session` the percentage is `100 * |a_lat| / session_best`,
# so it CANNOT exceed 100 and "under 100%" is true of all-but-one lap by
# arithmetic. Measured: 35% fire on tier 1 against 93% on tier 2 (14 of 15).
# The spec already cut `over_braking` and `envelope_exceedance` for exactly
# this defect (SS5.5); this applies the same rule to the case that slipped
# through.


def test_envelope_under_use_refuses_on_a_self_referential_tier_2_anchor():
    import driving_events as de

    ev = de.ENVELOPE_UNDER_USE.detect(_window(
        grip_anchor_pct=62.0, anchor_tier=de.ANCHOR_DRIVER_BEST_SESSION))

    assert ev is not None, (
        "silence would be counted 'not_triggered' -- looked and found "
        "nothing -- which is exactly the collapse this layer prevents")
    assert ev.validity == de.VALIDITY_NOT_MEASURABLE, (
        f"a 62.0% measured against a bound that cannot be exceeded is not a "
        f"measurement, got validity={ev.validity!r} magnitude={ev.magnitude!r}")
    assert ev.magnitude is None
    assert ev.reason == de.ANCHOR_REASON_SELF_REFERENTIAL_BOUND
    assert ev.anchor_tier == de.ANCHOR_DRIVER_BEST_SESSION


def test_the_tier_2_refusal_does_not_depend_on_the_value():
    """Refuse for EVERY tier-2 corner-lap, not only the ones under the floor.

    On tier 2 "it was above 100" carries exactly as little information as
    "it was below" -- both are arithmetic. Refusing uniformly is also what
    makes the size of the unjudgeable set readable off the output instead of
    inferable from missing rows.
    """
    import driving_events as de

    for pct in (10.0, 62.0, 99.9, 100.0, 140.0):
        ev = de.ENVELOPE_UNDER_USE.detect(_window(
            grip_anchor_pct=pct, anchor_tier=de.ANCHOR_DRIVER_BEST_SESSION))
        assert ev is not None and ev.validity == de.VALIDITY_NOT_MEASURABLE, pct


def test_envelope_under_use_still_measures_on_both_quotable_tiers():
    """The refusal must be aimed at the tautology, not at the detector."""
    import driving_events as de

    for tier in (de.ANCHOR_SESSION_ENVELOPE_FITTED,
                 de.ANCHOR_SESSION_ENVELOPE_DEFAULT_P2):
        ev = de.ENVELOPE_UNDER_USE.detect(
            _window(grip_anchor_pct=62.0, anchor_tier=tier))
        assert ev is not None and ev.validity == de.VALIDITY_MEASURED, tier
        assert ev.anchor_tier == tier


def test_an_unrecognised_tier_is_refused_with_its_own_reason():
    """Fail-safe: unknown provenance is never quotable, and it is not the
    same finding as the tier-2 tautology -- an operator seeing one should
    not go looking for the other."""
    import driving_events as de

    ev = de.ENVELOPE_UNDER_USE.detect(_window(
        grip_anchor_pct=62.0, anchor_tier="physics_ellipse"))
    assert ev.validity == de.VALIDITY_NOT_MEASURABLE
    assert ev.reason == de.ANCHOR_REASON_UNKNOWN_TIER
    # And the event itself still carries a LEGAL tier value.
    assert ev.anchor_tier in de.ANCHOR_TIERS


def test_a_window_with_no_tier_at_all_reads_insufficient():
    """`anchor_tier` is in `requires`, so a percentage with no provenance is
    'could not look', never 'looked and found nothing'."""
    import driving_events as de

    _, cap = de.run_registry([_window(grip_anchor_pct=62.0, anchor_tier=None)])
    assert cap["envelope_under_use"] == de.CAPABILITY_INSUFFICIENT


def test_the_silent_tier_collapse_is_now_visible_downstream():
    """The reachable failure the review demonstrated: step 09c degrading
    while 10d succeeds sends EVERY corner-lap to tier 2, which used to take
    this detector from 34/72 to 65/72 (90%) -- all `validity="measured"`,
    magnitudes in the same range, indistinguishable from a good run."""
    import driving_events as de

    good = [_window(lap_number=n, grip_anchor_pct=62.0,
                    anchor_tier=de.ANCHOR_SESSION_ENVELOPE_FITTED)
            for n in range(1, 10)]
    degraded = [_window(lap_number=n, grip_anchor_pct=62.0,
                        anchor_tier=de.ANCHOR_DRIVER_BEST_SESSION)
                for n in range(1, 10)]

    ev_good, _ = de.run_registry(good)
    ev_degraded, _ = de.run_registry(degraded)

    def measured_euu(evs):
        return [e for e in evs if e.event_type == "envelope_under_use"
                and e.validity == de.VALIDITY_MEASURED]

    assert len(measured_euu(ev_good)) == 9
    assert measured_euu(ev_degraded) == [], (
        "a wholesale degradation to the self-referential anchor still "
        "produces measured events -- the two runs are indistinguishable")


# ── re_braking: apex_idx must be honoured, not re-derived ─────────────────
#
# _window()'s default speed_mps is CONSTANT (np.full(40, 12.0)), so a real
# nanargmin over it would return index 0 -- a re_braking test built only on
# that default fixture cannot tell "sliced from apex_idx=20" apart from
# "sliced from index 0 by coincidence". This fixture gives speed_mps a
# genuine minimum at a known index (25), distinct from apex_idx (20), and
# places the sustained decel run BEFORE apex_idx to prove the detector
# slices from apex_idx (finds nothing post-apex) rather than from the
# genuine speed minimum (which would find the run and fire).

def _window_with_real_apex(a_long_mps2):
    speed = np.full(40, 12.0)
    speed[25] = 5.0                    # the genuine minimum: index 25
    return _window(
        a_long_mps2=a_long_mps2, speed_mps=speed,
        apex_idx=20, s_norm_apex=0.30,
    )


def test_re_braking_slices_from_apex_idx_not_from_a_re_derived_minimum():
    import driving_events as de

    a = np.zeros(40)
    a[10:14] = -2.0                    # sustained run, but BEFORE apex_idx=20
    # If the detector re-derived the apex via nanargmin(speed_mps) it would
    # land on index 25 (the genuine minimum) and still miss this pre-apex
    # run -- so also confirm a post-apex run (after 20, and after 25) DOES
    # fire, proving the slice point is apex_idx=20, not index 0 and not 25.
    assert de.RE_BRAKING.detect(_window_with_real_apex(a)) is None

    a2 = np.zeros(40)
    a2[30:33] = -2.0                   # sustained run after apex_idx=20
    ev = de.RE_BRAKING.detect(_window_with_real_apex(a2))
    assert ev is not None
    assert ev.event_type == "re_braking"


def test_re_braking_finds_a_run_between_apex_idx_and_a_later_speed_minimum():
    """Fix round 1: the reviewer showed the two prior slicing cases (before
    BOTH candidates, after BOTH candidates) pass unchanged against a
    hand-written wrong implementation (`apex_idx = int(np.nanargmin(w.speed_
    mps))`), because both candidate start points agree on the verdict for
    those two windows. This is the discriminating case: a sustained run at
    indices 21-24 sits strictly AFTER apex_idx=20 but BEFORE the genuine
    speed minimum at 25. A correct implementation slices post_apex from 20
    and finds it (fires); a nanargmin-based one slices from 25 and misses it
    entirely (returns None) -- the two implementations disagree here, which
    is what makes this a real regression guard rather than reading the
    source."""
    import driving_events as de

    a = np.zeros(40)
    a[21:25] = -2.0                    # indices 21-24: after apex_idx=20,
                                        # before the real min at 25
    ev = de.RE_BRAKING.detect(_window_with_real_apex(a))
    assert ev is not None
    assert ev.event_type == "re_braking"
