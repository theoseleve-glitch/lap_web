"""
lap_inclusion.py
----------------
Lap inclusion policy: learning set vs display set.

Splits laps into two sets:
- learning_laps: clean laps used for envelope, mu(s), calibration
- display_laps: all laps shown in report/replay

Each excluded lap carries queryable exclusion reasons.
Traffic-affected laps may be partially included via segment masks.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, asdict, field

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class LapExclusion:
    """Why a lap was excluded from the learning set."""
    lap_number: int
    reasons: list[str]       # e.g. ["outlap", "traffic"]
    detail: dict             # reason-specific metadata

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class LapInclusionPolicy:
    """Lap inclusion policy for learning vs display."""
    learning_laps: list[int]
    display_laps: list[int]
    exclusions: list[LapExclusion]
    traffic_masks: dict[int, list[tuple[float, float]]]

    def to_dict(self) -> dict:
        return {
            "learning_laps": list(self.learning_laps),
            "display_laps": list(self.display_laps),
            "exclusions": [e.to_dict() for e in self.exclusions],
            "traffic_masks": {
                str(k): [list(r) for r in v]
                for k, v in self.traffic_masks.items()
            },
        }

    def label(self, lap_number: int) -> str:
        """Return display label for a lap.

        Returns one of: "clean", "outlap", "inlap", "traffic", "degraded",
        "abnormal_length", "low_coverage", "excluded".
        """
        if lap_number in self.learning_laps:
            return "clean"
        for exc in self.exclusions:
            if exc.lap_number == lap_number:
                return exc.reasons[0] if exc.reasons else "excluded"
        return "excluded"


_OUTLAP_TIME_RATIO = 2.0          # > 2x median -> outlap/inlap
_TRAFFIC_FULL_EXCLUDE = 0.5       # traffic_score above this -> fully excluded
_NAN_COVERAGE_THRESHOLD = 0.20    # > 20% NaN in speed/accel -> excluded
_LAP_LENGTH_ZSCORE = 3.0          # z-score for abnormal lap length


def build_inclusion_policy(
    resampled_laps: dict[int, "pd.DataFrame"],
    lap_times: list[float],
    traffic_result: "TrafficResult",
    *,
    distance_quality: "dict | None" = None,
) -> "LapInclusionPolicy":
    """Build lap inclusion policy from traffic detection and quality data.

    Parameters
    ----------
    resampled_laps : lap_number -> resampled DataFrame
    lap_times : list of lap times in seconds (aligned with sorted lap keys)
    traffic_result : output from run_traffic_detection()
    distance_quality : optional distance quality dict from summary

    Returns
    -------
    LapInclusionPolicy with learning/display sets and traffic masks.
    """
    sorted_keys = sorted(resampled_laps.keys())
    exclusions: list[LapExclusion] = []
    excluded_set: set[int] = set()
    traffic_masks: dict[int, list[tuple[float, float]]] = {}

    # Align lap_times with sorted keys
    key_to_time = {}
    for i, k in enumerate(sorted_keys):
        if i < len(lap_times) and math.isfinite(lap_times[i]):
            key_to_time[k] = lap_times[i]

    finite_times = [t for t in key_to_time.values() if math.isfinite(t)]
    median_time = float(np.median(finite_times)) if finite_times else 0.0

    # -- Rule 1: Outlap / Inlap --
    if median_time > 0:
        for k in sorted_keys:
            t = key_to_time.get(k)
            if t is not None and t > median_time * _OUTLAP_TIME_RATIO:
                if k == sorted_keys[0]:
                    reason = "outlap"
                elif k == sorted_keys[-1]:
                    reason = "inlap"
                else:
                    reason = "outlap"
                exclusions.append(LapExclusion(k, [reason], {
                    "lap_time": round(t, 2),
                    "median_time": round(median_time, 2),
                    "ratio": round(t / median_time, 2),
                }))
                excluded_set.add(k)

    # -- Rule 2: Traffic --
    for k in sorted_keys:
        if k in excluded_set:
            continue
        score = traffic_result.per_lap_score.get(k, 0.0)
        if score > _TRAFFIC_FULL_EXCLUDE:
            exclusions.append(LapExclusion(k, ["traffic"], {
                "traffic_score": round(score, 3),
            }))
            excluded_set.add(k)
        elif score > 0:
            lap_events = [e for e in traffic_result.events if e.lap_number == k]
            if lap_events:
                traffic_masks[k] = [(e.s_start, e.s_end) for e in lap_events]

    # -- Rule 3: Distance quality --
    if distance_quality and isinstance(distance_quality, dict):
        degraded = distance_quality.get("laps_degraded", [])
        metrics = distance_quality.get("metrics", [])
        for lap_num in degraded:
            if lap_num not in excluded_set:
                exclusions.append(LapExclusion(lap_num, ["degraded"], {}))
                excluded_set.add(lap_num)
        for m in metrics:
            ln = m.get("lap_number")
            zscore = m.get("lap_length_zscore", 0.0)
            if ln and abs(zscore) > _LAP_LENGTH_ZSCORE and ln not in excluded_set:
                exclusions.append(LapExclusion(ln, ["abnormal_length"], {
                    "lap_length_zscore": round(zscore, 2),
                }))
                excluded_set.add(ln)

    # -- Rule 4: Low channel coverage --
    for k in sorted_keys:
        if k in excluded_set:
            continue
        df = resampled_laps[k]
        if df is None or len(df) == 0:
            exclusions.append(LapExclusion(k, ["low_coverage"], {"reason": "empty"}))
            excluded_set.add(k)
            continue

        speed_nan_frac = 0.0
        if "Speed (m/s)" in df.columns:
            speed_nan_frac = float(df["Speed (m/s)"].isna().mean())

        accel_nan_frac = 0.0
        if "accel_long_mps2" in df.columns:
            accel_nan_frac = float(df["accel_long_mps2"].isna().mean())

        max_nan = max(speed_nan_frac, accel_nan_frac)
        if max_nan > _NAN_COVERAGE_THRESHOLD:
            exclusions.append(LapExclusion(k, ["low_coverage"], {
                "speed_nan_pct": round(speed_nan_frac * 100, 1),
                "accel_nan_pct": round(accel_nan_frac * 100, 1),
            }))
            excluded_set.add(k)

    # Build sets
    learning_laps = [k for k in sorted_keys if k not in excluded_set]
    display_laps = list(sorted_keys)

    logger.info(
        "Lap inclusion: %d learning, %d display, %d excluded, %d masked.",
        len(learning_laps), len(display_laps),
        len(exclusions), len(traffic_masks),
    )

    return LapInclusionPolicy(
        learning_laps=learning_laps,
        display_laps=display_laps,
        exclusions=exclusions,
        traffic_masks=traffic_masks,
    )
