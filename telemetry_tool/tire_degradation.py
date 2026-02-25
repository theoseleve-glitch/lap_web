"""
tire_degradation.py
-------------------
Tire degradation tracker and stint analysis for karting / motorsport
telemetry.

Analyses lap-time sequences to quantify tire wear, detect performance
cliffs, estimate optimal stint lengths, and generate coaching hints.

Unlike ``tyre_degradation.py`` (which works on g-force telemetry
channels to build grip-evolution models), this module operates
purely on **lap times** -- making it usable even when detailed sensor
data is unavailable.

Public API
~~~~~~~~~~
- ``analyze_tire_degradation(lap_times, lap_numbers, ...)``
    Full pipeline: stint splitting, per-stint metrics, coaching.
- ``detect_stint_boundaries(lap_times, threshold_factor)``
    Auto-detect new stints from sudden pace improvements.
- ``compute_optimal_stint_length(stints)``
    Estimate ideal stint length before performance drops.
- ``estimate_tire_life(degradation_rate, cliff_lap, acceptable_loss_s)``
    Predict remaining competitive laps.

Design principles
~~~~~~~~~~~~~~~~~
- Pure functions; no global mutable state.
- NaN / None robust throughout.
- Structured logging; zero print statements.
- Deterministic: identical inputs -> identical outputs.
"""

from __future__ import annotations

import logging
import math
import traceback
from typing import Any, Final, Optional

import numpy as np

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

# Factor above median delta that flags a pit-stop / tire-change boundary
DEFAULT_BOUNDARY_FACTOR: Final[float] = 1.5

# Minimum laps in a stint to compute meaningful metrics
MIN_STINT_LAPS: Final[int] = 3

# Number of tail laps to inspect for cliff detection
CLIFF_SCAN_LAPS: Final[int] = 3

# A jump in the tail exceeding this multiple of the stint std is a cliff
CLIFF_STD_FACTOR: Final[float] = 2.0

# Minimum regression R^2 to trust the degradation slope
MIN_R2_FOR_TREND: Final[float] = 0.30

# Maximum acceptable degradation rate (s/lap) for the optimal-stint estimator
MAX_REASONABLE_DEG: Final[float] = 2.0


# ============================================================================
# Internal helpers
# ============================================================================


def _clean_inputs(
    lap_times: list[float],
    lap_numbers: list[int],
) -> tuple[list[float], list[int]]:
    """
    Pair lap_times with lap_numbers, drop any entry where either
    value is None, NaN, or non-positive.

    Returns
    -------
    tuple[list[float], list[int]]
        Cleaned (times, numbers) of equal length.
    """
    clean_t: list[float] = []
    clean_n: list[int] = []
    for t, n in zip(lap_times, lap_numbers):
        if t is None or n is None:
            continue
        try:
            tf = float(t)
            ni = int(n)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(tf) or tf <= 0:
            continue
        clean_t.append(tf)
        clean_n.append(ni)
    return clean_t, clean_n


def _linear_regression(x: np.ndarray, y: np.ndarray) -> tuple[float, float, float]:
    """
    Simple OLS linear regression  y = slope * x + intercept.

    Returns
    -------
    tuple[float, float, float]
        (slope, intercept, r_squared)
    """
    n = len(x)
    if n < 2:
        return 0.0, 0.0, 0.0
    mask = np.isfinite(x) & np.isfinite(y)
    if mask.sum() < 2:
        return 0.0, 0.0, 0.0
    xm, ym = x[mask].astype(float), y[mask].astype(float)
    x_bar = float(xm.mean())
    y_bar = float(ym.mean())
    ss_xx = float(((xm - x_bar) ** 2).sum())
    ss_xy = float(((xm - x_bar) * (ym - y_bar)).sum())
    ss_yy = float(((ym - y_bar) ** 2).sum())
    if ss_xx < 1e-12:
        return 0.0, y_bar, 0.0
    slope = ss_xy / ss_xx
    intercept = y_bar - slope * x_bar
    r2 = (ss_xy ** 2) / (ss_xx * ss_yy) if ss_yy > 1e-12 else 0.0
    return float(slope), float(intercept), float(max(0.0, min(1.0, r2)))


