"""
speed_profile.py
----------------
Track Segment Speed Profiler — breaks laps into distance-based segments,
classifies each as braking/acceleration/cornering/straight, and benchmarks
against the driver's best lap.

Core Features
~~~~~~~~~~~~~
1. **Segment Classification**: Identify braking zones, acceleration zones,
   corners, and straights from speed data.
2. **Speed Envelope**: min/max/mean speed at each distance point across laps.
3. **Best-Lap Benchmark**: Delta to best lap at each segment.
4. **Zone Summary**: Aggregate stats per zone type (avg time lost in braking,
   avg speed on straights, etc.).
5. **Coaching**: Identify where the most time is lost vs best lap.

Public API
~~~~~~~~~~
- ``analyze_speed_profile(laps_data)``
- ``classify_segments(speed_trace)``
- ``compute_speed_envelope(all_traces)``

Design Principles
~~~~~~~~~~~~~~~~~
- Pure functions; no global mutable state.
- NaN-robust throughout.
- Structured logging; zero print statements.
- Deterministic: identical inputs → identical outputs.
"""

from __future__ import annotations

import logging
import math
import traceback
from dataclasses import dataclass, field
from typing import Any, Final

import numpy as np

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

N_SEGMENTS: Final[int] = 20  # Number of equal-distance segments
BRAKE_DECEL_THRESHOLD: Final[float] = -1.5  # m/s² threshold for braking
ACCEL_THRESHOLD: Final[float] = 1.0  # m/s² threshold for acceleration
MIN_LAPS_FOR_ENVELOPE: Final[int] = 3


# ============================================================================
# Data Structures
# ============================================================================


@dataclass
class SpeedSegment:
    """A single distance-based segment of the track."""
    segment_id: int = 0
    start_pct: float = 0.0  # 0.0 to 1.0 position
    end_pct: float = 0.0
    zone_type: str = ""  # "braking", "acceleration", "corner", "straight"
    mean_speed_mps: float = 0.0
    min_speed_mps: float = 0.0
    max_speed_mps: float = 0.0
    best_lap_speed_mps: float = 0.0
    delta_to_best_mps: float = 0.0  # mean - best (positive = slower)
    time_loss_ms: float = 0.0  # approximate time lost vs best

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "start_pct": round(self.start_pct, 3),
            "end_pct": round(self.end_pct, 3),
            "zone_type": self.zone_type,
            "mean_speed_mps": round(self.mean_speed_mps, 2),
            "min_speed_mps": round(self.min_speed_mps, 2),
            "max_speed_mps": round(self.max_speed_mps, 2),
            "best_lap_speed_mps": round(self.best_lap_speed_mps, 2),
            "delta_to_best_mps": round(self.delta_to_best_mps, 2),
            "time_loss_ms": round(self.time_loss_ms, 1),
        }


@dataclass
class ZoneSummary:
    """Aggregated stats for a zone type."""
    zone_type: str = ""
    count: int = 0
    total_time_loss_ms: float = 0.0
    avg_speed_mps: float = 0.0
    avg_delta_mps: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "zone_type": self.zone_type,
            "count": self.count,
            "total_time_loss_ms": round(self.total_time_loss_ms, 1),
            "avg_speed_mps": round(self.avg_speed_mps, 2),
            "avg_delta_mps": round(self.avg_delta_mps, 2),
        }


@dataclass
class SpeedEnvelopePoint:
    """Speed envelope at a given track position."""
    position_pct: float = 0.0
    min_speed_mps: float = 0.0
    max_speed_mps: float = 0.0
    mean_speed_mps: float = 0.0
    best_speed_mps: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "position_pct": round(self.position_pct, 3),
            "min_speed_mps": round(self.min_speed_mps, 2),
            "max_speed_mps": round(self.max_speed_mps, 2),
            "mean_speed_mps": round(self.mean_speed_mps, 2),
            "best_speed_mps": round(self.best_speed_mps, 2),
        }


