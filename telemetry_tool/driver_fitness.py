"""
driver_fitness.py
-----------------
Driver fitness and endurance metrics for motorsport telemetry analysis.

Analyses session lap-time data to assess physical performance, mental
fatigue, and concentration quality over a session.  Unlike
``fatigue_detection.py`` (which uses telemetry channels such as braking
scatter and jerk), this module works exclusively from *lap times* and
*lap numbers*, making it usable even when high-frequency channel data
is unavailable.

Public API
~~~~~~~~~~
- ``analyze_session_endurance(lap_times, lap_numbers)``
- ``compute_concentration_index(lap_times, window)``
- ``compute_reaction_metrics(lap_times)``
- ``generate_fitness_report(lap_times, lap_numbers, driver_name)``

Design principles
~~~~~~~~~~~~~~~~~
- Pure functions; no global mutable state.
- NaN-robust throughout.
- Structured logging; zero print statements.
- Deterministic: identical inputs -> identical outputs.
- Returns plain dicts (JSON-serialisable).
- All thresholds are module-level ``Final`` constants.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Final

import numpy as np

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

# Minimum laps required for meaningful analysis
MIN_LAPS_ENDURANCE: Final[int] = 4
MIN_LAPS_CONCENTRATION: Final[int] = 6
MIN_LAPS_REACTION: Final[int] = 5

# Fatigue onset: lap whose rolling average exceeds Q1 mean by this fraction
FATIGUE_ONSET_THRESHOLD_PCT: Final[float] = 2.0

# Rolling window for fatigue-onset detection
FATIGUE_ROLLING_WINDOW: Final[int] = 3

# Endurance scoring weights
_W_PACE_FADE: Final[float] = 0.40
_W_CONSISTENCY_FADE: Final[float] = 0.35
_W_FATIGUE_ONSET: Final[float] = 0.25

# Concentration scoring: CV% above this is a "drop"
CONCENTRATION_DROP_CV_PCT: Final[float] = 3.0

# Reaction: a "bad lap" exceeds mean + this many standard deviations
BAD_LAP_SIGMA: Final[float] = 1.0

# Maximum recovery laps before we consider recovery failed
MAX_RECOVERY_LAPS: Final[int] = 10

# Fitness report weights
_W_ENDURANCE: Final[float] = 0.40
_W_CONCENTRATION: Final[float] = 0.35
_W_REACTION: Final[float] = 0.25


# ============================================================================
# Internal Helpers
# ============================================================================


def _r(v: float, places: int = 2) -> float:
    """Safe round that handles NaN / Inf."""
    if isinstance(v, (int, float)) and math.isfinite(v):
        return round(v, places)
    return float("nan")


def _safe_float(v: Any) -> float:
    """Convert value to float, returning NaN for None / invalid."""
    if v is None:
        return float("nan")
    try:
        f = float(v)
        return f
    except (TypeError, ValueError):
        return float("nan")


def _clean_inputs(
    lap_times: list[float],
    lap_numbers: list[int] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Filter out None / NaN / non-finite values and return matched arrays.

    Returns (times, numbers) -- both 1-D numpy arrays of equal length.
    If *lap_numbers* is None, synthetic 1-based indices are generated.
    """
    if lap_times is None:
        lap_times = []
    if lap_numbers is None:
        lap_numbers = list(range(1, len(lap_times) + 1))

    # Ensure both lists are the same length (truncate to shorter)
    n = min(len(lap_times), len(lap_numbers))
    times_raw = [_safe_float(lap_times[i]) for i in range(n)]
    nums_raw = lap_numbers[:n]

    # Keep only entries where time is finite and positive
    mask = [math.isfinite(t) and t > 0 for t in times_raw]
    times = np.array([t for t, m in zip(times_raw, mask) if m], dtype=float)
    nums = np.array([n for n, m in zip(nums_raw, mask) if m], dtype=int)

    return times, nums


def _cv_pct(arr: np.ndarray) -> float:
    """Coefficient of variation in percent.  Returns NaN for degenerate cases."""
    if len(arr) < 2:
        return float("nan")
    m = float(np.mean(arr))
    if abs(m) < 1e-12:
        return float("nan")
    return float(np.std(arr, ddof=1) / m * 100.0)