# ============================================================================
# Stint Boundary Detection
# ============================================================================


def detect_stint_boundaries(
    lap_times: list[float],
    threshold_factor: float = DEFAULT_BOUNDARY_FACTOR,
) -> list[int]:
    """
    Auto-detect stint changes from sudden pace improvements.

    A new stint begins when a lap is significantly *faster* than the
    previous lap -- indicating fresh tires.  The threshold is
    ``threshold_factor * median(|delta|)`` where delta is the
    lap-to-lap time difference.

    Parameters
    ----------
    lap_times :
        Ordered lap times (seconds).  None / NaN entries are skipped.
    threshold_factor :
        Multiplier on the median absolute delta to define a boundary.

    Returns
    -------
    list[int]
        0-based indices into *lap_times* where new stints begin.
        The first stint always starts at index 0 (not included in the
        returned list).
    """
    # Filter out None / NaN but keep track of original indices
    valid: list[tuple[int, float]] = []
    for i, t in enumerate(lap_times):
        if t is None:
            continue
        try:
            tf = float(t)
        except (TypeError, ValueError):
            continue
        if math.isfinite(tf) and tf > 0:
            valid.append((i, tf))

    if len(valid) < 3:
        return []

    # Compute deltas between consecutive valid laps
    deltas: list[tuple[int, float]] = []
    for k in range(1, len(valid)):
        idx = valid[k][0]
        delta = valid[k][1] - valid[k - 1][1]
        deltas.append((idx, delta))

    if not deltas:
        return []

    abs_deltas = np.array([abs(d) for _, d in deltas], dtype=float)
    median_abs = float(np.median(abs_deltas))
    if median_abs < 1e-6:
        median_abs = 1e-6  # avoid zero threshold on perfectly flat data

    threshold = threshold_factor * median_abs

    boundaries: list[int] = []
    for idx, delta in deltas:
        # A large *negative* delta means the driver got much faster
        # (fresh tires).  A large *positive* delta could also indicate
        # a pit-in lap followed by a fast out-lap on the next iteration,
        # but the primary signal is the big drop.
        if delta < -threshold:
            boundaries.append(idx)

    return boundaries


# ============================================================================
# Per-Stint Analysis
# ============================================================================


def _analyze_single_stint(
    times: list[float],
    lap_nums: list[int],
    stint_index: int,
) -> dict[str, Any]:
    """
    Compute metrics for one stint.

    Returns a dict with avg_pace, pace_trend_slope, degradation_rate,
    cliff_lap, cliff_severity, best_lap, worst_lap, n_laps, etc.
    """
    n = len(times)
    arr = np.array(times, dtype=float)

    result: dict[str, Any] = {
        "stint_index": stint_index,
        "lap_numbers": list(lap_nums),
        "n_laps": n,
        "avg_pace_s": round(float(np.mean(arr)), 3),
        "median_pace_s": round(float(np.median(arr)), 3),
        "std_s": round(float(np.std(arr, ddof=1)) if n > 1 else 0.0, 3),
        "best_time_s": round(float(np.min(arr)), 3),
        "worst_time_s": round(float(np.max(arr)), 3),
        "best_lap": int(lap_nums[int(np.argmin(arr))]),
        "worst_lap": int(lap_nums[int(np.argmax(arr))]),
        "pace_trend_slope": 0.0,
        "pace_trend_r2": 0.0,
        "degradation_rate_s_per_lap": 0.0,
        "cliff_detected": False,
        "cliff_lap": None,
        "cliff_severity_s": 0.0,
    }

    if n < MIN_STINT_LAPS:
        return result

    # --- Linear regression: pace vs lap index within stint ---
    x = np.arange(n, dtype=float)
    slope, intercept, r2 = _linear_regression(x, arr)
    result["pace_trend_slope"] = round(slope, 4)
    result["pace_trend_r2"] = round(r2, 3)

    # Degradation rate: positive slope means lap times are increasing
    if slope > 0 and r2 >= MIN_R2_FOR_TREND:
        result["degradation_rate_s_per_lap"] = round(slope, 4)
    elif slope > 0:
        # Slope is positive but noisy -- report but with caution
        result["degradation_rate_s_per_lap"] = round(slope, 4)

    # --- Cliff detection ---
    # Look at the last CLIFF_SCAN_LAPS laps; if any is much slower than
    # the stint average (excluding tail), declare a cliff.
    if n > CLIFF_SCAN_LAPS + 1:
        body = arr[:-CLIFF_SCAN_LAPS]
        tail = arr[-CLIFF_SCAN_LAPS:]
        body_mean = float(np.mean(body))
        body_std = float(np.std(body, ddof=1)) if len(body) > 1 else 0.0

        if body_std < 1e-6:
            body_std = 0.1  # fallback for perfectly consistent stints

        # Find first tail lap that exceeds body_mean + CLIFF_STD_FACTOR * body_std
        cliff_threshold = body_mean + CLIFF_STD_FACTOR * body_std
        for ci, tail_time in enumerate(tail):
            if tail_time > cliff_threshold:
                cliff_idx = n - CLIFF_SCAN_LAPS + ci
                result["cliff_detected"] = True
                result["cliff_lap"] = int(lap_nums[cliff_idx])
                result["cliff_severity_s"] = round(
                    float(tail_time - body_mean), 3
                )
                break

    return result


