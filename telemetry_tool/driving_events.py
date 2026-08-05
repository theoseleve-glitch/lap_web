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
from typing import Iterable, Protocol

import numpy as np

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

        # Defensive copy: evidence is mutable, so take a copy to prevent caller
        # mutations from affecting the frozen event. MappingProxyType does not
        # JSON-serialize (Task 10 persists this as JSON), so use dict().
        object.__setattr__(self, "evidence", dict(self.evidence))


@dataclass(frozen=True)
class CornerWindow:
    """Everything a detector gets to look at for one corner on one lap.

    Fields the detector cannot assume are present come typed ``| None``:
    ``a_long_mps2`` is None when the channel is absent from the log,
    ``throttle_onset_m`` is a speed-derivative proxy (NOT a real throttle
    channel) and is None when it could not be derived, and
    ``apex_speed_mps`` / ``corner_time_s`` / ``grip_anchor_pct`` are None
    when upstream could not compute them for this corner/lap. A detector
    declares which of these it needs via ``Detector.requires`` so the
    registry can tell "not present" apart from "present but nothing found".
    """

    lap_number: int
    corner_id: int
    s_norm_start: float
    s_norm_end: float
    n_samples: int
    speed_mps: np.ndarray
    a_lat_mps2: np.ndarray
    a_long_mps2: np.ndarray | None
    dist_m: np.ndarray
    apex_speed_mps: float | None
    corner_time_s: float | None
    throttle_onset_m: float | None
    reference: dict
    grip_anchor_pct: float | None


class Detector(Protocol):
    """One driving-mistake detector plugged into the registry.

    ``requires`` names the ``CornerWindow`` fields (by attribute name) that
    must be present (not None) before ``detect`` is even called -- e.g. a
    detector that needs longitudinal acceleration declares
    ``requires={"a_long_mps2"}`` so a window with that channel absent is
    reported ``insufficient`` instead of being silently skipped or crashing.
    ``min_samples`` is the separate, independent floor on ``n_samples``.
    """

    name: str
    requires: frozenset[str]
    min_samples: int

    def detect(self, w: CornerWindow) -> DrivingEvent | None: ...


REGISTRY: tuple[Detector, ...] = ()
"""Detectors plugged into `run_registry`. Empty until Tasks 7-8 populate it."""

CAPABILITY_DETECTED = "detected"
CAPABILITY_NOT_TRIGGERED = "not_triggered"
CAPABILITY_INSUFFICIENT = "insufficient"

CAPABILITIES = frozenset({
    CAPABILITY_DETECTED,
    CAPABILITY_NOT_TRIGGERED,
    CAPABILITY_INSUFFICIENT,
})
"""The three states a detector's run can land in, for one full pass over all
windows. This is the point of this module: "found nothing" (not_triggered)
and "could not look" (insufficient) are never allowed to collapse into the
same empty result -- see track_surface/prescriptive/_internal.py's
Detected/NotTriggered/Insufficient/Unregistered sum type, which models the
same distinction in production. There, NotTriggered is documented as "a
POSITIVE 'no issue detected' -- distinct from Insufficient", and Insufficient
is documented "Do NOT silently skip -- silent skips are exactly the failure
mode the brief forbids." Our capability value is a plain string per detector
rather than that module's class hierarchy, but the reasoning is identical.

"insufficient" itself covers three distinct can't-look causes -- a required
channel absent from the window, a window smaller than min_samples, and an
exception raised while detecting -- collapsed into one value on purpose: the
distinction that matters to a customer is look-vs-couldn't, not which of the
three reasons blocked the look.
"""


def _window_satisfies_requires(w: CornerWindow, requires: frozenset[str]) -> bool:
    """True when every field a detector `requires` is present (not None) on
    this window. Missing attribute names count as unmet, not as an error --
    a typo'd requires should degrade to "insufficient", never crash."""
    for field_name in requires:
        if getattr(w, field_name, None) is None:
            return False
    return True


def run_registry(windows: Iterable[CornerWindow]) -> tuple[list["DrivingEvent"], dict[str, str]]:
    """Run every registered detector across every window.

    Returns ``(events, capability)``. ``capability`` maps each detector's
    ``name`` to one of "detected" / "not_triggered" / "insufficient" -- see
    the CAPABILITIES docstring for why that distinction exists and why
    "insufficient" deliberately does not split further.

    Per detector, across all windows:
    - a window whose `requires` are not met, or whose `n_samples` is below
      `min_samples`, does not count as looked-at for that window
    - a `detect` call that raises is caught here and also does not count as
      looked-at for that window -- `run_registry` itself never raises
    - if any window yields an event, the detector is "detected"
    - else if any window was successfully looked at (no missing requires,
      enough samples, no exception) with nothing found, it is "not_triggered"
    - else (no window could be looked at) it is "insufficient"
    """
    windows = list(windows)
    events: list[DrivingEvent] = []
    capability: dict[str, str] = {}

    for detector in REGISTRY:
        any_detected = False
        any_looked_clean = False

        for w in windows:
            if not _window_satisfies_requires(w, detector.requires):
                continue
            if w.n_samples < detector.min_samples:
                continue

            try:
                result = detector.detect(w)
            except Exception:
                # Never raise out of run_registry: a broken detector on one
                # window must not take down the rest of the report, and
                # must not silently masquerade as "looked, found nothing".
                continue

            if result is not None:
                events.append(result)
                any_detected = True
            else:
                any_looked_clean = True

        if any_detected:
            capability[detector.name] = CAPABILITY_DETECTED
        elif any_looked_clean:
            capability[detector.name] = CAPABILITY_NOT_TRIGGERED
        else:
            capability[detector.name] = CAPABILITY_INSUFFICIENT

    return events, capability
