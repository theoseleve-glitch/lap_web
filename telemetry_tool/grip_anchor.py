"""Phase 1 grip anchor: an honestly-labelled "% of available grip used".

Every number this module emits carries a TIER naming what "available" was
measured against, and a machine-readable REASON when it had to degrade.
Pure and dependency-light — no I/O, no pipeline knowledge — so the decision
can be bite-checked without a database.

Fail-SAFE: any doubt degrades toward the lower tier. An unknown or absent
signal must never produce a physics tier.

Shape copied from ``track_surface/honesty.py``; values are our own.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np

# -- Tier vocabulary — the ONLY legal values of corner_metrics.grip_anchor_tier.
# Two physics tiers, not one: the ellipse exponent is FITTED from boundary
# samples but silently falls back to a hint when they are thin, and a claim of
# "fitted ellipse" over a defaulted p=2 would be a false provenance claim.
TIER_PHYSICS_ELLIPSE_FITTED: Final = "physics_ellipse_fitted"
TIER_PHYSICS_ELLIPSE_DEFAULT_P2: Final = "physics_ellipse_default_p2"
# Session-scoped only. Cross-session ("driver_best_track") is NOT available:
# corner_id is a positional index over curvature regions found in one lap of
# one session, and corner_persistence has zero production callers. Phase 2
# adds a new tier value rather than redefining this one.
TIER_DRIVER_BEST_SESSION: Final = "driver_best_session"
TIER_REFUSED: Final = "refused"

TIERS: Final = frozenset({
    TIER_PHYSICS_ELLIPSE_FITTED,
    TIER_PHYSICS_ELLIPSE_DEFAULT_P2,
    TIER_DRIVER_BEST_SESSION,
    TIER_REFUSED,
})

_PHYSICS_TIERS: Final = frozenset({
    TIER_PHYSICS_ELLIPSE_FITTED,
    TIER_PHYSICS_ELLIPSE_DEFAULT_P2,
})

# -- Reason taxonomy (machine-readable).
REASON_NO_ENVELOPE: Final = "no_envelope"
REASON_BIN_FABRICATED: Final = "bin_fabricated"
REASON_SPEED_OUT_OF_BINS: Final = "speed_out_of_bins"
REASON_CHANNEL_UNTRUSTED: Final = "channel_untrusted"
REASON_NO_LAP_BASELINE: Final = "no_lap_baseline"
REASON_NO_MEASUREMENT: Final = "no_measurement"
# Reserved for Phase 2 — see the tier comments above.
REASON_CONDITION_UNKNOWN: Final = "condition_unknown"
REASON_CORNER_IDENTITY_UNSTABLE: Final = "corner_identity_unstable"


def is_quotable_as_physics(tier: str | None) -> bool:
    """The consumer guard. ONLY a physics tier may be presented to a driver as
    an absolute claim about the car's limit. Everything else — including an
    unknown tier — is relative or nothing."""
    return tier in _PHYSICS_TIERS


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
# Real kart data measures 0.961; the production frontend uses [0.80, 1.20]
# after filtering zeros (TrackSurfacePanel.tsx:513).
TRUST_BAND_LOW: Final = 0.80
TRUST_BAND_HIGH: Final = 1.25


def channel_is_trusted(ratio: float | None) -> bool:
    """Fail-safe: None (not measurable) is NOT trusted."""
    return ratio is not None and TRUST_BAND_LOW <= ratio <= TRUST_BAND_HIGH