@dataclass
class SpeedProfileResult:
    """Full speed profile analysis."""
    n_laps: int = 0
    n_segments: int = 0
    segments: list[SpeedSegment] = field(default_factory=list)
    envelope: list[SpeedEnvelopePoint] = field(default_factory=list)
    zone_summary: list[ZoneSummary] = field(default_factory=list)
    worst_segment_id: int = -1
    best_improvement_zone: str = ""
    coaching: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_laps": self.n_laps,
            "n_segments": self.n_segments,
            "segments": [s.to_dict() for s in self.segments],
            "envelope": [e.to_dict() for e in self.envelope],
            "zone_summary": [z.to_dict() for z in self.zone_summary],
            "worst_segment_id": self.worst_segment_id,
            "best_improvement_zone": self.best_improvement_zone,
            "coaching": self.coaching,
        }


# ============================================================================
# Core Functions
# ============================================================================


def _generate_speed_trace(lap_time_s: float, n_points: int, lap_idx: int) -> list[float]:
    """
    Generate a synthetic speed trace for a lap when no GPS data available.
    Uses deterministic variation based on lap time and index.
    """
    base_speed = 1000.0 / lap_time_s if lap_time_s > 0 else 15.0  # rough m/s
    trace = []
    for i in range(n_points):
        phase = i / n_points
        # Simulate braking/accel pattern: 3 corners per lap
        corner_effect = 0.0
        for c in range(3):
            corner_pos = (c + 1) / 4.0
            dist = abs(phase - corner_pos)
            if dist < 0.08:
                corner_effect -= base_speed * 0.3 * (1 - dist / 0.08)

        # Deterministic variation per lap
        variation = ((lap_idx * 7 + i * 3) % 17 - 8) / 100.0
        speed = base_speed + corner_effect + base_speed * variation * 0.05
        trace.append(max(3.0, speed))
    return trace


def classify_segments(speed_trace: list[float], n_segments: int = N_SEGMENTS) -> list[str]:
    """
    Classify track segments by zone type based on speed changes.

    Returns list of zone types: "braking", "acceleration", "corner", "straight"
    """
    if not speed_trace or n_segments < 1:
        return []

    n = len(speed_trace)
    seg_size = n / n_segments
    zones = []

    for s in range(n_segments):
        start = int(s * seg_size)
        end = int((s + 1) * seg_size)
        end = min(end, n)
        if start >= end:
            zones.append("straight")
            continue

        seg_speeds = speed_trace[start:end]
        if len(seg_speeds) < 2:
            zones.append("straight")
            continue

        # Compute acceleration (speed change per point)
        accels = [seg_speeds[i + 1] - seg_speeds[i] for i in range(len(seg_speeds) - 1)]
        mean_accel = sum(accels) / len(accels)
        mean_speed = sum(seg_speeds) / len(seg_speeds)
        max_speed = max(speed_trace) if speed_trace else 1.0

        if mean_accel < BRAKE_DECEL_THRESHOLD:
            zones.append("braking")
        elif mean_accel > ACCEL_THRESHOLD:
            zones.append("acceleration")
        elif mean_speed < max_speed * 0.65:
            zones.append("corner")
        else:
            zones.append("straight")

    return zones


def compute_speed_envelope(
    all_traces: list[list[float]],
    best_trace: list[float],
    n_points: int = N_SEGMENTS * 5,
) -> list[SpeedEnvelopePoint]:
    """Compute speed envelope (min/max/mean) across all laps at each position."""
    if not all_traces:
        return []

    # Resample all traces to same length
    resampled = []
    for trace in all_traces:
        if len(trace) < 2:
            continue
        indices = np.linspace(0, len(trace) - 1, n_points)
        resampled.append(np.interp(indices, range(len(trace)), trace))

    if not resampled:
        return []

    matrix = np.array(resampled)
    # Resample best trace
    if best_trace and len(best_trace) >= 2:
        best_indices = np.linspace(0, len(best_trace) - 1, n_points)
        best_resampled = np.interp(best_indices, range(len(best_trace)), best_trace)
    else:
        best_resampled = np.mean(matrix, axis=0)

    envelope = []
    for i in range(n_points):
        col = matrix[:, i]
        envelope.append(SpeedEnvelopePoint(
            position_pct=i / n_points,
            min_speed_mps=float(np.min(col)),
            max_speed_mps=float(np.max(col)),
            mean_speed_mps=float(np.mean(col)),
            best_speed_mps=float(best_resampled[i]),
        ))

    return envelope


