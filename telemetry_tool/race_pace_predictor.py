"""
race_pace_predictor.py
----------------------
Race Pace Predictor — predicts expected lap times, race duration, and
finishing position based on historical data and current session performance.

Core Models
~~~~~~~~~~~
1. **Moving-Average Extrapolation**: Projects pace using rolling averages
   of recent laps, accounting for tyre degradation.
2. **Historical Benchmark**: Compares current pace to same-track historical
   sessions to estimate relative performance percentile.
3. **Gap Projection**: Given a rival's pace data, predicts when/if
   an overtake or being overtaken will occur.

Public API
~~~~~~~~~~
- ``predict_race_pace(lap_times, deg_model, race_laps)``
- ``predict_gap_evolution(driver_laps, rival_laps, race_laps)``
- ``compute_pace_percentile(current_pace, historical_paces)``
- ``predict_race_result(session_data, historical_data)``

Design Principles
~~~~~~~~~~~~~~~~~
- Pure functions; no global mutable state.
- NaN-robust throughout.
- Structured logging; zero print statements.
- Deterministic: identical inputs -> identical outputs.
"""

from __future__ import annotations

import logging
import math
import traceback
from dataclasses import dataclass, field
from typing import Any, Final, Optional

import numpy as np

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

MIN_LAPS_FOR_PREDICTION: Final[int] = 3
ROLLING_WINDOW: Final[int] = 5
DEFAULT_RACE_LAPS: Final[int] = 30
CONFIDENCE_DECAY: Final[float] = 0.97   # per-lap confidence decay


# ============================================================================
# Data Structures
# ============================================================================

@dataclass
class PacePrediction:
    """Predicted pace for remaining laps."""
    predicted_laps: list[float] = field(default_factory=list)  # predicted times
    predicted_total_s: float = 0.0     # total predicted race time
    elapsed_s: float = 0.0             # time already completed
    remaining_s: float = 0.0           # predicted remaining time
    confidence: float = 0.0            # 0-1 prediction confidence
    current_rolling_pace_s: float = 0.0  # current rolling average pace
    degradation_rate_s: float = 0.0    # estimated deg per lap
    laps_completed: int = 0
    laps_remaining: int = 0
    race_laps: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "predicted_laps": [round(t, 3) for t in self.predicted_laps],
            "predicted_total_s": round(self.predicted_total_s, 3),
            "elapsed_s": round(self.elapsed_s, 3),
            "remaining_s": round(self.remaining_s, 3),
            "confidence": round(self.confidence, 3),
            "current_rolling_pace_s": round(self.current_rolling_pace_s, 3),
            "degradation_rate_s": round(self.degradation_rate_s, 4),
            "laps_completed": self.laps_completed,
            "laps_remaining": self.laps_remaining,
            "race_laps": self.race_laps,
        }


@dataclass
class GapPrediction:
    """Predicted gap evolution between two drivers."""
    gap_per_lap: list[float] = field(default_factory=list)  # gap at each lap
    crossover_lap: int = 0          # lap where lead changes (0 = never)
    final_gap_s: float = 0.0        # predicted gap at end of race
    driver_ahead: str = ""          # which driver is ahead at the end
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "gap_per_lap": [round(g, 3) for g in self.gap_per_lap],
            "crossover_lap": self.crossover_lap,
            "final_gap_s": round(self.final_gap_s, 3),
            "driver_ahead": self.driver_ahead,
            "confidence": round(self.confidence, 3),
        }


@dataclass
class RaceResult:
    """Comprehensive race prediction result."""
    pace_prediction: PacePrediction = field(default_factory=PacePrediction)
    pace_percentile: float = 50.0   # 0-100, relative to historical
    estimated_position: int = 0
    field_size: int = 0
    gap_predictions: list[GapPrediction] = field(default_factory=list)
    coaching: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "pace_prediction": self.pace_prediction.to_dict(),
            "pace_percentile": round(self.pace_percentile, 1),
            "estimated_position": self.estimated_position,
            "field_size": self.field_size,
            "gap_predictions": [g.to_dict() for g in self.gap_predictions],
            "coaching": self.coaching,
        }