# ============================================================================
# Optimal Stint Length
# ============================================================================


def compute_optimal_stint_length(stints: list[dict]) -> int:
    """
    Estimate the optimal stint length before performance drops.

    Uses degradation rates and cliff lap positions across stints to
    recommend a stint length that avoids the worst drop-off while
    maximising track time between stops.

    Parameters
    ----------
    stints :
        List of per-stint dicts as returned by ``_analyze_single_stint``.

    Returns
    -------
    int
        Recommended stint length (laps).  Minimum 3.
    """
    if not stints:
        return MIN_STINT_LAPS

    candidates: list[int] = []

    for s in stints:
        n_laps = s.get("n_laps", 0)
        cliff_lap = s.get("cliff_lap")
        lap_numbers = s.get("lap_numbers", [])
        deg_rate = s.get("degradation_rate_s_per_lap", 0.0)

        if n_laps < MIN_STINT_LAPS:
            continue

        # If a cliff was detected, optimal length = laps before cliff
        if cliff_lap is not None and lap_numbers:
            first_lap = lap_numbers[0]
            laps_before_cliff = cliff_lap - first_lap
            if laps_before_cliff >= MIN_STINT_LAPS:
                candidates.append(laps_before_cliff)
            continue

        # If degradation is significant, estimate where 1s cumulative
        # loss is reached: n_laps_until_1s = 1.0 / deg_rate  (roughly)
        if deg_rate > 0.01 and deg_rate <= MAX_REASONABLE_DEG:
            est = int(math.ceil(1.0 / deg_rate))
            est = max(MIN_STINT_LAPS, min(est, n_laps + 5))
            candidates.append(est)
        else:
            # Low or zero degradation -- full stint length is fine
            candidates.append(n_laps)

    if not candidates:
        return MIN_STINT_LAPS

    # Take the median of candidates (robust against outliers)
    optimal = int(round(float(np.median(candidates))))
    return max(MIN_STINT_LAPS, optimal)


# ============================================================================
# Tire Life Estimation
# ============================================================================


