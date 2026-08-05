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
from typing import Final, Iterable, Protocol

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

# ── throttle-onset status taxonomy (machine-readable) ─────────────────────
#
# `throttle_onset_m` is derived upstream (s10b_corners._assign_throttle_onsets)
# by scanning forward from the apex for the first sample above a per-corner,
# session-fixed speed. That scan can legitimately come back empty, and the
# whole point of this vocabulary is that "empty" gets NAMED rather than
# collapsed into a missing value. `CornerWindow.throttle_onset_status` carries
# exactly one of these for every corner-lap the derivation actually ran on;
# it is None only when the derivation never ran at all (an absent distance or
# speed column, an upstream stage failure), which is the case `late_throttle`'s
# `requires` still gates out as "insufficient".
#
# Same discipline as grip_anchor.py's REASON_* taxonomy: a reason that names
# the wrong cause is worse than no reason, so each value below is reserved for
# one cause and `_LateThrottle.detect` maps anything it does not recognise to
# the last-resort value rather than passing an unknown string through to the
# customer-visible `DrivingEvent.reason`.
ONSET_MEASURED: Final = "measured"
# The scan ran over the full bounded window and speed never rose above the
# corner's session-fixed onset threshold while still climbing. A real,
# located refusal: this lap never got back to the reference speed inside the
# corner's own exit.
ONSET_NO_SPEED_CROSSING: Final = "onset_no_speed_crossing"
# No admissible lap at this corner produced a finite apex speed, so no
# session-fixed threshold could be established for any lap. Distinct from
# ONSET_NO_SPEED_CROSSING: there was nothing to cross, not a failure to cross.
ONSET_NO_SESSION_THRESHOLD: Final = "onset_no_session_threshold"
# This corner-lap's own window had no locatable apex (fewer than three
# samples inside the corner, or an all-NaN speed slice), so the scan had no
# start point.
ONSET_NO_APEX: Final = "onset_no_apex"
# The corner's geometry gives a degenerate search window (s_end <= s_start),
# so there is no forward span to scan.
ONSET_NO_SEARCH_WINDOW: Final = "onset_no_search_window"
# No session-wide reference length could be derived (the detection lap has no
# usable distance column / zero span), so there is no map between the
# normalised frame the scan runs in and the metres the metric is published
# in. Session-wide, not per-corner-lap: every corner-lap in the session
# carries this one together. See s10b_corners._detection_frame.
ONSET_NO_REFERENCE_FRAME: Final = "onset_no_reference_frame"
# Last resort, mirroring grip_anchor.REASON_NO_MEASUREMENT: the derivation
# refused and no more specific cause was identifiable.
ONSET_NO_MEASUREMENT: Final = "onset_no_measurement"

ONSET_STATUSES: Final = frozenset({
    ONSET_MEASURED,
    ONSET_NO_SPEED_CROSSING,
    ONSET_NO_SESSION_THRESHOLD,
    ONSET_NO_APEX,
    ONSET_NO_SEARCH_WINDOW,
    ONSET_NO_REFERENCE_FRAME,
    ONSET_NO_MEASUREMENT,
})

ONSET_REFUSAL_REASONS: Final = ONSET_STATUSES - {ONSET_MEASURED}
"""The closed set a `late_throttle` event's `reason` may ever carry."""

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

    ``throttle_onset_m`` and ``throttle_onset_norm`` are THE SAME
    MEASUREMENT in two units. ``_norm`` is the primitive -- a 0-1 position
    in the lap-length-invariant frame -- and ``_m`` is it converted once,
    session-wide, against the detection lap's span (see
    ``s10b_corners._assign_throttle_onsets``). Comparing two laps' ``_m``
    values is therefore legitimate; comparing two laps' RAW per-lap
    distances is not, and doing so was the coordinate-frame defect fixed on
    2026-08-05. ``_norm`` is carried onto the window and into the event's
    evidence so the conversion is auditable from the stored record rather
    than taken on trust.

    ``throttle_onset_status`` is the companion to ``throttle_onset_m`` and
    the field ``late_throttle`` actually gates on. It is one of
    ``ONSET_STATUSES`` whenever the upstream derivation RAN for this
    corner-lap -- ``ONSET_MEASURED`` when it found an onset, one of the
    refusal reasons when it looked and found none -- and None only when it
    never ran at all. That split is what lets a failed-but-attempted
    measurement surface as an explicit ``not_measurable`` event carrying the
    named cause, while a derivation that never ran still reads
    "insufficient" through ``requires``. Gating on ``throttle_onset_m``
    alone could not express the difference: both cases leave it None.

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
    throttle_onset_norm: float | None
    throttle_onset_status: str | None
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


