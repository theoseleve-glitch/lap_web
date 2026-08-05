"""Phase 1 grip anchor: an honestly-labelled "% of available grip used".

Every number this module emits carries a TIER naming what "available" was
measured against, and a machine-readable REASON when it had to degrade.
Pure and dependency-light — no I/O, no pipeline knowledge — so the decision
can be bite-checked without a database.

WHAT "AVAILABLE" IS, PLAINLY: the highest tier's baseline is
``FrictionCircle.lateral_vals``, which ``friction_model.build_friction_model``
builds as a per-speed-bin **p95 of |a_lat| taken from this session's own laps**
(``friction_model.py:574-577``). It is therefore **NOT an absolute vehicle
limit** and must never be presented as one. It is the same population as the
``driver_best_session`` tier, differing only in the statistic: a p95 across a
speed bin rather than a single maximum at one corner. A driver who never
approached the car's real limit collapses that envelope onto their own
performance and still reads ~100% "of available grip" — which is why the
real-data median on ``OK_R4.csv`` is 101.51%, not something comfortably under
100. The tier names say ``session_envelope`` precisely so that no consumer can
read them as a physics claim about the car.

Fail-SAFE: any doubt degrades toward the lower tier. An unknown or absent
signal must never produce a session-envelope tier.

Shape copied from ``track_surface/honesty.py``; values are our own.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

import numpy as np

# -- Tier vocabulary — the ONLY legal values of corner_metrics.grip_anchor_tier.
#
# READ THE NAMES LITERALLY. Both top tiers are ``session_envelope_*``, never
# "physics", because the envelope they measure against is derived from THIS
# SESSION'S OWN LAPS (see the module docstring). Naming them "physics" was the
# overclaim these names exist to retire.
#
# Two of them, not one: the ellipse exponent is FITTED from boundary samples
# but silently falls back to a hint when they are thin, and a claim of "fitted
# ellipse" over a defaulted p=2 would be a false provenance claim.
#
# PHASE 1 CAVEAT — the two are arithmetically IDENTICAL right now. The stage
# passes ``a_long_mps2=0.0`` (``s10d2_grip_anchor.run_grip_anchor``), so in
# ``ellipse_fill_pct`` the longitudinal ratio ``rx`` is exactly 0 and the fill
# collapses to ``100 * (0 + ry**p)**(1/p) == 100 * ry`` — the exponent cancels
# out entirely. So in Phase 1 these two tiers differ ONLY in provenance
# labelling, not in the number they produce. They stop being equivalent the
# moment Phase 2 threads a real longitudinal value through.
TIER_SESSION_ENVELOPE_ELLIPSE_FITTED: Final = "session_envelope_ellipse_fitted"
TIER_SESSION_ENVELOPE_ELLIPSE_DEFAULT_P2: Final = "session_envelope_ellipse_default_p2"
# Session-scoped only. Cross-session ("driver_best_track") is NOT available:
# corner_id is a positional index over curvature regions found in one lap of
# one session, and corner_persistence has zero production callers. Phase 2
# adds a new tier value rather than redefining this one.
TIER_DRIVER_BEST_SESSION: Final = "driver_best_session"
TIER_REFUSED: Final = "refused"

TIERS: Final = frozenset({
    TIER_SESSION_ENVELOPE_ELLIPSE_FITTED,
    TIER_SESSION_ENVELOPE_ELLIPSE_DEFAULT_P2,
    TIER_DRIVER_BEST_SESSION,
    TIER_REFUSED,
})

_SESSION_ENVELOPE_TIERS: Final = frozenset({
    TIER_SESSION_ENVELOPE_ELLIPSE_FITTED,
    TIER_SESSION_ENVELOPE_ELLIPSE_DEFAULT_P2,
})

# -- Reason taxonomy (machine-readable).
#
# THE WHOLE POINT OF A REASON IS THAT IT NAMES THE ACTUAL CAUSE. A reason that
# names the wrong one is worse than no reason at all: it sends an operator
# hunting a problem that does not exist. Three of these were emitted for the
# wrong cause before review; the comments below record which, so nobody
# re-merges them.

# Nothing to measure against. Covers BOTH "no FrictionCircle was supplied"
# and "no envelope bin existed to inspect" -- the latter is reachable whenever
# step 09i_grip_map degrades while 09c_friction_model succeeds. That case used
# to emit REASON_BIN_FABRICATED, which claimed a data-quality problem inside an
# envelope that was never built at all.
REASON_NO_ENVELOPE: Final = "no_envelope"
# An envelope bin EXISTS but is friction_envelope's synthetic fill, not a
# measurement. Reserved strictly for that; see REASON_NO_ENVELOPE above.
REASON_BIN_FABRICATED: Final = "bin_fabricated"
REASON_SPEED_OUT_OF_BINS: Final = "speed_out_of_bins"
REASON_CHANNEL_UNTRUSTED: Final = "channel_untrusted"
# The session-relative tier has no baseline for this corner AT ALL.
REASON_NO_LAP_BASELINE: Final = "no_lap_baseline"
# The baseline EXISTS but this corner-lap produced no usable |a_lat| (an empty
# corner window, an all-NaN lateral channel). Distinct from
# REASON_NO_LAP_BASELINE, which used to absorb it and thereby reported a
# missing baseline that was sitting right there.
REASON_NO_LATERAL_SAMPLE: Final = "no_lateral_sample"
# The friction ellipse has a collapsed axis. Named per axis because the
# longitudinal one carries NO weight in Phase 1 (the stage passes
# a_long_mps2=0.0, so the longitudinal term is 0**p == 0 whatever ax_max is) --
# reporting a degenerate traction axis as a generic "no measurement" told an
# operator their measurement failed when the axis they actually care about was
# healthy.
REASON_DEGENERATE_LATERAL_AXIS: Final = "degenerate_lateral_axis"
REASON_DEGENERATE_LONGITUDINAL_AXIS: Final = "degenerate_longitudinal_axis"
# Last resort: the fill genuinely could not be computed and no more specific
# cause was identifiable.
REASON_NO_MEASUREMENT: Final = "no_measurement"
# Reserved for Phase 2 — see the tier comments above.
REASON_CONDITION_UNKNOWN: Final = "condition_unknown"
REASON_CORNER_IDENTITY_UNSTABLE: Final = "corner_identity_unstable"


def is_quotable_as_session_envelope(tier: str | None) -> bool:
    """The consumer guard: may this percentage be quoted against the session's
    fitted grip envelope?

    Renamed from ``is_quotable_as_physics``, which named the wrong thing. "As
    physics" implied an absolute claim about the car's limit; the envelope is
    a p95 over this session's own laps, so no tier in this module supports
    such a claim. What the guard actually separates is *provenance*: True means
    the baseline is the session's speed-binned grip envelope, False means it is
    a single best sample (``driver_best_session``), nothing at all
    (``refused``), or an unknown tier.

    Every presentation of a True value still has to say "of the grip seen in
    this session", never "of the car's limit".
    """
    return tier in _SESSION_ENVELOPE_TIERS


def channel_trust_ratio(
    a_lat_mps2: np.ndarray,
    speed_mps: np.ndarray,
    curvature_1pm: np.ndarray,
    *,
    min_geo_accel: float = 2.0,
    min_samples: int = 20,
) -> float | None:
    """Median |a_lat| / (v^2 * kappa) over genuinely-cornering samples.

    1.0 means the measured lateral channel agrees with the path geometry.
    Returns None when there is not enough cornering to judge — which is a
    refusal, not a pass.

    ``min_geo_accel`` (m/s^2) is the whole point: on a straight, v^2*kappa is
    ~0 and the ratio is noise divided by noise. Averaging those in is what
    drags the persisted sensor_quality figure to 0.531. Restricted to real
    cornering, real kart data measures 0.961.
    """
    a = np.abs(np.asarray(a_lat_mps2, dtype=float))
    v = np.asarray(speed_mps, dtype=float)
    k = np.abs(np.asarray(curvature_1pm, dtype=float))

    a_geo = v ** 2 * k
    usable = np.isfinite(a) & np.isfinite(a_geo) & (a_geo > min_geo_accel)
    if int(usable.sum()) < min_samples:
        return None

    ratio = float(np.nanmedian(a[usable] / a_geo[usable]))
    return ratio if np.isfinite(ratio) else None


# Band within which the lateral channel is trusted for an absolute claim.
# Real kart data measures 0.961. The production frontend uses a tighter band
# [0.80, 1.20] for conservatism; we allow slightly more headroom here to reflect
# measurement uncertainty while still rejecting obviously-broken channels.
TRUST_BAND_LOW: Final = 0.80
TRUST_BAND_HIGH: Final = 1.25


def channel_is_trusted(ratio: float | None) -> bool:
    """Fail-safe: None (not measurable) is NOT trusted."""
    return ratio is not None and TRUST_BAND_LOW <= ratio <= TRUST_BAND_HIGH


def _scalar(x: Any) -> float:
    """FrictionCircle accessors return 0-d or 1-element arrays."""
    return float(np.asarray(x).reshape(-1)[0])


def ellipse_fill_pct(
    a_lat_mps2: float,
    a_long_mps2: float,
    speed_mps: float,
    friction: Any,
) -> float | None:
    """Percentage of the friction ellipse used, along this sample's own
    combined-g direction. NOT capped at 100 — see the module docstring.

    Superellipse: |ax/ax_max|^p + |ay/ay_max|^p = 1, so the fraction of the
    boundary reached is that sum raised to 1/p.
    """
    a_lat = abs(float(a_lat_mps2))
    a_long = float(a_long_mps2)
    if not (np.isfinite(a_lat) and np.isfinite(a_long) and np.isfinite(speed_mps)):
        return None

    try:
        ay_max = _scalar(friction.lateral_max(speed_mps))
        # Asymmetric axes: decelerating is bounded by braking grip, not traction.
        ax_max = _scalar(
            friction.braking_max(speed_mps) if a_long < 0
            else friction.traction_max(speed_mps)
        )
        p = float(friction.exponent)
    except Exception:
        return None

    if not (np.isfinite(ay_max) and np.isfinite(ax_max)) or ay_max <= 0 or ax_max <= 0 or p <= 0:
        return None

    # Do the power arithmetic in numpy float64, not plain Python float. Python's
    # `float ** float` RAISES OverflowError once the result exceeds the
    # representable range, whereas numpy float64 silently saturates to inf --
    # which is exactly what the isfinite guards below exist to catch. A
    # finite, strictly-positive, very small ax_max/ay_max (e.g. a corrupted
    # persisted envelope reconstructed via FrictionCircle.from_dict(), which
    # does not re-apply build_friction_model's _FLOOR) can raise a huge ratio
    # to the exponent and blow past float64 range; that must degrade to None,
    # not raise. The SAME is true of the second power below (frac ** (1/p)):
    # a finite frac raised to a huge 1/p (from a p close to 0, also
    # unclamped through from_dict()) can overflow on its own even when frac
    # itself was perfectly finite -- so its result needs its own isfinite
    # check, not just frac's.
    rx = np.float64(abs(a_long)) / np.float64(ax_max)
    ry = np.float64(a_lat) / np.float64(ay_max)
    p64 = np.float64(p)
    with np.errstate(over="ignore"):
        # Overflow in either power below is expected and handled by the
        # isfinite checks that follow each one -- not a real error, so
        # don't let it warn on every call.
        frac = rx ** p64 + ry ** p64
        if not np.isfinite(frac):
            return None
        result = 100.0 * frac ** (1.0 / p64)

    if not np.isfinite(result):
        return None
    return float(result)


# A FrictionBin is fabricated exactly when friction_envelope took its
# synthetic branch: n_in_bin < 8, which sets confidence to 0.0. Real bins get
# min(1.0, n/32) with n >= 8, hence confidence >= 0.25. The two are exclusive.
_MIN_MEASURED_SAMPLES: Final = 8


def bin_is_measured(bin_obj: Any) -> bool:
    """True only when this envelope bin is a real measurement.

    Fail-safe: anything we cannot inspect is treated as fabricated. Accepts
    either a live ``FrictionBin`` (attribute access) or the dict shape its
    ``.to_dict()`` produces (dict key access) -- the pipeline persists and
    threads through the latter (see ``s10d2_grip_anchor._bin_for_speed``),
    and a bare ``getattr`` used to silently read ``None``/raise for that
    shape regardless of the bin's real confidence, mislabelling a genuinely
    measured bin as fabricated. That confident mislabel, not a loud crash,
    is the failure this needs to guard against.
    """
    try:
        if isinstance(bin_obj, dict):
            confidence = float(bin_obj["confidence"])
            sample_count = int(bin_obj["sample_count"])
        else:
            confidence = float(getattr(bin_obj, "confidence"))
            sample_count = int(getattr(bin_obj, "sample_count"))
    except (AttributeError, TypeError, ValueError, KeyError):
        return False
    return confidence > 0.0 and sample_count >= _MIN_MEASURED_SAMPLES


_G: Final = 9.80665


@dataclass(frozen=True)
class Anchor:
    """One corner-lap's grip verdict. ``pct`` is never capped at 100."""
    tier: str
    reason: str | None
    pct: float | None
    baseline_g: float | None