def estimate_tire_life(
    degradation_rate: float,
    cliff_lap: int | None = None,
    acceptable_loss_s: float = 1.0,
) -> dict[str, Any]:
    """
    Given a degradation rate, estimate remaining competitive laps.

    Parameters
    ----------
    degradation_rate :
        Pace loss per lap (seconds/lap).  Must be > 0 for a meaningful
        estimate.
    cliff_lap :
        0-based lap index at which a cliff was detected (or None).
    acceptable_loss_s :
        Maximum cumulative time loss (seconds) before recommending a
        tire change.

    Returns
    -------
    dict
        ``estimated_laps_remaining`` : int
        ``confidence`` : str  ("high" | "medium" | "low")
        ``limiting_factor`` : str
        ``details`` : str
    """
    result: dict[str, Any] = {
        "estimated_laps_remaining": 0,
        "confidence": "low",
        "limiting_factor": "unknown",
        "details": "",
    }

    if degradation_rate <= 0 or not math.isfinite(degradation_rate):
        result["estimated_laps_remaining"] = 99
        result["confidence"] = "low"
        result["limiting_factor"] = "none_detected"
        result["details"] = (
            "No measurable degradation; tire life cannot be estimated "
            "from the available data."
        )
        return result

    if acceptable_loss_s <= 0:
        acceptable_loss_s = 1.0

    # Laps until cumulative loss exceeds acceptable_loss
    # Cumulative loss after N laps ~ degradation_rate * N
    laps_from_deg = int(math.floor(acceptable_loss_s / degradation_rate))
    laps_from_deg = max(1, laps_from_deg)

    # If cliff is known, that caps the estimate
    laps_from_cliff = None
    if cliff_lap is not None and cliff_lap > 0:
        laps_from_cliff = cliff_lap

    if laps_from_cliff is not None:
        estimated = min(laps_from_deg, laps_from_cliff)
        limiting = "cliff" if laps_from_cliff <= laps_from_deg else "degradation"
    else:
        estimated = laps_from_deg
        limiting = "degradation"

    # Confidence based on how stable the estimate is
    if degradation_rate > 0.1 and estimated < 30:
        confidence = "high"
    elif degradation_rate > 0.03:
        confidence = "medium"
    else:
        confidence = "low"

    result["estimated_laps_remaining"] = estimated
    result["confidence"] = confidence
    result["limiting_factor"] = limiting
    result["details"] = (
        f"At {degradation_rate:.3f} s/lap degradation, the tire will lose "
        f">{acceptable_loss_s:.1f}s after ~{laps_from_deg} laps."
        + (
            f" Cliff detected at lap {cliff_lap}."
            if cliff_lap is not None
            else ""
        )
    )

    return result


# ============================================================================
# Main Analysis Pipeline
# ============================================================================


def analyze_tire_degradation(
    lap_times: list[float],
    lap_numbers: list[int],
    stint_boundaries: list[int] | None = None,
) -> dict[str, Any]:
    """
    Full tire degradation analysis pipeline.

    Splits laps into stints (auto-detect or manual boundaries),
    computes per-stint metrics, estimates optimal stint length,
    and generates coaching hints.

    Parameters
    ----------
    lap_times :
        Lap times in seconds.  None / NaN entries are filtered.
    lap_numbers :
        Corresponding lap numbers (same length as *lap_times*).
    stint_boundaries :
        Optional list of 0-based indices where new stints begin.
        If None, boundaries are auto-detected.

    Returns
    -------
    dict
        ``stints``   : list[dict]  -- per-stint analysis
        ``overall``  : dict        -- aggregate metrics
        ``coaching`` : list[str]   -- actionable hints
    """
    # --- Edge case: empty or mismatched inputs ---
    if not lap_times or not lap_numbers:
        return _empty_result()

    if len(lap_times) != len(lap_numbers):
        # Truncate to shorter length
        min_len = min(len(lap_times), len(lap_numbers))
        lap_times = lap_times[:min_len]
        lap_numbers = lap_numbers[:min_len]

    # --- Clean inputs ---
    clean_times, clean_nums = _clean_inputs(lap_times, lap_numbers)
    if not clean_times:
        return _empty_result()

    if len(clean_times) == 1:
        return _single_lap_result(clean_times[0], clean_nums[0])

    # --- Detect or validate stint boundaries ---
    if stint_boundaries is None:
        boundaries = detect_stint_boundaries(clean_times)
    else:
        # Validate provided boundaries
        boundaries = sorted(set(
            b for b in stint_boundaries
            if isinstance(b, int) and 0 < b < len(clean_times)
        ))

    # --- Split into stints ---
    split_points = [0] + boundaries + [len(clean_times)]
    split_points = sorted(set(split_points))

    stint_results: list[dict[str, Any]] = []
    for si in range(len(split_points) - 1):
        start = split_points[si]
        end = split_points[si + 1]
        s_times = clean_times[start:end]
        s_nums = clean_nums[start:end]
        if s_times:
            stint_results.append(_analyze_single_stint(s_times, s_nums, si))

    if not stint_results:
        return _empty_result()

    # --- Overall metrics ---
    all_deg_rates = [
        s["degradation_rate_s_per_lap"]
        for s in stint_results
        if s["degradation_rate_s_per_lap"] > 0
    ]
    mean_deg = float(np.mean(all_deg_rates)) if all_deg_rates else 0.0

    total_deg_per_stint = []
    for s in stint_results:
        rate = s["degradation_rate_s_per_lap"]
        n = s["n_laps"]
        total_deg_per_stint.append(round(rate * n, 3))

    optimal_stint = compute_optimal_stint_length(stint_results)

    # Tire life estimate (using mean degradation rate)
    any_cliff = None
    for s in stint_results:
        if s["cliff_lap"] is not None:
            # Use relative position within stint
            cliff_offset = s["cliff_lap"] - s["lap_numbers"][0]
            if any_cliff is None or cliff_offset < any_cliff:
                any_cliff = cliff_offset

    tire_life = estimate_tire_life(mean_deg, any_cliff)

    overall: dict[str, Any] = {
        "n_stints": len(stint_results),
        "total_laps": len(clean_times),
        "mean_degradation_rate_s_per_lap": round(mean_deg, 4),
        "total_degradation_per_stint": total_deg_per_stint,
        "optimal_stint_length": optimal_stint,
        "tire_life_estimate": tire_life,
    }

    # --- Coaching ---
    coaching = _generate_coaching(stint_results, overall)

    return {
        "stints": stint_results,
        "overall": overall,
        "coaching": coaching,
    }