def _all_positive(*values) -> bool:
    """True when every value is finite AND strictly greater than zero.

    A SECOND, DIFFERENT CLASS OF BAD NUMBER FROM ``_all_finite``'s. That
    guard was built for NaN/inf -- values that are not numbers. This one is
    for values that ARE numbers and are IMPOSSIBLE: a speed of 0 m/s at the
    apex of a corner the driver drove through, a corner time of 0 s.

    It exists because ``corner_analysis.py:731`` substitutes
    ``actual_apex_speed_mps=0.0`` whenever its own corner slice is empty or
    all-NaN, and that 0.0 sails through every finiteness check there is. The
    reachable consequence, demonstrated by the final review: an
    ``over_slowing`` event with ``validity="measured"``, magnitude 17.82 m/s
    and evidence ``{"apex_speed_mps": 0.0, ...}`` -- telling the driver they
    were 17.8 m/s slow at an apex whose speed was never measured.

    WHAT MAKES IT REACHABLE IS A TWO-FRAME SPLIT. ``apex_speed_mps`` comes
    from ``corner_analysis``'s ABSOLUTE-metre mask while ``corner_time_s``
    comes from ``s10d2``'s NORMALISED mask, and the two disagree on sample
    count on 35 of 72 corner-laps on the real fixture -- so the absolute mask
    can fail silently into 0.0 exactly where the normalised mask succeeds and
    supplies the other field ``over_slowing.requires`` needs.

    Applied to apex SPEED and corner TIME only, on both the window and the
    reference side. Deliberately NOT applied to ``throttle_onset_m`` /
    ``throttle_onset_norm`` (0 is a legitimate position -- the start of the
    lap) nor to ``grip_anchor_pct`` (0% is implausible but arithmetically
    reachable from a genuine |a_lat| of 0, and inventing an impossibility
    claim for it would be the same error in the other direction; recorded as
    checked, not guarded).
    """
    for v in values:
        if v is None or not np.isfinite(v) or v <= 0:
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
        # And a SECOND, independent layer for the impossible-but-finite
        # class -- see `_all_positive`. `s10d3._build_one_window` already
        # strips non-positive apex speeds and corner times off the window so
        # `requires` reports "insufficient" (could not look) rather than this
        # detector reporting None (looked, found nothing); this catch here is
        # for a window built by any other caller.
        if not _all_positive(apex_speed, corner_time, ref_apex_speed, ref_corner_time):
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
# channel (``pipeline/stages/s10b_corners.py``'s
# ``_assign_throttle_onsets``: the first post-apex sample above the
# corner's session-fixed onset speed that is still climbing) -- as an
# absolute claim the metres number is fiction. Comparing this lap to this
# driver's own best pass through the SAME corner is what makes it usable:
# the proxy's bias appears on both sides of the comparison and cancels.
#
# THAT CANCELLATION IS A PROPERTY OF THE UPSTREAM DERIVATION, NOT A GIVEN.
# Until 2026-08-05 the onset threshold was THIS LAP'S OWN apex speed plus
# 0.5 m/s, so a faster lap had to reach a higher ABSOLUTE speed before the
# threshold tripped and its onset was reported LATER. The bias did not
# cancel: it was anti-correlated with performance. Measured on
# data/raw/OK_R4.csv, median within-corner corr(apex_speed, onset) was
# +0.552, corr(corner_time, onset) was NEGATIVE on 6 of 8 corners, and 8 of
# 59 events fired on the FASTEST pass through their own corner -- including
# the session's largest magnitude (40.5 m, corner 1 lap 7, the fastest
# corner-1 lap of the session). The threshold is now per-corner and
# SESSION-FIXED (the corner's session-best apex + 0.5 m/s), so every lap at a
# corner is measured against the same absolute speed. Any future change to
# that derivation has to preserve the session-fixed property or this detector
# goes back to penalising the driver for going fast.
#
# A SECOND, INDEPENDENT DEFECT WAS FIXED ON THE SAME DAY: the onset was
# reported as a RAW PER-LAP ABSOLUTE METRE and differenced across laps whose
# spans run 1198.65-1217.97 m, so a longer lap put the same tarmac at a larger
# metre and was reported as later. The scan and the metric are now in
# `distance_norm`, converted to metres once against one session reference
# length (s10b_corners._assign_throttle_onsets). Magnitudes fell accordingly:
# the largest late_throttle event was 41.2 m at corner 8 lap 4 and is now
# 28.9 m for the same corner-lap (12.3 m of it was lap length); corner 8's
# median fell 42%, corner 6's 38%, corner 3's 34%. Two events dropped below
# the 2.0 m emit floor. See `_LateThrottle`'s selection block in
# s10b_corners.py for what that did to the metric's measured added
# information -- it collapsed from +0.360 to +0.098 (t = 0.81), i.e. the
# apparent signal was largely the frame.
#
# HOW MUCH THIS DETECTOR ACTUALLY ADDS, AND WHY THE READ SURFACE MERGES IT.
# `corr(corner_time, apex_speed)` is about -0.75 on this session, so an onset
# that correlates with apex speed inherits a corner-time correlation for
# free; "corr(corner_time, onset) is positive" is therefore NOT evidence this
# detector measures throttle timing.
#
# THE COUPLING IS STRUCTURAL, NOT INCIDENTAL. With a session-fixed threshold,
# a slower lap arrives at the apex carrying less speed and must therefore
# climb FURTHER along the exit to reach the same fixed speed. The onset
# distance mechanically encodes the apex-speed deficit. The 2026-08-05 fix
# flipped the SIGN of that coupling (it used to report the faster lap as
# later, which is backwards); it did not and could not remove it.
#
# How much is left over: in the canonical distance frame, NOT DISTINGUISHABLE
# FROM ZERO IN ANY SPECIFICATION. The partial correlation
# r(corner_time, onset | apex_speed) is +0.098 (t = 0.81) pooled and +0.002
# (t = 0.02) under lap fixed effects, with a corner-cluster bootstrap 95% CI
# of [-0.265, +0.233]. The +0.360 previously quoted here was measured before
# the coordinate-frame fix and was largely lap length. See s10b_corners'
# `_assign_throttle_onsets` block comment for the full before/after table.
#
# CONSEQUENCES FOR ANY READ SURFACE (Phase 3, read this):
#
#   * `late_throttle`'s METRE magnitude must NEVER be rendered as a
#     standalone claim. On its own it reads as "you got on the power N metres
#     late", which the evidence above does not support -- a large part of
#     that N is the apex-speed deficit `over_slowing` already reported.
#   * It must NEVER be presented as a CAUSE of the event's `time_cost_s`.
#     The cost is `corner_time - reference_corner_time`, identical to the
#     cost `over_slowing` reports for the same corner-lap; attributing it to
#     throttle timing would be attributing one measurement twice.
#   * Render it as a facet OF the corner-lap, alongside the apex deficit --
#     which is exactly the shape `events_repo._dedupe_by_lap_corner`
#     produces via `evidence["also_fired"]`.
#
# The detector keeps its own event type deliberately: solo `late_throttle`
# events carry a median cost of 0.057 s against 0.181 s for co-firing ones,
# so the ranked view (ordered by `time_cost_s` DESC) already sinks them, and
# the dedupe already prevents double-counting on co-firing keys. Suppressing
# them outright would discard the ~30% that fire alone to solve a problem the
# ordering already solves. `over_slowing` and `late_throttle` co-fire on 39
# of 57 measured late_throttle events (68%) and carry the IDENTICAL
# `time_cost_s` by construction; the dedupe resolves that pair
# deterministically (over_slowing wins) rather than letting SQL row order
# decide which correction a driver is shown.