def analyze_speed_profile(
    lap_times: list[float],
    lap_numbers: list[int] | None = None,
    speed_traces: list[list[float]] | None = None,
) -> SpeedProfileResult:
    """
    Full speed profile analysis.

    Parameters
    ----------
    lap_times:
        List of valid lap times in seconds.
    lap_numbers:
        Optional corresponding lap numbers.
    speed_traces:
        Optional list of speed traces (one per lap). If None, synthetic
        traces are generated from lap times.

    Returns
    -------
    SpeedProfileResult
    """
    result = SpeedProfileResult()

    # Filter valid
    valid = []
    if lap_numbers is None:
        lap_numbers = list(range(1, len(lap_times) + 1))

    for i, (lt, ln) in enumerate(zip(lap_times, lap_numbers)):
        if lt is not None and math.isfinite(lt) and lt > 0:
            valid.append((lt, ln, i))

    if len(valid) < 2:
        result.coaching = "Not enough valid laps for speed profile analysis."
        return result

    result.n_laps = len(valid)
    result.n_segments = N_SEGMENTS

    # Generate or use speed traces
    n_trace_pts = 100
    traces = []
    if speed_traces and len(speed_traces) == len(lap_times):
        for lt, ln, idx in valid:
            trace = speed_traces[idx]
            if trace and len(trace) >= 2:
                traces.append(trace)
            else:
                traces.append(_generate_speed_trace(lt, n_trace_pts, idx))
    else:
        for lt, ln, idx in valid:
            traces.append(_generate_speed_trace(lt, n_trace_pts, idx))

    # Find best lap trace
    best_idx = 0
    best_time = valid[0][0]
    for i, (lt, ln, idx) in enumerate(valid):
        if lt < best_time:
            best_time = lt
            best_idx = i

    best_trace = traces[best_idx]

    # Classify segments using best lap
    zones = classify_segments(best_trace, N_SEGMENTS)

    # Compute segment-level stats
    seg_size = len(best_trace) / N_SEGMENTS
    segments = []
    for s in range(N_SEGMENTS):
        start_pt = int(s * seg_size)
        end_pt = int((s + 1) * seg_size)

        # Collect speeds across all laps for this segment
        all_speeds = []
        for trace in traces:
            t_seg_size = len(trace) / N_SEGMENTS
            t_start = int(s * t_seg_size)
            t_end = int((s + 1) * t_seg_size)
            seg_vals = trace[t_start:t_end]
            if seg_vals:
                all_speeds.append(sum(seg_vals) / len(seg_vals))

        # Best lap speed for this segment
        best_seg_vals = best_trace[start_pt:end_pt]
        best_seg_speed = sum(best_seg_vals) / len(best_seg_vals) if best_seg_vals else 0

        mean_speed = sum(all_speeds) / len(all_speeds) if all_speeds else 0
        delta = mean_speed - best_seg_speed

        # Approximate time loss (delta speed over segment distance)
        # segment_distance ≈ best_seg_speed * (lap_time / n_segments)
        seg_time_best = best_time / N_SEGMENTS
        if best_seg_speed > 0 and mean_speed > 0:
            seg_time_mean = seg_time_best * best_seg_speed / mean_speed
            time_loss_ms = (seg_time_mean - seg_time_best) * 1000
        else:
            time_loss_ms = 0

        seg = SpeedSegment(
            segment_id=s,
            start_pct=s / N_SEGMENTS,
            end_pct=(s + 1) / N_SEGMENTS,
            zone_type=zones[s] if s < len(zones) else "straight",
            mean_speed_mps=mean_speed,
            min_speed_mps=min(all_speeds) if all_speeds else 0,
            max_speed_mps=max(all_speeds) if all_speeds else 0,
            best_lap_speed_mps=best_seg_speed,
            delta_to_best_mps=delta,
            time_loss_ms=max(0, time_loss_ms),
        )
        segments.append(seg)

    result.segments = segments

    # Speed envelope
    result.envelope = compute_speed_envelope(traces, best_trace)

    # Zone summary
    zone_types = set(z.zone_type for z in segments)
    zone_summaries = []
    for zt in sorted(zone_types):
        zone_segs = [s for s in segments if s.zone_type == zt]
        zs = ZoneSummary(
            zone_type=zt,
            count=len(zone_segs),
            total_time_loss_ms=sum(s.time_loss_ms for s in zone_segs),
            avg_speed_mps=sum(s.mean_speed_mps for s in zone_segs) / len(zone_segs) if zone_segs else 0,
            avg_delta_mps=sum(s.delta_to_best_mps for s in zone_segs) / len(zone_segs) if zone_segs else 0,
        )
        zone_summaries.append(zs)
    result.zone_summary = zone_summaries

    # Worst segment
    worst = max(segments, key=lambda s: s.time_loss_ms)
    result.worst_segment_id = worst.segment_id

    # Best improvement zone
    if zone_summaries:
        best_zone = max(zone_summaries, key=lambda z: z.total_time_loss_ms)
        result.best_improvement_zone = best_zone.zone_type

    # Coaching
    result.coaching = _generate_coaching(result, worst)

    logger.info(
        "Speed profile: %d laps, %d segments, worst_segment=%d (%s), best_improvement=%s",
        result.n_laps, result.n_segments, worst.segment_id, worst.zone_type,
        result.best_improvement_zone,
    )

    return result


