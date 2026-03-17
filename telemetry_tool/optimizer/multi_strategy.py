"""Multi-strategy race planner.

Generates multiple complete race plans with different weather approaches,
scores each on time/risk/flexibility, and returns the top 3.

Pure algorithm — no DB, no Flask.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from optimizer.csp_solver import (
    SolverConfig,
    DriverConstraints,
    SolverResult,
    solve_stints,
)


@dataclass
class StrategyMetrics:
    """Computed metrics for a single strategy."""
    total_drive_s: int = 0
    total_pit_s: int = 0
    pits_in_rain: int = 0
    pits_in_dry: int = 0
    rain_drive_s: int = 0
    dry_drive_s: int = 0
    driver_transitions: int = 0
    min_stint_s: int = 0
    max_stint_s: int = 0
    flexibility_score: float = 0.0
    risk_score: float = 0.0
    regulation_ok: bool = True
    regulation_issues: list[str] = field(default_factory=list)


@dataclass
class RankedStrategy:
    """A complete strategy with its plan and metrics."""
    name: str
    description: str
    approach: str
    result: SolverResult
    metrics: StrategyMetrics
    score: float = 0.0


def _compute_metrics(
    config: SolverConfig,
    result: SolverResult,
    rain_ranges: list[tuple[int, int]],
) -> StrategyMetrics:
    """Compute detailed metrics for a solver result."""
    m = StrategyMetrics()
    if not result.stints:
        return m

    def _in_rain(t: int) -> bool:
        return any(s <= t < e for s, e in rain_ranges)

    prev_driver = None
    stint_durations = []
    for s in result.stints:
        dur = s.duration_s
        stint_durations.append(dur)
        m.total_drive_s += dur
        overlap = 0
        for rs, re in rain_ranges:
            os = max(s.start_s, rs)
            oe = min(s.start_s + dur, re)
            if oe > os:
                overlap += oe - os
        m.rain_drive_s += overlap
        m.dry_drive_s += dur - overlap
        if prev_driver is not None and prev_driver != s.driver_id:
            m.driver_transitions += 1
        prev_driver = s.driver_id

    m.min_stint_s = min(stint_durations) if stint_durations else 0
    m.max_stint_s = max(stint_durations) if stint_durations else 0

    for ps in result.pit_stops:
        pit_dur = ps.duration_s or config.pit_time_s
        m.total_pit_s += pit_dur
        if _in_rain(ps.at_s):
            m.pits_in_rain += 1
        else:
            m.pits_in_dry += 1

    ideal = m.total_drive_s / max(1, len(result.stints))
    adjustable = sum(1 for d in stint_durations if d > ideal * 0.5)
    m.flexibility_score = adjustable / max(1, len(result.stints))

    risk = 0.0
    short_streak = 0
    for d in stint_durations:
        if d < ideal * 0.6:
            short_streak += 1
            risk += short_streak * 0.05
        else:
            short_streak = 0
    risk += (1 - m.flexibility_score) * 0.3
    if m.max_stint_s > 0:
        variation = (m.max_stint_s - m.min_stint_s) / m.max_stint_s
        risk += variation * 0.2
    m.risk_score = min(1.0, risk)
    m.regulation_ok = len(result.violations) == 0
    m.regulation_issues = list(result.violations)
    return m


def _stint_signature(result: SolverResult) -> str:
    """Hash-like signature of a plan for dedup."""
    return "|".join(
        f"{s.driver_id}:{s.duration_s // 60}"
        for s in result.stints
    )


def _best_wet_driver(drivers: list[DriverConstraints]) -> DriverConstraints:
    """Find the driver with highest wet_confidence."""
    return max(drivers, key=lambda d: d.wet_confidence)


def _force_wet_driver_for_rain(
    drivers: list[DriverConstraints],
    rain_start: int,
    rain_end: int,
) -> list[DriverConstraints]:
    """Create modified driver list where only the best wet driver can
    drive during rain. Other drivers get a synthetic sleep window for
    the rain period, forcing the solver to assign the wet specialist.
    """
    best = _best_wet_driver(drivers)
    modified = []
    for d in drivers:
        if d.id == best.id:
            # Wet specialist: keep as-is, respect existing rules
            cd = copy.deepcopy(d)
            modified.append(cd)
        else:
            # Other drivers: add sleep window during rain so solver
            # can't assign them to rain stints
            cd = copy.deepcopy(d)
            cd.sleep_windows = list(cd.sleep_windows) + [(rain_start, rain_end)]
            modified.append(cd)
    return modified


def generate_strategies(
    config: SolverConfig,
    drivers: list[DriverConstraints],
) -> list[RankedStrategy]:
    """Generate multiple race plans with genuinely different approaches.

    Returns up to 3 diverse strategies, scored and ranked.
    """
    rain_ranges: list[tuple[int, int]] = []
    for w in config.weather_windows:
        if w.get("condition") in ("wet", "damp"):
            rain_ranges.append((w.get("start_s", 0), w.get("end_s", 0)))

    rain_window = rain_ranges[0] if rain_ranges else None
    rain_dur = (rain_window[1] - rain_window[0]) if rain_window else 0
    pit_time = config.pit_time_s

    # All strategies use the SAME n_stints — adding pits costs time.
    # The difference is WHEN pits happen and WHO drives in rain.
    # Each entry: (key, name, description, solver_config, driver_list)
    n = config.n_stints
    strategies: list[tuple[str, str, str, SolverConfig, list[DriverConstraints]]] = []

    # 1. Stay Out — ignore rain, keep current plan unchanged
    cfg1 = copy.deepcopy(config)
    cfg1.weather_windows = []
    strategies.append((
        "stay_out", "Stay Out",
        "Ignore rain — keep driving the original plan",
        cfg1, drivers,
    ))

    if rain_window and rain_dur > 0:
        rs, re = rain_window
        best_wet = _best_wet_driver(drivers)

        # 2. Pit Stack — same stints, but cluster pits during rain
        # Weather nudging shortens rain stints and extends dry ones,
        # so pits naturally fall in the rain window.
        cfg2 = copy.deepcopy(config)
        strategies.append((
            "pit_stack", "Pit Stack",
            "Same pit count — cluster pit stops during rain for cheaper pit time",
            cfg2, drivers,
        ))

        # 3. Wet Driver — same stints, force wet specialist into rain
        cfg3 = copy.deepcopy(config)
        wet_drivers = _force_wet_driver_for_rain(drivers, rs, re)
        strategies.append((
            "wet_driver", "Wet Driver",
            f"Same pit count — {best_wet.name} covers rain window",
            cfg3, wet_drivers,
        ))

        # 4. Ride Through — no weather adjustment, wet driver rides through
        cfg4 = copy.deepcopy(config)
        cfg4.weather_windows = []  # no stint shortening during rain
        wet_drivers_ride = _force_wet_driver_for_rain(drivers, rs, re)
        strategies.append((
            "ride_through", "Ride Through",
            f"No rain adjustment — {best_wet.name} rides through at normal stint length",
            cfg4, wet_drivers_ride,
        ))
    else:
        # No rain — offer longer vs shorter stint alternatives
        cfg_more = copy.deepcopy(config)
        cfg_more.n_stints = n + 2
        strategies.append((
            "more_pits", "More Pits",
            "2 extra stints — shorter stints, more flexibility",
            cfg_more, drivers,
        ))
        cfg_fewer = copy.deepcopy(config)
        cfg_fewer.n_stints = max(2, n - 2)
        strategies.append((
            "fewer_pits", "Fewer Pits",
            "2 fewer stints — longer stints, fewer pit stops",
            cfg_fewer, drivers,
        ))

    # ── Run solver for each strategy ──────────────────────────────────
    results: list[RankedStrategy] = []
    seen_signatures: set[str] = set()

    for strategy_key, name, description, variant_config, driver_list in strategies:
        result = solve_stints(variant_config, driver_list)
        if not result.stints:
            continue

        sig = _stint_signature(result)
        if sig in seen_signatures:
            continue
        seen_signatures.add(sig)

        metrics = _compute_metrics(config, result, rain_ranges)
        if not metrics.regulation_ok:
            continue

        pit_time_saved = metrics.pits_in_rain * 5
        time_score = pit_time_saved / max(1, metrics.total_pit_s) * 100
        risk_penalty = metrics.risk_score * 50
        flex_bonus = metrics.flexibility_score * 20
        score = time_score - risk_penalty + flex_bonus

        results.append(RankedStrategy(
            name=name, description=description, approach=strategy_key,
            result=result, metrics=metrics, score=score,
        ))

    results.sort(key=lambda r: -r.score)

    if len(results) <= 3:
        return results

    # Pick 3 diverse strategies: best score, a wet-driver strategy, and one more
    top3: list[RankedStrategy] = [results[0]]

    # Always include a wet-driver strategy if available
    wet_strats = [r for r in results if r.approach in ("wet_driver", "rain_specialist", "ride_through")]
    if wet_strats and wet_strats[0] not in top3:
        top3.append(wet_strats[0])

    # Fill with next best unique
    for r in results:
        if len(top3) >= 3:
            break
        if r not in top3:
            top3.append(r)

    return top3[:3]
