"""
distance_integrity.py
---------------------
Pre-resampling distance_m quality check, repair, and gating.

Inserted as pipeline stage 6.5 — after derived channels compute
distance_m, before resampling normalises to a uniform grid.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# ── Thresholds (configurable via pipeline config) ─────────────────
MONO_RATIO_REPAIR = 0.95      # below this → attempt repair
JUMP_COUNT_REPAIR = 5         # above this → attempt repair
MONO_RATIO_GATE = 0.99        # below this after repair → gate advanced
LAP_LENGTH_ZSCORE_OUTLIER = 3.0  # flag outlier laps


@dataclass
class LapDistanceMetrics:
    """Per-lap distance quality metrics."""
    lap_number: int
    monotonic_ratio: float
    jump_count: int
    compression_ratio: float
    lap_length: float
    lap_length_zscore: float = 0.0  # set later when all laps known

    def to_dict(self) -> dict:
        return asdict(self)


def compute_lap_metrics(distance: np.ndarray, *, lap_number: int) -> LapDistanceMetrics:
    """Compute distance quality metrics for a single lap.

    Parameters
    ----------
    distance : 1-D array of distance_m values for one lap.
    lap_number : Lap identifier.
    """
    d = np.asarray(distance, dtype=np.float64)
    n = len(d)

    if n < 2:
        return LapDistanceMetrics(
            lap_number=lap_number,
            monotonic_ratio=0.0,
            jump_count=0,
            compression_ratio=0.0,
            lap_length=0.0,
        )

    diffs = np.diff(d)
    n_diffs = len(diffs)

    # monotonic_ratio: fraction of strictly increasing steps
    mono_count = int(np.sum(diffs > 0))
    monotonic_ratio = mono_count / n_diffs if n_diffs > 0 else 0.0

    # jump_count: number of backward jumps (d[i+1] < d[i])
    jump_count = int(np.sum(diffs < 0))

    # compression_ratio: std(diff) / mean(diff) — coefficient of variation
    pos_diffs = diffs[diffs > 0]
    if len(pos_diffs) > 1:
        compression_ratio = float(np.std(pos_diffs) / np.mean(pos_diffs))
    else:
        compression_ratio = 0.0

    # lap_length: total span
    finite = d[np.isfinite(d)]
    lap_length = float(finite.max() - finite.min()) if len(finite) >= 2 else 0.0

    return LapDistanceMetrics(
        lap_number=lap_number,
        monotonic_ratio=monotonic_ratio,
        jump_count=jump_count,
        compression_ratio=compression_ratio,
        lap_length=lap_length,
    )