def _generate_coaching(result: SpeedProfileResult, worst: SpeedSegment) -> str:
    """Generate coaching insight from speed profile."""
    parts = []

    if worst.time_loss_ms > 0:
        parts.append(
            f"Segment {worst.segment_id + 1} ({worst.zone_type}) shows the most time loss "
            f"({worst.time_loss_ms:.0f}ms vs best lap)."
        )

    if result.best_improvement_zone:
        zone_data = next(
            (z for z in result.zone_summary if z.zone_type == result.best_improvement_zone),
            None,
        )
        if zone_data and zone_data.total_time_loss_ms > 0:
            parts.append(
                f"Biggest improvement area: {result.best_improvement_zone} zones "
                f"(total {zone_data.total_time_loss_ms:.0f}ms lost across {zone_data.count} segments)."
            )

    # Specific zone advice
    for z in result.zone_summary:
        if z.zone_type == "braking" and z.total_time_loss_ms > 50:
            parts.append("Focus on brake consistency — later braking with more confidence could unlock pace.")
        elif z.zone_type == "acceleration" and z.total_time_loss_ms > 50:
            parts.append("Throttle application zones show losses — work on earlier, smoother throttle.")
        elif z.zone_type == "corner" and z.total_time_loss_ms > 50:
            parts.append("Cornering speed is below best — try carrying more speed through apexes.")

    if not parts:
        parts.append("Speed profile is close to the best lap across all segments — very consistent driving.")

    return " ".join(parts)


# ============================================================================
# Self-Tests
# ============================================================================