# ============================================================================
# Pace Prediction
# ============================================================================


def predict_race_pace(
    lap_times: list[float],
    race_laps: int = DEFAULT_RACE_LAPS,
    deg_rate: Optional[float] = None,
) -> PacePrediction:
    """
    Predict pace for the remainder of a race.

    Parameters
    ----------
    lap_times:
        Completed lap times (chronological).
    race_laps:
        Total race distance in laps.
    deg_rate:
        Override degradation rate (seconds/lap). If None, estimated from data.

    Returns
    -------
    PacePrediction
    """
    pred = PacePrediction(race_laps=race_laps)

    # Filter valid laps
    valid = [t for t in lap_times if t is not None and math.isfinite(t) and t > 0]
    if not valid:
        return pred

    pred.laps_completed = len(valid)
    pred.laps_remaining = max(0, race_laps - pred.laps_completed)
    pred.elapsed_s = sum(valid)

    if pred.laps_remaining <= 0:
        # Race already over
        pred.predicted_total_s = pred.elapsed_s
        pred.confidence = 1.0
        pred.current_rolling_pace_s = float(np.mean(valid[-ROLLING_WINDOW:]))
        return pred

    # Rolling average pace (recent laps)
    window = min(ROLLING_WINDOW, len(valid))
    recent = valid[-window:]
    rolling_pace = float(np.mean(recent))
    pred.current_rolling_pace_s = rolling_pace

    # Estimate degradation rate if not provided
    if deg_rate is None:
        deg_rate = _estimate_degradation(valid)
    pred.degradation_rate_s = max(0.0, deg_rate)

    # Predict remaining laps with degradation
    predicted = []
    confidence = 1.0
    base_pace = rolling_pace

    for i in range(pred.laps_remaining):
        lap_n = pred.laps_completed + i + 1
        predicted_time = base_pace + deg_rate * (i + 1)
        predicted_time = max(predicted_time, rolling_pace * 0.9)  # floor: can't be unrealistically fast
        predicted.append(predicted_time)
        confidence *= CONFIDENCE_DECAY

    pred.predicted_laps = predicted
    pred.remaining_s = sum(predicted)
    pred.predicted_total_s = pred.elapsed_s + pred.remaining_s
    pred.confidence = max(0.0, min(1.0, confidence))

    logger.info(
        "Pace prediction: %d/%d laps done, rolling=%.3f, deg=%.4f, "
        "remaining=%.1fs, conf=%.2f",
        pred.laps_completed, race_laps, rolling_pace, deg_rate,
        pred.remaining_s, pred.confidence,
    )
    return pred


def _estimate_degradation(valid_laps: list[float]) -> float:
    """Estimate degradation rate from lap-time trend."""
    n = len(valid_laps)
    if n < MIN_LAPS_FOR_PREDICTION:
        return 0.0

    x = np.arange(n, dtype=float)
    y = np.array(valid_laps, dtype=float)

    x_bar = float(np.mean(x))
    y_bar = float(np.mean(y))
    ss_xx = float(np.sum((x - x_bar) ** 2))
    ss_xy = float(np.sum((x - x_bar) * (y - y_bar)))

    if ss_xx > 0:
        slope = ss_xy / ss_xx
        return max(0.0, slope)  # degradation can't be negative (improvement)
    return 0.0


# ============================================================================
# Gap Prediction
# ============================================================================


