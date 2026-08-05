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
import logging
from dataclasses import dataclass
from typing import Iterable, Protocol

import numpy as np

logger = logging.getLogger(__name__)

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
            # A NaN/inf defeats an `is None` guard upstream (NaN != None, and
            # every comparison with NaN is False) and would otherwise let a
            # meaningless number through labelled "measured" -- exactly what
            # this module exists to prevent, and something `json.dumps`
            # would later emit as a bare, invalid-JSON `NaN` token (Task 10
            # persists events as JSON). Enforced here, not just at each
            # detector, so no future detector can reintroduce this class of
            # bug.
            if self.magnitude is not None and not np.isfinite(self.magnitude):
                raise ValueError(f"magnitude must be finite for a measured event, got {self.magnitude!r}")
            if self.time_cost_s is not None and not np.isfinite(self.time_cost_s):
                raise ValueError(f"time_cost_s must be finite for a measured event, got {self.time_cost_s!r}")
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
    ``apex_speed_mps`` / ``apex_idx`` / ``s_norm_apex`` / ``corner_time_s`` /
    ``grip_anchor_pct`` are None when upstream could not compute them for
    this corner/lap. A detector declares which of these it needs via
    ``Detector.requires`` so the registry can tell "not present" apart from
    "present but nothing found".

    ``apex_idx`` is an index into this window's own arrays (``speed_mps``,
    ``a_lat_mps2``, ``a_long_mps2``, ``dist_m``) -- e.g. a post-apex detector
    like re_braking slices ``a_long_mps2[apex_idx:]`` directly rather than
    re-deriving the apex itself (which can diverge from ``apex_speed_mps`` on
    ties or noise: see ``pipeline/stages/s10b_corners.py:484-492``'s
    ``np.nanargmin`` derivation for the precedent this mirrors). ``s_norm_apex``
    carries the same location in normalised-distance terms for evidence/
    reporting, so a detector doesn't have to interpolate it from ``dist_m``.
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
    apex_idx: int | None
    s_norm_apex: float | None
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
    a typo'd requires should degrade to "insufficient", never crash. Safe
    even when `w` itself is None: `getattr(None, name, None)` returns the
    default rather than raising."""
    for field_name in requires:
        if getattr(w, field_name, None) is None:
            return False
    return True


def _safe_windows(windows) -> list:
    """Materialise `windows` defensively so a bad argument can never make
    `run_registry` raise. Handles: `windows` itself not being iterable
    (e.g. None), and an iterable/generator that raises partway through
    (e.g. lazily built from raw telemetry that fails on a corrupt lap).

    Windows already produced before a failure are kept -- consumption just
    stops at the point of failure rather than discarding everything, so a
    generator that yields three good windows and then blows up on the
    fourth still leaves those three windows available to every detector.
    """
    try:
        iterator = iter(windows)
    except TypeError:
        logger.exception("run_registry: windows argument is not iterable: %r", windows)
        return []

    collected = []
    while True:
        try:
            w = next(iterator)
        except StopIteration:
            break
        except Exception:
            logger.exception("run_registry: windows iterator raised while producing a window")
            break
        collected.append(w)
    return collected


def run_registry(windows: Iterable[CornerWindow]) -> tuple[list["DrivingEvent"], dict[str, str]]:
    """Run every registered detector across every window.

    Returns ``(events, capability)``. ``capability`` maps each detector's
    ``name`` to one of "detected" / "not_triggered" / "insufficient" -- see
    the CAPABILITIES docstring for why that distinction exists and why
    "insufficient" deliberately does not split further.

    `run_registry` never raises, for any input -- not just a well-formed
    `Iterable[CornerWindow]`. `windows` may be None, empty, a generator that
    raises partway through, or contain a None/malformed window; a registered
    detector's `detect` may raise. Every one of those is caught here rather
    than a caller learning about a corrupt lap via a stack trace out of a
    report-generation call. The always-true invariant: for any input, the
    return value is a 2-tuple whose `capability` values are all drawn from
    the closed ``{"detected", "not_triggered", "insufficient"}`` set.

    Per detector, across all windows:
    - a window whose `requires` are not met, whose `n_samples` is below
      `min_samples` (or is missing/unreadable), or whose `detect` call
      raises, does not count as looked-at for that window -- all three are
      caught by the same try/except below, deliberately: `min_samples` is
      evaluated inside the guarded block precisely so a malformed window
      (e.g. None, or missing `n_samples`) degrades the same way a raising
      `detect` call does, instead of crashing before `detect` is even
      reached
    - if any window yields an event, the detector is "detected"
    - else if any window was successfully looked at (no missing requires,
      enough samples, no exception) with nothing found, it is "not_triggered"
    - else (no window could be looked at) it is "insufficient"
    """
    windows = _safe_windows(windows)
    events: list[DrivingEvent] = []
    capability: dict[str, str] = {}

    for detector in REGISTRY:
        any_detected = False
        any_looked_clean = False

        for w in windows:
            try:
                if not _window_satisfies_requires(w, detector.requires):
                    continue
                if w.n_samples < detector.min_samples:
                    continue

                result = detector.detect(w)
            except Exception:
                # Never raise out of run_registry: a broken detector, or a
                # malformed window (None, missing n_samples, ...), on one
                # window must not take down the rest of the report, and
                # must not silently masquerade as "looked, found nothing".
                logger.exception(
                    "run_registry: detector %r failed evaluating a window",
                    getattr(detector, "name", detector),
                )
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


def _all_finite(*values) -> bool:
    """True when every value is neither ``None`` nor NaN/+-inf.

    `x is None` alone is not enough: NaN equals nothing, including None
    (`float("nan") is None` is False), and every comparison against NaN
    (including a floor check like ``deficit <= FLOOR``) is False -- so a NaN
    silently defeats both an ``is None`` guard and an emit-floor guard,
    producing a confidently-labelled ``validity="measured"`` event carrying
    a meaningless number. Detectors call this before doing any arithmetic
    with reference/window values; `DrivingEvent.__post_init__` re-checks the
    two numbers that actually leave the module (`magnitude`, `time_cost_s`)
    as a second, independent layer.
    """
    for v in values:
        if v is None or not np.isfinite(v):
            return False
    return True


# ── over_slowing ────────────────────────────────────────────────────────
#
# Compares this lap's apex speed at a corner against this driver's own best
# apex speed at the SAME corner (``reference["apex_speed_mps"]``). Measured
# on the real kart session this fires on 57% of corner-laps -- arithmetic,
# not an accusation: only one lap can hold the record. It exists to RANK
# ("why did this corner-lap cost time"), ordered by ``time_cost_s`` at the
# read surface (Task 10), not to flag every lap that isn't the best one.

# Measured probe: apex-speed deficits at or below 0.5 m/s did not separate
# from sample-to-sample scatter on the real session -- only deficits above
# this floor read as a genuine hang-back at the apex rather than lap noise.
# Emit strictly above it.
OVER_SLOWING_APEX_DEFICIT_FLOOR_MPS = 0.5


class _OverSlowing:
    """``over_slowing``: this lap's apex speed fell short of the driver's
    own best apex speed at this corner, by more than the measured floor."""

    name = "over_slowing"
    requires = frozenset({"apex_speed_mps", "corner_time_s"})
    # Real corner windows on this grid measured 25-79 samples (review probe,
    # fix round 1). 5 is a deliberately permissive floor, not a tuned one:
    # it only rejects windows an order of magnitude smaller than anything
    # seen on real data -- catching truncated/degenerate windows without
    # asserting a "right" value nobody has measured for this detector.
    min_samples = 5

    def detect(self, w: CornerWindow) -> DrivingEvent | None:
        reference = w.reference or {}
        apex_speed = w.apex_speed_mps
        corner_time = w.corner_time_s
        ref_apex_speed = reference.get("apex_speed_mps")
        ref_corner_time = reference.get("corner_time_s")

        # Refuse rather than guess: every number this claim needs must be
        # real (not missing, not NaN, not +-inf) before it gets made -- an
        # incomplete reference (e.g. no admissible lap has established this
        # corner's bests yet) is silence, not a fabricated zero.
        if not _all_finite(apex_speed, corner_time, ref_apex_speed, ref_corner_time):
            return None

        deficit = ref_apex_speed - apex_speed
        if deficit <= OVER_SLOWING_APEX_DEFICIT_FLOOR_MPS:
            return None

        return DrivingEvent(
            event_type="over_slowing",
            lap_number=w.lap_number,
            corner_id=w.corner_id,
            s_norm_start=w.s_norm_start,
            s_norm_end=w.s_norm_end,
            magnitude=deficit,
            magnitude_unit="m/s",
            time_cost_s=corner_time - ref_corner_time,
            validity=VALIDITY_MEASURED,
            reason=None,
            n_samples_in_window=w.n_samples,
            evidence={
                "apex_speed_mps": apex_speed,
                "reference_apex_speed_mps": ref_apex_speed,
                "corner_time_s": corner_time,
                "reference_corner_time_s": ref_corner_time,
            },
        )


OVER_SLOWING = _OverSlowing()


# ── late_throttle ───────────────────────────────────────────────────────
#
# Compares this lap's throttle-onset distance against this driver's own
# best onset at the SAME corner (``reference["throttle_onset_m"]``).
# ``throttle_onset_m`` is a speed-derivative PROXY, not a real throttle
# channel (``pipeline/stages/s10b_corners.py:494-498``: the first post-apex
# sample where speed exceeds apex+0.5 m/s and keeps rising) -- as an
# absolute claim the metres number is fiction. Comparing this lap to this
# driver's own best pass through the SAME corner is what makes it usable:
# the proxy's bias appears on both sides of the comparison and cancels.
# Measured to fire on 68% of corner-laps -- same "only one lap holds the
# record" arithmetic as over_slowing, so this ranks rather than flags.

# Measured probe: throttle-onset deltas at or below 2 m did not separate
# from proxy noise on the real session. Emit strictly above it.
LATE_THROTTLE_ONSET_FLOOR_M = 2.0


class _LateThrottle:
    """``late_throttle``: this lap's (proxy) throttle onset landed further
    down the straight than the driver's own best onset at this corner, by
    more than the measured proxy-noise floor. Evidence names the proxy so
    this is never read downstream as a real throttle measurement."""

    name = "late_throttle"
    requires = frozenset({"throttle_onset_m", "corner_time_s"})
    # Same measured floor as over_slowing: real corner windows on this grid
    # measured 25-79 samples (review probe, fix round 1), so 5 is a
    # deliberately permissive floor pending any detector-specific tuning,
    # not a value derived to be "correct" for this detector specifically.
    min_samples = 5

    def detect(self, w: CornerWindow) -> DrivingEvent | None:
        reference = w.reference or {}
        onset = w.throttle_onset_m
        corner_time = w.corner_time_s
        ref_onset = reference.get("throttle_onset_m")
        ref_corner_time = reference.get("corner_time_s")

        # Refuse rather than guess: no onset found on this lap, no reference
        # onset to compare against, or either value non-finite, means no
        # claim -- not a fabricated one.
        if not _all_finite(onset, corner_time, ref_onset, ref_corner_time):
            return None

        delta = onset - ref_onset
        if delta <= LATE_THROTTLE_ONSET_FLOOR_M:
            return None

        return DrivingEvent(
            event_type="late_throttle",
            lap_number=w.lap_number,
            corner_id=w.corner_id,
            s_norm_start=w.s_norm_start,
            s_norm_end=w.s_norm_end,
            magnitude=delta,
            magnitude_unit="m",
            time_cost_s=corner_time - ref_corner_time,
            validity=VALIDITY_MEASURED,
            reason=None,
            n_samples_in_window=w.n_samples,
            evidence={
                "throttle_onset_m": onset,
                "reference_throttle_onset_m": ref_onset,
                "source": "speed_derivative_proxy",
                "corner_time_s": corner_time,
                "reference_corner_time_s": ref_corner_time,
            },
        )


LATE_THROTTLE = _LateThrottle()


REGISTRY = (OVER_SLOWING, LATE_THROTTLE)
"""Tasks 7-8's detectors. Task 7 populates over_slowing/late_throttle here;
Task 8 appends re_braking/envelope_under_use."""
