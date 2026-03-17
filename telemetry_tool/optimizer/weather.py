"""Weather scenario evaluation and pace adjustment helpers."""
from __future__ import annotations


def effective_lap_time(base_s: float, wet_confidence: float, condition: str) -> float:
    """Compute effective lap time adjusted for weather and driver confidence.

    A driver with high wet_confidence loses less time in wet/damp conditions.
    The factor represents the fraction of dry-pace the driver can maintain:
      - dry:  factor = 1.0 (no penalty)
      - damp: factor = 0.5 + 0.5 * wet_confidence  (range 0.5 .. 1.0)
      - wet:  factor = wet_confidence                (range 0.0 .. 1.0)

    Effective lap time = base_s / factor, so lower confidence => slower laps.
    """
    if condition == "dry" or wet_confidence <= 0:
        return base_s
    if condition == "damp":
        factor = 0.5 + 0.5 * wet_confidence
    else:  # wet
        factor = wet_confidence
    return base_s / max(0.01, factor)


def pit_cost_laps(pit_time_s: float, lap_time_s: float) -> float:
    """How many laps a pit stop costs at the given pace."""
    return pit_time_s / max(0.1, lap_time_s)