def _fill_failure_reason(
    a_lat_mps2: float,
    a_long_mps2: float,
    speed_mps: float,
    friction: Any,
) -> str:
    """Name WHY ``ellipse_fill_pct`` refused — down to which axis collapsed.

    ``REASON_NO_MEASUREMENT`` used to absorb every one of these outcomes,
    including the case where the LONGITUDINAL axis is degenerate while the
    lateral axis is perfectly healthy. In Phase 1 the stage passes
    ``a_long_mps2=0.0``, so the longitudinal term contributes exactly nothing
    to the answer — telling an operator "no measurement" because
    ``traction_max`` collapsed, on a session whose lateral channel measured
    fine, points them at the wrong half of the model.

    Mirrors ``ellipse_fill_pct``'s own guards in the same order, so the two
    cannot drift into disagreeing about what happened.
    """
    try:
        if not (np.isfinite(float(a_lat_mps2)) and np.isfinite(float(a_long_mps2))):
            return REASON_NO_LATERAL_SAMPLE
        if not np.isfinite(float(speed_mps)):
            return REASON_NO_MEASUREMENT
        ay_max = _scalar(friction.lateral_max(speed_mps))
        ax_max = _scalar(
            friction.braking_max(speed_mps) if float(a_long_mps2) < 0
            else friction.traction_max(speed_mps)
        )
    except Exception:
        return REASON_NO_MEASUREMENT

    if not np.isfinite(ay_max) or ay_max <= 0:
        return REASON_DEGENERATE_LATERAL_AXIS
    if not np.isfinite(ax_max) or ax_max <= 0:
        return REASON_DEGENERATE_LONGITUDINAL_AXIS
    return REASON_NO_MEASUREMENT