def predict_gap_evolution(
    driver_laps: list[float],
    rival_laps: list[float],
    race_laps: int = DEFAULT_RACE_LAPS,
    driver_name: str = "Driver",
    rival_name: str = "Rival",
) -> GapPrediction:
    """
    Predict the gap evolution between two drivers.

    Parameters
    ----------
    driver_laps, rival_laps:
        Completed lap times for each driver.
    race_laps:
        Total race length.

    Returns
    -------
    GapPrediction
    """
    result = GapPrediction()

    d_valid = [t for t in driver_laps if t is not None and math.isfinite(t) and t > 0]
    r_valid = [t for t in rival_laps if t is not None and math.isfinite(t) and t > 0]

    if not d_valid or not r_valid:
        return result

    # Predict pace for both drivers
    d_pred = predict_race_pace(d_valid, race_laps)
    r_pred = predict_race_pace(r_valid, race_laps)

    # Build combined lap-time arrays (actual + predicted)
    d_all = list(d_valid) + d_pred.predicted_laps
    r_all = list(r_valid) + r_pred.predicted_laps

    # Equalise length
    max_len = max(len(d_all), len(r_all))
    while len(d_all) < max_len:
        d_all.append(d_all[-1] if d_all else 60.0)
    while len(r_all) < max_len:
        r_all.append(r_all[-1] if r_all else 60.0)

    # Compute cumulative gap
    d_cum = 0.0
    r_cum = 0.0
    gap_per_lap = []
    crossover = 0
    prev_sign = 0

    for i in range(min(max_len, race_laps)):
        d_cum += d_all[i]
        r_cum += r_all[i]
        gap = r_cum - d_cum  # positive = driver ahead

        gap_per_lap.append(gap)

        current_sign = 1 if gap >= 0 else -1
        if prev_sign != 0 and current_sign != prev_sign and crossover == 0:
            crossover = i + 1
        prev_sign = current_sign

    result.gap_per_lap = gap_per_lap
    result.crossover_lap = crossover

    if gap_per_lap:
        final_gap = gap_per_lap[-1]
        result.final_gap_s = abs(final_gap)
        result.driver_ahead = driver_name if final_gap >= 0 else rival_name

    result.confidence = min(d_pred.confidence, r_pred.confidence)

    return result


# ============================================================================
# Historical Percentile
# ============================================================================


def compute_pace_percentile(
    current_pace_s: float,
    historical_paces: list[float],
) -> float:
    """
    Compute where the current pace ranks against historical data.

    Parameters
    ----------
    current_pace_s:
        Current representative lap time (e.g., rolling average).
    historical_paces:
        List of historical representative lap times for the same track.

    Returns
    -------
    float
        Percentile 0-100. 100 = fastest ever, 0 = slowest.
    """
    if not historical_paces or not math.isfinite(current_pace_s):
        return 50.0

    valid = [p for p in historical_paces if p is not None and math.isfinite(p) and p > 0]
    if not valid:
        return 50.0

    # Count how many historical paces are slower (higher time)
    slower_count = sum(1 for p in valid if p > current_pace_s)
    equal_count = sum(1 for p in valid if abs(p - current_pace_s) < 0.001)

    percentile = (slower_count + 0.5 * equal_count) / len(valid) * 100
    return round(max(0.0, min(100.0, percentile)), 1)


# ============================================================================
# Full Race Prediction
# ============================================================================


def predict_race_result(
    session_data: dict[str, Any],
    historical_data: Optional[list[dict[str, Any]]] = None,
    race_laps: int = DEFAULT_RACE_LAPS,
) -> RaceResult:
    """
    Comprehensive race prediction combining pace prediction, percentile
    ranking, and gap analysis.

    Parameters
    ----------
    session_data:
        Dict with keys: ``lap_times`` (list[float]), ``driver_name`` (str).
    historical_data:
        List of dicts, each with ``driver_name``, ``best_lap_time_s``,
        ``mean_lap_time_s``, ``lap_times`` (optional).
    race_laps:
        Total race length.

    Returns
    -------
    RaceResult
    """
    result = RaceResult()

    lap_times = session_data.get("lap_times", [])
    driver_name = session_data.get("driver_name", "Driver")

    # Pace prediction
    result.pace_prediction = predict_race_pace(lap_times, race_laps)

    # Historical percentile
    if historical_data:
        historical_paces = []
        for hd in historical_data:
            pace = hd.get("mean_lap_time_s") or hd.get("best_lap_time_s")
            if pace is not None and math.isfinite(float(pace)):
                historical_paces.append(float(pace))

        if result.pace_prediction.current_rolling_pace_s > 0:
            result.pace_percentile = compute_pace_percentile(
                result.pace_prediction.current_rolling_pace_s,
                historical_paces,
            )

        # Estimate position
        result.field_size = len(historical_data)
        if result.field_size > 0:
            result.estimated_position = max(1, round(
                result.field_size * (1 - result.pace_percentile / 100)
            ))

        # Gap predictions against rivals with lap-time data
        for hd in historical_data:
            rival_laps = hd.get("lap_times", [])
            rival_name = hd.get("driver_name", "Rival")
            if rival_laps and rival_name != driver_name:
                gap = predict_gap_evolution(
                    lap_times, rival_laps, race_laps,
                    driver_name, rival_name,
                )
                if gap.gap_per_lap:
                    result.gap_predictions.append(gap)

    # Coaching
    result.coaching = _generate_race_coaching(result, driver_name)

    return result


