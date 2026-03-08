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


@dataclass
class DistanceQuality:
    """Overall distance quality assessment across all laps."""
    status: str                          # "ok" | "repaired" | "degraded"
    repair_method: Optional[str] = None  # "xy_rebuild" | "isotonic_regression" | None
    laps_repaired: list[int] = field(default_factory=list)
    laps_degraded: list[int] = field(default_factory=list)
    metrics: list[dict] = field(default_factory=list)
    gate_advanced: bool = False
    message: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def assess_all_laps(
    lap_dict: dict[int, "pd.DataFrame"],
    *,
    dist_col: str = "Distance (m)",
) -> DistanceQuality:
    """Compute per-lap distance metrics and identify laps needing repair.

    Does NOT repair — only assesses.  Returns a DistanceQuality with
    status="ok" if all laps pass, or lists of laps needing attention.
    """
    import pandas as pd

    all_metrics: list[LapDistanceMetrics] = []
    needs_repair: list[int] = []

    for lap_num in sorted(lap_dict.keys()):
        df = lap_dict[lap_num]
        if dist_col not in df.columns:
            continue
        d = pd.to_numeric(df[dist_col], errors="coerce").values.astype(np.float64)
        m = compute_lap_metrics(d, lap_number=lap_num)
        all_metrics.append(m)

        if m.monotonic_ratio < MONO_RATIO_REPAIR or m.jump_count > JUMP_COUNT_REPAIR:
            needs_repair.append(lap_num)

    # Compute z-scores for lap_length
    if len(all_metrics) >= 3:
        lengths = np.array([m.lap_length for m in all_metrics])
        med = float(np.median(lengths))
        mad = float(np.median(np.abs(lengths - med)))
        # Use MAD-based z-score (robust to outliers)
        sigma = mad * 1.4826 if mad > 0 else 1.0  # MAD → σ estimator
        for m in all_metrics:
            m.lap_length_zscore = abs(m.lap_length - med) / sigma

    metrics_dicts = [m.to_dict() for m in all_metrics]

    if not needs_repair:
        return DistanceQuality(
            status="ok",
            metrics=metrics_dicts,
            message="Distance data is clean across all laps.",
        )

    return DistanceQuality(
        status="ok",  # Will be updated by repair step
        laps_repaired=needs_repair,  # Candidates for repair
        metrics=metrics_dicts,
        message=f"Laps needing repair: {needs_repair}",
    )