# Measured probe: throttle-onset deltas at or below 2 m did not separate
# from proxy noise on the real session. Emit strictly above it.
LATE_THROTTLE_ONSET_FLOOR_M = 2.0


class _LateThrottle:
    """``late_throttle``: this lap's (proxy) throttle onset landed further
    down the straight than the driver's own best onset at this corner, by
    more than the measured proxy-noise floor. Evidence names the proxy so
    this is never read downstream as a real throttle measurement."""

    name = "late_throttle"
    # Gates on the STATUS, not on the value. `throttle_onset_m` is None both
    # when the derivation ran and found nothing and when it never ran, and
    # those two must not produce the same answer -- see CornerWindow's
    # docstring. With the status required instead, an attempted-but-empty
    # measurement reaches `detect` and becomes an explicit `not_measurable`
    # event naming its cause, while a derivation that never ran leaves the
    # status None and is still gated out as "insufficient".
    requires = frozenset({"throttle_onset_status", "corner_time_s"})
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
        status = w.throttle_onset_status

        if status != ONSET_MEASURED:
            # The derivation LOOKED and came back empty. Say so, located and
            # named, rather than dropping the corner-lap: a dropped window
            # would still be counted out of the per-corner reference, biasing
            # that reference toward the subset of laps where the scan happened
            # to succeed. `reason` is clamped to the closed vocabulary so an
            # unrecognised upstream string can never reach a customer.
            return DrivingEvent(
                event_type="late_throttle",
                lap_number=w.lap_number,
                corner_id=w.corner_id,
                s_norm_start=w.s_norm_start,
                s_norm_end=w.s_norm_end,
                magnitude=None,
                magnitude_unit="m",
                time_cost_s=None,
                validity=VALIDITY_NOT_MEASURABLE,
                reason=(status if status in ONSET_REFUSAL_REASONS
                        else ONSET_NO_MEASUREMENT),
                n_samples_in_window=w.n_samples,
                evidence={"source": "speed_derivative_proxy"},
            )

        # Refuse rather than guess: no onset found on this lap, no reference
        # onset to compare against, or either value non-finite, means no
        # claim -- not a fabricated one.
        if not _all_finite(onset, corner_time, ref_onset, ref_corner_time):
            return None
        # `corner_time` alone gets the positivity check: this detector's own
        # magnitude is a distance, where 0 is a real position, but its
        # `time_cost_s` is a corner-time gap and a 0 s corner time is the
        # same impossible-but-finite substitution `_all_positive` documents.
        if not _all_positive(corner_time, ref_corner_time):
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
                # The frame both metre values above were converted from,
                # named so a reader can tell a canonical-frame metre from a
                # raw per-lap one. `_norm` may be absent on a window built
                # by hand or by a pre-2026-08-05 metric dict.
                "onset_frame": "distance_norm_x_detection_lap_span",
                "throttle_onset_norm": w.throttle_onset_norm,
                "source": "speed_derivative_proxy",
                "corner_time_s": corner_time,
                "reference_corner_time_s": ref_corner_time,
            },
        )


