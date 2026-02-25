"""
race_simulator.py
-----------------
Deterministic Race Pace Simulator -- predicts lap-by-lap race times from
user-defined parameters (tire deg, fuel effect, fatigue, pit stops, etc.).

Unlike race_pace_predictor.py (which extrapolates from actual session data),
this module runs a pure simulation: no DB, no session history. It takes
explicit parameters and produces a deterministic predicted timeline.

Public API
~~~~~~~~~~
- ``simulate_race(params: SimulationParams) -> SimulationResult``

Design Principles
~~~~~~~~~~~~~~~~~
- Pure functions; no global mutable state.
- Deterministic: identical inputs -> identical outputs.
- NaN-robust; all outputs are finite floats.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Final

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

FATIGUE_RATE_S_PER_LAP: Final[float] = 0.015  # seconds/lap after fatigue onset


# ============================================================================
# Data Structures
# ============================================================================


@dataclass
class SimulationParams:
    """User-defined simulation inputs."""
    race_laps: int = 25
    pit_stop_loss_s: float = 30.0
    num_pit_stops: int = 1
    tire_deg_rate_s: float = 0.05
    fuel_effect_s: float = 0.0
    target_lap_time_s: float = 62.0
    consistency_cv_pct: float = 1.5
    fatigue_onset_lap: int = 18
    stint_length: int = 12
    traffic_penalty_s: float = 0.3


@dataclass
class SimulationResult:
    """Output of the race simulation."""
    predicted_laps: list[float] = field(default_factory=list)
    total_race_time_s: float = 0.0
    best_stint_pace_s: float = 0.0
    worst_stint_pace_s: float = 0.0
    pit_stop_laps: list[int] = field(default_factory=list)
    fatigue_impact_s: float = 0.0
    tire_impact_s: float = 0.0
    coaching: str = ""
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "predicted_laps": [round(t, 3) for t in self.predicted_laps],
            "total_race_time_s": round(self.total_race_time_s, 3),
            "best_stint_pace_s": round(self.best_stint_pace_s, 3),
            "worst_stint_pace_s": round(self.worst_stint_pace_s, 3),
            "pit_stop_laps": self.pit_stop_laps,
            "fatigue_impact_s": round(self.fatigue_impact_s, 3),
            "tire_impact_s": round(self.tire_impact_s, 3),
            "coaching": self.coaching,
            "confidence": round(self.confidence, 3),
        }


# ============================================================================
# Simulation Engine
# ============================================================================


def simulate_race(params: SimulationParams) -> SimulationResult:
    """
    Run a deterministic race simulation.

    For each lap, the predicted time is:
        base_time + tire_deg + fuel_offset + fatigue + traffic

    Pit stops are inserted at stint boundaries. Tire degradation resets
    after each pit stop. Fuel effect is cumulative (lighter each lap).
    Fatigue kicks in after fatigue_onset_lap.
    """
    result = SimulationResult()

    if params.race_laps <= 0:
        return result

    # Determine pit stop laps (evenly spaced by stint length)
    pit_laps = _compute_pit_laps(
        params.race_laps, params.num_pit_stops, params.stint_length,
    )
    result.pit_stop_laps = pit_laps

    tire_age = 0
    total_fatigue = 0.0
    total_tire_deg = 0.0
    stint_times: list[list[float]] = [[]]

    for lap in range(1, params.race_laps + 1):
        base = params.target_lap_time_s

        # Tire degradation: increases with tire age
        tire_offset = params.tire_deg_rate_s * tire_age
        total_tire_deg += tire_offset

        # Fuel effect: car gets lighter each lap (negative offset = faster)
        fuel_offset = -params.fuel_effect_s * (lap - 1)

        # Fatigue: kicks in after onset lap
        fatigue_offset = 0.0
        if lap > params.fatigue_onset_lap:
            laps_fatigued = lap - params.fatigue_onset_lap
            fatigue_offset = FATIGUE_RATE_S_PER_LAP * laps_fatigued
            total_fatigue += fatigue_offset

        # Traffic penalty (constant per lap)
        traffic = params.traffic_penalty_s

        # Compute lap time (deterministic)
        lap_time = base + tire_offset + fuel_offset + fatigue_offset + traffic

        # Pit stop: add pit loss to this lap
        is_pit = lap in pit_laps
        if is_pit:
            lap_time += params.pit_stop_loss_s
            tire_age = 0
            stint_times.append([])
        else:
            tire_age += 1

        result.predicted_laps.append(round(lap_time, 3))
        stint_times[-1].append(lap_time)

    result.total_race_time_s = sum(result.predicted_laps)
    result.fatigue_impact_s = total_fatigue
    result.tire_impact_s = total_tire_deg

    # Best/worst stint pace
    stint_avgs = []
    for stint in stint_times:
        if not stint:
            continue
        stint_avgs.append(sum(stint) / len(stint))

    if stint_avgs:
        result.best_stint_pace_s = min(stint_avgs)
        result.worst_stint_pace_s = max(stint_avgs)

    # Confidence
    non_default_count = sum([
        params.tire_deg_rate_s > 0,
        params.fuel_effect_s > 0,
        params.fatigue_onset_lap < params.race_laps,
        params.traffic_penalty_s > 0,
        params.num_pit_stops > 0,
    ])
    result.confidence = min(1.0, 0.5 + non_default_count * 0.1)

    result.coaching = _generate_coaching(params, result)

    logger.info(
        "Race simulation: %d laps, total=%.1fs, pits=%d, tire_impact=%.1fs, fatigue=%.1fs",
        params.race_laps, result.total_race_time_s,
        len(pit_laps), result.tire_impact_s, result.fatigue_impact_s,
    )

    return result


def _compute_pit_laps(
    race_laps: int, num_pits: int, stint_length: int,
) -> list[int]:
    """Compute which laps to pit on, evenly spaced by stint length."""
    if num_pits <= 0 or race_laps <= 1:
        return []

    pits = []
    for i in range(1, num_pits + 1):
        pit_lap = i * stint_length
        if pit_lap < race_laps:
            pits.append(pit_lap)

    return pits[:num_pits]


def _generate_coaching(params: SimulationParams, result: SimulationResult) -> str:
    """Generate actionable coaching from simulation results."""
    parts: list[str] = []

    parts.append(
        f"Simulated {params.race_laps}-lap race: "
        f"total {result.total_race_time_s / 60:.1f} min."
    )

    if result.tire_impact_s > 5:
        parts.append(
            f"Tire degradation adds {result.tire_impact_s:.1f}s total. "
            f"Consider an extra pit stop if deg rate exceeds "
            f"{params.tire_deg_rate_s * 2:.2f}s/lap."
        )

    if result.fatigue_impact_s > 3:
        parts.append(
            f"Fatigue costs {result.fatigue_impact_s:.1f}s after lap "
            f"{params.fatigue_onset_lap}. "
            f"Physical conditioning could delay onset."
        )

    if params.traffic_penalty_s > 0.5:
        parts.append(
            f"Traffic adds {params.traffic_penalty_s:.1f}s/lap -- "
            f"qualifying higher reduces this significantly."
        )

    if params.fuel_effect_s > 0 and params.race_laps > 10:
        saved = params.fuel_effect_s * params.race_laps
        parts.append(
            f"Fuel burn-off saves {saved:.1f}s over the race -- "
            f"late-stint pace will be naturally faster."
        )

    if len(result.pit_stop_laps) > 0:
        pit_str = ", ".join(f"L{p}" for p in result.pit_stop_laps)
        parts.append(f"Pit stops on: {pit_str}.")

    return " ".join(parts)
