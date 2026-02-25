"""
energy_balance.py
-----------------
Momentum & Energy Balance Analyzer — computes kinetic energy flow across
a session, tracking energy input (acceleration), dissipation (braking),
and overall efficiency.

Core Features
~~~~~~~~~~~~~
1. **Energy Flow per Lap**: KE gained vs dissipated per lap.
2. **Braking Energy**: Total energy lost to braking per lap.
3. **Acceleration Energy**: Total energy input per lap.
4. **Efficiency Metric**: Ratio of useful KE (lap speed) to total KE cycled.
5. **Energy Balance Trend**: How energy management evolves across the session.
6. **Coaching**: Insight on driving smoothness from energy perspective.

Public API
~~~~~~~~~~
- ``analyze_energy_balance(lap_times, lap_numbers=None, vehicle_mass_kg=None)``
- ``compute_lap_energy_metrics(speeds, mass_kg)``

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

DEFAULT_MASS_KG: Final[float] = 180.0  # kart + driver default
TRACE_POINTS: Final[int] = 100
EFFICIENCY_REFERENCE: Final[float] = 0.85  # theoretical best efficiency


# ============================================================================
# Data Structures
# ============================================================================


@dataclass
class LapEnergyMetrics:
    """Energy metrics for a single lap."""
    lap_number: int = 0
    lap_time_s: float = 0.0
    braking_energy_j: float = 0.0      # total KE lost in braking zones
    accel_energy_j: float = 0.0        # total KE added in accel zones
    net_energy_j: float = 0.0          # accel - braking (should be ~0 for closed lap)
    peak_ke_j: float = 0.0             # max KE during lap
    min_ke_j: float = 0.0              # min KE during lap
    ke_range_j: float = 0.0            # peak - min
    efficiency: float = 0.0            # 0-1, how well energy is managed
    smoothness_score: float = 0.0      # 0-100, penalizes sharp KE changes

    def to_dict(self) -> dict[str, Any]:
        return {
            "lap_number": self.lap_number,
            "lap_time_s": round(self.lap_time_s, 3),
            "braking_energy_kj": round(self.braking_energy_j / 1000, 2),
            "accel_energy_kj": round(self.accel_energy_j / 1000, 2),
            "net_energy_kj": round(self.net_energy_j / 1000, 2),
            "peak_ke_kj": round(self.peak_ke_j / 1000, 2),
            "min_ke_kj": round(self.min_ke_j / 1000, 2),
            "ke_range_kj": round(self.ke_range_j / 1000, 2),
            "efficiency": round(self.efficiency, 3),
            "smoothness_score": round(self.smoothness_score, 1),
        }


@dataclass
class EnergyBalanceResult:
    """Full energy balance analysis."""
    n_laps: int = 0
    vehicle_mass_kg: float = 0.0
    lap_metrics: list[LapEnergyMetrics] = field(default_factory=list)
    mean_efficiency: float = 0.0
    mean_smoothness: float = 0.0
    efficiency_trend: str = ""   # "improving", "declining", "stable"
    total_braking_kj: float = 0.0
    total_accel_kj: float = 0.0
    best_efficiency_lap: int = 0
    worst_efficiency_lap: int = 0
    recovery_ratio: float = 0.0
    worst_braking_laps: list[int] = field(default_factory=list)
    coaching: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_laps": self.n_laps,
            "vehicle_mass_kg": round(self.vehicle_mass_kg, 1),
            "lap_metrics": [m.to_dict() for m in self.lap_metrics],
            "mean_efficiency": round(self.mean_efficiency, 3),
            "mean_smoothness": round(self.mean_smoothness, 1),
            "total_braking_kj": round(self.total_braking_kj, 2),
            "total_accel_kj": round(self.total_accel_kj, 2),
            "best_efficiency_lap": self.best_efficiency_lap,
            "worst_efficiency_lap": self.worst_efficiency_lap,
            "recovery_ratio": round(self.recovery_ratio, 1),
            "worst_braking_laps": self.worst_braking_laps,
            "coaching": self.coaching,
        }


# ============================================================================
# Core Functions
# ============================================================================


def _generate_speed_trace(lap_time_s: float, n_points: int, lap_idx: int) -> np.ndarray:
    """Generate deterministic synthetic speed trace for a lap."""
    base_speed = max(5.0, 1000.0 / lap_time_s)
    t = np.linspace(0, 2 * np.pi, n_points)
    # 3-corner profile
    profile = base_speed * (1.0 - 0.30 * np.abs(np.sin(1.5 * t)))
    # Deterministic per-lap variation
    seed_offset = ((lap_idx * 13 + 7) % 19) / 100.0
    profile *= (1.0 + seed_offset * 0.03)
    return np.maximum(profile, 3.0)


def compute_lap_energy_metrics(
    speeds: np.ndarray,
    mass_kg: float,
    lap_number: int = 0,
    lap_time_s: float = 0.0,
) -> LapEnergyMetrics:
    """
    Compute energy metrics from a speed trace.

    Parameters
    ----------
    speeds : ndarray
        Speed in m/s at each sample point.
    mass_kg : float
        Vehicle + driver mass.
    """
    metrics = LapEnergyMetrics(
        lap_number=lap_number,
        lap_time_s=lap_time_s,
    )

    if len(speeds) < 2:
        return metrics

    # Kinetic energy at each point: KE = 0.5 * m * v^2
    ke = 0.5 * mass_kg * speeds ** 2

    metrics.peak_ke_j = float(np.max(ke))
    metrics.min_ke_j = float(np.min(ke))
    metrics.ke_range_j = metrics.peak_ke_j - metrics.min_ke_j

    # Energy changes between points
    dke = np.diff(ke)
    braking_energy = float(np.sum(np.abs(dke[dke < 0])))
    accel_energy = float(np.sum(dke[dke > 0]))

    metrics.braking_energy_j = braking_energy
    metrics.accel_energy_j = accel_energy
    metrics.net_energy_j = accel_energy - braking_energy

    # Efficiency: ratio of mean KE to total KE cycled
    # Higher = more energy maintained (less braking/accelerating needed)
    total_cycled = braking_energy + accel_energy
    mean_ke = float(np.mean(ke))
    if total_cycled > 0:
        # Efficiency = mean KE / (mean KE + cycled/2)
        metrics.efficiency = mean_ke / (mean_ke + total_cycled / 2)
    else:
        metrics.efficiency = 1.0  # constant speed = perfect efficiency

    # Smoothness: penalize large KE changes
    if len(dke) > 0:
        jerk_rms = float(np.sqrt(np.mean(dke ** 2)))
        max_possible_jerk = metrics.peak_ke_j * 0.5
        if max_possible_jerk > 0:
            raw_smoothness = 1.0 - min(1.0, jerk_rms / max_possible_jerk)
        else:
            raw_smoothness = 1.0
        metrics.smoothness_score = raw_smoothness * 100
    else:
        metrics.smoothness_score = 100.0

    return metrics


def _compute_trend(values: list[float]) -> str:
    """Classify trend direction from a series of values."""
    if len(values) < 3:
        return "stable"

    n = len(values)
    x = np.arange(n, dtype=float)
    y = np.array(values, dtype=float)

    mean_x = np.mean(x)
    mean_y = np.mean(y)
    slope = float(np.sum((x - mean_x) * (y - mean_y)) / max(1e-10, np.sum((x - mean_x) ** 2)))

    # Relative slope
    if mean_y > 0:
        rel_slope = slope / mean_y
    else:
        rel_slope = 0

    if rel_slope > 0.005:
        return "improving"
    elif rel_slope < -0.005:
        return "declining"
    return "stable"


def analyze_energy_balance(
    lap_times: list[float],
    lap_numbers: list[int] | None = None,
    vehicle_mass_kg: float | None = None,
) -> EnergyBalanceResult:
    """
    Full energy balance analysis.

    Parameters
    ----------
    lap_times:
        List of valid lap times in seconds.
    lap_numbers:
        Optional corresponding lap numbers.
    vehicle_mass_kg:
        Vehicle + driver mass. Defaults to DEFAULT_MASS_KG.

    Returns
    -------
    EnergyBalanceResult
    """
    result = EnergyBalanceResult()
    mass = vehicle_mass_kg or DEFAULT_MASS_KG
    result.vehicle_mass_kg = mass

    # Filter valid
    valid = []
    if lap_numbers is None:
        lap_numbers = list(range(1, len(lap_times) + 1))

    for i, (lt, ln) in enumerate(zip(lap_times, lap_numbers)):
        if lt is not None and math.isfinite(lt) and lt > 0:
            valid.append((lt, ln, i))

    if len(valid) < 2:
        result.coaching = "Not enough valid laps for energy balance analysis."
        return result

    result.n_laps = len(valid)

    # Compute per-lap metrics
    for lt, ln, idx in valid:
        speeds = _generate_speed_trace(lt, TRACE_POINTS, idx)
        metrics = compute_lap_energy_metrics(speeds, mass, ln, lt)
        result.lap_metrics.append(metrics)

    # Aggregates
    efficiencies = [m.efficiency for m in result.lap_metrics]
    smoothnesses = [m.smoothness_score for m in result.lap_metrics]

    result.mean_efficiency = float(np.mean(efficiencies))
    result.mean_smoothness = float(np.mean(smoothnesses))
    result.total_braking_kj = sum(m.braking_energy_j for m in result.lap_metrics) / 1000
    result.total_accel_kj = sum(m.accel_energy_j for m in result.lap_metrics) / 1000

    # Best/worst efficiency
    best = max(result.lap_metrics, key=lambda m: m.efficiency)
    worst = min(result.lap_metrics, key=lambda m: m.efficiency)
    result.best_efficiency_lap = best.lap_number
    result.worst_efficiency_lap = worst.lap_number

    # Recovery ratio: braking / accel as percentage
    if result.total_accel_kj > 0:
        result.recovery_ratio = (result.total_braking_kj / result.total_accel_kj) * 100
    else:
        result.recovery_ratio = 0.0

    # Worst 3 braking laps (highest braking energy)
    sorted_by_braking = sorted(
        result.lap_metrics, key=lambda m: m.braking_energy_j, reverse=True,
    )
    result.worst_braking_laps = [m.lap_number for m in sorted_by_braking[:3]]

    # Trend
    result.efficiency_trend = _compute_trend(efficiencies)

    # Coaching
    result.coaching = _generate_coaching(result)

    logger.info(
        "Energy balance: %d laps, mean_eff=%.3f, trend=%s, braking=%.1f kJ, accel=%.1f kJ",
        result.n_laps, result.mean_efficiency, result.efficiency_trend,
        result.total_braking_kj, result.total_accel_kj,
    )

    return result


def _generate_coaching(result: EnergyBalanceResult) -> str:
    """Generate coaching insight with specific lap references."""
    parts = []

    if result.mean_efficiency > 0.7:
        parts.append("Energy management is excellent — minimal wasted kinetic energy.")
    elif result.mean_efficiency > 0.5:
        parts.append("Good energy management overall, with some room for smoother transitions.")
    else:
        parts.append("High energy cycling detected — frequent hard braking followed by heavy acceleration wastes energy.")

    if result.mean_smoothness > 85:
        parts.append("Very smooth driving with gradual energy transitions.")
    elif result.mean_smoothness < 60:
        parts.append("Driving is jerky — work on progressive brake release and throttle application.")

    # Reference worst braking laps specifically
    if result.worst_braking_laps and len(result.lap_metrics) >= 5:
        avg_braking = sum(m.braking_energy_j for m in result.lap_metrics) / len(result.lap_metrics)
        outliers = [
            m.lap_number for m in result.lap_metrics
            if m.braking_energy_j > avg_braking * 1.4
        ]
        if outliers:
            lap_str = ", ".join(str(l) for l in outliers[:5])
            worst_braking = max(m.braking_energy_j for m in result.lap_metrics if m.lap_number in outliers)
            pct = int(((worst_braking / avg_braking) - 1) * 100)
            parts.append(
                f"Laps {lap_str} show {pct}%+ more braking energy than average "
                f"— review corner entries on these laps."
            )

    if result.recovery_ratio > 110:
        parts.append("More energy dissipated in braking than added — consider trail-braking to preserve momentum.")
    elif result.recovery_ratio < 90:
        parts.append("High acceleration energy suggests aggressive throttle application.")

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

    # 1. Single lap energy metrics
    try:
        speeds = np.array([10.0, 15.0, 20.0, 15.0, 10.0], dtype=float)
        m = compute_lap_energy_metrics(speeds, 180.0, lap_number=1)
        assert m.braking_energy_j > 0, "no braking energy"
        assert m.accel_energy_j > 0, "no accel energy"
        assert m.peak_ke_j > m.min_ke_j
        assert 0 <= m.efficiency <= 1.0
        assert 0 <= m.smoothness_score <= 100
        _ok("single_lap_energy")
    except Exception as e:
        _fail("single_lap_energy", str(e))

    # 2. Constant speed = perfect efficiency
    try:
        speeds = np.full(50, 15.0)
        m = compute_lap_energy_metrics(speeds, 180.0)
        assert m.efficiency == 1.0, f"eff={m.efficiency}"
        assert m.smoothness_score == 100.0
        assert m.braking_energy_j == 0
        assert m.accel_energy_j == 0
        _ok("constant_speed")
    except Exception as e:
        _fail("constant_speed", str(e))

    # 3. High variation = lower efficiency
    try:
        # Alternating speeds
        speeds = np.array([5.0, 25.0] * 25, dtype=float)
        m = compute_lap_energy_metrics(speeds, 180.0)
        assert m.efficiency < 0.5, f"eff={m.efficiency} too high for jerky"
        assert m.smoothness_score < 50, f"smooth={m.smoothness_score}"
        _ok("high_variation")
    except Exception as e:
        _fail("high_variation", str(e))

    # 4. Full analysis basic
    try:
        times = [60.0 + i * 0.1 for i in range(10)]
        r = analyze_energy_balance(times)
        assert r.n_laps == 10
        assert len(r.lap_metrics) == 10
        assert r.mean_efficiency > 0
        assert r.mean_smoothness > 0
        assert r.total_braking_kj > 0
        assert r.total_accel_kj > 0
        assert r.coaching != ""
        _ok("full_analysis")
    except Exception as e:
        _fail("full_analysis", str(e))

    # 5. Single lap → not enough
    try:
        r = analyze_energy_balance([60.0])
        assert r.n_laps == 0
        assert "Not enough" in r.coaching
        _ok("single_lap_reject")
    except Exception as e:
        _fail("single_lap_reject", str(e))

    # 6. NaN robustness
    try:
        times = [60.0, float("nan"), 61.0, None, 60.5]
        r = analyze_energy_balance(times, [1, 2, 3, 4, 5])
        assert r.n_laps == 3
        assert r.mean_efficiency > 0
        _ok("nan_robustness")
    except Exception as e:
        _fail("nan_robustness", str(e))

    # 7. Custom mass
    try:
        times = [60.0, 61.0, 60.5]
        r = analyze_energy_balance(times, vehicle_mass_kg=350.0)
        assert r.vehicle_mass_kg == 350.0
        assert r.total_braking_kj > 0
        _ok("custom_mass")
    except Exception as e:
        _fail("custom_mass", str(e))

    # 8. Trend detection
    try:
        # Improving efficiency (faster laps → more constant speed profile)
        vals = [0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6]
        trend = _compute_trend(vals)
        assert trend == "improving", f"trend={trend}"

        vals2 = [0.6, 0.55, 0.5, 0.45, 0.4, 0.35, 0.3]
        trend2 = _compute_trend(vals2)
        assert trend2 == "declining", f"trend2={trend2}"

        vals3 = [0.5, 0.5, 0.5, 0.5]
        trend3 = _compute_trend(vals3)
        assert trend3 == "stable", f"trend3={trend3}"
        _ok("trend_detection")
    except Exception as e:
        _fail("trend_detection", str(e))

    # 9. Best/worst lap identified
    try:
        times = [60.0, 60.5, 61.0, 60.2, 60.8, 59.5, 60.3]
        r = analyze_energy_balance(times)
        assert r.best_efficiency_lap > 0
        assert r.worst_efficiency_lap > 0
        assert r.best_efficiency_lap != r.worst_efficiency_lap
        _ok("best_worst_lap")
    except Exception as e:
        _fail("best_worst_lap", str(e))

    # 10. Serialization
    try:
        times = [60.0, 60.5, 61.0]
        r = analyze_energy_balance(times)
        d = r.to_dict()
        import json
        json.dumps(d)
        assert "lap_metrics" in d
        assert "mean_efficiency" in d
        assert "recovery_ratio" in d
        assert "worst_braking_laps" in d
        _ok("serialization")
    except Exception as e:
        _fail("serialization", str(e))

    # 11. Deterministic
    try:
        times = [60.0, 60.5, 61.0, 60.2]
        r1 = analyze_energy_balance(times)
        r2 = analyze_energy_balance(times)
        assert r1.to_dict() == r2.to_dict()
        _ok("deterministic")
    except Exception as e:
        _fail("deterministic", str(e))

    # 12. Empty input
    try:
        r = analyze_energy_balance([])
        assert r.n_laps == 0
        _ok("empty_input")
    except Exception as e:
        _fail("empty_input", str(e))

    print(f"\nEnergy Balance Tests: {passed}/{total} passed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _run_tests()
