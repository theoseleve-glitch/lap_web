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