# ============================================================================
# Coaching Generation
# ============================================================================


def _generate_coaching(
    stints: list[dict[str, Any]],
    overall: dict[str, Any],
) -> list[str]:
    """Produce actionable coaching hints from stint analysis."""
    hints: list[str] = []

    if not stints:
        return hints

    # 1. Cliff warnings
    for s in stints:
        if s.get("cliff_detected"):
            hints.append(
                f"Stint {s['stint_index'] + 1}: tire cliff detected at "
                f"lap {s['cliff_lap']} ({s['cliff_severity_s']:.1f}s drop). "
                f"Consider pitting before this point."
            )

    # 2. High degradation rate warning
    deg_rate = overall.get("mean_degradation_rate_s_per_lap", 0.0)
    if deg_rate > 0.15:
        hints.append(
            f"High degradation rate ({deg_rate:.3f} s/lap). "
            f"Focus on smoother inputs and reducing tire abuse "
            f"through slides and lock-ups."
        )
    elif deg_rate > 0.05:
        hints.append(
            f"Moderate degradation rate ({deg_rate:.3f} s/lap). "
            f"Monitor tire performance closely in the second half "
            f"of each stint."
        )

    # 3. Optimal stint length suggestion
    opt = overall.get("optimal_stint_length", 0)
    if opt > 0 and len(stints) > 0:
        longest_stint = max(s["n_laps"] for s in stints)
        if longest_stint > opt + 3:
            hints.append(
                f"Optimal stint length is ~{opt} laps, but your longest "
                f"stint was {longest_stint} laps. Consider an earlier "
                f"tire change to maintain pace."
            )

    # 4. Multi-stint comparison
    if len(stints) >= 2:
        paces = [s["avg_pace_s"] for s in stints]
        best_stint_idx = int(np.argmin(paces))
        worst_stint_idx = int(np.argmax(paces))
        gap = paces[worst_stint_idx] - paces[best_stint_idx]
        if gap > 0.5:
            hints.append(
                f"Stint {best_stint_idx + 1} was {gap:.2f}s/lap faster "
                f"on average than stint {worst_stint_idx + 1}. "
                f"Replicate the approach from stint {best_stint_idx + 1}."
            )

    # 5. Consistency comment for best stint
    if stints:
        best_cv_stint = min(stints, key=lambda s: s.get("std_s", 999.0))
        cv = best_cv_stint.get("std_s", 0.0)
        if cv < 0.3 and best_cv_stint["n_laps"] >= MIN_STINT_LAPS:
            hints.append(
                f"Stint {best_cv_stint['stint_index'] + 1} showed "
                f"excellent consistency (std={cv:.2f}s). Strong tire "
                f"management."
            )

    if not hints:
        hints.append(
            "Tire degradation is minimal across the session. "
            "Maintain current driving style."
        )

    return hints