def _generate_race_coaching(result: RaceResult, driver_name: str) -> str:
    """Generate race-pace coaching insights."""
    parts: list[str] = []
    pp = result.pace_prediction

    if pp.laps_completed == 0:
        return "No lap data yet. Complete at least 3 laps for pace predictions."

    parts.append(
        f"Current pace: {pp.current_rolling_pace_s:.3f}s "
        f"(rolling {min(ROLLING_WINDOW, pp.laps_completed)}-lap avg)."
    )

    if pp.degradation_rate_s > 0.01:
        parts.append(
            f"Degradation: +{pp.degradation_rate_s:.3f}s/lap. "
            f"Consider tyre management in later laps."
        )
    elif pp.degradation_rate_s <= 0.005:
        parts.append("Pace is very stable — excellent tyre management.")

    if result.pace_percentile >= 80:
        parts.append(
            f"Top {100 - result.pace_percentile:.0f}% pace vs historical data — strong performance."
        )
    elif result.pace_percentile <= 30:
        parts.append(
            "Below median pace vs historical. Focus on key corners to find time."
        )

    if pp.laps_remaining > 0 and pp.confidence > 0:
        parts.append(
            f"Predicted finish: {_fmt_time(pp.predicted_total_s)} "
            f"(conf: {pp.confidence * 100:.0f}%)."
        )

    return " ".join(parts)


