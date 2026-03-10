"""Corner exit importance scoring.

Scores how important a corner's exit speed is based on the length of the
straight that follows.  Longer straight → more time gained/lost from exit
speed differences → higher importance (0.0 to 1.0).

Uses a saturating curve: importance = 1 - exp(-straight_length / scale).
Scale of 200m means a 200m straight gives ~63% importance, 400m gives ~86%.
"""
from __future__ import annotations

_SCALE_M = 200.0  # characteristic length — tune based on typical circuits


def score_exit_importance(straight_length_m: float) -> float:
    """Return exit importance score 0.0–1.0 for a given following straight length."""
    import math
    if straight_length_m <= 0:
        return 0.0
    return min(1.0, 1.0 - math.exp(-straight_length_m / _SCALE_M))