def _run_tests() -> None:
    """Verify all functions with synthetic data."""
    import sys

    passed = 0
    failed = 0
    total = 12

    def _ok(name: str):
        nonlocal passed
        passed += 1
        print(f"  OK {name}")

    def _fail(name: str, msg: str):
        nonlocal failed
        failed += 1
        print(f"  FAIL {name}: {msg}")

    # 1. Classify segments basic
    try:
        # Constant speed → all straights
        trace = [20.0] * 100
        zones = classify_segments(trace, 5)
        assert len(zones) == 5
        assert all(z == "straight" for z in zones)
        _ok("classify_constant")
    except Exception as e:
        _fail("classify_constant", str(e))

    # 2. Classify with braking
    try:
        # Speed drops sharply in middle
        trace = [20.0] * 30 + [20.0 - i * 2.0 for i in range(15)] + [5.0] * 10 + [5.0 + i * 2.0 for i in range(15)] + [20.0] * 30
        zones = classify_segments(trace, 10)
        assert "braking" in zones or "corner" in zones, f"zones={zones}"
        _ok("classify_braking")
    except Exception as e:
        _fail("classify_braking", str(e))

    # 3. Speed envelope
    try:
        traces = [
            [10.0, 15.0, 20.0, 15.0, 10.0],
            [12.0, 17.0, 22.0, 17.0, 12.0],
            [11.0, 16.0, 21.0, 16.0, 11.0],
        ]
        env = compute_speed_envelope(traces, traces[1], n_points=5)
        assert len(env) == 5
        assert env[0].min_speed_mps <= env[0].mean_speed_mps <= env[0].max_speed_mps
        _ok("speed_envelope")
    except Exception as e:
        _fail("speed_envelope", str(e))

    # 4. Envelope empty
    try:
        env = compute_speed_envelope([], [])
        assert env == []
        _ok("envelope_empty")
    except Exception as e:
        _fail("envelope_empty", str(e))

    # 5. Full analysis basic
    try:
        times = [60.0 + i * 0.2 for i in range(10)]
        r = analyze_speed_profile(times)
        assert r.n_laps == 10
        assert r.n_segments == N_SEGMENTS
        assert len(r.segments) == N_SEGMENTS
        assert len(r.zone_summary) > 0
        assert r.coaching != ""
        _ok("full_analysis")
    except Exception as e:
        _fail("full_analysis", str(e))

    # 6. Single lap
    try:
        r = analyze_speed_profile([60.0])
        assert r.n_laps == 0
        assert "Not enough" in r.coaching
        _ok("single_lap")
    except Exception as e:
        _fail("single_lap", str(e))

    # 7. NaN robustness
    try:
        times = [60.0, float("nan"), 61.0, None, 60.5]
        nums = [1, 2, 3, 4, 5]
        r = analyze_speed_profile(times, nums)
        assert r.n_laps == 3
        _ok("nan_robustness")
    except Exception as e:
        _fail("nan_robustness", str(e))

    # 8. Worst segment identified
    try:
        times = [60.0, 60.5, 61.0, 60.2, 60.8, 59.5, 60.3]
        r = analyze_speed_profile(times)
        assert r.worst_segment_id >= 0
        assert r.worst_segment_id < N_SEGMENTS
        _ok("worst_segment")
    except Exception as e:
        _fail("worst_segment", str(e))

    # 9. Zone summary populated
    try:
        times = [60.0 + i * 0.1 for i in range(15)]
        r = analyze_speed_profile(times)
        assert len(r.zone_summary) > 0
        for z in r.zone_summary:
            assert z.zone_type in ("braking", "acceleration", "corner", "straight"), z.zone_type
            assert z.count > 0
        _ok("zone_summary")
    except Exception as e:
        _fail("zone_summary", str(e))

    # 10. Serialization
    try:
        times = [60.0, 60.5, 61.0, 60.2, 60.8]
        r = analyze_speed_profile(times)
        d = r.to_dict()
        import json
        json.dumps(d)
        assert "segments" in d
        assert "envelope" in d
        assert "zone_summary" in d
        _ok("serialization")
    except Exception as e:
        _fail("serialization", str(e))

    # 11. Deterministic
    try:
        times = [60.0, 60.5, 61.0, 60.2]
        r1 = analyze_speed_profile(times)
        r2 = analyze_speed_profile(times)
        assert r1.to_dict() == r2.to_dict()
        _ok("deterministic")
    except Exception as e:
        _fail("deterministic", str(e))

    # 12. With speed traces
    try:
        times = [60.0, 61.0, 60.5]
        traces = [
            [10.0, 15.0, 20.0, 15.0, 10.0],
            [9.0, 14.0, 19.0, 14.0, 9.0],
            [11.0, 16.0, 21.0, 16.0, 11.0],
        ]
        r = analyze_speed_profile(times, speed_traces=traces)
        assert r.n_laps == 3
        assert len(r.segments) == N_SEGMENTS
        _ok("with_traces")
    except Exception as e:
        _fail("with_traces", str(e))

    print(f"\nSpeed Profile Tests: {passed}/{total} passed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _run_tests()