# ============================================================================
# Result helpers
# ============================================================================


def _empty_result() -> dict[str, Any]:
    """Return a well-formed but empty analysis result."""
    return {
        "stints": [],
        "overall": {
            "n_stints": 0,
            "total_laps": 0,
            "mean_degradation_rate_s_per_lap": 0.0,
            "total_degradation_per_stint": [],
            "optimal_stint_length": MIN_STINT_LAPS,
            "tire_life_estimate": {
                "estimated_laps_remaining": 0,
                "confidence": "low",
                "limiting_factor": "insufficient_data",
                "details": "Not enough data for tire life estimation.",
            },
        },
        "coaching": ["Insufficient data for tire degradation analysis."],
    }


def _single_lap_result(time_s: float, lap_num: int) -> dict[str, Any]:
    """Result for a single-lap session."""
    stint = {
        "stint_index": 0,
        "lap_numbers": [lap_num],
        "n_laps": 1,
        "avg_pace_s": round(time_s, 3),
        "median_pace_s": round(time_s, 3),
        "std_s": 0.0,
        "best_time_s": round(time_s, 3),
        "worst_time_s": round(time_s, 3),
        "best_lap": lap_num,
        "worst_lap": lap_num,
        "pace_trend_slope": 0.0,
        "pace_trend_r2": 0.0,
        "degradation_rate_s_per_lap": 0.0,
        "cliff_detected": False,
        "cliff_lap": None,
        "cliff_severity_s": 0.0,
    }
    return {
        "stints": [stint],
        "overall": {
            "n_stints": 1,
            "total_laps": 1,
            "mean_degradation_rate_s_per_lap": 0.0,
            "total_degradation_per_stint": [0.0],
            "optimal_stint_length": MIN_STINT_LAPS,
            "tire_life_estimate": {
                "estimated_laps_remaining": 0,
                "confidence": "low",
                "limiting_factor": "insufficient_data",
                "details": "Only one lap recorded; cannot estimate degradation.",
            },
        },
        "coaching": ["Only one lap recorded. More data needed for degradation analysis."],
    }


# ============================================================================
# Self-test
# ============================================================================


