"""Step 10d2: attach an honestly-labelled grip anchor to each corner-lap.

Runs immediately after 10d_per_lap_corners, the only point where the friction
model, the corner list, the resampled laps and the per-lap metrics all coexist.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

import grip_anchor as ga
from corner_analysis import _resolve_accel_lat

logger = logging.getLogger(__name__)

_ANCHOR_KEYS = (
    "grip_anchor_tier", "grip_anchor_reason",
    "grip_anchor_pct", "grip_anchor_baseline_g",
)


def _corner_mask(lap_df: pd.DataFrame, corner: dict) -> np.ndarray | None:
    """Distances are 0-based per-lap metres (canonical frame, see
    resampling.resample_lap_by_distance)."""
    col = next((c for c in ("Distance (m)", "distance_m") if c in lap_df.columns), None)
    if col is None:
        return None
    dist = pd.to_numeric(lap_df[col], errors="coerce").values
    mask = (dist >= float(corner.get("s_start", 0.0))) & (dist <= float(corner.get("s_end", 0.0)))
    return mask if mask.sum() >= 3 else None


def _apply(metric: dict, anchor: ga.Anchor) -> None:
    metric["grip_anchor_tier"] = anchor.tier
    metric["grip_anchor_reason"] = anchor.reason
    metric["grip_anchor_pct"] = anchor.pct
    metric["grip_anchor_baseline_g"] = anchor.baseline_g


def run_grip_anchor(
    per_lap_corner_metrics: list[dict[str, Any]],
    corners: list[dict[str, Any]],
    resampled_laps: dict[int, pd.DataFrame],
    *,
    friction_model: Any = None,
    friction_envelope: Any = None,
    curvature_profile: Any = None,
) -> list[dict[str, Any]]:
    """Attach grip_anchor_* to every metric dict. Returns the same list."""
    metrics = list(per_lap_corner_metrics or [])
    if not metrics:
        return metrics

    corners_by_id = {c.get("corner_id"): c for c in (corners or [])}

    # Peak lateral per (corner, lap), and the session best per corner. Both
    # come from this session only: corner_id is not stable across sessions.
    peak: dict[tuple[Any, Any], float] = {}
    for lap_num, lap_df in (resampled_laps or {}).items():
        if lap_df is None or len(lap_df) < 10:
            continue
        a_lat = _resolve_accel_lat(lap_df)          # already m/s², already abs
        for cid, corner in corners_by_id.items():
            mask = _corner_mask(lap_df, corner)
            if mask is None:
                continue
            vals = a_lat[mask]
            vals = vals[np.isfinite(vals)]
            if vals.size:
                peak[(cid, lap_num)] = float(np.nanmax(vals))

    session_best: dict[Any, float] = {}
    for (cid, _lap), v in peak.items():
        if v > session_best.get(cid, 0.0):
            session_best[cid] = v

    # One trust ratio per session, over cornering samples only.
    trust = _session_trust_ratio(resampled_laps, curvature_profile)

    for m in metrics:
        try:
            cid, lap_num = m.get("corner_id"), m.get("lap_number")
            anchor = ga.decide_anchor(
                a_lat_mps2=peak.get((cid, lap_num), float("nan")),
                a_long_mps2=0.0,
                speed_mps=float(m.get("apex_speed_mps") or 0.0),
                friction=friction_model,
                envelope_bin=_bin_for_speed(friction_envelope, m.get("apex_speed_mps")),
                trust_ratio=trust,
                session_best_lat_mps2=session_best.get(cid),
            )
        except Exception:
            logger.debug("grip anchor failed for corner=%s lap=%s", m.get("corner_id"), m.get("lap_number"))
            anchor = ga.Anchor(ga.TIER_REFUSED, ga.REASON_NO_MEASUREMENT, None, None)
        _apply(m, anchor)

    tiers = {}
    for m in metrics:
        tiers[m["grip_anchor_tier"]] = tiers.get(m["grip_anchor_tier"], 0) + 1
    logger.info("Grip anchor tiers across %d corner-laps: %s", len(metrics), tiers)
    return metrics


def _bin_for_speed(envelope: Any, speed: Any) -> Any:
    """Nearest friction bin to this corner's apex speed, or None."""
    bins = getattr(envelope, "friction_bins", None)
    if not bins or speed is None:
        return None
    try:
        v = float(speed)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(v):
        return None
    return min(bins, key=lambda b: abs(float(b.speed_center_mps) - v))


def _session_trust_ratio(
    resampled_laps: dict[int, pd.DataFrame] | None, curvature_profile: Any,
) -> float | None:
    """Median |a_lat| / (v^2*kappa) over cornering samples across all laps."""
    if not resampled_laps or curvature_profile is None:
        return None
    try:
        cp_d = pd.to_numeric(curvature_profile["distance_m"], errors="coerce").values
        cp_k = pd.to_numeric(curvature_profile["curvature_1pm"], errors="coerce").values
    except Exception:
        return None

    ratios = []
    for lap_df in resampled_laps.values():
        if lap_df is None or len(lap_df) < 50:
            continue
        col = next((c for c in ("Distance (m)", "distance_m") if c in lap_df.columns), None)
        spd = next((c for c in ("Speed (m/s)", "speed_mps") if c in lap_df.columns), None)
        if col is None or spd is None:
            continue
        d = pd.to_numeric(lap_df[col], errors="coerce").values
        v = pd.to_numeric(lap_df[spd], errors="coerce").values
        r = ga.channel_trust_ratio(_resolve_accel_lat(lap_df), v, np.interp(d, cp_d, cp_k))
        if r is not None:
            ratios.append(r)
    return float(np.median(ratios)) if ratios else None
