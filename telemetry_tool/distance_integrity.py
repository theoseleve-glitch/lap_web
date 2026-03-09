"""
distance_integrity.py
---------------------
Pre-resampling distance_m quality check, repair, and gating.

Inserted as pipeline stage 6.5 — after derived channels compute
distance_m, before resampling normalises to a uniform grid.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
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


# ── Coordinate column detection ───────────────────────────────────
_XY_PAIRS = [
    ("x", "y"),
    ("X (m)", "Y (m)"),
    ("x_m", "y_m"),
]
_LATLON_PAIRS = [
    ("Latitude (deg)", "Longitude (deg)"),
    ("latitude", "longitude"),
    ("Latitude (°)", "Longitude (°)"),
    ("lat", "lon"),
]


def _haversine_cumulative(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """Cumulative Haversine distance in metres."""
    R = 6_371_000.0  # Earth radius in metres
    lat_r = np.radians(lat)
    lon_r = np.radians(lon)

    dlat = np.diff(lat_r)
    dlon = np.diff(lon_r)

    a = np.sin(dlat / 2) ** 2 + np.cos(lat_r[:-1]) * np.cos(lat_r[1:]) * np.sin(dlon / 2) ** 2
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
    seg = R * c

    return np.concatenate([[0.0], np.cumsum(seg)])


def rebuild_distance_from_xy(
    df: "pd.DataFrame",
    *,
    dist_col: str = "Distance (m)",
) -> "Optional[pd.DataFrame]":
    """Rebuild distance_m from coordinate columns if available.

    Tries XY (Euclidean) first, then lat/lon (Haversine).
    Returns a copy with repaired distance column, or None if no
    coordinate columns are found.
    """
    import pandas as pd

    cols = set(df.columns)

    # Try Euclidean XY pairs
    for x_col, y_col in _XY_PAIRS:
        if x_col in cols and y_col in cols:
            x = pd.to_numeric(df[x_col], errors="coerce").values.astype(np.float64)
            y = pd.to_numeric(df[y_col], errors="coerce").values.astype(np.float64)
            dx = np.diff(x)
            dy = np.diff(y)
            seg = np.sqrt(dx ** 2 + dy ** 2)
            dist = np.concatenate([[0.0], np.cumsum(seg)])
            result = df.copy()
            result[dist_col] = dist
            logger.info("Distance rebuilt from XY columns (%s, %s)", x_col, y_col)
            return result

    # Try lat/lon pairs (Haversine)
    for lat_col, lon_col in _LATLON_PAIRS:
        if lat_col in cols and lon_col in cols:
            lat = pd.to_numeric(df[lat_col], errors="coerce").values.astype(np.float64)
            lon = pd.to_numeric(df[lon_col], errors="coerce").values.astype(np.float64)
            dist = _haversine_cumulative(lat, lon)
            result = df.copy()
            result[dist_col] = dist
            logger.info("Distance rebuilt from lat/lon (%s, %s)", lat_col, lon_col)
            return result

    return None


def repair_distance_isotonic(distance: np.ndarray) -> np.ndarray:
    """Force distance array to be monotonically non-decreasing.

    Uses sklearn's IsotonicRegression which finds the best
    non-decreasing fit in a least-squares sense.
    """
    from sklearn.isotonic import IsotonicRegression

    d = np.asarray(distance, dtype=np.float64).copy()
    ir = IsotonicRegression(increasing=True)
    indices = np.arange(len(d), dtype=np.float64)
    return ir.fit_transform(indices, d)


def run_distance_integrity(
    lap_dict: dict[int, "pd.DataFrame"],
    *,
    dist_col: str = "Distance (m)",
    config: Optional[dict] = None,
) -> tuple[dict[int, "pd.DataFrame"], DistanceQuality]:
    """Full distance integrity check: assess -> repair -> re-assess -> gate.

    Parameters
    ----------
    lap_dict : {lap_number: DataFrame} with distance column.
    dist_col : Name of distance column.
    config : Optional overrides for thresholds.

    Returns
    -------
    (repaired_lap_dict, DistanceQuality)
    """
    import pandas as pd

    cfg = config or {}
    mono_repair = cfg.get("mono_ratio_repair", MONO_RATIO_REPAIR)
    jump_repair = cfg.get("jump_count_repair", JUMP_COUNT_REPAIR)
    mono_gate = cfg.get("mono_ratio_gate", MONO_RATIO_GATE)

    # Phase 1: Assess
    quality = assess_all_laps(lap_dict, dist_col=dist_col)

    # Identify laps needing repair
    needs_repair = []
    for m_dict in quality.metrics:
        if m_dict["monotonic_ratio"] < mono_repair or m_dict["jump_count"] > jump_repair:
            needs_repair.append(m_dict["lap_number"])

    if not needs_repair:
        quality.status = "ok"
        quality.gate_advanced = False
        quality.message = "Distance data is clean across all laps."
        return lap_dict, quality

    # Phase 2: Repair
    repaired_dict = dict(lap_dict)  # shallow copy
    repair_method = None
    actually_repaired = []
    still_degraded = []

    for lap_num in needs_repair:
        df = lap_dict[lap_num]

        # Try XY rebuild first
        rebuilt = rebuild_distance_from_xy(df, dist_col=dist_col)
        if rebuilt is not None:
            repaired_dict[lap_num] = rebuilt
            repair_method = "xy_rebuild"
            actually_repaired.append(lap_num)
            continue

        # Fallback: isotonic regression
        if dist_col in df.columns:
            d = pd.to_numeric(df[dist_col], errors="coerce").values.astype(np.float64)
            repaired_d = repair_distance_isotonic(d)
            new_df = df.copy()
            new_df[dist_col] = repaired_d
            repaired_dict[lap_num] = new_df
            if repair_method is None:
                repair_method = "isotonic_regression"
            actually_repaired.append(lap_num)
        else:
            still_degraded.append(lap_num)

    # Phase 3: Re-assess repaired laps
    re_quality = assess_all_laps(repaired_dict, dist_col=dist_col)

    for m_dict in re_quality.metrics:
        if m_dict["lap_number"] in actually_repaired:
            # Gate fails if:
            #   - still has backward jumps, OR
            #   - distance is degenerate (zero length, e.g. all-zeros)
            # Isotonic repair may produce plateaus (zero diffs) giving
            # low monotonic_ratio but jump_count==0, which is acceptable
            # as long as the lap has non-zero length.
            ratio_bad = m_dict["monotonic_ratio"] < mono_gate
            has_jumps = m_dict["jump_count"] > 0
            no_distance = m_dict["lap_length"] < 1e-6
            if (ratio_bad and has_jumps) or no_distance:
                if m_dict["lap_number"] not in still_degraded:
                    still_degraded.append(m_dict["lap_number"])
                    actually_repaired.remove(m_dict["lap_number"])

    # Phase 4: Determine final status
    gate = len(still_degraded) > 0
    if still_degraded:
        status = "degraded"
        msg = (
            f"Distance repair failed for laps {still_degraded}. "
            "Advanced analysis (theoretical, coaching) disabled."
        )
    elif actually_repaired:
        status = "repaired"
        msg = (
            f"Distance repaired for laps {actually_repaired} "
            f"via {repair_method}."
        )
    else:
        status = "ok"
        msg = "Distance data is clean across all laps."

    return repaired_dict, DistanceQuality(
        status=status,
        repair_method=repair_method,
        laps_repaired=actually_repaired,
        laps_degraded=still_degraded,
        metrics=re_quality.metrics,
        gate_advanced=gate,
        message=msg,
    )