def _split_quarters(times: np.ndarray, nums: np.ndarray) -> list[dict]:
    """
    Split arrays into four roughly equal quarters and compute stats.

    Each quarter dict:
        start_lap, end_lap, n_laps, mean_pace, cv_pct
    """
    n = len(times)
    if n < 4:
        return []

    indices = np.array_split(np.arange(n), 4)

    quarters = []
    for q_idx, idx_arr in enumerate(indices, start=1):
        if len(idx_arr) == 0:
            continue
        q_times = times[idx_arr]
        q_nums = nums[idx_arr]
        quarters.append({
            "quarter": q_idx,
            "start_lap": int(q_nums[0]),
            "end_lap": int(q_nums[-1]),
            "n_laps": len(idx_arr),
            "mean_pace": _r(float(np.mean(q_times)), 3),
            "cv_pct": _r(_cv_pct(q_times)),
        })

    return quarters


def _empty_endurance_result() -> dict:
    """Return a valid but empty endurance result dict."""
    return {
        "quarters": [],
        "endurance_score": float("nan"),
        "fatigue_onset_lap": None,
        "pace_fade_pct": float("nan"),
        "consistency_fade_pct": float("nan"),
        "coaching": ["Insufficient data for endurance analysis."],
    }


def _empty_concentration_result() -> dict:
    """Return a valid but empty concentration result dict."""
    return {
        "rolling_cv": [],
        "concentration_score": float("nan"),
        "drop_laps": [],
        "coaching": ["Insufficient data for concentration analysis."],
    }


def _empty_reaction_result() -> dict:
    """Return a valid but empty reaction result dict."""
    return {
        "avg_recovery_laps": float("nan"),
        "recovery_rate_pct": float("nan"),
        "reaction_score": float("nan"),
        "bad_lap_count": 0,
        "recoveries": [],
        "coaching": ["Insufficient data for reaction analysis."],
    }


# ============================================================================
# 1. Session Endurance Analysis
# ============================================================================


def analyze_session_endurance(
    lap_times: list[float],
    lap_numbers: list[int],
) -> dict:
    """
    Assess driver endurance across a session by splitting it into quarters.

    Computes pace fade (Q4 vs Q1 delta), consistency degradation, fatigue
    onset detection, and a composite endurance score (0--100).

    Parameters
    ----------
    lap_times:
        Ordered list of lap times (seconds).
    lap_numbers:
        Corresponding lap numbers.

    Returns
    -------
    dict with keys:
        quarters, endurance_score, fatigue_onset_lap, pace_fade_pct,
        consistency_fade_pct, coaching.
    """
    try:
        times, nums = _clean_inputs(lap_times, lap_numbers)

        if len(times) < MIN_LAPS_ENDURANCE:
            logger.info(
                "Endurance analysis skipped: %d laps < minimum %d",
                len(times), MIN_LAPS_ENDURANCE,
            )
            return _empty_endurance_result()

        # -- Quarter split --------------------------------------------------
        quarters = _split_quarters(times, nums)

        if len(quarters) < 2:
            return _empty_endurance_result()

        q1_pace = quarters[0]["mean_pace"]
        q4_pace = quarters[-1]["mean_pace"]
        q1_cv = quarters[0]["cv_pct"]
        q4_cv = quarters[-1]["cv_pct"]

        # -- Pace fade (positive = got slower) ------------------------------
        if q1_pace > 0 and math.isfinite(q1_pace):
            pace_fade_pct = (q4_pace - q1_pace) / q1_pace * 100.0
        else:
            pace_fade_pct = 0.0

        # -- Consistency fade (positive = less consistent) ------------------
        if math.isfinite(q1_cv) and math.isfinite(q4_cv):
            consistency_fade_pct = q4_cv - q1_cv
        else:
            consistency_fade_pct = 0.0

        # -- Fatigue onset detection ----------------------------------------
        fatigue_onset_lap = _detect_fatigue_onset(times, nums, q1_pace)

        # -- Endurance score ------------------------------------------------
        #   100 = perfect (no fade, no consistency loss, no early fatigue)
        #   Penalties applied for each dimension.

        # Pace fade penalty: 0-40 points lost for 0-5% fade
        pace_penalty = min(40.0, max(0.0, pace_fade_pct) * 8.0)

        # Consistency penalty: 0-35 points lost for 0-5% CV increase
        cons_penalty = min(35.0, max(0.0, consistency_fade_pct) * 7.0)

        # Fatigue onset penalty: lose up to 25 points if fatigue onset
        # is in the first half of the session
        if fatigue_onset_lap is not None:
            n_total = len(times)
            # Find positional index of fatigue onset
            onset_idx = int(np.searchsorted(nums, fatigue_onset_lap))
            onset_frac = onset_idx / n_total if n_total > 0 else 1.0
            # Earlier onset = bigger penalty
            fatigue_penalty = max(0.0, (1.0 - onset_frac) * 25.0)
        else:
            fatigue_penalty = 0.0

        endurance_score = max(0.0, min(100.0,
            100.0 - pace_penalty - cons_penalty - fatigue_penalty
        ))

        # -- Coaching -------------------------------------------------------
        coaching = _endurance_coaching(
            pace_fade_pct, consistency_fade_pct, fatigue_onset_lap, endurance_score
        )

        return {
            "quarters": quarters,
            "endurance_score": _r(endurance_score, 1),
            "fatigue_onset_lap": fatigue_onset_lap,
            "pace_fade_pct": _r(pace_fade_pct),
            "consistency_fade_pct": _r(consistency_fade_pct),
            "coaching": coaching,
        }

    except Exception:
        logger.error("analyze_session_endurance failed:\n%s",
                      __import__("traceback").format_exc())
        return _empty_endurance_result()


