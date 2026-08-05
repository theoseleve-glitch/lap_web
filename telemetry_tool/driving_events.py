"""Driving events — located, named, quantified driver mistakes.

There is no confidence field. The existing handling/ subsystem's confidence
is circularly calibrated: its weight calibrator correlates each detector against
the ensemble's own consensus, with a multiplier that floors at 0.4x and never
goes negative — so three detectors anti-correlating with ground truth push the
posterior the wrong way at 40-90% strength. Its own source comment records that
the formula was retuned to lift mean confidence from ~20% to ~50% with no
actual calibration. There is no labelled ground truth anywhere in this repo to
calibrate a replacement.

Instead, an event carries checkable claims: mandatory evidence (what this lap
did, what the reference lap did, which lap that was, how many samples), a
validity tier, and n_samples_in_window. A probability nobody can calibrate is
worse than no number at all.
"""
from dataclasses import dataclass

VALIDITY_MEASURED = "measured"
VALIDITY_INSUFFICIENT_SAMPLES = "insufficient_samples"
VALIDITY_NOT_MEASURABLE = "not_measurable"

VALIDITIES = frozenset({
    VALIDITY_MEASURED,
    VALIDITY_INSUFFICIENT_SAMPLES,
    VALIDITY_NOT_MEASURABLE,
})

EVENT_TYPES = frozenset({
    "over_slowing",
    "late_throttle",
    "re_braking",
    "envelope_under_use",
})


@dataclass(frozen=True)
class DrivingEvent:
    """One located, named, quantified driver mistake."""

    event_type: str
    lap_number: int
    corner_id: int
    s_norm_start: float
    s_norm_end: float
    magnitude: float | None
    magnitude_unit: str
    time_cost_s: float | None
    validity: str
    reason: str | None
    n_samples_in_window: int
    evidence: dict

    def __post_init__(self):
        """Validate the event's structural invariants."""
        if self.event_type not in EVENT_TYPES:
            raise ValueError(f"event_type must be one of {EVENT_TYPES}, got {self.event_type!r}")

        if self.validity not in VALIDITIES:
            raise ValueError(f"validity must be one of {VALIDITIES}, got {self.validity!r}")

        if self.validity == VALIDITY_MEASURED:
            if not self.evidence:
                raise ValueError("evidence must be non-empty for a measured event")
        else:
            if self.magnitude is not None:
                raise ValueError(f"magnitude must be None for a {self.validity} event, got {self.magnitude!r}")
            if self.time_cost_s is not None:
                raise ValueError(f"time_cost_s must be None for a {self.validity} event, got {self.time_cost_s!r}")