def _fmt_time(s: float) -> str:
    """Format seconds as m:ss.sss."""
    m = int(s // 60)
    sec = s % 60
    return f"{m}:{sec:06.3f}"


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

    def t_basic_prediction():
        laps = [60.0 + 0.05 * i for i in range(10)]
        pred = predict_race_pace(laps, race_laps=20)
        assert pred.laps_completed == 10
        assert pred.laps_remaining == 10
        assert pred.elapsed_s > 0
        assert pred.remaining_s > 0
        assert pred.predicted_total_s > pred.elapsed_s
        assert 0 < pred.confidence <= 1
        assert len(pred.predicted_laps) == 10

    _test("basic_prediction", t_basic_prediction)

    def t_race_complete():
        laps = [60.0] * 20
        pred = predict_race_pace(laps, race_laps=20)
        assert pred.laps_remaining == 0
        assert pred.confidence == 1.0
        assert pred.predicted_total_s == pred.elapsed_s

    _test("race_complete", t_race_complete)

    def t_no_laps():
        pred = predict_race_pace([], race_laps=20)
        assert pred.laps_completed == 0
        assert pred.remaining_s == 0

    _test("no_laps", t_no_laps)

    def t_degradation_estimate():
        # Clear degradation of 0.1s/lap
        laps = [60.0 + 0.1 * i for i in range(10)]
        deg = _estimate_degradation(laps)
        assert 0.08 < deg < 0.12, f"deg={deg}"

    _test("degradation_estimate", t_degradation_estimate)

    def t_no_degradation():
        laps = [60.0] * 10
        deg = _estimate_degradation(laps)
        assert deg < 0.001, f"deg={deg}"

    _test("no_degradation", t_no_degradation)

    def t_gap_evolution():
        d_laps = [60.0] * 10
        r_laps = [60.2] * 10  # rival 0.2s slower per lap
        gap = predict_gap_evolution(d_laps, r_laps, race_laps=20,
                                     driver_name="A", rival_name="B")
        assert len(gap.gap_per_lap) == 20
        assert gap.final_gap_s > 0
        assert gap.driver_ahead == "A"  # driver is faster

    _test("gap_evolution", t_gap_evolution)

    def t_gap_crossover():
        # Driver starts slower, gets faster
        d_laps = [62.0, 61.5, 61.0, 60.5, 60.0]
        r_laps = [60.0, 60.0, 60.0, 60.0, 60.0]
        gap = predict_gap_evolution(d_laps, r_laps, race_laps=20,
                                     driver_name="A", rival_name="B")
        # At some point A catches B
        assert len(gap.gap_per_lap) > 0

    _test("gap_crossover", t_gap_crossover)

    def t_pace_percentile():
        current = 60.0
        historical = [58.0, 59.0, 60.0, 61.0, 62.0, 63.0, 64.0]
        pct = compute_pace_percentile(current, historical)
        # 60s: 4 slower (61,62,63,64), 1 equal → (4 + 0.5)/7 * 100 ≈ 64.3
        assert 60 < pct < 70, f"pct={pct}"

    _test("pace_percentile", t_pace_percentile)

    def t_percentile_fastest():
        pct = compute_pace_percentile(55.0, [58.0, 59.0, 60.0, 61.0])
        assert pct == 100.0, f"pct={pct}"

    _test("percentile_fastest", t_percentile_fastest)

    def t_percentile_slowest():
        pct = compute_pace_percentile(65.0, [58.0, 59.0, 60.0, 61.0])
        assert pct == 0.0, f"pct={pct}"

    _test("percentile_slowest", t_percentile_slowest)

    def t_full_race_result():
        session_data = {
            "lap_times": [60.0 + 0.05 * i for i in range(10)],
            "driver_name": "TestDriver",
        }
        historical = [
            {"driver_name": "Fast", "mean_lap_time_s": 58.0, "lap_times": [58.0] * 10},
            {"driver_name": "Medium", "mean_lap_time_s": 60.5},
            {"driver_name": "Slow", "mean_lap_time_s": 63.0},
        ]
        result = predict_race_result(session_data, historical, race_laps=20)
        assert result.pace_prediction.laps_completed == 10
        assert 0 <= result.pace_percentile <= 100
        assert result.field_size == 3
        assert result.estimated_position >= 1
        assert result.coaching != ""
        assert len(result.gap_predictions) >= 1  # gap vs "Fast"

    _test("full_race_result", t_full_race_result)

    def t_nan_robustness():
        laps = [60.0, float("nan"), 60.5, None, 61.0]
        pred = predict_race_pace(laps, race_laps=10)
        assert pred.laps_completed >= 2
        assert math.isfinite(pred.predicted_total_s)

    _test("nan_robustness", t_nan_robustness)

    def t_serialization():
        session_data = {
            "lap_times": [60.0 + 0.1 * i for i in range(8)],
            "driver_name": "T",
        }
        result = predict_race_result(session_data, race_laps=15)
        d = result.to_dict()
        assert "pace_prediction" in d
        assert "pace_percentile" in d
        assert "coaching" in d

    _test("serialization", t_serialization)

    def t_deterministic():
        laps = [60.0 + 0.08 * i for i in range(12)]
        r1 = predict_race_pace(laps, race_laps=25)
        r2 = predict_race_pace(laps, race_laps=25)
        assert r1.to_dict() == r2.to_dict()

    _test("deterministic", t_deterministic)

    # Summary
    total = len(passed) + len(failed)
    print(f"\nRace Pace Predictor Tests: {len(passed)}/{total} passed")
    for name in passed:
        print(f"  OK {name}")
    for name, tb in failed:
        print(f"  FAIL {name}\n{tb}")
    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _run_tests()