def _detect_fatigue_onset(
    times: np.ndarray,
    nums: np.ndarray,
    q1_mean: float,
) -> int | None:
    """
    Find the first lap where the rolling average pace exceeds the Q1
    mean by more than FATIGUE_ONSET_THRESHOLD_PCT percent.

    Returns the lap number, or None if no onset detected.
    """
    if len(times) < FATIGUE_ROLLING_WINDOW + 2:
        return None
    if not (math.isfinite(q1_mean) and q1_mean > 0):
        return None

    threshold = q1_mean * (1.0 + FATIGUE_ONSET_THRESHOLD_PCT / 100.0)

    for i in range(FATIGUE_ROLLING_WINDOW, len(times)):
        window_mean = float(np.mean(times[i - FATIGUE_ROLLING_WINDOW + 1: i + 1]))
        if window_mean > threshold:
            return int(nums[i])

    return None


def _endurance_coaching(
    pace_fade_pct: float,
    consistency_fade_pct: float,
    fatigue_onset_lap: int | None,
    score: float,
) -> list[str]:
    """Generate coaching advice based on endurance metrics."""
    tips: list[str] = []

    if score >= 90:
        tips.append("Excellent endurance -- pace and consistency held throughout.")
    elif score >= 75:
        tips.append("Good endurance -- minor degradation in the final quarter.")
    elif score >= 55:
        tips.append("Moderate endurance -- noticeable fade; focus on physical conditioning.")
    else:
        tips.append("Poor endurance -- significant fade; prioritise fitness and hydration.")

    if pace_fade_pct > 3.0:
        tips.append(
            f"Pace faded {pace_fade_pct:.1f}% from Q1 to Q4. "
            "Consider improving cardiovascular fitness or in-car hydration."
        )
    elif pace_fade_pct > 1.0:
        tips.append(
            f"Mild pace fade ({pace_fade_pct:.1f}%). "
            "Maintaining focus in the last stint will help close this gap."
        )

    if consistency_fade_pct > 2.0:
        tips.append(
            f"Consistency degraded by {consistency_fade_pct:.1f}% CV. "
            "Work on mental routines to maintain focus late in sessions."
        )

    if fatigue_onset_lap is not None:
        tips.append(
            f"Fatigue onset detected at lap {fatigue_onset_lap}. "
            "Build stamina to push this further into the session."
        )

    return tips


# ============================================================================
# 2. Concentration Index
# ============================================================================


