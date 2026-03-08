"""
traffic_detection.py
--------------------
Detect traffic-induced speed lifts on straights.

Uses curvature-based straight detection and cross-lap speed envelope
comparison to flag segments where the driver lifted due to slower
traffic ahead. Produces per-lap traffic_score and per-segment flags.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict, field
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# ── Column name constants ──────────────────────────────────────────
_COL_DIST = "Distance (m)"
_COL_SPEED = "Speed (m/s)"
_COL_BEARING = "Bearing (deg)"
_COL_ACCEL_LONG = "accel_long_mps2"
_COL_YAW = "yaw_rate_dps"

# ── Detection thresholds ──────────────────────────────────────────
_CURVATURE_STRAIGHT_THRESHOLD = 0.005  # 1/m — below this is "straight"
_MIN_STRAIGHT_LENGTH_M = 30.0          # metres — minimum straight segment
_SPEED_DEFICIT_FACTOR = 0.95           # flag when v < envelope * this
_MIN_DEFICIT_LENGTH_M = 10.0           # metres — minimum continuous deficit
_DECEL_THRESHOLD_MPS2 = -0.5           # m/s² — unexplained braking
_CORNER_PROXIMITY_M = 20.0             # metres — don't flag near corners
_ENVELOPE_PERCENTILE = 90.0            # cross-lap speed envelope percentile


@dataclass
class TrafficEvent:
    """A single traffic-induced speed lift on a straight."""
    lap_number: int
    s_start: float              # metres
    s_end: float                # metres
    speed_deficit_pct: float    # how much below envelope (%)
    max_decel_mps2: float       # worst a_long in event (m/s²)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TrafficResult:
    """Result of traffic detection across all laps."""
    straights: list[dict]           # detected straight segments
    events: list[TrafficEvent]      # all traffic events
    per_lap_score: dict[int, float] # lap_number → traffic_score [0-1]
    n_laps_affected: int

    def to_dict(self) -> dict:
        return {
            "straights": list(self.straights),
            "events": [e.to_dict() for e in self.events],
            "per_lap_score": dict(self.per_lap_score),
            "n_laps_affected": self.n_laps_affected,
        }


def _compute_curvature(df: "pd.DataFrame") -> np.ndarray:
    """Compute curvature from heading derivative w.r.t. distance.

    curvature = dheading/ds (rad/m).
    Uses Bearing (deg) and Distance (m) columns.
    """
    import pandas as pd

    bearing = pd.to_numeric(df[_COL_BEARING], errors="coerce").values.astype(float)
    dist = pd.to_numeric(df[_COL_DIST], errors="coerce").values.astype(float)

    # Convert bearing to radians, unwrap to remove 0/360 jumps
    hdg_rad = np.unwrap(np.radians(bearing))

    # dheading / ds
    ds = np.diff(dist)
    dh = np.diff(hdg_rad)
    ds = np.where(ds > 0, ds, np.nan)

    curvature = np.concatenate([[0.0], dh / ds])
    curvature = np.where(np.isfinite(curvature), curvature, 0.0)

    # Smooth with a small window to reduce noise
    if len(curvature) > 7:
        kernel = np.ones(7) / 7
        curvature = np.convolve(curvature, kernel, mode="same")

    return curvature


def detect_straights(
    df: "pd.DataFrame",
    *,
    curvature_threshold: float = _CURVATURE_STRAIGHT_THRESHOLD,
    min_length_m: float = _MIN_STRAIGHT_LENGTH_M,
) -> list[dict]:
    """Detect straight segments from curvature.

    Returns list of dicts with keys: s_start, s_end, length_m.
    """
    import pandas as pd

    if _COL_BEARING not in df.columns or _COL_DIST not in df.columns:
        logger.warning("detect_straights: missing Bearing or Distance column.")
        return []

    dist = pd.to_numeric(df[_COL_DIST], errors="coerce").values.astype(float)
    curvature = _compute_curvature(df)

    # Identify low-curvature regions
    is_straight = np.abs(curvature) < curvature_threshold

    # Find contiguous runs of True
    straights = []
    in_straight = False
    start_idx = 0

    for i in range(len(is_straight)):
        if is_straight[i] and not in_straight:
            start_idx = i
            in_straight = True
        elif not is_straight[i] and in_straight:
            s_start = float(dist[start_idx])
            s_end = float(dist[i - 1])
            length = s_end - s_start
            if length >= min_length_m:
                straights.append({
                    "s_start": round(s_start, 1),
                    "s_end": round(s_end, 1),
                    "length_m": round(length, 1),
                })
            in_straight = False

    # Handle straight that extends to end
    if in_straight:
        s_start = float(dist[start_idx])
        s_end = float(dist[-1])
        length = s_end - s_start
        if length >= min_length_m:
            straights.append({
                "s_start": round(s_start, 1),
                "s_end": round(s_end, 1),
                "length_m": round(length, 1),
            })

    logger.info("detect_straights: found %d straight segments.", len(straights))
    return straights


def _find_contiguous_runs(
    mask: np.ndarray, distances: np.ndarray, min_length: float,
) -> list[tuple[float, float]]:
    """Find contiguous True runs in mask that span >= min_length in distance."""
    runs = []
    in_run = False
    start_idx = 0

    for i in range(len(mask)):
        if mask[i] and not in_run:
            start_idx = i
            in_run = True
        elif not mask[i] and in_run:
            d_start = float(distances[start_idx])
            d_end = float(distances[i - 1])
            if d_end - d_start >= min_length:
                runs.append((d_start, d_end))
            in_run = False

    if in_run:
        d_start = float(distances[start_idx])
        d_end = float(distances[-1])
        if d_end - d_start >= min_length:
            runs.append((d_start, d_end))

    return runs


def _flag_straight_traffic(
    laps: dict[int, "pd.DataFrame"],
    straight: dict,
    corner_entries: list[float],
) -> list[TrafficEvent]:
    """Flag traffic events on a single straight segment across all laps.

    1. Extract speed for each lap on this straight
    2. Build p90 envelope across laps
    3. For each lap, check speed deficit + unexplained decel
    """
    import pandas as pd

    s_start = straight["s_start"]
    s_end = straight["s_end"]
    events = []

    # Build shared distance grid for this straight
    n_grid = max(20, int((s_end - s_start) / 2.0))
    grid = np.linspace(s_start, s_end, n_grid)

    # Interpolate each lap's speed onto grid
    speed_matrix = np.full((len(laps), n_grid), np.nan)
    accel_matrix = np.full((len(laps), n_grid), np.nan)
    lap_keys = sorted(laps.keys())

    for i, lap_num in enumerate(lap_keys):
        df = laps[lap_num]
        dist = pd.to_numeric(df[_COL_DIST], errors="coerce").values
        speed = pd.to_numeric(df[_COL_SPEED], errors="coerce").values
        mask = np.isfinite(dist) & np.isfinite(speed)
        if mask.sum() < 2:
            continue
        d_m, s_m = dist[mask], speed[mask]
        order = np.argsort(d_m)
        speed_matrix[i] = np.interp(grid, d_m[order], s_m[order])

        # Accel
        if _COL_ACCEL_LONG in df.columns:
            accel = pd.to_numeric(df[_COL_ACCEL_LONG], errors="coerce").values
            a_m = accel[mask]
            accel_matrix[i] = np.interp(grid, d_m[order], a_m[order])

    # Build p90 envelope
    envelope = np.nanpercentile(speed_matrix, _ENVELOPE_PERCENTILE, axis=0)
    if not np.any(np.isfinite(envelope)):
        return events

    # Check each lap against envelope
    threshold = envelope * _SPEED_DEFICIT_FACTOR

    for i, lap_num in enumerate(lap_keys):
        if not np.any(np.isfinite(speed_matrix[i])):
            continue

        # Find deficit zones: v_lap < threshold
        is_deficit = speed_matrix[i] < threshold
        if not np.any(is_deficit):
            continue

        # Find contiguous deficit runs >= MIN_DEFICIT_LENGTH_M
        deficit_runs = _find_contiguous_runs(is_deficit, grid, _MIN_DEFICIT_LENGTH_M)

        for run_start, run_end in deficit_runs:
            # Check for unexplained decel within this run
            run_mask = (grid >= run_start) & (grid <= run_end)

            # Skip if near a corner entry
            near_corner = any(
                abs(ce - run_start) < _CORNER_PROXIMITY_M or
                abs(ce - run_end) < _CORNER_PROXIMITY_M
                for ce in corner_entries
            )
            if near_corner:
                continue

            accel_in_run = accel_matrix[i, run_mask]
            if not np.any(np.isfinite(accel_in_run)):
                continue

            max_decel = float(np.nanmin(accel_in_run))
            if max_decel > _DECEL_THRESHOLD_MPS2:
                continue  # No unexplained braking

            # Compute speed deficit percentage
            env_in_run = envelope[run_mask]
            spd_in_run = speed_matrix[i, run_mask]
            finite = np.isfinite(env_in_run) & np.isfinite(spd_in_run) & (env_in_run > 0)
            if not np.any(finite):
                continue
            deficit_pct = float(np.nanmean(
                (env_in_run[finite] - spd_in_run[finite]) / env_in_run[finite] * 100
            ))

            events.append(TrafficEvent(
                lap_number=lap_num,
                s_start=round(run_start, 1),
                s_end=round(run_end, 1),
                speed_deficit_pct=round(deficit_pct, 1),
                max_decel_mps2=round(max_decel, 2),
            ))

    return events


def run_traffic_detection(
    resampled_laps: dict[int, "pd.DataFrame"],
    corner_list: "list[dict] | None" = None,
) -> TrafficResult:
    """Run traffic detection across all resampled laps.

    Parameters
    ----------
    resampled_laps : dict mapping lap_number → resampled DataFrame
    corner_list : optional list of corner dicts with s_start keys
                  (from corner_detection)

    Returns
    -------
    TrafficResult with per-lap scores and traffic events.
    """
    if not resampled_laps:
        return TrafficResult(straights=[], events=[], per_lap_score={}, n_laps_affected=0)

    # Use first lap for straight detection (all laps share same track)
    first_lap = resampled_laps[min(resampled_laps.keys())]
    straights = detect_straights(first_lap)

    if not straights:
        logger.info("run_traffic_detection: no straights found — skipping.")
        per_lap = {k: 0.0 for k in resampled_laps}
        return TrafficResult(
            straights=[], events=[], per_lap_score=per_lap, n_laps_affected=0,
        )

    # Corner entries for proximity check
    corner_entries: list[float] = []
    if corner_list:
        corner_entries = [c.get("s_start", 0.0) for c in corner_list]

    # Detect traffic on each straight
    all_events: list[TrafficEvent] = []
    for straight in straights:
        events = _flag_straight_traffic(resampled_laps, straight, corner_entries)
        all_events.extend(events)

    # Compute per-lap traffic_score
    total_straight_dist = sum(s["length_m"] for s in straights)
    per_lap_score: dict[int, float] = {}

    for lap_num in resampled_laps:
        lap_events = [e for e in all_events if e.lap_number == lap_num]
        if not lap_events or total_straight_dist <= 0:
            per_lap_score[lap_num] = 0.0
            continue
        flagged_dist = sum(e.s_end - e.s_start for e in lap_events)
        per_lap_score[lap_num] = round(
            min(1.0, flagged_dist / total_straight_dist), 3,
        )

    n_affected = sum(1 for s in per_lap_score.values() if s > 0)

    logger.info(
        "Traffic detection: %d straights, %d events, %d/%d laps affected.",
        len(straights), len(all_events), n_affected, len(resampled_laps),
    )

    return TrafficResult(
        straights=straights,
        events=all_events,
        per_lap_score=per_lap_score,
        n_laps_affected=n_affected,
    )