LATE_THROTTLE = _LateThrottle()


# ── re_braking ──────────────────────────────────────────────────────────
#
# Looks for a SUSTAINED post-apex deceleration run in `a_long_mps2` -- a
# second, distinct dab of the brake after the corner's main braking event is
# already behind the driver. Measured on the real kart session this fires on
# 7% of corner-laps -- rare enough to work as a FLAG rather than a ranking,
# unlike over_slowing/late_throttle (57%/68%): with one driver-vs-self
# comparison, a re-brake is either present or it isn't.
#
# Units: the resampled frame carries `Longitudinal acceleration (G) *calc`
# in G, not m/s^2 -- Task 9's window builder converts (x 9.80665) before
# this detector ever sees the array. This detector receives m/s^2 already
# and must not convert again.
#
# Slices from `apex_idx`, never re-derives it via nanargmin: `apex_idx` is
# the window builder's single source of truth for "where is the apex", and
# a second argmin over `speed_mps` can disagree with it on ties or noise
# (see CornerWindow's docstring). Re-deriving here would give this module
# two different notions of "the apex" inside one record.

# Measured probe: at ~85-105 ms/sample on this grid, a genuine brake dab
# spans 2-3 samples; a single sample is noise. Requiring >= 3 consecutive
# samples rejects isolated-sample noise, but by itself does NOT reproduce
# the measured 7% (see RE_BRAKING_DECEL_FLOOR_MPS2 below: floor 0.0 with
# this same run-length gate measured 35.6% on real data, not 7%). Getting to
# 7% needs BOTH gates together -- run length rejects a too-short blip,
# the magnitude floor rejects a too-shallow one.
RE_BRAKING_MIN_RUN_SAMPLES = 3