def compute_concentration_index(
    lap_times: list[float],
    window: int = 5,
) -> dict:
    """
    Rolling-window CV% analysis to assess concentration quality.

    A spike in rolling CV% indicates a momentary loss of concentration
    (inconsistent pace within a short window).

    Parameters
    ----------
    lap_times:
        Ordered list of lap times (seconds).
    window:
        Rolling window size for CV% computation.

    Returns
    -------
    dict with keys:
        rolling_cv, concentration_score, drop_laps, coaching.
    """
    try:
        times, nums = _clean_inputs(lap_times)

        if len(times) < max(MIN_LAPS_CONCENTRATION, window + 1):
            logger.info(
                "Concentration analysis skipped: %d laps < minimum %d",
                len(times), max(MIN_LAPS_CONCENTRATION, window + 1),
            )
            return _empty_concentration_result()

        # -- Rolling CV% ---------------------------------------------------
        rolling_cv: list[float] = []
        for i in range(window - 1, len(times)):
            seg = times[i - window + 1: i + 1]
            rolling_cv.append(_cv_pct(seg))

        rolling_cv_arr = np.array(rolling_cv, dtype=float)
        valid_cv = rolling_cv_arr[np.isfinite(rolling_cv_arr)]

        if len(valid_cv) < 2:
            return _empty_concentration_result()

        # -- Detect drops (CV% spikes) -------------------------------------
        cv_mean = float(np.mean(valid_cv))
        cv_std = float(np.std(valid_cv, ddof=1))

        drop_threshold = max(CONCENTRATION_DROP_CV_PCT, cv_mean + 1.5 * cv_std)

        drop_laps: list[int] = []
        for i, cv_val in enumerate(rolling_cv):
            if math.isfinite(cv_val) and cv_val > drop_threshold:
                # Map rolling window index back to lap number
                lap_idx = i + window - 1
                if lap_idx < len(nums):
                    drop_laps.append(int(nums[lap_idx]))

        # -- Concentration score (0-100) -----------------------------------
        # Lower average CV% = better concentration
        # Fewer drops = better concentration
        if cv_mean < 1e-12:
            cv_component = 100.0
        else:
            # Map CV% [0, 5] -> score [100, 0]
            cv_component = max(0.0, min(100.0, 100.0 - cv_mean * 20.0))

        # Penalty for drops: each drop costs up to 5 points
        n_windows = len(rolling_cv)
        drop_frac = len(drop_laps) / n_windows if n_windows > 0 else 0.0
        drop_penalty = min(40.0, drop_frac * 200.0)

        concentration_score = max(0.0, min(100.0, cv_component - drop_penalty))

        # -- Coaching -------------------------------------------------------
        coaching = _concentration_coaching(
            concentration_score, len(drop_laps), cv_mean
        )

        return {
            "rolling_cv": [_r(v, 3) for v in rolling_cv],
            "concentration_score": _r(concentration_score, 1),
            "drop_laps": drop_laps,
            "mean_rolling_cv_pct": _r(cv_mean, 3),
            "coaching": coaching,
        }

    except Exception:
        logger.error("compute_concentration_index failed:\n%s",
                      __import__("traceback").format_exc())
        return _empty_concentration_result()


def _concentration_coaching(
    score: float,
    n_drops: int,
    mean_cv: float,
) -> list[str]:
    """Generate coaching advice for concentration."""
    tips: list[str] = []

    if score >= 90:
        tips.append("Outstanding concentration -- very consistent pace throughout.")
    elif score >= 75:
        tips.append("Good concentration with minor lapses.")
    elif score >= 55:
        tips.append("Moderate concentration -- inconsistencies appearing mid-session.")
    else:
        tips.append("Concentration needs work -- frequent pace inconsistencies detected.")

    if n_drops > 0:
        tips.append(
            f"{n_drops} concentration drop(s) detected. "
            "Practice mental reset routines between laps."
        )

    if mean_cv > 3.0:
        tips.append(
            f"Average rolling CV is {mean_cv:.2f}% -- aim for below 2% "
            "for elite-level consistency."
        )

    return tips


# ============================================================================
# 3. Reaction / Recovery Metrics
# ============================================================================


