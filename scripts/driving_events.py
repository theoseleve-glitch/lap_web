#!/usr/bin/env python
"""Driving event library — realistic human-like input variation with full labels.

Detects corners from physics, plans events across laps, applies physically-
motivated modifications, and labels everything for impact analysis.

Lap structure (5 laps):
  1: warmup    — conservative, slight extra delays
  2: building  — approaching optimal
  3: REFERENCE — cleanest lap, near-optimal (the eventless baseline)
  4: events    — 2-3 mild events (severity 0.3-0.5)
  5: events    — 2-3 hard events (severity 0.6-0.9)

10-lap structure:
  1-2: warmup, 3: building, 4-5: reference, 6-7: mild events,
  8-9: hard events, 10: fatigue

Output labels per sample:
  event_type, event_id, event_severity, event_phase, lap_type, corner_id
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Corner:
    entry: int          # sample index: braking start
    apex: int           # sample index: minimum speed
    exit: int           # sample index: throttle opens
    corner_id: int = 0
    speed_entry: float = 0.0
    speed_apex: float = 0.0
    speed_exit: float = 0.0


@dataclass
class DrivingEvent:
    event_type: str
    event_id: int
    corner_idx: int     # which corner (0-based), -1 for non-corner events
    severity: float     # 0.0-1.0
    start: int          # sample index
    end: int            # sample index
    phases: List[Tuple[int, int, str]] = field(default_factory=list)
    # [(start, end, "onset"), (start, end, "peak"), (start, end, "recovery")]


@dataclass
class LapPlan:
    lap_type: str       # warmup, building, reference, event_mild, event_hard, fatigue
    events: List[Tuple[str, int, float]] = field(default_factory=list)
    # [(event_type, corner_idx, severity), ...]


SAMPLE_HZ = 60

# All event types
EVENT_TYPES = [
    "understeer", "oversteer",
    "late_brake", "early_brake",
    "late_turnin", "early_turnin",
    "slow_correction", "fast_correction",
    "throttle_hesitation", "brake_lockup",
]


# ---------------------------------------------------------------------------
# Corner detection
# ---------------------------------------------------------------------------

def detect_corners(
    speed_ms: np.ndarray,
    g_lat: np.ndarray | None = None,
    min_speed_drop_ms: float = 3.0,
    min_gap_samples: int = 60,
) -> List[Corner]:
    """Find corners as speed valleys in the trace.

    Uses scipy peak detection on inverted speed to find apexes,
    then expands outward to find entry/exit boundaries.
    """
    n = len(speed_ms)
    if n < min_gap_samples * 3:
        return []

    # Smooth speed to avoid detecting noise as corners
    from scripts.postprocess_ac_telemetry import _smooth
    smooth_spd = _smooth(speed_ms.copy(), min(31, max(7, n // 200)))

    # Find valleys: invert and find peaks
    try:
        from scipy.signal import find_peaks
        inv = -smooth_spd
        peaks, props = find_peaks(
            inv,
            distance=min_gap_samples,
            prominence=min_speed_drop_ms,
        )
    except ImportError:
        # Fallback: manual valley detection
        peaks = _find_valleys_manual(smooth_spd, min_speed_drop_ms, min_gap_samples)

    corners = []
    for ci, apex_idx in enumerate(peaks):
        # Expand entry: walk backward while speed is decreasing
        entry = apex_idx
        while entry > 1 and smooth_spd[entry - 1] >= smooth_spd[entry] - 0.5:
            entry -= 1
            if apex_idx - entry > SAMPLE_HZ * 8:  # max 8s braking zone
                break

        # Expand exit: walk forward while speed is increasing
        exit_idx = apex_idx
        while exit_idx < n - 2 and smooth_spd[exit_idx + 1] >= smooth_spd[exit_idx] - 0.5:
            exit_idx += 1
            if exit_idx - apex_idx > SAMPLE_HZ * 8:
                break

        # Don't overlap with previous corner
        if corners and entry < corners[-1].exit:
            entry = corners[-1].exit + 1

        if entry >= apex_idx or apex_idx >= exit_idx:
            continue

        corners.append(Corner(
            entry=entry, apex=apex_idx, exit=exit_idx,
            corner_id=ci,
            speed_entry=float(smooth_spd[entry]),
            speed_apex=float(smooth_spd[apex_idx]),
            speed_exit=float(smooth_spd[exit_idx]),
        ))

    return corners


def _find_valleys_manual(speed, min_drop, min_gap):
    """Fallback valley detection without scipy."""
    n = len(speed)
    valleys = []
    i = min_gap
    while i < n - min_gap:
        # Check if local minimum
        window = speed[max(0, i - min_gap):min(n, i + min_gap)]
        if speed[i] == window.min() and (speed[i - min_gap // 2] - speed[i]) > min_drop:
            valleys.append(i)
            i += min_gap
        else:
            i += 1
    return np.array(valleys)


# ---------------------------------------------------------------------------
# Lap planner
# ---------------------------------------------------------------------------

def plan_laps(
    n_laps: int,
    n_corners: int,
    rng: np.random.RandomState,
) -> List[LapPlan]:
    """Assign lap types and distribute events across laps and corners.

    Reference lap is always in the middle. Events are distributed so
    every corner gets at least one event across all laps.
    """
    plans: List[LapPlan] = []

    if n_laps <= 0 or n_corners <= 0:
        return [LapPlan("reference") for _ in range(max(1, n_laps))]

    # Assign lap types based on total laps
    if n_laps <= 3:
        types = ["warmup", "reference", "event_mild"][:n_laps]
    elif n_laps <= 5:
        types = ["warmup", "building", "reference", "event_mild", "event_hard"][:n_laps]
    elif n_laps <= 8:
        types = (
            ["warmup", "building", "reference", "reference"]
            + ["event_mild"] * min(2, n_laps - 4)
            + ["event_hard"] * max(0, n_laps - 6)
        )[:n_laps]
    else:
        types = (
            ["warmup", "warmup", "building", "reference", "reference"]
            + ["event_mild"] * 2
            + ["event_hard"] * max(1, n_laps - 7 - 1)
            + ["fatigue"]
        )[:n_laps]

    # Pad if needed
    while len(types) < n_laps:
        types.append("event_mild")

    # Event pool for mild/hard laps
    mild_events = ["late_brake", "early_brake", "late_turnin", "early_turnin",
                   "throttle_hesitation"]
    hard_events = ["understeer", "oversteer", "brake_lockup",
                   "slow_correction", "fast_correction"]

    # Track which corners have been assigned events (ensure coverage)
    corner_coverage = set()
    all_corners = list(range(n_corners))

    for lap_type in types:
        plan = LapPlan(lap_type=lap_type)

        if lap_type == "event_mild":
            n_events = rng.randint(1, min(4, n_corners + 1))
            # Prefer uncovered corners
            available = [c for c in all_corners if c not in corner_coverage] or all_corners
            chosen_corners = rng.choice(available, size=min(n_events, len(available)), replace=False)
            for ci in chosen_corners:
                etype = rng.choice(mild_events)
                severity = round(rng.uniform(0.3, 0.55), 2)
                plan.events.append((etype, int(ci), severity))
                corner_coverage.add(int(ci))

        elif lap_type == "event_hard":
            n_events = rng.randint(2, min(5, n_corners + 1))
            available = [c for c in all_corners if c not in corner_coverage] or all_corners
            chosen_corners = rng.choice(available, size=min(n_events, len(available)), replace=False)
            for ci in chosen_corners:
                etype = rng.choice(hard_events)
                severity = round(rng.uniform(0.55, 0.92), 2)
                plan.events.append((etype, int(ci), severity))
                corner_coverage.add(int(ci))

        elif lap_type == "fatigue":
            # Fatigue: mild events at random corners + global slowdown
            n_events = rng.randint(1, min(3, n_corners + 1))
            chosen = rng.choice(all_corners, size=min(n_events, len(all_corners)), replace=False)
            for ci in chosen:
                etype = rng.choice(["slow_correction", "late_brake", "throttle_hesitation"])
                severity = round(rng.uniform(0.4, 0.7), 2)
                plan.events.append((etype, int(ci), severity))

        plans.append(plan)

    return plans


# ---------------------------------------------------------------------------
# Event applicators — each modifies traces and returns event metadata
# ---------------------------------------------------------------------------

def _ms(seconds: float) -> int:
    """Convert seconds to sample count at 60Hz."""
    return max(1, int(seconds * SAMPLE_HZ))


def apply_late_brake(thr, brk, steer, corner: Corner, severity: float, rng) -> DrivingEvent:
    """Shift brake point later → higher pressure to compensate."""
    shift = _ms(severity * 0.5)  # up to 500ms late
    entry, apex = corner.entry, corner.apex

    # Extend throttle into what should be braking zone
    late_start = entry
    late_end = min(entry + shift, apex - 2)
    thr[late_start:late_end] = np.clip(thr[late_start:late_end] + 0.3 * severity, 0, 1)
    brk[late_start:late_end] *= (1 - severity * 0.8)

    # Compensate: harder braking after the delayed onset
    comp_start = late_end
    comp_end = min(apex, comp_start + _ms(0.8))
    brk[comp_start:comp_end] = np.clip(brk[comp_start:comp_end] * (1 + severity * 0.4), 0, 1)

    return DrivingEvent("late_brake", 0, corner.corner_id, severity, late_start, comp_end,
                        phases=[(late_start, late_end, "onset"), (comp_start, comp_end, "peak")])


def apply_early_brake(thr, brk, steer, corner: Corner, severity: float, rng) -> DrivingEvent:
    """Brake earlier than optimal → lower pressure, time lost on approach."""
    shift = _ms(severity * 0.4)  # up to 400ms early
    entry = corner.entry

    early_start = max(0, entry - shift)
    # Start light braking before the real brake point
    ramp = np.linspace(severity * 0.3, 0, shift)
    end_idx = min(early_start + len(ramp), len(brk))
    brk[early_start:end_idx] = np.clip(brk[early_start:end_idx] + ramp[:end_idx - early_start], 0, 1)
    thr[early_start:end_idx] *= (1 - severity * 0.5)

    return DrivingEvent("early_brake", 0, corner.corner_id, severity, early_start, entry,
                        phases=[(early_start, entry, "onset")])


def apply_late_turnin(thr, brk, steer, corner: Corner, severity: float, rng) -> DrivingEvent:
    """Delay steering input → more aggressive correction to make apex."""
    shift = _ms(severity * 0.35)
    entry, apex = corner.entry, corner.apex

    # Reduce steering for the delayed period
    delay_end = min(entry + shift, apex - 2)
    steer[entry:delay_end] *= (1 - severity * 0.7)

    # Aggressive correction: overshoot steering to catch up
    corr_end = min(apex + _ms(0.3), corner.exit)
    steer[delay_end:corr_end] *= (1 + severity * 0.25)

    return DrivingEvent("late_turnin", 0, corner.corner_id, severity, entry, corr_end,
                        phases=[(entry, delay_end, "onset"), (delay_end, corr_end, "peak")])


def apply_early_turnin(thr, brk, steer, corner: Corner, severity: float, rng) -> DrivingEvent:
    """Steer too early → mid-corner correction → wide exit."""
    shift = _ms(severity * 0.3)
    entry, apex, exit_idx = corner.entry, corner.apex, corner.exit

    # Extra steering before entry
    early_start = max(0, entry - shift)
    steer[early_start:entry] += np.sign(steer[apex]) * severity * 0.15

    # Mid-corner: must reduce steering (overturned)
    mid = (entry + apex) // 2
    steer[mid:apex] *= (1 - severity * 0.2)

    # Wide exit: delayed throttle
    throttle_delay = _ms(severity * 0.3)
    thr[apex:min(apex + throttle_delay, exit_idx)] *= (1 - severity * 0.5)

    return DrivingEvent("early_turnin", 0, corner.corner_id, severity, early_start, exit_idx,
                        phases=[(early_start, entry, "onset"), (mid, apex, "peak"),
                                (apex, exit_idx, "recovery")])


def apply_understeer(thr, brk, steer, corner: Corner, severity: float, rng) -> DrivingEvent:
    """Front push: extra steering lock + throttle lift around apex."""
    apex = corner.apex
    duration = _ms(0.5 + severity * 1.5)  # 0.5-2.0 seconds
    start = max(corner.entry, apex - duration // 3)
    end = min(corner.exit, apex + duration * 2 // 3)

    # Driver adds more steering (front is pushing, needs more lock)
    steer_sign = np.sign(steer[apex]) if steer[apex] != 0 else 1.0
    extra_lock = severity * 0.3 * steer_sign
    ramp_in = np.linspace(0, extra_lock, apex - start) if apex > start else np.array([])
    ramp_out = np.linspace(extra_lock, 0, end - apex) if end > apex else np.array([])
    steer[start:apex] += ramp_in[:apex - start]
    steer[apex:end] += ramp_out[:end - apex]

    # Throttle lift in response
    thr[start:end] *= (1 - severity * 0.4)

    # Slight brake tap if severe
    if severity > 0.6:
        tap_start = apex - _ms(0.15)
        tap_end = apex + _ms(0.15)
        brk[max(0, tap_start):min(len(brk), tap_end)] += severity * 0.15

    onset_end = (start + apex) // 2
    return DrivingEvent("understeer", 0, corner.corner_id, severity, start, end,
                        phases=[(start, onset_end, "onset"), (onset_end, apex, "peak"),
                                (apex, end, "recovery")])


def apply_oversteer(thr, brk, steer, corner: Corner, severity: float, rng) -> DrivingEvent:
    """Rear slide: counter-steer + throttle lift + optional panic brake."""
    apex = corner.apex
    duration = _ms(0.3 + severity * 1.2)
    # Oversteer typically happens just past apex (power oversteer)
    start = min(apex + _ms(0.1), corner.exit - 2)
    end = min(start + duration, corner.exit)
    if start >= end:
        start = max(apex, end - _ms(0.3))

    # Counter-steer: steering reduces or reverses
    steer_at_start = steer[start] if start < len(steer) else 0
    counter_mag = severity * 0.5
    counter_profile = np.concatenate([
        np.linspace(0, -counter_mag, max(1, (end - start) // 3)),
        np.linspace(-counter_mag, -counter_mag * 0.5, max(1, (end - start) // 3)),
        np.linspace(-counter_mag * 0.5, 0, max(1, (end - start) - 2 * ((end - start) // 3))),
    ])[:end - start]
    steer[start:start + len(counter_profile)] += np.sign(steer_at_start) * counter_profile

    # Complete throttle lift
    thr[start:end] *= (1 - severity * 0.8)

    # Panic brake tap for high severity
    if severity > 0.5:
        tap_len = _ms(0.12 + severity * 0.1)
        brk[start:min(start + tap_len, end)] += severity * 0.25

    peak_end = start + max(1, (end - start) * 2 // 3)
    return DrivingEvent("oversteer", 0, corner.corner_id, severity, start, end,
                        phases=[(start, start + (end - start) // 3, "onset"),
                                (start + (end - start) // 3, peak_end, "peak"),
                                (peak_end, end, "recovery")])


def apply_slow_correction(thr, brk, steer, corner: Corner, severity: float, rng) -> DrivingEvent:
    """Sluggish response to a slide — 300-500ms before correction kicks in."""
    # First create a small slide (understeer or oversteer)
    is_understeer = rng.random() > 0.5
    apex = corner.apex
    delay = _ms(0.3 + severity * 0.2)  # 300-500ms delay

    slide_start = apex
    slide_end = min(apex + _ms(0.4), corner.exit)
    correction_end = min(slide_end + delay + _ms(0.5), corner.exit)

    if is_understeer:
        sign = np.sign(steer[apex]) if steer[apex] != 0 else 1.0
        steer[slide_start:slide_end] += sign * severity * 0.2
        # Delayed response: no correction for `delay` frames
        steer[slide_end:min(slide_end + delay, correction_end)] += sign * severity * 0.15
    else:
        sign = np.sign(steer[apex]) if steer[apex] != 0 else 1.0
        steer[slide_start:slide_end] -= sign * severity * 0.2
        steer[slide_end:min(slide_end + delay, correction_end)] -= sign * severity * 0.1

    thr[slide_start:correction_end] *= (1 - severity * 0.5)

    return DrivingEvent("slow_correction", 0, corner.corner_id, severity, slide_start, correction_end,
                        phases=[(slide_start, slide_end, "onset"),
                                (slide_end, slide_end + delay, "peak"),
                                (slide_end + delay, correction_end, "recovery")])


def apply_fast_correction(thr, brk, steer, corner: Corner, severity: float, rng) -> DrivingEvent:
    """Quick snap response — 100-200ms, small deviation, clean recovery."""
    apex = corner.apex
    response_time = _ms(0.1 + (1 - severity) * 0.1)  # faster with higher severity
    slide_dur = _ms(0.2)

    slide_start = min(apex + _ms(0.05), corner.exit - 2)
    slide_end = min(slide_start + slide_dur, corner.exit)
    corr_end = min(slide_end + response_time + _ms(0.2), corner.exit)

    sign = np.sign(steer[apex]) if steer[apex] != 0 else 1.0
    # Small slide
    steer[slide_start:slide_end] -= sign * severity * 0.12
    # Quick counter
    steer[slide_end:min(slide_end + response_time, corr_end)] += sign * severity * 0.08
    # Brief throttle lift
    thr[slide_start:min(slide_start + _ms(0.3), corr_end)] *= (1 - severity * 0.3)

    return DrivingEvent("fast_correction", 0, corner.corner_id, severity, slide_start, corr_end,
                        phases=[(slide_start, slide_end, "onset"),
                                (slide_end, slide_end + response_time, "peak"),
                                (slide_end + response_time, corr_end, "recovery")])


def apply_throttle_hesitation(thr, brk, steer, corner: Corner, severity: float, rng) -> DrivingEvent:
    """Pulse/lift before committing to full throttle on corner exit."""
    apex, exit_idx = corner.apex, corner.exit
    zone_start = apex + (exit_idx - apex) // 4
    zone_end = min(zone_start + _ms(0.8 + severity * 0.5), exit_idx)

    # Initial application
    first_app = zone_start + _ms(0.15)
    # Lift
    lift_start = first_app
    lift_end = min(lift_start + _ms(0.15 + severity * 0.2), zone_end)
    # Reapply
    reapply = lift_end

    thr[lift_start:lift_end] *= (1 - severity * 0.5)
    # Second hesitation for high severity
    if severity > 0.6 and reapply + _ms(0.3) < zone_end:
        h2_start = reapply + _ms(0.1)
        h2_end = min(h2_start + _ms(0.12), zone_end)
        thr[h2_start:h2_end] *= (1 - severity * 0.3)

    return DrivingEvent("throttle_hesitation", 0, corner.corner_id, severity, zone_start, zone_end,
                        phases=[(zone_start, lift_start, "onset"),
                                (lift_start, lift_end, "peak"),
                                (lift_end, zone_end, "recovery")])


def apply_brake_lockup(thr, brk, steer, corner: Corner, severity: float, rng) -> DrivingEvent:
    """Excessive brake pressure → lockup → release → reapply."""
    entry, apex = corner.entry, corner.apex
    lockup_start = entry + _ms(0.1)
    lockup_dur = _ms(0.2 + severity * 0.3)
    lockup_end = min(lockup_start + lockup_dur, apex)

    # Slam brakes (overpress)
    brk[lockup_start:lockup_end] = np.clip(brk[lockup_start:lockup_end] + severity * 0.4, 0, 1)

    # Release (panic)
    release_end = min(lockup_end + _ms(0.1), apex)
    brk[lockup_end:release_end] *= (1 - severity * 0.7)

    # Reapply at lower pressure
    reapply_end = min(release_end + _ms(0.3), apex)
    brk[release_end:reapply_end] *= (1 - severity * 0.15)

    return DrivingEvent("brake_lockup", 0, corner.corner_id, severity, lockup_start, reapply_end,
                        phases=[(lockup_start, lockup_end, "onset"),
                                (lockup_end, release_end, "peak"),
                                (release_end, reapply_end, "recovery")])


# Dispatch table
_APPLY_FNS = {
    "understeer": apply_understeer,
    "oversteer": apply_oversteer,
    "late_brake": apply_late_brake,
    "early_brake": apply_early_brake,
    "late_turnin": apply_late_turnin,
    "early_turnin": apply_early_turnin,
    "slow_correction": apply_slow_correction,
    "fast_correction": apply_fast_correction,
    "throttle_hesitation": apply_throttle_hesitation,
    "brake_lockup": apply_brake_lockup,
}


# ---------------------------------------------------------------------------
# Global lap modifiers (warmup / fatigue)
# ---------------------------------------------------------------------------

def apply_warmup(thr, brk, steer, rng, intensity=0.5):
    """Conservative driving: earlier braking, less aggressive steering."""
    n = len(thr)
    # Slightly reduce peak throttle
    thr *= (1 - intensity * 0.08)
    # Slightly earlier braking (shift brake trace forward by a few frames)
    shift = int(intensity * 4)
    if shift > 0:
        brk[:-shift] = np.maximum(brk[:-shift], brk[shift:] * 0.3)
    # Slightly reduce steering aggressiveness
    steer *= (1 - intensity * 0.05)


def apply_fatigue(thr, brk, steer, rng, intensity=0.5):
    """Tired driving: delayed reactions, wider lines, inconsistent pressure."""
    from scripts.postprocess_ac_telemetry import _smooth
    n = len(thr)
    t = np.arange(n) / SAMPLE_HZ

    # Global reaction delay (2-5 frames)
    delay = int(2 + intensity * 3)
    thr[:] = np.roll(thr, delay)
    thr[:delay] = thr[delay]
    brk[:] = np.roll(brk, delay)
    brk[:delay] = brk[delay]
    steer[:] = np.roll(steer, delay)
    steer[:delay] = steer[delay]

    # Slow wandering noise (fatigue drift)
    for _ in range(2):
        f = rng.uniform(0.2, 0.8)
        phase = rng.uniform(0, 2 * np.pi)
        drift = np.sin(2 * np.pi * f * t + phase) * intensity * 0.02
        steer += drift


# ---------------------------------------------------------------------------
# Master pipeline: per-car, per-lap processing
# ---------------------------------------------------------------------------

def generate_human_laps(
    opt_thr: np.ndarray,
    opt_brk: np.ndarray,
    opt_str: np.ndarray,
    speed_ms: np.ndarray,
    g_lat: np.ndarray,
    lap_ids: np.ndarray,
    seed: int = 42,
) -> dict:
    """Generate event-driven human-like inputs from optimal reference.

    Returns dict with arrays:
      human_throttle, human_brake, human_steer, driver_skill,
      event_type, event_id, event_severity, event_phase, lap_type, corner_id
    """
    from scripts.postprocess_ac_telemetry import _smooth

    rng = np.random.RandomState(seed)
    n = len(opt_thr)

    # Output arrays
    h_thr = opt_thr.copy()
    h_brk = opt_brk.copy()
    h_str = opt_str.copy()
    event_type_arr = np.full(n, "none", dtype=object)
    event_id_arr = np.zeros(n, dtype=np.int32)
    event_severity_arr = np.zeros(n, dtype=np.float32)
    event_phase_arr = np.full(n, "none", dtype=object)
    lap_type_arr = np.full(n, "reference", dtype=object)
    corner_id_arr = np.zeros(n, dtype=np.int32)
    skill_arr = np.full(n, 0.0, dtype=np.float32)

    # Split into laps
    unique_laps = np.unique(lap_ids)
    n_laps = len(unique_laps)

    if n_laps == 0:
        return _pack_results(h_thr, h_brk, h_str, skill_arr,
                             event_type_arr, event_id_arr, event_severity_arr,
                             event_phase_arr, lap_type_arr, corner_id_arr)

    # Detect corners from the first valid lap (most representative)
    mid_lap = unique_laps[n_laps // 2]
    mid_mask = lap_ids == mid_lap
    mid_speed = speed_ms[mid_mask]
    corners = detect_corners(mid_speed, min_speed_drop_ms=2.0)

    # Plan events across laps
    plans = plan_laps(n_laps, len(corners), rng)

    # Assign driver skill for this car
    base_skill = round(rng.uniform(0.65, 0.95), 2)

    # Global event ID counter
    eid_counter = 1

    for lap_i, lap_val in enumerate(unique_laps):
        lap_mask = lap_ids == lap_val
        idx = np.where(lap_mask)[0]
        if len(idx) < SAMPLE_HZ * 2:
            continue

        i0, i1 = idx[0], idx[-1] + 1
        plan = plans[lap_i] if lap_i < len(plans) else LapPlan("reference")

        # Set lap type label
        lap_type_arr[i0:i1] = plan.lap_type

        # Detect corners for THIS lap (positions may shift slightly)
        lap_speed = speed_ms[i0:i1]
        lap_corners = detect_corners(lap_speed, min_speed_drop_ms=2.0)

        # Label corner zones
        for c in lap_corners:
            corner_id_arr[i0 + c.entry:i0 + c.exit + 1] = c.corner_id + 1

        # Skill varies by lap type
        if plan.lap_type == "warmup":
            lap_skill = base_skill * 0.9
        elif plan.lap_type == "building":
            lap_skill = base_skill * 0.95
        elif plan.lap_type == "reference":
            lap_skill = base_skill
        elif plan.lap_type == "fatigue":
            lap_skill = base_skill * 0.85
        else:
            lap_skill = base_skill * 0.92
        skill_arr[i0:i1] = round(lap_skill, 2)

        # Apply global modifiers (warmup / fatigue)
        if plan.lap_type == "warmup":
            apply_warmup(h_thr[i0:i1], h_brk[i0:i1], h_str[i0:i1], rng, intensity=0.5)
        elif plan.lap_type == "fatigue":
            apply_fatigue(h_thr[i0:i1], h_brk[i0:i1], h_str[i0:i1], rng, intensity=0.6)

        # Add baseline human noise (very subtle for all laps, scaled by skill)
        noise_scale = 1.0 - lap_skill
        t = np.arange(i1 - i0) / SAMPLE_HZ
        for _ in range(2):
            f = rng.uniform(0.3, 1.2)
            phase = rng.uniform(0, 2 * np.pi)
            slow = np.sin(2 * np.pi * f * t + phase) * noise_scale * 0.015
            h_thr[i0:i1] += slow
            h_str[i0:i1] += slow * 0.5

        # Apply planned events at specific corners
        for etype, corner_idx, sev in plan.events:
            if corner_idx >= len(lap_corners):
                continue
            corner = lap_corners[corner_idx]

            apply_fn = _APPLY_FNS.get(etype)
            if not apply_fn:
                continue

            # Apply event to the lap-local traces (offset by i0)
            ev = apply_fn(
                h_thr[i0:i1], h_brk[i0:i1], h_str[i0:i1],
                corner, sev, rng,
            )
            ev.event_id = eid_counter
            eid_counter += 1

            # Label the affected region
            for phase_start, phase_end, phase_name in ev.phases:
                s = i0 + max(0, phase_start)
                e = i0 + min(i1 - i0, phase_end)
                event_type_arr[s:e] = etype
                event_id_arr[s:e] = ev.event_id
                event_severity_arr[s:e] = sev
                event_phase_arr[s:e] = phase_name

        # Light smoothing to blend events naturally (15-frame, ~0.25s)
        h_thr[i0:i1] = _smooth(np.clip(h_thr[i0:i1], 0, 1), 15)
        h_brk[i0:i1] = _smooth(np.clip(h_brk[i0:i1], 0, 1), 15)
        h_str[i0:i1] = _smooth(np.clip(h_str[i0:i1], -1, 1), 11)

    # Final clamp
    np.clip(h_thr, 0, 1, out=h_thr)
    np.clip(h_brk, 0, 1, out=h_brk)
    np.clip(h_str, -1, 1, out=h_str)

    return _pack_results(h_thr, h_brk, h_str, skill_arr,
                         event_type_arr, event_id_arr, event_severity_arr,
                         event_phase_arr, lap_type_arr, corner_id_arr)


def _pack_results(h_thr, h_brk, h_str, skill, etype, eid, esev, ephase, ltype, cid):
    return {
        "human_throttle": h_thr,
        "human_brake": h_brk,
        "human_steer": h_str,
        "driver_skill": skill,
        "event_type": etype,
        "event_id": eid,
        "event_severity": esev,
        "event_phase": ephase,
        "lap_type": ltype,
        "corner_id": cid,
    }