# Sign convention: a_long_mps2 is signed, negative = decelerating.
#
# -0.5 m/s^2, NOT 0.0 -- measured, not assumed. Fix round 1: the run-length
# gate alone does NOT do the noise rejection the comment above claims. The
# reviewer ran the shipped `_longest_run_below` over the REAL post-apex
# `a_long` from `data/raw/OK_R4.csv` (corners/per-lap frames captured from
# an actual `run_full_analysis`):
#     floor -0.5 (the original probe's floor):  4/59 = 6.8%  -- reproduces
#                                                                the cited 7%
#     floor  0.0 (what Task 8 first shipped):  21/59 = 35.6% -- 5x too high,
#                                                                over_slowing/
#                                                                late_throttle
#                                                                ranking
#                                                                territory,
#                                                                not a flag
# A magnitude floor of 0.0 lets throttle-off engine-braking / road noise
# that never truly decelerates hard count as a "re-brake". -0.5 is the
# measured boundary below which that noise stops dominating.
RE_BRAKING_DECEL_FLOOR_MPS2 = -0.5


def _longest_run_below(values: np.ndarray, floor: float) -> tuple[int, int]:
    """(length, start_index) of the longest run of consecutive samples
    strictly below `floor`. Returns (0, -1) for an empty array or no such
    run. On a tie for longest, the FIRST run found wins -- deterministic,
    and it is the earliest re-brake that matters for locating the event."""
    longest = 0
    longest_start = -1
    current = 0
    current_start = -1
    for i, v in enumerate(values):
        if v < floor:
            if current == 0:
                current_start = i
            current += 1
            if current > longest:
                longest = current
                longest_start = current_start
        else:
            current = 0
    return longest, longest_start


