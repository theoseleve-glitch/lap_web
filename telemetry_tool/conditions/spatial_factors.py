"""Day-12 — per-segment spatial μ modifier factors.

Spec ``LAP_V1_CONDITIONS_ENGINE_SPEC.md`` §7. Three independent factors
multiplied per segment to produce a wetness multiplier; final spatial
factor inverts the product (factors > 1 = wetter section → lower
effective μ → divide).

Pure functions. No I/O. Each factor returns a numpy array of the same
shape as its primary input.
"""
from __future__ import annotations

import numpy as np


# ── Factor 1: Drainage ────────────────────────────────────────────────


# Spec §7 Factor 1 lookup (treats slope as absolute; signed climb/descent
# drain identically). Boundary inclusion: higher-slope bucket wins.
_DRAINAGE_BOUNDARIES_PCT = (0.5, 2.0, 5.0)
_DRAINAGE_FACTORS = (1.30, 1.10, 1.00, 0.85)


def drainage_factor(slope_pct: np.ndarray) -> np.ndarray:
    """Spec §7 Factor 1 — drainage from local longitudinal slope.

    Args:
        slope_pct: per-segment slope in percent (`dz/ds × 100`).
            Sign-agnostic: |slope| used; descent drains same as climb.

    Returns:
        Per-segment factor in ``{0.85, 1.00, 1.10, 1.30}``.

    Spec table (treating slope as absolute):
        |slope| < 0.5%   → 1.30 (flat: water pools)
        0.5% ≤ |s| < 2%  → 1.10 (mild: slow drainage)
        2%   ≤ |s| < 5%  → 1.00 (good: neutral)
        |slope| ≥ 5%     → 0.85 (steep: drains fast, dries first)

    Boundary convention: at boundary values (0.5%, 2.0%, 5.0%) the
    higher-slope bucket applies (lower factor — more drainage).
    Grounding: AASHTO Drainage Manual identifies < 0.5% grade as the
    threshold for ponding risk on asphalt.
    """
    abs_slope = np.abs(np.asarray(slope_pct, dtype=np.float64))
    # Bucket index 0..3 via right-edge inclusive boundaries.
    # np.digitize with right=False returns indices of buckets such that
    # bins[i-1] <= x < bins[i]. For boundary inclusion at top, use
    # right=True: bins[i-1] < x <= bins[i]. We want at 0.5% to map to
    # bucket 1 (mild), so we want strictly-less-than for upper edges:
    # use right=False, which gives < behavior, then take the result
    # directly as bucket index.
    bucket = np.digitize(abs_slope, _DRAINAGE_BOUNDARIES_PCT, right=False)
    # Validate: bucket ∈ [0, 3]
    factors = np.array(_DRAINAGE_FACTORS, dtype=np.float64)
    return factors[bucket]