def compute_reaction_metrics(lap_times: list[float]) -> dict:
    """
    Analyse how quickly the driver recovers after a bad lap.

    A "bad lap" is one exceeding mean + 1 sigma.  Recovery is measured as
    the number of laps until the driver returns to (or below) the mean.

    Parameters
    ----------
    lap_times:
        Ordered list of lap times (seconds).

    Returns
    -------
    dict with keys:
        avg_recovery_laps, recovery_rate_pct, reaction_score,
        bad_lap_count, recoveries, coaching.
    """
    try:
        times, nums = _clean_inputs(lap_times)

        if len(times) < MIN_LAPS_REACTION:
            logger.info(
                "Reaction analysis skipped: %d laps < minimum %d",
                len(times), MIN_LAPS_REACTION,
            )
            return _empty_reaction_result()

        mean_time = float(np.mean(times))
        std_time = float(np.std(times, ddof=1))

        if std_time < 1e-12 or not math.isfinite(std_time):
            # Perfectly consistent -- no bad laps to recover from
            return {
                "avg_recovery_laps": 0.0,
                "recovery_rate_pct": 100.0,
                "reaction_score": 100.0,
                "bad_lap_count": 0,
                "recoveries": [],
                "coaching": ["No pace outliers detected -- excellent consistency."],
            }

        bad_threshold = mean_time + BAD_LAP_SIGMA * std_time

        # -- Find bad laps and measure recovery ----------------------------
        recoveries: list[dict] = []
        i = 0
        while i < len(times):
            if times[i] > bad_threshold:
                bad_lap_num = int(nums[i])
                bad_time = float(times[i])
                # Count laps until recovery (back to mean or better)
                recovery_laps = 0
                recovered = False
                for j in range(i + 1, min(i + 1 + MAX_RECOVERY_LAPS, len(times))):
                    recovery_laps += 1
                    if times[j] <= mean_time:
                        recovered = True
                        break

                recoveries.append({
                    "bad_lap": bad_lap_num,
                    "bad_time": _r(bad_time, 3),
                    "recovery_laps": recovery_laps,
                    "recovered": recovered,
                })
                # Skip past the recovery period to avoid double-counting
                i = i + 1 + recovery_laps
            else:
                i += 1

        bad_lap_count = len(recoveries)

        if bad_lap_count == 0:
            return {
                "avg_recovery_laps": 0.0,
                "recovery_rate_pct": 100.0,
                "reaction_score": 100.0,
                "bad_lap_count": 0,
                "recoveries": [],
                "coaching": ["No significant pace drops -- strong mental composure."],
            }

        # -- Aggregate recovery stats --------------------------------------
        recovery_lap_counts = [r["recovery_laps"] for r in recoveries]
        recovered_count = sum(1 for r in recoveries if r["recovered"])

        avg_recovery = float(np.mean(recovery_lap_counts))
        recovery_rate_pct = (recovered_count / bad_lap_count) * 100.0

        # -- Reaction score ------------------------------------------------
        # Fast recovery (1 lap) = high score; slow or failed recovery = low score
        # Component 1: average recovery speed (1 lap = 100, MAX_RECOVERY = 0)
        speed_score = max(0.0, 100.0 * (1.0 - (avg_recovery - 1.0) / (MAX_RECOVERY_LAPS - 1.0)))

        # Component 2: recovery success rate
        rate_score = recovery_rate_pct

        # Component 3: frequency of bad laps (fewer = better)
        bad_frac = bad_lap_count / len(times)
        freq_score = max(0.0, 100.0 * (1.0 - bad_frac * 5.0))

        reaction_score = max(0.0, min(100.0,
            speed_score * 0.45 + rate_score * 0.35 + freq_score * 0.20
        ))

        # -- Coaching -------------------------------------------------------
        coaching = _reaction_coaching(avg_recovery, recovery_rate_pct, reaction_score)

        return {
            "avg_recovery_laps": _r(avg_recovery, 1),
            "recovery_rate_pct": _r(recovery_rate_pct, 1),
            "reaction_score": _r(reaction_score, 1),
            "bad_lap_count": bad_lap_count,
            "recoveries": recoveries,
            "coaching": coaching,
        }

    except Exception:
        logger.error("compute_reaction_metrics failed:\n%s",
                      __import__("traceback").format_exc())
        return _empty_reaction_result()


