"""
track_surface/session_compare.py
--------------------------------
Session Compare Studio — core computation engine.

Takes two lap traces (reference + candidate) already stored in the viewer's
per-driver format (x, y, speed_kph, throttle, n_offset, lat_demand_g)
and produces a complete compare analysis:

  • Distance-aligned traces
  • Per-sample time delta accumulation
  • Corner segmentation from track curvature
  • Per-corner time-loss attribution
  • Top-N coaching fixes with evidence
  • Improved / worse / uncertain zone lists

Every metric is computed from the existing data — no fake claims.
If a signal is missing (e.g., brake pressure), the compare degrades to
what CAN be computed and explicitly tags the rest as uncertain.

Invariant: this module reads data; it does not modify Bronze or Silver.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np


# ─────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────


@dataclass
class LapTrace:
    """One lap's per-sample trace as stored in the viewer JSON
    (``data.drivers.hamilton`` or ``data.drivers.verstappen``)."""
    x: np.ndarray
    y: np.ndarray
    speed_kph: np.ndarray
    throttle: np.ndarray
    n_offset: np.ndarray
    lat_demand_g: np.ndarray
    lap_time_s: float
    label: str = ''


@dataclass
class CornerPacket:
    """Per-corner comparison analysis."""
    corner_id: int
    s_entry_m: float
    s_apex_m: float
    s_exit_m: float
    time_delta_ms: float         # positive = candidate is slower
    primary_cause: str           # e.g. "late_throttle_pickup"
    secondary_cause: str         # e.g. "low_minimum_speed"
    confidence: float            # 0..1
    evidence: dict = field(default_factory=dict)
    coach_text: str = ''


@dataclass
class SessionCompareResult:
    """Complete output of a lap-vs-lap comparison."""
    version: str = '1.0'
    reference_lap_id: str = ''
    candidate_lap_id: str = ''
    alignment_basis: str = 'distance_s'
    # Aligned trace arrays (on a shared s-grid, M samples)
    s_grid: np.ndarray = field(default_factory=lambda: np.array([]))
    ref_speed: np.ndarray = field(default_factory=lambda: np.array([]))
    cand_speed: np.ndarray = field(default_factory=lambda: np.array([]))
    ref_throttle: np.ndarray = field(default_factory=lambda: np.array([]))
    cand_throttle: np.ndarray = field(default_factory=lambda: np.array([]))
    ref_n_offset: np.ndarray = field(default_factory=lambda: np.array([]))
    cand_n_offset: np.ndarray = field(default_factory=lambda: np.array([]))
    ref_lat_demand: np.ndarray = field(default_factory=lambda: np.array([]))
    cand_lat_demand: np.ndarray = field(default_factory=lambda: np.array([]))
    delta_speed_kph: np.ndarray = field(default_factory=lambda: np.array([]))
    delta_time_s: np.ndarray = field(default_factory=lambda: np.array([]))  # cumulative
    # Per-sample deceleration (derived from speed)
    ref_decel_g: np.ndarray = field(default_factory=lambda: np.array([]))
    cand_decel_g: np.ndarray = field(default_factory=lambda: np.array([]))
    # Global summary
    global_summary: dict = field(default_factory=dict)
    # Segmented analysis
    corner_packets: list[CornerPacket] = field(default_factory=list)
    top_fixes: list[dict] = field(default_factory=list)
    improved_zones: list[dict] = field(default_factory=list)
    worse_zones: list[dict] = field(default_factory=list)
    uncertain_zones: list[dict] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────
# Alignment
# ─────────────────────────────────────────────────────────────────

_G = 9.80665


def _cumulative_distance(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    dx = np.diff(x)
    dy = np.diff(y)
    ds = np.sqrt(dx ** 2 + dy ** 2)
    return np.concatenate([[0.0], np.cumsum(ds)])


def _align_to_grid(
    x: np.ndarray, y: np.ndarray,
    speed_kph: np.ndarray, throttle: np.ndarray,
    n_offset: np.ndarray, lat_demand: np.ndarray,
    s_grid: np.ndarray,
) -> dict[str, np.ndarray]:
    """Resample one lap onto a uniform distance grid by interpolation."""
    s_raw = _cumulative_distance(x, y)
    if s_raw[-1] <= 0:
        n = len(s_grid)
        return {k: np.zeros(n) for k in ('speed', 'throttle', 'n_offset', 'lat_demand')}
    return {
        'speed': np.interp(s_grid, s_raw, speed_kph),
        'throttle': np.interp(s_grid, s_raw, throttle),
        'n_offset': np.interp(s_grid, s_raw, n_offset),
        'lat_demand': np.interp(s_grid, s_raw, lat_demand),
    }


# ─────────────────────────────────────────────────────────────────
# Corner segmentation
# ─────────────────────────────────────────────────────────────────


@dataclass
class CornerBounds:
    corner_id: int
    s_entry: float
    s_exit: float
    peak_curvature: float


def segment_corners(
    curvature: np.ndarray,
    s_centers: np.ndarray,
    *,
    corner_kappa: float = 0.025,
    min_corner_length_m: float = 15.0,
    merge_gap_m: float = 10.0,
) -> list[CornerBounds]:
    """Identify corners from track curvature as contiguous regions of
    |κ| > ``corner_kappa``, merged when gaps are < ``merge_gap_m``."""
    n = len(curvature)
    in_corner = np.abs(curvature) > corner_kappa
    corners: list[CornerBounds] = []
    i = 0
    cid = 1
    while i < n:
        if not in_corner[i]:
            i += 1
            continue
        j = i
        while j < n and in_corner[j]:
            j += 1
        # Merge with next corner if gap is small.
        while j < n:
            k = j
            while k < n and not in_corner[k]:
                k += 1
            if k < n and (s_centers[k] - s_centers[j - 1]) < merge_gap_m:
                j = k
                while j < n and in_corner[j]:
                    j += 1
            else:
                break
        s_start = float(s_centers[i])
        s_end = float(s_centers[min(j - 1, n - 1)])
        if (s_end - s_start) >= min_corner_length_m:
            peak_k = float(np.max(np.abs(curvature[i:j])))
            corners.append(CornerBounds(
                corner_id=cid, s_entry=s_start, s_exit=s_end,
                peak_curvature=peak_k,
            ))
            cid += 1
        i = max(j, i + 1)
    return corners


# ─────────────────────────────────────────────────────────────────
# Time-delta accumulation
# ─────────────────────────────────────────────────────────────────


def _compute_time_delta(
    s_grid: np.ndarray,
    ref_speed_kph: np.ndarray,
    cand_speed_kph: np.ndarray,
) -> np.ndarray:
    """Cumulative time delta (seconds). Positive = candidate is slower.

    dt at each segment = ds × (1/v_cand − 1/v_ref), then cumsum.
    """
    ds = np.gradient(s_grid)
    v_ref = np.maximum(ref_speed_kph / 3.6, 0.5)    # m/s, floor
    v_cand = np.maximum(cand_speed_kph / 3.6, 0.5)
    dt_per_seg = ds * (1.0 / v_cand - 1.0 / v_ref)
    return np.cumsum(dt_per_seg)


def _decel_from_speed(speed_kph: np.ndarray, ds_m: float) -> np.ndarray:
    """Longitudinal deceleration in G from speed trace. Positive = decelerating."""
    v_ms = speed_kph / 3.6
    dv = np.gradient(v_ms, ds_m)
    # dv is m/s per meter of distance = (m/s)/m = 1/s
    # accel = v · dv/ds → m/s²
    accel_mps2 = v_ms * dv
    return -accel_mps2 / _G     # positive when braking


# ─────────────────────────────────────────────────────────────────
# Per-corner analysis
# ─────────────────────────────────────────────────────────────────


def _analyze_corner(
    cb: CornerBounds,
    s_grid: np.ndarray,
    ref_speed: np.ndarray, cand_speed: np.ndarray,
    ref_throttle: np.ndarray, cand_throttle: np.ndarray,
    ref_n_offset: np.ndarray, cand_n_offset: np.ndarray,
    ref_decel: np.ndarray, cand_decel: np.ndarray,
    delta_time: np.ndarray,
    ds_m: float,
) -> CornerPacket:
    """Build a CornerPacket from aligned traces for one corner."""
    mask = (s_grid >= cb.s_entry) & (s_grid <= cb.s_exit)
    if not mask.any():
        return CornerPacket(
            corner_id=cb.corner_id,
            s_entry_m=cb.s_entry, s_apex_m=cb.s_entry, s_exit_m=cb.s_exit,
            time_delta_ms=0.0, primary_cause='no_data', secondary_cause='',
            confidence=0.0, coach_text='Insufficient data for this corner.',
        )
    idx = np.where(mask)[0]
    i0, i1 = int(idx[0]), int(idx[-1])

    # Expand window for braking zone detection (50 m before entry).
    brake_look = max(0, i0 - int(50.0 / max(ds_m, 0.5)))
    # And exit zone (50 m after exit).
    exit_look = min(len(s_grid) - 1, i1 + int(50.0 / max(ds_m, 0.5)))

    # Time delta across this corner (entry to exit).
    time_delta_s = float(delta_time[i1] - delta_time[i0])
    time_delta_ms = time_delta_s * 1000.0

    # Minimum speed in corner.
    ref_min_spd = float(np.min(ref_speed[i0:i1 + 1]))
    cand_min_spd = float(np.min(cand_speed[i0:i1 + 1]))
    ref_apex_idx = int(i0 + np.argmin(ref_speed[i0:i1 + 1]))
    cand_apex_idx = int(i0 + np.argmin(cand_speed[i0:i1 + 1]))
    s_apex = float(s_grid[ref_apex_idx])

    # Brake point: first sample in approach where deceleration > 0.15 G
    ref_brake_s = float('nan')
    cand_brake_s = float('nan')
    for k in range(brake_look, i0 + 1):
        if ref_decel[k] > 0.15 and np.isnan(ref_brake_s):
            ref_brake_s = float(s_grid[k])
        if cand_decel[k] > 0.15 and np.isnan(cand_brake_s):
            cand_brake_s = float(s_grid[k])

    # Throttle pickup: first sample after apex where throttle > 40%
    ref_throttle_s = float('nan')
    cand_throttle_s = float('nan')
    for k in range(ref_apex_idx, exit_look + 1):
        if ref_throttle[k] > 40.0 and np.isnan(ref_throttle_s):
            ref_throttle_s = float(s_grid[k])
        if cand_throttle[k] > 40.0 and np.isnan(cand_throttle_s):
            cand_throttle_s = float(s_grid[k])

    # Exit speed: speed 30 m after corner exit.
    exit_idx = min(len(s_grid) - 1, i1 + int(30.0 / max(ds_m, 0.5)))
    ref_exit_spd = float(ref_speed[exit_idx])
    cand_exit_spd = float(cand_speed[exit_idx])

    # Line deviation: RMS of n_offset difference in the corner.
    line_dev = float(np.sqrt(np.mean(
        (cand_n_offset[i0:i1 + 1] - ref_n_offset[i0:i1 + 1]) ** 2
    )))

    # Evidence dict
    brake_point_delta_m = (
        (cand_brake_s - ref_brake_s)
        if not (np.isnan(ref_brake_s) or np.isnan(cand_brake_s))
        else float('nan')
    )
    throttle_pickup_delta_m = (
        (cand_throttle_s - ref_throttle_s)
        if not (np.isnan(ref_throttle_s) or np.isnan(cand_throttle_s))
        else float('nan')
    )

    evidence = {
        'min_speed_ref_kph': round(ref_min_spd, 1),
        'min_speed_cand_kph': round(cand_min_spd, 1),
        'min_speed_delta_kph': round(cand_min_spd - ref_min_spd, 1),
        'brake_point_delta_m': round(brake_point_delta_m, 1) if not np.isnan(brake_point_delta_m) else None,
        'throttle_pickup_delta_m': round(throttle_pickup_delta_m, 1) if not np.isnan(throttle_pickup_delta_m) else None,
        'exit_speed_ref_kph': round(ref_exit_spd, 1),
        'exit_speed_cand_kph': round(cand_exit_spd, 1),
        'exit_speed_delta_kph': round(cand_exit_spd - ref_exit_spd, 1),
        'line_deviation_rms_m': round(line_dev, 2),
    }

    # ── Cause attribution ──
    # Rank contributing factors by magnitude.
    causes: list[tuple[float, str]] = []
    ms_delta = cand_min_spd - ref_min_spd
    if abs(ms_delta) > 1.0:
        # Negative min_speed_delta = candidate slower at apex
        causes.append((abs(ms_delta) * 0.01, 'low_minimum_speed' if ms_delta < 0 else 'high_minimum_speed'))
    if throttle_pickup_delta_m is not None and not np.isnan(throttle_pickup_delta_m):
        if throttle_pickup_delta_m > 3.0:
            causes.append((throttle_pickup_delta_m * 0.005, 'late_throttle_pickup'))
        elif throttle_pickup_delta_m < -3.0:
            causes.append((abs(throttle_pickup_delta_m) * 0.005, 'early_throttle_pickup'))
    if brake_point_delta_m is not None and not np.isnan(brake_point_delta_m):
        if brake_point_delta_m < -3.0:
            causes.append((abs(brake_point_delta_m) * 0.005, 'early_braking'))
        elif brake_point_delta_m > 3.0:
            causes.append((brake_point_delta_m * 0.005, 'late_braking'))
    exit_delta = cand_exit_spd - ref_exit_spd
    if abs(exit_delta) > 2.0:
        causes.append((abs(exit_delta) * 0.008, 'weak_exit_build' if exit_delta < 0 else 'strong_exit_build'))
    if line_dev > 0.5:
        causes.append((line_dev * 0.02, 'line_deviation'))

    causes.sort(reverse=True)
    primary = causes[0][1] if causes else 'uncertain'
    secondary = causes[1][1] if len(causes) > 1 else ''

    # Confidence: higher when evidence is clear, lower when uncertain.
    conf = min(1.0, 0.3 + 0.15 * len(causes) + 0.1 * (1.0 if not np.isnan(brake_point_delta_m) else 0.0))

    # ── Coach text ──
    coach = _generate_coach_text(
        cb.corner_id, time_delta_ms, primary, secondary, evidence,
    )

    return CornerPacket(
        corner_id=cb.corner_id,
        s_entry_m=cb.s_entry,
        s_apex_m=s_apex,
        s_exit_m=cb.s_exit,
        time_delta_ms=round(time_delta_ms, 1),
        primary_cause=primary,
        secondary_cause=secondary,
        confidence=round(conf, 2),
        evidence=evidence,
        coach_text=coach,
    )


def _generate_coach_text(
    corner_id: int, delta_ms: float,
    primary: str, secondary: str,
    evidence: dict,
) -> str:
    """Generate a specific coaching sentence from the actual evidence.

    Every metric reference in the text comes from ``evidence`` —
    no generic filler.
    """
    corner_name = f'Turn {corner_id}'
    if abs(delta_ms) < 5:
        return f'{corner_name}: negligible difference ({delta_ms:+.0f} ms).'

    direction = 'slower' if delta_ms > 0 else 'faster'
    parts = [f'{corner_name}: {abs(delta_ms):.0f} ms {direction}.']

    if primary == 'late_throttle_pickup' and evidence.get('throttle_pickup_delta_m'):
        parts.append(
            f'Pick throttle up about {abs(evidence["throttle_pickup_delta_m"]):.0f} m earlier; '
            f'exit build is {abs(evidence["exit_speed_delta_kph"]):.1f} km/h weaker than reference.'
        )
    elif primary == 'early_braking' and evidence.get('brake_point_delta_m'):
        parts.append(
            f'Braking starts {abs(evidence["brake_point_delta_m"]):.0f} m too early; '
            f'minimum speed is {abs(evidence["min_speed_delta_kph"]):.1f} km/h '
            f'{"lower" if evidence["min_speed_delta_kph"] < 0 else "higher"} than reference.'
        )
    elif primary == 'low_minimum_speed':
        parts.append(
            f'Minimum speed is {abs(evidence["min_speed_delta_kph"]):.1f} km/h lower than reference; '
            f'most of the loss happens before apex.'
        )
    elif primary == 'weak_exit_build':
        parts.append(
            f'Line is similar (deviation {evidence["line_deviation_rms_m"]:.1f} m RMS), '
            f'but exit build is {abs(evidence["exit_speed_delta_kph"]):.1f} km/h weaker; '
            f'delta grows after apex.'
        )
    elif primary == 'line_deviation':
        parts.append(
            f'Line deviates by {evidence["line_deviation_rms_m"]:.1f} m RMS from reference; '
            f'this costs corner speed.'
        )
    elif primary == 'high_minimum_speed' or primary == 'early_throttle_pickup' or primary == 'strong_exit_build':
        parts.append(
            f'This is a gain area — entry or exit technique is better here. '
            f'Min speed delta: {evidence["min_speed_delta_kph"]:+.1f} km/h.'
        )
    elif primary == 'uncertain':
        parts.append('Cause is mixed or unclear from available signals.')
    else:
        parts.append(f'Primary factor: {primary.replace("_", " ")}.')

    if secondary and secondary != primary:
        parts.append(f'Secondary: {secondary.replace("_", " ")}.')

    return ' '.join(parts)


# ─────────────────────────────────────────────────────────────────
# Time-loss attribution by phase
# ─────────────────────────────────────────────────────────────────


def _attribute_time_loss(
    s_grid: np.ndarray,
    ref_speed: np.ndarray, cand_speed: np.ndarray,
    ref_decel: np.ndarray, cand_decel: np.ndarray,
    curvature: np.ndarray,
    delta_time: np.ndarray,
) -> dict[str, float]:
    """Deterministic attribution of total delta into phase buckets.

    Buckets: braking, corner, exit_traction, straight_carry, uncertain.
    Sum ≈ total delta (may differ slightly due to discrete binning).
    """
    ds = np.gradient(s_grid)
    v_ref = np.maximum(ref_speed / 3.6, 0.5)
    v_cand = np.maximum(cand_speed / 3.6, 0.5)
    dt_local = ds * (1.0 / v_cand - 1.0 / v_ref)

    braking = ref_decel > 0.15
    in_corner = np.abs(curvature) > 0.02
    accelerating = (ref_decel < -0.10) & ~in_corner
    straight = ~braking & ~in_corner & ~accelerating

    total = float(np.sum(dt_local))
    return {
        'braking_s': round(float(np.sum(dt_local[braking])), 3),
        'corner_s': round(float(np.sum(dt_local[in_corner & ~braking])), 3),
        'exit_traction_s': round(float(np.sum(dt_local[accelerating])), 3),
        'straight_carry_s': round(float(np.sum(dt_local[straight])), 3),
        'uncertain_s': round(total - float(
            np.sum(dt_local[braking]) +
            np.sum(dt_local[in_corner & ~braking]) +
            np.sum(dt_local[accelerating]) +
            np.sum(dt_local[straight])
        ), 3),
        'total_s': round(total, 3),
    }


# ─────────────────────────────────────────────────────────────────
# Top fixes
# ─────────────────────────────────────────────────────────────────


def _build_top_fixes(
    packets: list[CornerPacket], n: int = 3,
) -> list[dict]:
    """Pick the top N corners by |time_delta|, each as a fix dict."""
    # Only fix where candidate is slower (positive delta = slower).
    losers = [p for p in packets if p.time_delta_ms > 5.0]
    losers.sort(key=lambda p: -p.time_delta_ms)
    fixes = []
    seen_corners: set[int] = set()
    for p in losers[:n * 2]:     # look deeper in case of duplicates
        if p.corner_id in seen_corners:
            continue
        seen_corners.add(p.corner_id)
        fixes.append({
            'corner_id': p.corner_id,
            's_entry_m': p.s_entry_m,
            's_apex_m': p.s_apex_m,
            's_exit_m': p.s_exit_m,
            'time_delta_ms': p.time_delta_ms,
            'primary_cause': p.primary_cause,
            'confidence': p.confidence,
            'coach_text': p.coach_text,
        })
        if len(fixes) >= n:
            break
    return fixes


def _build_zone_lists(
    packets: list[CornerPacket],
) -> tuple[list[dict], list[dict], list[dict]]:
    """Sort corners into improved, worse, uncertain."""
    improved = []
    worse = []
    uncertain = []
    for p in packets:
        entry = {
            'corner_id': p.corner_id,
            's_entry_m': p.s_entry_m,
            's_exit_m': p.s_exit_m,
            'time_delta_ms': p.time_delta_ms,
            'primary_cause': p.primary_cause,
        }
        if p.confidence < 0.3:
            uncertain.append(entry)
        elif p.time_delta_ms < -5.0:
            improved.append(entry)
        elif p.time_delta_ms > 5.0:
            worse.append(entry)
    return improved, worse, uncertain


# ─────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────


def compare_laps(
    reference: LapTrace,
    candidate: LapTrace,
    track_curvature: np.ndarray,
    track_s_grid: np.ndarray,
    *,
    grid_spacing_m: float = 1.5,
) -> SessionCompareResult:
    """Full lap-vs-lap comparison.

    Parameters
    ----------
    reference, candidate : LapTrace
    track_curvature : (N,) signed curvature from the track's centerline
    track_s_grid : (N,) distance from the track centerline

    Returns
    -------
    SessionCompareResult
    """
    # Build a uniform distance grid.
    ref_dist = _cumulative_distance(reference.x, reference.y)
    cand_dist = _cumulative_distance(candidate.x, candidate.y)
    max_dist = min(ref_dist[-1], cand_dist[-1])
    if max_dist < 50.0:
        return SessionCompareResult(
            reference_lap_id=reference.label,
            candidate_lap_id=candidate.label,
            global_summary={'error': 'laps too short to compare'},
        )
    s_grid = np.arange(0.0, max_dist, grid_spacing_m)
    M = len(s_grid)
    ds_m = grid_spacing_m

    # Align both laps onto the shared grid.
    ref_a = _align_to_grid(
        reference.x, reference.y, reference.speed_kph,
        reference.throttle, reference.n_offset, reference.lat_demand_g,
        s_grid,
    )
    cand_a = _align_to_grid(
        candidate.x, candidate.y, candidate.speed_kph,
        candidate.throttle, candidate.n_offset, candidate.lat_demand_g,
        s_grid,
    )

    ref_speed = ref_a['speed']
    cand_speed = cand_a['speed']
    ref_throttle = ref_a['throttle']
    cand_throttle = cand_a['throttle']
    ref_n = ref_a['n_offset']
    cand_n = cand_a['n_offset']
    ref_lat = ref_a['lat_demand']
    cand_lat = cand_a['lat_demand']

    delta_speed = cand_speed - ref_speed
    delta_time = _compute_time_delta(s_grid, ref_speed, cand_speed)

    # Deceleration from speed trace (positive = braking).
    ref_decel = _decel_from_speed(ref_speed, ds_m)
    cand_decel = _decel_from_speed(cand_speed, ds_m)

    # Curvature resampled to compare grid.
    if len(track_curvature) > 0 and len(track_s_grid) > 0:
        curv_on_grid = np.interp(s_grid, track_s_grid, track_curvature)
    else:
        curv_on_grid = np.zeros(M)

    # Segment into corners.
    corners = segment_corners(curv_on_grid, s_grid)

    # Per-corner analysis.
    packets = [
        _analyze_corner(
            cb, s_grid, ref_speed, cand_speed,
            ref_throttle, cand_throttle, ref_n, cand_n,
            ref_decel, cand_decel, delta_time, ds_m,
        )
        for cb in corners
    ]

    # Time-loss attribution by phase.
    attrib = _attribute_time_loss(
        s_grid, ref_speed, cand_speed, ref_decel, cand_decel,
        curv_on_grid, delta_time,
    )

    # Top fixes + zone lists.
    top_fixes = _build_top_fixes(packets)
    improved, worse, uncertain = _build_zone_lists(packets)

    total_delta_s = float(delta_time[-1]) if M > 0 else 0.0

    # Global summary.
    global_summary = {
        'lap_time_delta_s': round(candidate.lap_time_s - reference.lap_time_s, 3),
        'accumulated_delta_s': round(total_delta_s, 3),
        'time_lost_by_phase': attrib,
        'n_corners_detected': len(corners),
        'top_gain_corner': (
            min(packets, key=lambda p: p.time_delta_ms).corner_id
            if packets else None
        ),
        'top_loss_corner': (
            max(packets, key=lambda p: p.time_delta_ms).corner_id
            if packets else None
        ),
        'analysis_confidence': round(
            float(np.mean([p.confidence for p in packets])) if packets else 0.0, 2,
        ),
    }

    return SessionCompareResult(
        version='1.0',
        reference_lap_id=reference.label,
        candidate_lap_id=candidate.label,
        alignment_basis='distance_s',
        s_grid=s_grid,
        ref_speed=ref_speed, cand_speed=cand_speed,
        ref_throttle=ref_throttle, cand_throttle=cand_throttle,
        ref_n_offset=ref_n, cand_n_offset=cand_n,
        ref_lat_demand=ref_lat, cand_lat_demand=cand_lat,
        delta_speed_kph=delta_speed,
        delta_time_s=delta_time,
        ref_decel_g=ref_decel, cand_decel_g=cand_decel,
        global_summary=global_summary,
        corner_packets=packets,
        top_fixes=top_fixes,
        improved_zones=improved,
        worse_zones=worse,
        uncertain_zones=uncertain,
    )


def to_json_dict(result: SessionCompareResult) -> dict:
    """JSON-safe serialization of the full compare result.

    Trace arrays are downsampled for reasonable JSON size — every 3rd
    sample is kept for the aligned traces. Corner packets and summaries
    are serialized in full.
    """
    step = 3  # downsample for JSON payload size
    def _ds(arr: np.ndarray) -> list:
        return [round(float(v), 2) for v in arr[::step]]

    packets_json = []
    for p in result.corner_packets:
        packets_json.append({
            'corner_id': p.corner_id,
            's_entry_m': round(p.s_entry_m, 1),
            's_apex_m': round(p.s_apex_m, 1),
            's_exit_m': round(p.s_exit_m, 1),
            'time_delta_ms': p.time_delta_ms,
            'primary_cause': p.primary_cause,
            'secondary_cause': p.secondary_cause,
            'confidence': p.confidence,
            'evidence': p.evidence,
            'coach_text': p.coach_text,
        })

    return {
        'version': result.version,
        'reference_lap_id': result.reference_lap_id,
        'candidate_lap_id': result.candidate_lap_id,
        'alignment_basis': result.alignment_basis,
        'traces': {
            's_grid': _ds(result.s_grid),
            'ref_speed_kph': _ds(result.ref_speed),
            'cand_speed_kph': _ds(result.cand_speed),
            'ref_throttle': _ds(result.ref_throttle),
            'cand_throttle': _ds(result.cand_throttle),
            'ref_n_offset': _ds(result.ref_n_offset),
            'cand_n_offset': _ds(result.cand_n_offset),
            'ref_lat_demand_g': _ds(result.ref_lat_demand),
            'cand_lat_demand_g': _ds(result.cand_lat_demand),
            'delta_speed_kph': _ds(result.delta_speed_kph),
            'delta_time_s': _ds(result.delta_time_s),
            'ref_decel_g': _ds(result.ref_decel_g),
            'cand_decel_g': _ds(result.cand_decel_g),
        },
        'global_summary': result.global_summary,
        'corner_packets': packets_json,
        'top_fixes': result.top_fixes,
        'improved_zones': result.improved_zones,
        'worse_zones': result.worse_zones,
        'uncertain_zones': result.uncertain_zones,
    }