def _session_best_anchor(
    a_lat_mps2: float, session_best_lat_mps2: float | None, reason: str,
) -> Anchor:
    """Tier 2: relative to the driver's own best in THIS session.

    The two refusal branches below name DIFFERENT causes and must not be
    re-merged. No baseline means this corner has no session-best to compare
    against at all — the tier's own prerequisite is missing. No lateral sample
    means the baseline is right there but THIS corner-lap produced no usable
    ``|a_lat|``. Collapsing the second into the first, as this used to, reports
    a missing baseline that exists. The baseline is checked first because it is
    the tier's prerequisite: when neither is available, "no baseline" is the
    fact that has to be fixed first.
    """
    if (
        session_best_lat_mps2 is None
        or not np.isfinite(session_best_lat_mps2)
        or session_best_lat_mps2 <= 0
    ):
        return Anchor(TIER_REFUSED, REASON_NO_LAP_BASELINE, None, None)
    if not np.isfinite(a_lat_mps2):
        return Anchor(TIER_REFUSED, REASON_NO_LATERAL_SAMPLE, None, None)
    return Anchor(
        TIER_DRIVER_BEST_SESSION,
        reason,
        100.0 * abs(a_lat_mps2) / session_best_lat_mps2,
        session_best_lat_mps2 / _G,
    )