def _run_tests() -> None:
    passed: list[str] = []
    failed: list[tuple[str, str]] = []

    def _test(name: str, fn) -> None:
        try:
            fn()
            passed.append(name)
        except Exception:
            failed.append((name, traceback.format_exc()))

    # ── Test 1: detect_stint_boundaries -- clear tire change ──────────

    def t_boundary_detection_basic():
        # Stint 1: gradually degrading, then a big improvement (new tires)
        times = [45.0, 45.2, 45.5, 45.8, 46.2, 46.8,
                 44.5, 44.7, 44.9, 45.1, 45.4]
        boundaries = detect_stint_boundaries(times, threshold_factor=1.5)
        assert 6 in boundaries, (
            f"Expected boundary at index 6, got {boundaries}"
        )

    _test("boundary_detection_basic", t_boundary_detection_basic)

    # ── Test 2: detect_stint_boundaries -- no change on flat data ─────

    def t_boundary_detection_flat():
        times = [45.0, 45.0, 45.0, 45.0, 45.0]
        boundaries = detect_stint_boundaries(times)
        assert boundaries == [], (
            f"Flat data should produce no boundaries, got {boundaries}"
        )

    _test("boundary_detection_flat", t_boundary_detection_flat)

    # ── Test 3: detect_stint_boundaries -- empty / tiny input ─────────

    def t_boundary_detection_edge():
        assert detect_stint_boundaries([]) == []
        assert detect_stint_boundaries([45.0]) == []
        assert detect_stint_boundaries([45.0, 46.0]) == []
        assert detect_stint_boundaries([None, None, None]) == []

    _test("boundary_detection_edge", t_boundary_detection_edge)

    # ── Test 4: analyze with manual stint boundaries ──────────────────

    def t_analyze_manual_boundaries():
        times = [45.0, 45.2, 45.4, 45.7, 46.0,
                 44.0, 44.2, 44.5, 44.8, 45.2]
        nums = list(range(1, 11))
        result = analyze_tire_degradation(times, nums, stint_boundaries=[5])
        assert len(result["stints"]) == 2
        assert result["overall"]["n_stints"] == 2
        assert result["stints"][0]["n_laps"] == 5
        assert result["stints"][1]["n_laps"] == 5

    _test("analyze_manual_boundaries", t_analyze_manual_boundaries)

    # ── Test 5: analyze with auto-detection ───────────────────────────

    def t_analyze_auto_detection():
        # Two stints with clear boundary
        times = [44.0, 44.3, 44.6, 45.0, 45.5, 46.0,
                 43.5, 43.7, 44.0, 44.3, 44.6, 45.0]
        nums = list(range(1, 13))
        result = analyze_tire_degradation(times, nums)
        assert result["overall"]["n_stints"] >= 1
        assert len(result["coaching"]) >= 1
        assert "stints" in result
        assert "overall" in result

    _test("analyze_auto_detection", t_analyze_auto_detection)

    # ── Test 6: empty / None inputs don't crash ───────────────────────

    def t_analyze_empty_inputs():
        r1 = analyze_tire_degradation([], [])
        assert r1["overall"]["n_stints"] == 0

        r2 = analyze_tire_degradation([None, None], [1, 2])
        assert r2["overall"]["n_stints"] == 0

        r3 = analyze_tire_degradation([45.0], [1])
        assert r3["overall"]["n_stints"] == 1
        assert r3["stints"][0]["n_laps"] == 1

    _test("analyze_empty_inputs", t_analyze_empty_inputs)

    # ── Test 7: degradation rate is positive for worsening times ──────

    def t_degradation_rate_positive():
        # Clear linear degradation: 0.2s per lap
        times = [45.0 + 0.2 * i for i in range(15)]
        nums = list(range(1, 16))
        result = analyze_tire_degradation(times, nums)
        stint = result["stints"][0]
        assert stint["degradation_rate_s_per_lap"] > 0.1, (
            f"Expected positive deg rate, got {stint['degradation_rate_s_per_lap']}"
        )
        assert stint["pace_trend_slope"] > 0.1

    _test("degradation_rate_positive", t_degradation_rate_positive)

    # ── Test 8: cliff detection ───────────────────────────────────────

    def t_cliff_detection():
        # Stable for 8 laps, then a big jump in the last 3
        # Use stint_boundaries=[] to force single stint so we test
        # cliff detection, not boundary detection.
        times = [45.0, 45.1, 44.9, 45.0, 45.1, 45.0, 44.9, 45.0,
                 47.0, 47.5, 48.0]
        nums = list(range(1, 12))
        result = analyze_tire_degradation(times, nums, stint_boundaries=[])
        stint = result["stints"][0]
        assert stint["cliff_detected"], "Should detect cliff"
        assert stint["cliff_lap"] is not None
        assert stint["cliff_severity_s"] > 1.0

    _test("cliff_detection", t_cliff_detection)

    # ── Test 9: compute_optimal_stint_length ──────────────────────────

    def t_optimal_stint_length():
        stints = [
            {
                "n_laps": 12,
                "degradation_rate_s_per_lap": 0.1,
                "cliff_lap": None,
                "lap_numbers": list(range(1, 13)),
            },
            {
                "n_laps": 10,
                "degradation_rate_s_per_lap": 0.12,
                "cliff_lap": None,
                "lap_numbers": list(range(13, 23)),
            },
        ]
        opt = compute_optimal_stint_length(stints)
        assert opt >= MIN_STINT_LAPS
        assert opt <= 15, f"Expected opt <= 15 for ~0.1 s/lap deg, got {opt}"

    _test("optimal_stint_length", t_optimal_stint_length)

    # ── Test 10: optimal stint length with cliff ──────────────────────

    def t_optimal_stint_with_cliff():
        stints = [
            {
                "n_laps": 15,
                "degradation_rate_s_per_lap": 0.05,
                "cliff_lap": 10,
                "lap_numbers": list(range(1, 16)),
            },
        ]
        opt = compute_optimal_stint_length(stints)
        # Should recommend pitting before lap 10
        assert opt <= 10, (
            f"With cliff at lap 10, optimal should be <=10, got {opt}"
        )

    _test("optimal_stint_with_cliff", t_optimal_stint_with_cliff)

    # ── Test 11: estimate_tire_life ───────────────────────────────────

    def t_estimate_tire_life_basic():
        life = estimate_tire_life(0.1, cliff_lap=None, acceptable_loss_s=1.0)
        assert life["estimated_laps_remaining"] == 10
        assert life["confidence"] in ("high", "medium", "low")
        assert life["limiting_factor"] == "degradation"

    _test("estimate_tire_life_basic", t_estimate_tire_life_basic)

    # ── Test 12: estimate_tire_life with cliff ────────────────────────

    def t_estimate_tire_life_cliff():
        life = estimate_tire_life(0.05, cliff_lap=8, acceptable_loss_s=2.0)
        # 2.0 / 0.05 = 40 laps from deg, but cliff at 8 caps it
        assert life["estimated_laps_remaining"] == 8
        assert life["limiting_factor"] == "cliff"

    _test("estimate_tire_life_cliff", t_estimate_tire_life_cliff)

    # ── Test 13: estimate_tire_life zero degradation ──────────────────

    def t_estimate_tire_life_zero():
        life = estimate_tire_life(0.0)
        assert life["estimated_laps_remaining"] == 99
        assert life["limiting_factor"] == "none_detected"

    _test("estimate_tire_life_zero", t_estimate_tire_life_zero)

    # ── Test 14: mismatched input lengths ─────────────────────────────

    def t_mismatched_lengths():
        # More times than numbers -- should truncate, not crash
        result = analyze_tire_degradation(
            [45.0, 45.1, 45.2, 45.3, 45.4],
            [1, 2, 3],
        )
        assert result["overall"]["total_laps"] == 3

    _test("mismatched_lengths", t_mismatched_lengths)

    # ── Test 15: NaN / None values are filtered ───────────────────────

    def t_nan_filtering():
        times = [45.0, None, 45.2, float("nan"), 45.4, 45.6, 45.8]
        nums = [1, 2, 3, 4, 5, 6, 7]
        result = analyze_tire_degradation(times, nums)
        assert result["overall"]["total_laps"] == 5  # 2 filtered out

    _test("nan_filtering", t_nan_filtering)

    # ── Test 16: coaching hints are generated ─────────────────────────

    def t_coaching_generated():
        # Strong degradation should trigger coaching
        times = [44.0 + 0.3 * i for i in range(12)]
        nums = list(range(1, 13))
        result = analyze_tire_degradation(times, nums)
        assert len(result["coaching"]) >= 1
        assert any("degradation" in c.lower() or "tire" in c.lower()
                    for c in result["coaching"])

    _test("coaching_generated", t_coaching_generated)

    # ── Test 17: deterministic results ────────────────────────────────

    def t_deterministic():
        times = [44.5 + 0.1 * i for i in range(10)]
        nums = list(range(1, 11))
        r1 = analyze_tire_degradation(times, nums)
        r2 = analyze_tire_degradation(times, nums)
        assert r1 == r2, "Results should be deterministic"

    _test("deterministic", t_deterministic)

    # ── Test 18: compute_optimal_stint_length empty ───────────────────

    def t_optimal_empty():
        assert compute_optimal_stint_length([]) == MIN_STINT_LAPS

    _test("optimal_empty", t_optimal_empty)

    # ── Summary ───────────────────────────────────────────────────────
    total = len(passed) + len(failed)
    status = "PASS" if not failed else "FAIL"
    print(f"\nTire Degradation Tests: {len(passed)}/{total} passed [{status}]")
    for name in passed:
        print(f"  OK {name}")
    for name, tb in failed:
        print(f"  FAIL {name}\n{tb}")
    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _run_tests()