def _reaction_coaching(
    avg_recovery: float,
    recovery_rate: float,
    score: float,
) -> list[str]:
    """Generate coaching advice for reaction / recovery."""
    tips: list[str] = []

    if score >= 90:
        tips.append("Excellent recovery ability -- bounces back quickly after bad laps.")
    elif score >= 70:
        tips.append("Good recovery, but could improve response after mistakes.")
    elif score >= 50:
        tips.append("Recovery is slow -- bad laps tend to cascade into multiple slow laps.")
    else:
        tips.append("Poor recovery -- struggles to reset after pace drops. Mental resilience training recommended.")

    if avg_recovery > 3.0:
        tips.append(
            f"Average recovery takes {avg_recovery:.1f} laps. "
            "Practice mental reset: deep breath, refocus on next braking zone."
        )

    if recovery_rate < 80.0:
        tips.append(
            f"Only {recovery_rate:.0f}% of pace drops were fully recovered. "
            "Focus on returning to rhythm quickly after errors."
        )

    return tips


# ============================================================================
# 4. Comprehensive Fitness Report
# ============================================================================


def generate_fitness_report(
    lap_times: list[float],
    lap_numbers: list[int],
    driver_name: str = "",
) -> dict:
    """
    Aggregate all fitness metrics into a comprehensive report.

    Combines endurance, concentration, and reaction analyses into
    a single weighted fitness score with targeted coaching.

    Parameters
    ----------
    lap_times:
        Ordered list of lap times (seconds).
    lap_numbers:
        Corresponding lap numbers.
    driver_name:
        Optional driver name for the report header.

    Returns
    -------
    dict with keys:
        driver_name, n_laps, overall_fitness_score,
        endurance, concentration, reaction,
        primary_weakness, coaching_summary.
    """
    try:
        times, nums = _clean_inputs(lap_times, lap_numbers)
        n_laps = len(times)

        # -- Sub-analyses ---------------------------------------------------
        endurance = analyze_session_endurance(lap_times, lap_numbers)
        concentration = compute_concentration_index(lap_times)
        reaction = compute_reaction_metrics(lap_times)

        # -- Overall fitness score (weighted) -------------------------------
        scores = {
            "endurance": endurance.get("endurance_score", float("nan")),
            "concentration": concentration.get("concentration_score", float("nan")),
            "reaction": reaction.get("reaction_score", float("nan")),
        }

        weights = {
            "endurance": _W_ENDURANCE,
            "concentration": _W_CONCENTRATION,
            "reaction": _W_REACTION,
        }

        # Only include finite scores in weighted average
        total_w = 0.0
        weighted_sum = 0.0
        for key in scores:
            s = scores[key]
            if isinstance(s, (int, float)) and math.isfinite(s):
                w = weights[key]
                weighted_sum += s * w
                total_w += w

        if total_w > 0:
            overall = weighted_sum / total_w
        else:
            overall = float("nan")

        # -- Primary weakness -----------------------------------------------
        primary_weakness = _identify_weakness(scores)

        # -- Coaching summary -----------------------------------------------
        coaching_summary = _build_coaching_summary(
            scores, primary_weakness, overall, n_laps
        )

        return {
            "driver_name": driver_name or "Unknown",
            "n_laps": n_laps,
            "overall_fitness_score": _r(overall, 1),
            "endurance": endurance,
            "concentration": concentration,
            "reaction": reaction,
            "component_scores": {k: _r(v, 1) for k, v in scores.items()},
            "primary_weakness": primary_weakness,
            "coaching_summary": coaching_summary,
        }

    except Exception:
        logger.error("generate_fitness_report failed:\n%s",
                      __import__("traceback").format_exc())
        return {
            "driver_name": driver_name or "Unknown",
            "n_laps": 0,
            "overall_fitness_score": float("nan"),
            "endurance": _empty_endurance_result(),
            "concentration": _empty_concentration_result(),
            "reaction": _empty_reaction_result(),
            "component_scores": {},
            "primary_weakness": None,
            "coaching_summary": ["Analysis failed due to an internal error."],
        }


def _identify_weakness(scores: dict[str, float]) -> str | None:
    """Return the key of the lowest finite score, or None."""
    finite = {k: v for k, v in scores.items()
              if isinstance(v, (int, float)) and math.isfinite(v)}
    if not finite:
        return None
    return min(finite, key=finite.get)  # type: ignore[arg-type]