class _ReBraking:
    """``re_braking``: a sustained (>= 3 consecutive samples) deceleration
    run found AFTER the apex -- a second dab of the brake once the corner's
    main braking event is already over."""

    name = "re_braking"
    requires = frozenset({"a_long_mps2", "apex_idx"})
    # A post-apex slice needs at least the run length itself present after
    # the apex to have any chance of finding one; 5 mirrors the permissive
    # floor used by Tasks 7's detectors (not a tuned value for this one).
    min_samples = 5

    def detect(self, w: CornerWindow) -> DrivingEvent | None:
        a_long = w.a_long_mps2
        apex_idx = w.apex_idx

        # Refuse rather than guess: no channel, no apex location, or a
        # non-finite apex index means no claim can be made.
        if a_long is None or not _all_finite(apex_idx):
            return None
        apex_idx = int(apex_idx)
        if apex_idx < 0 or apex_idx >= len(a_long):
            return None

        post_apex = a_long[apex_idx:]
        if not _all_finite(*post_apex):
            return None

        run_length, run_start = _longest_run_below(post_apex, RE_BRAKING_DECEL_FLOOR_MPS2)
        if run_length < RE_BRAKING_MIN_RUN_SAMPLES:
            return None

        # The strongest (most negative) sample within the run, reported as a
        # positive magnitude -- the checkable physical claim ("how hard"),
        # not just "how long".
        run_slice = post_apex[run_start:run_start + run_length]
        peak_decel_mps2 = float(-np.min(run_slice))
        if not _all_finite(peak_decel_mps2):
            return None

        return DrivingEvent(
            event_type="re_braking",
            lap_number=w.lap_number,
            corner_id=w.corner_id,
            s_norm_start=w.s_norm_start,
            s_norm_end=w.s_norm_end,
            magnitude=peak_decel_mps2,
            magnitude_unit="m/s2",
            time_cost_s=None,
            validity=VALIDITY_MEASURED,
            reason=None,
            n_samples_in_window=w.n_samples,
            evidence={
                "run_length_samples": run_length,
                "run_start_idx_post_apex": run_start,
                "apex_idx": apex_idx,
            },
        )


RE_BRAKING = _ReBraking()


# ── envelope_under_use ─────────────────────────────────────────────────────
#
# A per-phase slice of Phase 1's `grip_anchor_pct`, already computed onto
# the window -- this detector adds no new math, only a floor. It inherits
# Phase 1's tier and reason "for free" in the sense that the number itself
# was already measured upstream; this detector's only job is deciding when
# that number is low enough to be worth surfacing.
#
# 100% IS the measured floor, not an arbitrary round number: Phase 1's
# baseline is this session's own p95 envelope (grip_anchor.py's module
# docstring), so "under 100%" means literally "used less grip than this
# driver's own best at this speed/phase" -- the honest reading of
# "under-use". It is also the only floor consistent with the one number
# already measured on real data: median 101.5%, 37 of 57 corner-laps above
# 100% (grip_anchor.py:17, s10d2_grip_anchor.py probe) -- a 100% floor fires
# on the remaining 20/57 (~35%), i.e. well under half, matching the brief.
ENVELOPE_UNDER_USE_FLOOR_PCT = 100.0


class _EnvelopeUnderUse:
    """``envelope_under_use``: this lap's grip-anchor usage for this phase
    fell below the measured floor -- meaningful margin left unused."""

    name = "envelope_under_use"
    requires = frozenset({"grip_anchor_pct"})
    # Same permissive floor as Tasks 7's detectors -- real corner windows
    # measured 25-79 samples; not tuned specifically for this detector.
    min_samples = 5

    def detect(self, w: CornerWindow) -> DrivingEvent | None:
        grip_pct = w.grip_anchor_pct

        # Refuse rather than guess: no Phase 1 number for this phase means
        # no claim, not a fabricated one.
        if not _all_finite(grip_pct):
            return None

        if grip_pct >= ENVELOPE_UNDER_USE_FLOOR_PCT:
            return None

        return DrivingEvent(
            event_type="envelope_under_use",
            lap_number=w.lap_number,
            corner_id=w.corner_id,
            s_norm_start=w.s_norm_start,
            s_norm_end=w.s_norm_end,
            magnitude=grip_pct,
            magnitude_unit="pct",
            time_cost_s=None,
            validity=VALIDITY_MEASURED,
            reason=None,
            n_samples_in_window=w.n_samples,
            evidence={
                "grip_anchor_pct": grip_pct,
                "floor_pct": ENVELOPE_UNDER_USE_FLOOR_PCT,
            },
        )


ENVELOPE_UNDER_USE = _EnvelopeUnderUse()


REGISTRY = (OVER_SLOWING, LATE_THROTTLE, RE_BRAKING, ENVELOPE_UNDER_USE)
"""All four Phase 2 detectors: Task 7 built over_slowing/late_throttle,
Task 8 appends re_braking/envelope_under_use."""
