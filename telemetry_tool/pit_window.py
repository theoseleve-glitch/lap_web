"""
pit_window.py
-------------
Optimal Pit Window Calculator.

Uses tyre degradation modelling, stint performance data, and race-length
parameters to recommend the ideal lap(s) for a pit stop.

Core Concept
~~~~~~~~~~~~
The "crossover point" is the lap where the cumulative time lost from
degradation exceeds the pit-stop time penalty. Before the crossover,
staying out is faster. After the crossover, pitting would have been better.

The optimal pit window is a range around the crossover point, adjusted for
traffic/position considerations and safety margins.

Models
~~~~~~
1. **Linear degradation**: pace_loss(lap) = base_deg * lap_in_stint
2. **Exponential (tyre cliff)**: pace_loss(lap) = base_deg * exp(k * (lap - cliff_onset))
3. **Empirical**: fits a curve to actual stint data and extrapolates

Public API
~~~~~~~~~~
- ``compute_degradation_model(stint_laps)``
- ``find_crossover_lap(deg_model, pit_loss_s)``
- ``compute_optimal_window(stints, pit_loss_s, race_laps, safety_margin)``
- ``simulate_strategies(deg_model, race_laps, pit_loss_s, max_stops)``

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

DEFAULT_PIT_LOSS_S: Final[float] = 25.0   # typical pit-stop time loss (seconds)
MIN_STINT_LAPS: Final[int] = 4            # minimum laps to fit degradation model
SAFETY_MARGIN_LAPS: Final[int] = 2        # pit window buffer
MAX_EXTRAPOLATION_LAPS: Final[int] = 60   # don't extrapolate beyond this


# ============================================================================
# Data Structures
# ============================================================================

@dataclass
class DegradationModel:
    """Fitted tyre degradation model for a stint."""
    model_type: str = "linear"      # "linear" | "exponential" | "flat"
    base_deg_s: float = 0.0         # linear degradation per lap (seconds)
    cliff_onset_lap: int = 0        # lap where exponential kicks in (0 = none)
    cliff_rate: float = 0.0         # exponential growth rate
    r_squared: float = 0.0          # goodness of fit
    base_pace_s: float = 0.0        # best clean pace in stint (intercept)
    n_laps: int = 0

    def predict(self, lap_in_stint: int) -> float:
        """Predict lap time at given stint lap number (1-indexed)."""
        if self.model_type == "flat":
            return self.base_pace_s
        if self.model_type == "exponential" and self.cliff_onset_lap > 0:
            if lap_in_stint < self.cliff_onset_lap:
                return self.base_pace_s + self.base_deg_s * (lap_in_stint - 1)
            else:
                linear_part = self.base_deg_s * (self.cliff_onset_lap - 1)
                exp_part = self.base_deg_s * math.exp(
                    self.cliff_rate * (lap_in_stint - self.cliff_onset_lap)
                )
                return self.base_pace_s + linear_part + exp_part
        # linear
        return self.base_pace_s + self.base_deg_s * (lap_in_stint - 1)

    def cumulative_loss(self, n_laps: int) -> float:
        """Total time lost to degradation over n laps vs fresh tyre pace."""
        total = 0.0
        for i in range(1, n_laps + 1):
            total += self.predict(i) - self.base_pace_s
        return total

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_type": self.model_type,
            "base_deg_s": round(self.base_deg_s, 4),
            "cliff_onset_lap": self.cliff_onset_lap,
            "cliff_rate": round(self.cliff_rate, 4),
            "r_squared": round(self.r_squared, 4),
            "base_pace_s": round(self.base_pace_s, 3),
            "n_laps": self.n_laps,
        }


@dataclass
class PitStrategy:
    """A candidate pit strategy with timing and total race time."""
    n_stops: int = 0
    pit_laps: list[int] = field(default_factory=list)
    stint_lengths: list[int] = field(default_factory=list)
    total_race_time_s: float = 0.0
    total_deg_loss_s: float = 0.0
    total_pit_loss_s: float = 0.0
    advantage_vs_no_stop_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_stops": self.n_stops,
            "pit_laps": self.pit_laps,
            "stint_lengths": self.stint_lengths,
            "total_race_time_s": round(self.total_race_time_s, 3),
            "total_deg_loss_s": round(self.total_deg_loss_s, 3),
            "total_pit_loss_s": round(self.total_pit_loss_s, 3),
            "advantage_vs_no_stop_s": round(self.advantage_vs_no_stop_s, 3),
        }


@dataclass
class PitWindowResult:
    """Complete pit window analysis result."""
    degradation_model: DegradationModel = field(default_factory=DegradationModel)
    crossover_lap: int = 0
    optimal_window: tuple[int, int] = (0, 0)
    strategies: list[PitStrategy] = field(default_factory=list)
    best_strategy: Optional[PitStrategy] = None
    race_laps: int = 0
    pit_loss_s: float = DEFAULT_PIT_LOSS_S
    coaching: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "degradation_model": self.degradation_model.to_dict(),
            "crossover_lap": self.crossover_lap,
            "optimal_window": list(self.optimal_window),
            "strategies": [s.to_dict() for s in self.strategies],
            "best_strategy": self.best_strategy.to_dict() if self.best_strategy else None,
            "race_laps": self.race_laps,
            "pit_loss_s": round(self.pit_loss_s, 1),
            "coaching": self.coaching,
        }


# ============================================================================
# Degradation Modelling
# ============================================================================


def compute_degradation_model(
    lap_times: list[float],
    *,
    min_laps: int = MIN_STINT_LAPS,
) -> DegradationModel:
    """
    Fit a degradation model to stint lap times.

    Parameters
    ----------
    lap_times:
        Chronological lap times within a single stint.
    min_laps:
        Minimum laps needed for a meaningful fit.

    Returns
    -------
    DegradationModel
    """
    model = DegradationModel()

    # Filter valid
    valid = [(i, t) for i, t in enumerate(lap_times) if t is not None and math.isfinite(t) and t > 0]
    if len(valid) < min_laps:
        model.model_type = "flat"
        if valid:
            model.base_pace_s = min(t for _, t in valid)
            model.n_laps = len(valid)
        return model

    model.n_laps = len(valid)
    x = np.array([i + 1 for i, _ in valid], dtype=float)  # 1-indexed stint lap
    y = np.array([t for _, t in valid], dtype=float)

    model.base_pace_s = float(np.min(y))

    # Linear fit: y = a + b*x
    x_bar = float(np.mean(x))
    y_bar = float(np.mean(y))
    ss_xx = float(np.sum((x - x_bar) ** 2))
    ss_xy = float(np.sum((x - x_bar) * (y - y_bar)))

    if ss_xx > 0:
        slope = ss_xy / ss_xx
        intercept = y_bar - slope * x_bar
    else:
        slope = 0.0
        intercept = y_bar

    # R-squared
    y_pred = intercept + slope * x
    ss_res = float(np.sum((y - y_pred) ** 2))
    ss_tot = float(np.sum((y - y_bar) ** 2))
    r_sq = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

    model.base_deg_s = max(0.0, slope)  # degradation can't improve
    model.base_pace_s = max(0.0, intercept)
    model.r_squared = max(0.0, r_sq)

    if model.base_deg_s < 0.005:
        # Negligible degradation
        model.model_type = "flat"
        model.base_pace_s = float(np.min(y))
        return model

    model.model_type = "linear"

    # Check for exponential (tyre cliff) pattern:
    # If last 30% of laps deviate significantly upward from linear
    n = len(valid)
    cutoff = max(int(n * 0.7), min_laps)
    if n > cutoff + 1:
        late_x = x[cutoff:]
        late_y = y[cutoff:]
        late_pred = intercept + slope * late_x
        late_residual = float(np.mean(late_y - late_pred))
        if late_residual > model.base_deg_s * 2:
            # Significant cliff-like behaviour
            model.model_type = "exponential"
            model.cliff_onset_lap = int(x[cutoff])
            # Estimate cliff rate from late-stint deviations
            if len(late_x) >= 2:
                late_excess = late_y - late_pred
                late_excess = np.maximum(late_excess, 0.01)
                log_excess = np.log(late_excess)
                late_x_shifted = late_x - late_x[0]
                if float(np.sum(late_x_shifted ** 2)) > 0:
                    model.cliff_rate = float(
                        np.sum(late_x_shifted * log_excess) /
                        np.sum(late_x_shifted ** 2)
                    )
                    model.cliff_rate = max(0.01, min(1.0, model.cliff_rate))

    logger.info(
        "Deg model: type=%s base_deg=%.4f base_pace=%.3f r2=%.3f cliff=%d n=%d",
        model.model_type, model.base_deg_s, model.base_pace_s,
        model.r_squared, model.cliff_onset_lap, model.n_laps,
    )
    return model


# ============================================================================
# Crossover & Pit Window
# ============================================================================


def find_crossover_lap(
    model: DegradationModel,
    pit_loss_s: float = DEFAULT_PIT_LOSS_S,
    max_laps: int = MAX_EXTRAPOLATION_LAPS,
) -> int:
    """
    Find the lap where cumulative degradation exceeds pit-stop time loss.

    This is the theoretical lap where pitting becomes beneficial.

    Returns
    -------
    int
        Crossover lap number (1-indexed). 0 if no crossover within max_laps.
    """
    if model.model_type == "flat" or model.base_deg_s <= 0:
        return 0  # no degradation → never worth pitting for tyres

    for lap in range(1, max_laps + 1):
        cum_loss = model.cumulative_loss(lap)
        if cum_loss >= pit_loss_s:
            return lap

    return 0


def compute_optimal_window(
    stints: list[list[float]],
    pit_loss_s: float = DEFAULT_PIT_LOSS_S,
    race_laps: int = 0,
    safety_margin: int = SAFETY_MARGIN_LAPS,
) -> PitWindowResult:
    """
    Compute the optimal pit window from historical stint data.

    Parameters
    ----------
    stints:
        List of stint lap-time arrays. Each inner list is one stint.
    pit_loss_s:
        Time penalty for a pit stop (seconds).
    race_laps:
        Total race distance in laps. If 0, estimates from longest stint * 2.
    safety_margin:
        Laps before/after crossover to define the window.

    Returns
    -------
    PitWindowResult
    """
    result = PitWindowResult(pit_loss_s=pit_loss_s)

    if not stints:
        result.coaching = "No stint data available for pit window calculation."
        return result

    # Fit degradation models for each stint, pick the best
    models = []
    for stint_laps in stints:
        m = compute_degradation_model(stint_laps)
        models.append(m)

    # Use the model with the most data / best fit
    best_model = max(models, key=lambda m: (m.n_laps, m.r_squared))
    result.degradation_model = best_model

    # Estimate race length if not provided
    if race_laps <= 0:
        max_stint = max(m.n_laps for m in models)
        race_laps = max(max_stint * 2, 20)  # reasonable estimate
    result.race_laps = race_laps

    # Find crossover
    crossover = find_crossover_lap(best_model, pit_loss_s)
    result.crossover_lap = crossover

    if crossover > 0:
        window_start = max(1, crossover - safety_margin)
        window_end = min(race_laps - 1, crossover + safety_margin)
        result.optimal_window = (window_start, window_end)
    else:
        # No crossover → no-stop is likely optimal
        result.optimal_window = (0, 0)

    # Simulate strategies (0-stop through 3-stop)
    strategies = simulate_strategies(best_model, race_laps, pit_loss_s, max_stops=3)
    result.strategies = strategies

    if strategies:
        result.best_strategy = min(strategies, key=lambda s: s.total_race_time_s)

    # Coaching text
    result.coaching = _generate_pit_coaching(result)

    logger.info(
        "Pit window: crossover=%d window=%s best_strategy=%d-stop race=%d laps",
        crossover,
        result.optimal_window,
        result.best_strategy.n_stops if result.best_strategy else 0,
        race_laps,
    )
    return result


# ============================================================================
# Strategy Simulation
# ============================================================================


def simulate_strategies(
    model: DegradationModel,
    race_laps: int,
    pit_loss_s: float = DEFAULT_PIT_LOSS_S,
    max_stops: int = 3,
) -> list[PitStrategy]:
    """
    Simulate race strategies from 0-stop to max_stops.

    For each stop count, finds the best even-split stint distribution.

    Returns
    -------
    list[PitStrategy]
        Sorted by total race time (fastest first).
    """
    strategies: list[PitStrategy] = []

    for n_stops in range(0, max_stops + 1):
        n_stints = n_stops + 1

        if n_stints > race_laps:
            continue

        # Even split
        base_stint = race_laps // n_stints
        remainder = race_laps % n_stints
        stint_lengths = [base_stint] * n_stints
        for i in range(remainder):
            stint_lengths[i] += 1

        # Calculate race time
        total_deg = 0.0
        total_time = 0.0
        pit_laps: list[int] = []
        lap_counter = 0

        for stint_idx, stint_len in enumerate(stint_lengths):
            deg = model.cumulative_loss(stint_len)
            stint_time = stint_len * model.base_pace_s + deg
            total_deg += deg
            total_time += stint_time
            lap_counter += stint_len
            if stint_idx < n_stints - 1:
                pit_laps.append(lap_counter)

        total_pit = n_stops * pit_loss_s
        total_time += total_pit

        strat = PitStrategy(
            n_stops=n_stops,
            pit_laps=pit_laps,
            stint_lengths=stint_lengths,
            total_race_time_s=total_time,
            total_deg_loss_s=total_deg,
            total_pit_loss_s=total_pit,
        )
        strategies.append(strat)

    # Calculate advantage vs no-stop
    if strategies:
        no_stop_time = strategies[0].total_race_time_s
        for s in strategies:
            s.advantage_vs_no_stop_s = no_stop_time - s.total_race_time_s

    # Sort by total time
    strategies.sort(key=lambda s: s.total_race_time_s)

    return strategies


# ============================================================================
# Coaching
# ============================================================================


def _generate_pit_coaching(result: PitWindowResult) -> str:
    """Generate a human-readable pit strategy recommendation."""
    parts: list[str] = []

    m = result.degradation_model
    if m.model_type == "flat":
        parts.append(
            "Negligible tyre degradation detected. A no-stop strategy is likely optimal."
        )
    elif m.model_type == "exponential":
        parts.append(
            f"Tyre cliff detected around lap {m.cliff_onset_lap} of each stint. "
            f"Plan pit stops before the cliff to avoid severe pace loss."
        )
    else:
        parts.append(
            f"Linear degradation of {m.base_deg_s:.3f}s per lap. "
        )

    if result.crossover_lap > 0:
        parts.append(
            f"Crossover at lap {result.crossover_lap}: "
            f"after this lap, cumulative deg exceeds the {result.pit_loss_s:.0f}s pit penalty."
        )
        w = result.optimal_window
        if w[0] > 0:
            parts.append(f"Optimal pit window: laps {w[0]}-{w[1]}.")

    bs = result.best_strategy
    if bs:
        if bs.n_stops == 0:
            parts.append("Best strategy: NO STOP. Staying out is faster overall.")
        else:
            parts.append(
                f"Best strategy: {bs.n_stops}-STOP "
                f"(pit on lap{'s' if bs.n_stops > 1 else ''} "
                f"{', '.join(str(l) for l in bs.pit_laps)}). "
                f"Saves {bs.advantage_vs_no_stop_s:.1f}s vs no-stop."
            )

    return " ".join(parts)


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

    def t_linear_model():
        # Laps that degrade 0.1s per lap
        times = [60.0 + 0.1 * i for i in range(20)]
        m = compute_degradation_model(times)
        assert m.model_type == "linear", f"Expected linear, got {m.model_type}"
        assert 0.08 < m.base_deg_s < 0.12, f"base_deg_s={m.base_deg_s}"
        assert m.r_squared > 0.95, f"r2={m.r_squared}"
        assert m.n_laps == 20

    _test("linear_model", t_linear_model)

    def t_flat_model():
        # Consistent laps = flat model
        times = [60.0] * 10
        m = compute_degradation_model(times)
        assert m.model_type == "flat", f"Expected flat, got {m.model_type}"
        assert abs(m.base_pace_s - 60.0) < 0.01

    _test("flat_model", t_flat_model)

    def t_prediction():
        times = [60.0 + 0.2 * i for i in range(15)]
        m = compute_degradation_model(times)
        # Lap 1 should be close to base pace
        p1 = m.predict(1)
        assert abs(p1 - m.base_pace_s) < 0.5, f"predict(1)={p1}"
        # Lap 10 should be higher
        p10 = m.predict(10)
        assert p10 > p1, f"predict(10)={p10} not > predict(1)={p1}"

    _test("prediction", t_prediction)

    def t_cumulative_loss():
        m = DegradationModel(
            model_type="linear", base_deg_s=0.1, base_pace_s=60.0, n_laps=20
        )
        # Loss over 10 laps = sum(0.1*0 + 0.1*1 + ... + 0.1*9) = 0.1 * 45 = 4.5
        loss = m.cumulative_loss(10)
        assert abs(loss - 4.5) < 0.01, f"loss={loss}"

    _test("cumulative_loss", t_cumulative_loss)

    def t_crossover_lap():
        m = DegradationModel(
            model_type="linear", base_deg_s=0.1, base_pace_s=60.0, n_laps=20
        )
        # Crossover: when cumulative loss >= 25s
        # sum(0.1*i for i=0..n-1) >= 25 → 0.1 * n*(n-1)/2 >= 25 → n*(n-1) >= 500
        # n=23 → 23*22=506 >= 500 ✓
        cross = find_crossover_lap(m, pit_loss_s=25.0)
        assert cross == 23, f"crossover={cross}"

    _test("crossover_lap", t_crossover_lap)

    def t_no_crossover_flat():
        m = DegradationModel(model_type="flat", base_pace_s=60.0)
        cross = find_crossover_lap(m, pit_loss_s=25.0)
        assert cross == 0, "Flat model should never crossover"

    _test("no_crossover_flat", t_no_crossover_flat)

    def t_strategies():
        m = DegradationModel(
            model_type="linear", base_deg_s=0.15, base_pace_s=60.0, n_laps=20
        )
        strats = simulate_strategies(m, race_laps=30, pit_loss_s=25.0, max_stops=3)
        assert len(strats) == 4, f"Expected 4 strategies, got {len(strats)}"
        # All should have valid total times
        for s in strats:
            assert s.total_race_time_s > 0
            assert sum(s.stint_lengths) == 30
        # Best should be first (sorted)
        assert strats[0].total_race_time_s <= strats[-1].total_race_time_s

    _test("strategies", t_strategies)

    def t_optimal_window():
        stints = [[60.0 + 0.15 * i for i in range(20)]]
        result = compute_optimal_window(stints, pit_loss_s=25.0, race_laps=40)
        assert result.crossover_lap > 0, "Should have a crossover"
        assert result.optimal_window[0] > 0, "Window should be set"
        assert result.best_strategy is not None
        assert result.coaching != ""

    _test("optimal_window", t_optimal_window)

    def t_no_stop_optimal():
        # Very low degradation → no-stop best
        stints = [[60.0 + 0.001 * i for i in range(10)]]
        result = compute_optimal_window(stints, pit_loss_s=25.0, race_laps=20)
        bs = result.best_strategy
        assert bs is not None
        assert bs.n_stops == 0, f"Expected 0-stop, got {bs.n_stops}-stop"

    _test("no_stop_optimal", t_no_stop_optimal)

    def t_high_deg_multi_stop():
        # High degradation → multiple stops
        stints = [[60.0 + 0.5 * i for i in range(20)]]
        result = compute_optimal_window(stints, pit_loss_s=20.0, race_laps=50)
        bs = result.best_strategy
        assert bs is not None
        assert bs.n_stops >= 1, f"Expected >= 1 stop, got {bs.n_stops}"

    _test("high_deg_multi_stop", t_high_deg_multi_stop)

    def t_insufficient_data():
        stints = [[60.0, 61.0]]  # Only 2 laps
        result = compute_optimal_window(stints, race_laps=30)
        assert result.degradation_model.model_type == "flat"

    _test("insufficient_data", t_insufficient_data)

    def t_nan_robustness():
        stints = [[60.0, float("nan"), 60.5, None, 61.0, 61.5, 62.0, 62.5]]
        m = compute_degradation_model(stints[0])
        assert m.n_laps >= 4  # NaN/None filtered out
        assert math.isfinite(m.base_pace_s)

    _test("nan_robustness", t_nan_robustness)

    def t_serialization():
        stints = [[60.0 + 0.1 * i for i in range(15)]]
        result = compute_optimal_window(stints, race_laps=30)
        d = result.to_dict()
        assert "degradation_model" in d
        assert "crossover_lap" in d
        assert "strategies" in d
        assert "best_strategy" in d
        assert "coaching" in d
        assert len(d["strategies"]) >= 1

    _test("serialization", t_serialization)

    def t_deterministic():
        stints = [[60.0 + 0.12 * i for i in range(18)]]
        r1 = compute_optimal_window(stints, race_laps=35, pit_loss_s=22.0)
        r2 = compute_optimal_window(stints, race_laps=35, pit_loss_s=22.0)
        assert r1.to_dict() == r2.to_dict()

    _test("deterministic", t_deterministic)

    # Summary
    total = len(passed) + len(failed)
    print(f"\nPit Window Calculator Tests: {passed.__len__()}/{total} passed")
    for name in passed:
        print(f"  OK {name}")
    for name, tb in failed:
        print(f"  FAIL {name}\n{tb}")
    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _run_tests()