def _build_coaching_summary(
    scores: dict[str, float],
    weakness: str | None,
    overall: float,
    n_laps: int,
) -> list[str]:
    """Build a top-level coaching summary for the fitness report."""
    tips: list[str] = []

    if n_laps < MIN_LAPS_ENDURANCE:
        tips.append(
            f"Only {n_laps} valid laps available. "
            "Longer sessions will yield more reliable fitness metrics."
        )
        return tips

    if math.isfinite(overall):
        if overall >= 85:
            tips.append(
                f"Overall fitness score: {overall:.0f}/100 -- race-ready condition."
            )
        elif overall >= 70:
            tips.append(
                f"Overall fitness score: {overall:.0f}/100 -- solid, with room for improvement."
            )
        elif overall >= 50:
            tips.append(
                f"Overall fitness score: {overall:.0f}/100 -- targeted training recommended."
            )
        else:
            tips.append(
                f"Overall fitness score: {overall:.0f}/100 -- significant fitness work needed."
            )

    if weakness:
        labels = {
            "endurance": "Endurance (pace fade over session)",
            "concentration": "Concentration (lap-to-lap consistency)",
            "reaction": "Reaction (recovery after bad laps)",
        }
        tips.append(
            f"Primary area for improvement: {labels.get(weakness, weakness)}."
        )

    return tips


# ============================================================================
# Self-tests
# ============================================================================


