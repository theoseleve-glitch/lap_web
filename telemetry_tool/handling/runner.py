"""Top-level entry point for handling balance detection.

Called from the pipeline (s10b_corners) to run the full detection chain:
  1. Build CornerWindows from session data
  2. Calibrate session (D1-D6)
  3. Run all 16 detectors via registry
  4. Fuse votes via Bayesian fusion (C1/C3/C5/C6)
  5. Optionally calibrate weights (C4) and re-run
  6. Return FusedEvents serialized as dicts

This module is the ONLY import the pipeline needs.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from scipy.signal import butter, filtfilt

from telemetry_tool.handling.types import CornerWindow, FusedEvent, SessionContext
from telemetry_tool.handling.calibration import (
    build_corner_window, calibrate_session,
)
from telemetry_tool.handling.detectors.base import DetectorRegistry
from telemetry_tool.handling.detectors.apex_timing import ApexTimingDetector
from telemetry_tool.handling.detectors.corner_balance import CornerBalanceDetector
from telemetry_tool.handling.detectors.speed_recovery import SpeedRecoveryDetector
from telemetry_tool.handling.detectors.lat_g_jerk import LatGJerkDetector
from telemetry_tool.handling.detectors.trail_braking import TrailBrakingDetector
from telemetry_tool.handling.detectors.gg_shape import GGShapeDetector
from telemetry_tool.handling.detectors.path_divergence import PathDivergenceDetector
from telemetry_tool.handling.detectors.yaw_residual import YawResidualDetector
from telemetry_tool.handling.detectors.heading_accel import HeadingAccelDetector
from telemetry_tool.handling.detectors.friction_asymmetry import FrictionAsymmetryDetector
from telemetry_tool.handling.detectors.speed_scrub import SpeedScrubDetector
from telemetry_tool.handling.detectors.throttle_response import ThrottleResponseDetector
from telemetry_tool.handling.detectors.steering_corrections import SteeringCorrectionsDetector
from telemetry_tool.handling.detectors.lat_g_plateau import LatGPlateauDetector
from telemetry_tool.handling.detectors.braking_distance import BrakingDistanceDetector
from telemetry_tool.handling.detectors.line_variation import LineVariationDetector
from telemetry_tool.handling.detectors.pipeline_ensemble import PipelineEnsembleDetector
from telemetry_tool.handling.fusion import BayesianFusion
from telemetry_tool.handling.weight_calibrator import calibrate_weights

logger = logging.getLogger(__name__)

_ALL_DETECTOR_CLASSES = [
    ApexTimingDetector, CornerBalanceDetector, SpeedRecoveryDetector,
    LatGJerkDetector, TrailBrakingDetector, GGShapeDetector,
    PathDivergenceDetector, YawResidualDetector, HeadingAccelDetector,
    FrictionAsymmetryDetector, SpeedScrubDetector, ThrottleResponseDetector,
    SteeringCorrectionsDetector, LatGPlateauDetector, BrakingDistanceDetector,
    PipelineEnsembleDetector,
    LineVariationDetector,
]

LPF_HZ = 1.5
LPF_ORDER = 2
CORNER_MIN_S = 0.8
CORNER_GAP_S = 0.3


def _build_filter(fs: float):
    nyq = fs / 2.0
    return butter(LPF_ORDER, min(LPF_HZ / nyq, 0.99), btype="low")


def _filt(signal: np.ndarray, b, a) -> np.ndarray:
    s = pd.Series(signal).interpolate(limit_direction="both").values
    return filtfilt(b, a, s)


def run_handling_analysis(
    time_s: np.ndarray,
    dist_m: np.ndarray,
    speed_mps: np.ndarray,
    a_lat_g: np.ndarray,
    a_lon_g: np.ndarray,
    bearing_deg: np.ndarray,
    lat_deg: np.ndarray,
    lon_deg: np.ndarray,
    lap_col: np.ndarray,
    best_lap: int,
    *,
    wheelbase_m: float = 1.0,
    vehicle_class: str = "kart",
    use_dynamic_weights: bool = True,
) -> dict:
    """Run the full handling balance analysis on a session.

    Returns a dict with:
      - "events": list of FusedEvent.to_dict() for the best lap
      - "corners": list of corner summaries
      - "calibration": session calibration values
      - "detector_weights": per-detector weights used
      - "summary": overall handling tendency
    """
    # Compute derived channels
    dt_med = np.nanmedian(np.diff(time_s))
    fs = 1.0 / dt_med if dt_med > 0 else 25.0
    b, a = _build_filter(fs)

    speed_f = _filt(speed_mps, b, a)
    a_lat_f = _filt(a_lat_g, b, a)
    a_lon_f = _filt(a_lon_g, b, a)

    db = np.diff(bearing_deg, prepend=bearing_deg[0])
    db = (db + 180) % 360 - 180
    dt_arr = np.diff(time_s, prepend=time_s[0])
    dt_arr[dt_arr <= 0] = 1e-6
    yaw_dps = _filt(db / dt_arr, b, a)

    cos_lat = np.cos(np.radians(np.nanmean(lat_deg)))
    dx = np.gradient(_filt(lon_deg, b, a) * 111320 * cos_lat)
    dy = np.gradient(_filt(lat_deg, b, a) * 110540)
    ddx = np.gradient(dx)
    ddy = np.gradient(dy)
    denom = (dx ** 2 + dy ** 2) ** 1.5 + 1e-12
    curvature = np.abs(dx * ddy - dy * ddx) / denom

    # Detect corners in best lap
    lap_mask = lap_col == best_lap
    idx = np.where(lap_mask)[0]
    if len(idx) < 50:
        logger.warning("Best lap %d has only %d samples, skipping handling", best_lap, len(idx))
        return {"events": [], "corners": [], "calibration": {}, "summary": {}}

    corners = _detect_corners(
        idx, a_lat_f, time_s, dist_m, speed_f, a_lon_f,
        bearing_deg, lat_deg, lon_deg, yaw_dps, curvature, fs
    )

    if not corners:
        return {"events": [], "corners": [], "calibration": {}, "summary": {}}

    # Calibrate session
    ctx = calibrate_session(
        time_s, speed_f, a_lat_f, a_lon_f, bearing_deg, yaw_dps, curvature,
        corners, wheelbase_m=wheelbase_m, vehicle_class=vehicle_class,
    )

    # Build registry
    registry = DetectorRegistry()
    for cls in _ALL_DETECTOR_CLASSES:
        registry.register(cls())

    # Dynamic weight calibration (C4)
    if use_dynamic_weights and len(corners) >= 5:
        weights = calibrate_weights(registry, corners, ctx)
    else:
        weights = {d.name: d.default_weight for d in registry.detectors}

    # Run detectors + fusion
    fusion = BayesianFusion()
    all_events: list[FusedEvent] = []
    corner_summaries = []

    for cw in corners:
        votes = registry.run_all(cw, ctx)
        events = fusion.fuse_corner(cw, votes, detector_weights=weights)
        all_events.extend(events)

        corner_summaries.append({
            "corner_id": cw.corner_id,
            "start_m": round(float(cw.dist_m[0]), 1),
            "end_m": round(float(cw.dist_m[-1]), 1),
            "peak_g": round(cw.peak_g, 3),
            "direction": cw.direction,
            "n_votes": len([v for v in votes if not v.is_confidence_modifier]),
            "n_events": len(events),
            "events": [e.to_dict() for e in events],
        })

    # Display tiers — only count high-confidence events for the summary
    # >85% = confirmed, 60-85% = likely, 40-60% = possible, <40% = hidden from summary
    CONFIRMED_THR = 0.85
    LIKELY_THR = 0.60
    POSSIBLE_THR = 0.40

    confirmed = [e for e in all_events if e.confidence >= CONFIRMED_THR]
    likely = [e for e in all_events if LIKELY_THR <= e.confidence < CONFIRMED_THR]
    possible = [e for e in all_events if POSSIBLE_THR <= e.confidence < LIKELY_THR]
    weak = [e for e in all_events if e.confidence < POSSIBLE_THR]

    # For overall tendency, weight by confidence (only count meaningful events)
    meaningful = [e for e in all_events if e.confidence >= POSSIBLE_THR]
    us = [e for e in meaningful if e.direction > 0.15]
    os_ = [e for e in meaningful if e.direction < -0.15]
    overall = float(np.mean([e.direction * e.confidence for e in meaningful])) if meaningful else 0.0

    summary = {
        "n_corners": len(corners),
        "n_events_total": len(all_events),
        "n_events": len(confirmed) + len(likely),  # shown in summary
        "n_confirmed": len(confirmed),
        "n_likely": len(likely),
        "n_possible": len(possible),
        "n_weak": len(weak),
        "n_understeer": len(us),
        "n_oversteer": len(os_),
        "n_conflicts": sum(1 for e in meaningful if e.conflict),
        "avg_confidence": round(float(np.mean([e.confidence for e in meaningful])), 3) if meaningful else 0,
        "max_confidence": round(float(max(e.confidence for e in all_events)), 3) if all_events else 0,
        "overall_direction": round(overall, 3),
        "tendency": "understeer" if overall > 0.1 else ("oversteer" if overall < -0.1 else "balanced"),
    }

    # Top-3 focus corners: only from meaningful events (>40% confidence)
    focus_corners = _rank_focus_corners(corner_summaries, meaningful if meaningful else all_events)

    # Best lap mistakes: events sorted by impact (confidence × severity)
    best_lap_mistakes = _extract_best_lap_mistakes(all_events, corner_summaries)

    # Driving tips (primary actionable — what the driver should change)
    from telemetry_tool.handling.driving_tips import generate_driving_tips
    driving_tips = generate_driving_tips([e.to_dict() for e in all_events], max_tips=3)

    # Corner GPS positions for track map
    corner_positions = [
        {"corner_number": cw.corner_id + 1, "lat": cw.apex_lat, "lon": cw.apex_lon}
        for cw in corners if cw.apex_lat != 0
    ]

    return {
        "events": [e.to_dict() for e in all_events],
        "corners": corner_summaries,
        "focus_corners": focus_corners,
        "best_lap_mistakes": best_lap_mistakes,
        "driving_tips": driving_tips,
        "corner_positions": corner_positions,
        "calibration": {
            "yaw_ratio_offset": round(ctx.yaw_ratio_offset, 3),
            "corner_g_threshold": round(ctx.corner_g_threshold, 3),
            "friction_estimate_g": round(ctx.friction_estimate_g, 3),
            "trail_braking_slope": round(ctx.trail_braking_slope, 3),
        },
        "detector_weights": {k: round(v, 3) for k, v in weights.items()},
        "summary": summary,
    }


def _rank_focus_corners(
    corner_summaries: list[dict],
    all_events: list[FusedEvent],
) -> list[dict]:
    """Rank corners by handling severity to find the top 3 to focus on.

    Score = n_events * avg_confidence * peak_g (severity-weighted).
    """
    scored = []
    for cs in corner_summaries:
        cid = cs["corner_id"]
        corner_events = [e for e in all_events if e.corner_id == cid]
        if not corner_events:
            continue

        n = len(corner_events)
        avg_conf = float(np.mean([e.confidence for e in corner_events]))
        max_conf = float(max(e.confidence for e in corner_events))
        peak_g = cs.get("peak_g", 0.5)

        # Dominant tendency
        us = sum(1 for e in corner_events if e.direction > 0.15)
        os_ = sum(1 for e in corner_events if e.direction < -0.15)
        tendency = "understeer" if us > os_ else ("oversteer" if os_ > us else "mixed")

        # Dominant zone
        zones = [e.zone for e in corner_events]
        zone_counts = {}
        for z in zones:
            zone_counts[z] = zone_counts.get(z, 0) + 1
        dominant_zone = max(zone_counts, key=zone_counts.get) if zone_counts else "mid"

        score = n * avg_conf * peak_g
        scored.append({
            "corner_id": cid,
            "corner_number": cid + 1,
            "score": round(score, 3),
            "n_events": n,
            "avg_confidence": round(avg_conf, 3),
            "max_confidence": round(max_conf, 3),
            "peak_g": round(peak_g, 2),
            "tendency": tendency,
            "dominant_zone": dominant_zone,
            "start_m": cs.get("start_m", 0),
            "end_m": cs.get("end_m", 0),
        })

    scored.sort(key=lambda x: -x["score"])
    return scored[:3]


def _extract_best_lap_mistakes(
    all_events: list[FusedEvent],
    corner_summaries: list[dict],
) -> list[dict]:
    """Extract the most impactful handling events from the best lap.

    Ranked by impact = |direction| × confidence × peak_g.
    """
    mistakes = []
    corner_peak_g = {cs["corner_id"]: cs.get("peak_g", 0.5) for cs in corner_summaries}

    for ev in all_events:
        impact = abs(ev.direction) * ev.confidence * corner_peak_g.get(ev.corner_id, 0.5)
        if impact < 0.01:
            continue

        # Find top detector
        top_detector = None
        if ev.detector_votes:
            top_detector = max(ev.detector_votes.items(),
                             key=lambda x: abs(x[1][0]) * x[1][1]
                             if isinstance(x[1], tuple) else abs(x[1].get("direction", 0)))[0]

        mistakes.append({
            "corner_number": ev.corner_id + 1,
            "zone": ev.zone,
            "type": ev.label,
            "direction": round(ev.direction, 3),
            "confidence": round(ev.confidence, 3),
            "duration_s": round(ev.duration_s, 2),
            "impact": round(impact, 4),
            "top_detector": top_detector,
            "n_voters": ev.n_voters,
            "conflict": ev.conflict,
        })

    mistakes.sort(key=lambda x: -x["impact"])
    return mistakes[:5]


def _detect_corners(
    idx: np.ndarray,
    a_lat_f: np.ndarray,
    time_s: np.ndarray,
    dist_m: np.ndarray,
    speed_f: np.ndarray,
    a_lon_f: np.ndarray,
    bearing: np.ndarray,
    lat_deg: np.ndarray,
    lon_deg: np.ndarray,
    yaw_dps: np.ndarray,
    curvature: np.ndarray,
    fs: float,
) -> list[CornerWindow]:
    """Detect corners in a single lap's index range."""
    abs_alat = np.abs(a_lat_f[idx])
    in_corner = abs_alat > 0.25

    changes = np.diff(in_corner.astype(int))
    starts = np.where(changes == 1)[0] + 1
    ends = np.where(changes == -1)[0] + 1
    if in_corner[0]:
        starts = np.concatenate([[0], starts])
    if in_corner[-1]:
        ends = np.concatenate([ends, [len(idx) - 1]])

    min_samples = int(CORNER_MIN_S * fs)
    gap_samples = int(CORNER_GAP_S * fs)

    # Merge close corners
    raw = list(zip(starts, ends))
    merged = []
    for s, e in raw:
        if merged and s - merged[-1][1] < gap_samples:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))

    corners = []
    for s, e in merged:
        if e - s < min_samples:
            continue
        si, ei = idx[s], idx[e]
        cw = build_corner_window(
            len(corners), si, ei,
            time_s, dist_m, speed_f, a_lat_f, a_lon_f,
            bearing, lat_deg, lon_deg, yaw_dps, curvature,
        )
        corners.append(cw)

    return corners