def decide_anchor(
    *,
    a_lat_mps2: float,
    a_long_mps2: float,
    speed_mps: float,
    friction: Any,
    envelope_bin: Any,
    trust_ratio: float | None,
    session_best_lat_mps2: float | None,
    bin_out_of_range: bool = False,
) -> Anchor:
    """Decide what this corner-lap's grip usage may honestly be quoted against.

    Fail-SAFE, strongest doubt first: an absent envelope, an out-of-range
    speed, a fabricated bin, an untrusted channel or an uncomputable fill each
    drop us to the session-relative tier; if even that is unavailable we
    refuse. Every degradation carries the reason that ACTUALLY caused it —
    see the reason taxonomy above for the three that used to name the wrong
    cause.

    ``bin_out_of_range`` lets the caller say "I looked for a bin near this
    speed and every candidate was too far away to trust" -- distinct from
    ``envelope_bin`` simply being unmeasured/fabricated. Checked before
    ``bin_is_measured`` so an out-of-range speed is never misreported as a
    data-quality problem with the bin itself.
    """
    if friction is None:
        return _session_best_anchor(a_lat_mps2, session_best_lat_mps2, REASON_NO_ENVELOPE)

    if bin_out_of_range:
        return _session_best_anchor(a_lat_mps2, session_best_lat_mps2, REASON_SPEED_OUT_OF_BINS)

    if envelope_bin is None:
        # There was no bin to inspect AT ALL -- typically because no
        # FrictionEnvelope exists (step 09i_grip_map degraded while
        # 09c_friction_model succeeded, a genuinely reachable split). Calling
        # that "bin_fabricated", as this used to, blames a data-quality
        # problem on an envelope that was never built.
        return _session_best_anchor(a_lat_mps2, session_best_lat_mps2, REASON_NO_ENVELOPE)

    if not bin_is_measured(envelope_bin):
        return _session_best_anchor(a_lat_mps2, session_best_lat_mps2, REASON_BIN_FABRICATED)

    if not channel_is_trusted(trust_ratio):
        return _session_best_anchor(a_lat_mps2, session_best_lat_mps2, REASON_CHANNEL_UNTRUSTED)

    pct = ellipse_fill_pct(a_lat_mps2, a_long_mps2, speed_mps, friction)
    if pct is None:
        return _session_best_anchor(
            a_lat_mps2,
            session_best_lat_mps2,
            _fill_failure_reason(a_lat_mps2, a_long_mps2, speed_mps, friction),
        )

    try:
        baseline_g = _scalar(friction.lateral_max(speed_mps)) / _G
    except Exception:
        baseline_g = None

    tier = (
        TIER_SESSION_ENVELOPE_ELLIPSE_FITTED
        if getattr(friction, "exponent_source", "hint") == "fitted"
        else TIER_SESSION_ENVELOPE_ELLIPSE_DEFAULT_P2
    )
    return Anchor(tier, None, pct, baseline_g)