if __name__ == "__main__":
    import sys

    passed = 0
    failed = 0

    def _assert(condition: bool, label: str):
        global passed, failed
        if condition:
            passed += 1
            print(f"  PASS: {label}")
        else:
            failed += 1
            print(f"  FAIL: {label}")

    # ---- Test 1: Empty inputs do not crash --------------------------------
    print("\nTest 1: Empty / None inputs")
    r = analyze_session_endurance([], [])
    _assert(isinstance(r, dict), "empty list returns dict")
    _assert(r["fatigue_onset_lap"] is None, "no fatigue onset for empty")
    _assert(len(r["coaching"]) > 0, "coaching present even for empty")

    r2 = compute_concentration_index([])
    _assert(isinstance(r2, dict), "empty concentration returns dict")

    r3 = compute_reaction_metrics([])
    _assert(isinstance(r3, dict), "empty reaction returns dict")

    # ---- Test 2: None values in input are filtered out --------------------
    print("\nTest 2: None values filtered")
    times_with_none = [90.0, None, 91.0, None, 92.0, 93.0, 94.0, 95.0]
    nums_with_none = [1, 2, 3, 4, 5, 6, 7, 8]
    r = analyze_session_endurance(times_with_none, nums_with_none)
    _assert(isinstance(r, dict), "handles None in lap_times")
    _assert(math.isfinite(r["endurance_score"]) or len(r["quarters"]) == 0,
            "score is finite or no quarters")

    # ---- Test 3: Steady driver = high endurance score ---------------------
    print("\nTest 3: Steady driver (high endurance)")
    steady_times = [90.0 + 0.05 * (i % 3) for i in range(20)]
    steady_nums = list(range(1, 21))
    r = analyze_session_endurance(steady_times, steady_nums)
    _assert(r["endurance_score"] >= 85.0,
            f"steady driver score >= 85 (got {r['endurance_score']})")
    _assert(len(r["quarters"]) == 4, "4 quarters produced")
    _assert(abs(r["pace_fade_pct"]) < 1.0,
            f"pace fade < 1% (got {r['pace_fade_pct']})")

    # ---- Test 4: Fading driver = lower endurance score --------------------
    print("\nTest 4: Fading driver (low endurance)")
    fading_times = [90.0 + 0.3 * i for i in range(20)]  # steadily slowing
    fading_nums = list(range(1, 21))
    r = analyze_session_endurance(fading_times, fading_nums)
    _assert(r["endurance_score"] < 80.0,
            f"fading driver score < 80 (got {r['endurance_score']})")
    _assert(r["pace_fade_pct"] > 2.0,
            f"pace fade > 2% (got {r['pace_fade_pct']})")

    # ---- Test 5: Concentration index with consistent driver ---------------
    print("\nTest 5: Concentration -- consistent driver")
    consistent = [90.0 + 0.02 * (i % 2) for i in range(20)]
    r = compute_concentration_index(consistent, window=5)
    _assert(r["concentration_score"] >= 80.0,
            f"consistent driver conc >= 80 (got {r['concentration_score']})")
    _assert(len(r["drop_laps"]) == 0,
            f"no drops for consistent driver (got {len(r['drop_laps'])} drops)")

    # ---- Test 6: Concentration index with erratic driver ------------------
    print("\nTest 6: Concentration -- erratic driver")
    erratic = [90.0 if i % 3 != 0 else 95.0 for i in range(20)]
    r = compute_concentration_index(erratic, window=5)
    _assert(r["concentration_score"] < 80.0,
            f"erratic driver conc < 80 (got {r['concentration_score']})")

    # ---- Test 7: Reaction metrics -- quick recovery -----------------------
    print("\nTest 7: Reaction -- quick recovery")
    #   Bad lap on lap 5 and lap 12, immediate recovery
    quick_recovery = [90.0] * 20
    quick_recovery[4] = 97.0   # bad lap
    quick_recovery[5] = 90.0   # immediate recovery
    quick_recovery[11] = 96.0  # bad lap
    quick_recovery[12] = 89.5  # immediate recovery
    r = compute_reaction_metrics(quick_recovery)
    _assert(r["reaction_score"] >= 70.0,
            f"quick recovery score >= 70 (got {r['reaction_score']})")
    _assert(r["avg_recovery_laps"] <= 2.0,
            f"avg recovery <= 2 laps (got {r['avg_recovery_laps']})")

    # ---- Test 8: Reaction metrics -- slow recovery ------------------------
    print("\nTest 8: Reaction -- slow recovery")
    slow_recovery = [90.0] * 20
    slow_recovery[3] = 97.0
    slow_recovery[4] = 94.0
    slow_recovery[5] = 93.0
    slow_recovery[6] = 92.0
    slow_recovery[7] = 91.0
    slow_recovery[8] = 90.0   # 5 laps to recover
    r = compute_reaction_metrics(slow_recovery)
    _assert(r["avg_recovery_laps"] >= 3.0,
            f"slow recovery >= 3 laps (got {r['avg_recovery_laps']})")

    # ---- Test 9: Full fitness report --------------------------------------
    print("\nTest 9: Full fitness report")
    report_times = [90.0 + 0.1 * i + 0.3 * (1 if i == 8 else 0)
                    for i in range(24)]
    report_nums = list(range(1, 25))
    r = generate_fitness_report(report_times, report_nums, driver_name="TestDriver")
    _assert(r["driver_name"] == "TestDriver", "driver name preserved")
    _assert(r["n_laps"] == 24, f"n_laps == 24 (got {r['n_laps']})")
    _assert(math.isfinite(r["overall_fitness_score"]),
            f"overall score finite (got {r['overall_fitness_score']})")
    _assert("endurance" in r, "endurance sub-report present")
    _assert("concentration" in r, "concentration sub-report present")
    _assert("reaction" in r, "reaction sub-report present")
    _assert(r["primary_weakness"] in ("endurance", "concentration", "reaction"),
            f"primary weakness identified (got {r['primary_weakness']})")
    _assert(len(r["coaching_summary"]) >= 1, "coaching summary non-empty")

    # ---- Test 10: Fewer than 4 laps yields safe empty result ----------------
    print("\nTest 10: Fewer than 4 laps (edge case)")
    r = analyze_session_endurance([90.0, 91.0], [1, 2])
    _assert(len(r["quarters"]) == 0, "no quarters for 2 laps")
    _assert(not math.isfinite(r["endurance_score"]),
            "endurance score is NaN for 2 laps")

    # ---- Test 11: Perfectly identical lap times ----------------------------
    print("\nTest 11: Perfectly identical lap times")
    identical = [90.0] * 20
    r = compute_concentration_index(identical, window=5)
    _assert(r["concentration_score"] >= 95.0,
            f"identical laps conc >= 95 (got {r['concentration_score']})")

    r2 = compute_reaction_metrics(identical)
    _assert(r2["bad_lap_count"] == 0,
            f"no bad laps for identical times (got {r2['bad_lap_count']})")
    _assert(r2["reaction_score"] == 100.0,
            f"perfect reaction score for identical (got {r2['reaction_score']})")

    # ---- Summary ----------------------------------------------------------
    print(f"\n{'=' * 50}")
    print(f"Results: {passed} passed, {failed} failed out of {passed + failed}")
    if failed:
        print("SOME TESTS FAILED")
        sys.exit(1)
    else:
        print("ALL TESTS PASSED")
