"""
joker_detection.py
------------------
Detect which lap in a session used the "joker" (alternative) track section.

The joker section is usually *longer* than the standard racing line.  Detection
uses a two-signal approach:

* **Distance** (weight 70%) — primary signal.  The joker lap will show a
  positive distance delta compared to the session median.
* **Time** (weight 30%) — secondary confirmation.  A longer section normally
  adds time, but driver variability makes this less reliable.

The module is a pure function — no Flask or DB dependencies.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

import numpy as np

logger = logging.getLogger(__name__)

# ── Weighting ────────────────────────────────────────────────────────────
_W_DISTANCE = 0.70
_W_TIME = 0.30

# ── Fallback thresholds (when no expected delta configured) ──────────────
_OUTLIER_SIGMA = 1.8     # How many σ above median to consider an outlier
_MIN_DISTANCE_DELTA_M = 5.0   # Ignore distance diffs smaller than 5 m


@dataclass
class JokerDetectionResult:
    """Outcome of joker-lap detection for a session."""

    candidate_lap: Optional[int] = None
    """Lap number of the most likely joker lap (None if not detected)."""

    confidence: float = 0.0
    """0.0 – 1.0 confidence score for the candidate."""

    all_distances: dict[int, float] = field(default_factory=dict)
    """Lap number → total distance (metres) for every non-excluded lap."""

    median_distance: float = 0.0
    """Median lap distance across non-excluded laps (metres)."""

    delta_from_median: dict[int, float] = field(default_factory=dict)
    """Lap number → (distance − median) for every non-excluded lap."""

    all_times: dict[int, float] = field(default_factory=dict)
    """Lap number → lap time (seconds) for every non-excluded lap."""

    median_time: float = 0.0
    """Median lap time across non-excluded laps (seconds)."""

    time_delta_from_median: dict[int, float] = field(default_factory=dict)
    """Lap number → (time − median_time) for every non-excluded lap."""

    reason: str = ""
    """Human-readable explanation of the result."""


# ── Public API ───────────────────────────────────────────────────────────

def detect_joker_lap(
    lap_metrics: Sequence[dict[str, Any]],
    lap_times: Sequence[float],
    *,
    expected_distance_delta_m: Optional[float] = None,
    expected_time_delta_s: Optional[float] = None,
    excluded_laps: set[int] | frozenset[int] = frozenset(),
    min_confidence: float = 0.3,
) -> JokerDetectionResult:
    """Detect the joker lap from per-lap metrics and times.

    Parameters
    ----------
    lap_metrics:
        Sequence of metric dicts, one per lap (from pipeline step 08).
        Each dict must contain ``lap_number`` (int) and ``line_length_m`` (float).
    lap_times:
        Parallel list of lap times in seconds (same order as ``lap_metrics``).
    expected_distance_delta_m:
        If the track has a configured expected distance delta (metres).
        ``None`` → use outlier detection.
    expected_time_delta_s:
        If the track has a configured expected time delta (seconds).
        ``None`` → skip time-target scoring (fall back to outlier).
    excluded_laps:
        Set of lap numbers to ignore (invalid, incomplete, anomalous, deviated).
    min_confidence:
        Minimum confidence threshold to accept a candidate.

    Returns
    -------
    JokerDetectionResult
    """
    result = JokerDetectionResult()

    # ── Build lap → distance / time maps (excluding already-rejected laps) ──
    lap_distances: dict[int, float] = {}
    lap_time_map: dict[int, float] = {}

    for metric, t in zip(lap_metrics, lap_times):
        lap_num = int(metric.get("lap_number", -1))
        if lap_num < 0 or lap_num in excluded_laps:
            continue
        dist = metric.get("line_length_m")
        if dist is None or not math.isfinite(dist):
            continue
        if not math.isfinite(t):
            continue
        lap_distances[lap_num] = float(dist)
        lap_time_map[lap_num] = float(t)

    if len(lap_distances) < 3:
        result.reason = (
            f"Not enough valid laps for joker detection "
            f"({len(lap_distances)} available, need ≥3)."
        )
        logger.info("Joker detection skipped: %s", result.reason)
        return result

    result.all_distances = dict(lap_distances)
    result.all_times = dict(lap_time_map)

    # ── Compute medians ──────────────────────────────────────────────────
    distances = np.array(list(lap_distances.values()))
    times = np.array(list(lap_time_map.values()))

    med_dist = float(np.median(distances))
    med_time = float(np.median(times))
    result.median_distance = med_dist
    result.median_time = med_time

    # Deltas from median
    for lap_num, d in lap_distances.items():
        result.delta_from_median[lap_num] = round(d - med_dist, 2)
    for lap_num, t in lap_time_map.items():
        result.time_delta_from_median[lap_num] = round(t - med_time, 3)

    # ── Score each lap ───────────────────────────────────────────────────
    scores: dict[int, float] = {}

    for lap_num in lap_distances:
        d_delta = lap_distances[lap_num] - med_dist
        t_delta = lap_time_map[lap_num] - med_time

        dist_score = _distance_score(
            d_delta, distances, expected_distance_delta_m,
        )
        time_score = _time_score(
            t_delta, times, expected_time_delta_s,
        )
        combined = _W_DISTANCE * dist_score + _W_TIME * time_score
        scores[lap_num] = combined

    if not scores:
        result.reason = "No laps scored."
        return result

    # ── Pick best candidate ──────────────────────────────────────────────
    best_lap = max(scores, key=scores.get)  # type: ignore[arg-type]
    best_score = scores[best_lap]

    # The candidate must have a *positive* distance delta (joker is longer)
    if result.delta_from_median.get(best_lap, 0) < _MIN_DISTANCE_DELTA_M:
        result.reason = (
            f"Top candidate lap {best_lap} has distance delta "
            f"{result.delta_from_median.get(best_lap, 0):.1f} m — "
            f"below minimum {_MIN_DISTANCE_DELTA_M:.0f} m. No joker detected."
        )
        logger.info("Joker detection: %s", result.reason)
        return result

    result.candidate_lap = best_lap
    result.confidence = round(min(best_score, 1.0), 3)

    if result.confidence < min_confidence:
        result.reason = (
            f"Candidate lap {best_lap} confidence {result.confidence:.2f} "
            f"is below threshold {min_confidence:.2f}."
        )
        logger.info("Joker detection: %s", result.reason)
        # Still return the candidate so the user can decide
        return result

    result.reason = (
        f"Lap {best_lap} identified as joker candidate "
        f"(confidence {result.confidence:.2f}, "
        f"distance delta +{result.delta_from_median[best_lap]:.1f} m, "
        f"time delta {result.time_delta_from_median[best_lap]:+.3f} s)."
    )
    logger.info("Joker detection: %s", result.reason)
    return result


# ── Internal scoring helpers ─────────────────────────────────────────────

def _distance_score(
    delta: float,
    all_distances: np.ndarray,
    expected_delta: Optional[float],
) -> float:
    """Score a single lap's distance delta.

    Two modes:
    * **Target mode** (``expected_delta`` is set) — Gaussian closeness to
      the expected value.  Peak score 1.0 when delta == expected_delta.
    * **Outlier mode** (``expected_delta`` is None) — How many standard
      deviations above the median this lap sits.  Score rises from 0 at
      the median to 1.0 at ``_OUTLIER_SIGMA`` σ and above.
    """
    if delta < _MIN_DISTANCE_DELTA_M:
        return 0.0

    if expected_delta is not None and expected_delta > 0:
        # Gaussian closeness: score = exp(-(delta - target)^2 / (2 * sigma^2))
        # sigma = 30% of target (generous tolerance for GPS drift)
        sigma = expected_delta * 0.30
        if sigma < 1.0:
            sigma = 1.0
        return float(np.exp(-((delta - expected_delta) ** 2) / (2 * sigma ** 2)))

    # Outlier mode — normalise by standard deviation
    std = float(np.std(all_distances))
    if std < 1.0:
        # Essentially no variation — if delta > threshold it's clearly an outlier
        return 1.0 if delta > _MIN_DISTANCE_DELTA_M else 0.0

    z = delta / std
    # Sigmoid-like mapping: 0 at z=0, ~1.0 at z=_OUTLIER_SIGMA
    return float(min(z / _OUTLIER_SIGMA, 1.0))


def _time_score(
    delta: float,
    all_times: np.ndarray,
    expected_delta: Optional[float],
) -> float:
    """Score a single lap's time delta.

    Same dual-mode approach as ``_distance_score`` but for time.
    The joker lap is expected to be *slower* (positive delta).
    """
    # A joker lap *could* be faster if the driver is quicker, but typically
    # it's slower.  We score positive deltas more highly.
    if expected_delta is not None and expected_delta > 0:
        sigma = expected_delta * 0.40  # wider tolerance (more driver variability)
        if sigma < 0.5:
            sigma = 0.5
        return float(np.exp(-((delta - expected_delta) ** 2) / (2 * sigma ** 2)))

    # Outlier mode for time
    std = float(np.std(all_times))
    if std < 0.1:
        return 0.5  # Can't tell much from times — neutral score

    z = delta / std
    if z <= 0:
        # Faster than median — weak negative signal but not disqualifying
        return max(0.0, 0.3 + 0.1 * z)  # gentle slope, floor at 0
    # Slower than median — supportive signal
    return float(min(z / _OUTLIER_SIGMA, 1.0))
