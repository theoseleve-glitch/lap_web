"""CSP backtracking solver for race stint planning.

Pure algorithm -- no DB, no Flask, no side effects.
Takes race config + driver constraints, returns a feasible stint plan.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SolverConfig:
    race_duration_s: int
    n_stints: int
    pit_time_s: int = 120
    fuel_capacity_kg: float = 0.0
    fuel_burn_rate_kgs: float = 0.0
    initial_fuel_kg: float = 0.0  # fuel at start of stint 1 (post-quali); 0 = use fuel_capacity_kg
    blackout_start_s: int = 0
    blackout_end_s: int = 0
    quick_change: bool = False
    optimization_mode: str = "equal"  # "equal" or "performance"
    weather_windows: list[dict] = field(default_factory=list)


@dataclass
class DriverConstraints:
    id: int
    name: str
    avg_lap_time_s: float = 60.0
    weight_kg: float = 70.0
    wet_confidence: float = 0.5
    max_stint_s: int | None = None
    min_stint_s: int | None = None
    max_cumulative_s: int | None = None
    min_cumulative_s: int | None = None
    min_rest_s: int = 0
    allow_double_stint: bool = False
    sleep_windows: list[tuple[int, int]] = field(default_factory=list)


@dataclass
class StintResult:
    stint_order: int
    driver_id: int
    driver_name: str
    start_s: int
    duration_s: int
    fuel_at_start: float = 0.0
    fuel_at_end: float = 0.0


@dataclass
class PitStopResult:
    after_stint: int
    at_s: int
    duration_s: int
    refuel: bool
    driver_change: bool


@dataclass
class SolverResult:
    feasible: bool
    stints: list[StintResult]
    pit_stops: list[PitStopResult]
    violations: list[str]
    warnings: list[str]
    driver_summary: dict[str, Any]


def _is_sleeping(driver: DriverConstraints, start: int, end: int) -> bool:
    """Check whether a driver's sleep window overlaps [start, end)."""
    for sw_start, sw_end in driver.sleep_windows:
        if max(start, sw_start) < min(end, sw_end):
            return True
    return False


def _get_weather_at(config: SolverConfig, time_s: int) -> str:
    """Return the weather condition at a given race-clock second."""
    for w in config.weather_windows:
        if w.get("start_s", 0) <= time_s < w.get("end_s", 0):
            return w.get("condition", "dry")
    return "dry"


def _effective_lap_time(driver: DriverConstraints, condition: str) -> float:
    """Compute weather-adjusted lap time. Low wet_confidence => slower."""
    if condition in ("wet", "damp") and driver.wet_confidence > 0:
        factor = (
            0.5 + 0.5 * driver.wet_confidence
            if condition == "damp"
            else driver.wet_confidence
        )
        return driver.avg_lap_time_s / factor
    return driver.avg_lap_time_s


def _weather_adjusted_duration(
    config: SolverConfig,
    clock: int,
    ideal_duration: int,
    min_dur: int,
    max_dur: int,
    pit_time: int,
) -> int:
    """Nudge stint duration to stack pit stops during rain.

    Core insight: pit stops cost fewer laps in rain (everyone is slower).
    So we want MORE pits during rain, FEWER during dry.

    Strategy:
    - SHORTEN stints during rain → more pits happen in slow conditions
    - EXTEND stints in dry before rain → delay pit until rain starts
    - EXTEND stints in dry after rain → avoid pitting right after rain ends
    - Tolerance: nudge up to 25% of ideal duration.
    """
    if not config.weather_windows:
        return ideal_duration

    pit_at = clock + ideal_duration
    nudge_tolerance = max(int(ideal_duration * 0.35), 1800)  # at least 30 min or 35% of stint

    best_duration = ideal_duration
    best_score = 0.0

    for w in config.weather_windows:
        w_start = w.get("start_s", 0)
        w_end = w.get("end_s", 0)
        condition = w.get("condition", "dry")
        if condition == "dry":
            continue

        # Strategy 1: currently in DRY, rain starts soon → EXTEND stint
        # to push pit into the rain window (pit during rain = cheap)
        if clock < w_start and w_start - pit_at <= nudge_tolerance and w_start > pit_at:
            extended = w_start - clock
            if min_dur <= extended <= max_dur:
                score = 2.5  # strongest: delay pit to rain boundary
                if score > best_score:
                    best_duration = extended
                    best_score = score

        # Strategy 2: currently IN RAIN → USE MINIMUM STINT
        # Stack as many pits as possible during slow conditions.
        if w_start <= clock < w_end:
            # Use regulation minimum stint length to maximize rain pits
            shortened = min_dur
            if shortened <= max_dur:
                score = 2.0
                if score > best_score:
                    best_duration = shortened
                    best_score = score

        # Strategy 3: rain ending soon → SHORTEN to pit before dry
        # so the next driver starts fresh on a drying track
        if w_start <= clock < w_end and w_end - clock <= ideal_duration:
            to_rain_end = w_end - clock
            shortened = max(min_dur, to_rain_end - pit_time)
            if min_dur <= shortened <= max_dur:
                score = 1.5
                if score > best_score:
                    best_duration = shortened
                    best_score = score

        # Strategy 4: just after rain ended → EXTEND stint
        # avoid wasting a pit in the first dry laps
        if clock >= w_end and clock - w_end < nudge_tolerance:
            extended = min(max_dur, int(ideal_duration * 1.2))
            if extended >= min_dur:
                score = 1.0
                if score > best_score:
                    best_duration = extended
                    best_score = score

    return best_duration


def _priority_score(config: SolverConfig, clock: int) -> float:
    """Competitive-period weighting: 1.5x start/end, 2.0x post-weather."""
    race_dur = config.race_duration_s
    if clock < race_dur * 0.05:
        return 1.5
    if clock > race_dur * 0.9:
        return 1.5
    for w in config.weather_windows:
        transition_at = w.get("start_s", 0)
        if transition_at <= clock < transition_at + 300:
            return 2.0
        end_at = w.get("end_s", 0)
        if end_at <= clock < end_at + 300:
            return 2.0
    return 1.0


def _driver_score(
    driver: DriverConstraints,
    config: SolverConfig,
    clock: int,
    driver_budgets: dict[int, float] | None,
) -> float:
    """Score a driver for a stint slot. Higher = preferred.

    Equal mode: all drivers score equally (1.0) — pure round-robin.
    Performance mode: faster drivers score higher via budget weighting.
    In wet conditions, wet_confidence is always used regardless of mode.
    """
    condition = _get_weather_at(config, clock)
    priority = _priority_score(config, clock)

    if condition in ("wet", "damp"):
        # Always prefer high wet-confidence drivers in rain
        return driver.wet_confidence * priority

    if driver_budgets and driver.id in driver_budgets:
        # Performance mode: weight by speed-proportional budget
        total_budget = sum(driver_budgets.values())
        if total_budget > 0:
            return (driver_budgets[driver.id] / total_budget) * priority

    # Equal mode: all drivers equal — round-robin via constraint filtering only
    return 1.0 * priority


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def solve_stints(
    config: SolverConfig,
    drivers: list[DriverConstraints],
) -> SolverResult:
    """Solve stint assignment using CSP backtracking.

    Returns a SolverResult with feasible=True if a valid plan was found.
    Max 200 backtracks, then returns best partial solution.
    """
    if not drivers:
        return SolverResult(
            feasible=False, stints=[], pit_stops=[],
            violations=["No drivers"], warnings=[], driver_summary={},
        )

    n = config.n_stints
    pit_time = config.pit_time_s
    race_dur = config.race_duration_s
    drive_time = race_dur - (n - 1) * pit_time

    if drive_time <= 0:
        return SolverResult(
            feasible=False, stints=[], pit_stops=[],
            violations=["Pit stops exceed race duration"], warnings=[],
            driver_summary={},
        )

    ideal_stint = drive_time / n

    # Performance mode: distribute drive time proportional to speed
    driver_budgets: dict[int, float] | None = None
    if config.optimization_mode == "performance":
        avg_times = {
            d.id: d.avg_lap_time_s
            for d in drivers
            if d.avg_lap_time_s > 0
        }
        if len(avg_times) >= 2:
            inv_sum = sum(1.0 / v for v in avg_times.values())
            driver_budgets = {
                did: ((1.0 / avg) / inv_sum) * drive_time
                for did, avg in avg_times.items()
            }

    # Mutable best-so-far containers shared across recursion
    best_result: list[tuple[int, int, int, float]] = []
    best_violations: list[str] = []

    def _eligible_candidates(
        clock: int,
        prev_driver: int | None,
        cumulative: dict[int, int],
        last_end: dict[int, int],
        relax_double: bool,
    ) -> list[tuple[float, DriverConstraints]]:
        """Collect and score eligible drivers for the current slot."""
        candidates: list[tuple[float, DriverConstraints]] = []
        for d in drivers:
            est_end = clock + ideal_stint
            if _is_sleeping(d, clock, int(est_end)):
                continue
            if (
                not relax_double
                and prev_driver == d.id
                and not d.allow_double_stint
                and len(drivers) > 1
            ):
                continue
            if d.id in last_end and d.min_rest_s > 0:
                if clock - last_end[d.id] < d.min_rest_s:
                    continue
            if d.max_cumulative_s and cumulative.get(d.id, 0) >= d.max_cumulative_s:
                continue
            score = _driver_score(d, config, clock, driver_budgets)
            candidates.append((score, d))
        candidates.sort(key=lambda x: -x[0])
        return candidates

    def _feasible_duration(
        driver: DriverConstraints,
        slot: int,
        clock: int,
        fuel: float,
        cumulative: dict[int, int],
        assignments: list[tuple[int, int, int, float]],
    ) -> tuple[int, int] | None:
        """Compute (min_dur, duration) for a driver in this slot.

        Returns None if the slot is infeasible for this driver.
        """
        did = driver.id
        remaining_drive = drive_time - sum(a[2] for a in assignments)
        remaining_stints = n - slot

        # Dynamic ideal factoring in awake drivers
        awake = max(1, sum(
            1 for d in drivers
            if not _is_sleeping(d, clock, int(clock + ideal_stint))
        ))
        dynamic_ideal = remaining_drive / max(1, remaining_stints)
        if awake < len(drivers):
            dynamic_ideal = min(
                dynamic_ideal * len(drivers) / awake,
                remaining_drive / awake,
            )

        # Performance budget: steer toward proportional share
        if driver_budgets and did in driver_budgets:
            spent = cumulative.get(did, 0)
            budget_remaining = driver_budgets[did] - spent
            if budget_remaining > 0:
                # Count how many more stints this driver is likely to get
                driver_remaining_stints = max(
                    1,
                    (remaining_stints + 1) // len(drivers),
                )
                budget_ideal = budget_remaining / driver_remaining_stints
                dynamic_ideal = budget_ideal

        # max_dur starts at ideal; weather nudging may override in _weather_adjusted_duration
        max_dur = int(dynamic_ideal)
        # Add headroom ONLY if a rain boundary is near this stint's pit time
        if config.weather_windows:
            pit_at = clock + int(dynamic_ideal)
            for w in config.weather_windows:
                ws = w.get("start_s", 0)
                if w.get("condition", "dry") != "dry" and ws > pit_at and ws - pit_at < 1800:
                    # Rain starts soon after our pit — allow extending to reach it
                    max_dur = max(max_dur, ws - clock)
                    break

        # Fuel cap
        current_fuel = fuel
        if config.quick_change and slot > 0:
            current_fuel = config.fuel_capacity_kg
        if config.fuel_burn_rate_kgs > 0 and current_fuel > 0:
            fuel_cap = int(current_fuel / config.fuel_burn_rate_kgs)
            max_dur = min(max_dur, fuel_cap)

        # Driver max stint
        if driver.max_stint_s:
            max_dur = min(max_dur, driver.max_stint_s)

        # Cumulative cap
        if driver.max_cumulative_s:
            cum_room = driver.max_cumulative_s - cumulative.get(did, 0)
            max_dur = min(max_dur, cum_room)

        # Sleep window: clamp to before next sleep start
        for sw_start, _sw_end in driver.sleep_windows:
            if clock < sw_start < clock + max_dur:
                max_dur = sw_start - clock

        # Blackout start: first stint must be at least this long
        if slot == 0 and config.blackout_start_s > 0:
            max_dur = max(max_dur, config.blackout_start_s)

        # Blackout end: last pit must be before cutoff
        if slot == n - 1 and config.blackout_end_s > 0:
            max_dur = max(max_dur, remaining_drive)

        # Last stint must absorb whatever drive time remains, but still
        # respect hard caps (max_stint, cumulative, fuel).  If the
        # remaining time exceeds what this driver can handle, the
        # slot is infeasible and the solver will backtrack.
        if slot == n - 1:
            min_dur = remaining_drive
            # Re-apply hard caps on top of required remaining drive
            cap = remaining_drive
            if driver.max_stint_s:
                cap = min(cap, driver.max_stint_s)
            if driver.max_cumulative_s:
                cap = min(
                    cap,
                    driver.max_cumulative_s - cumulative.get(did, 0),
                )
            if config.fuel_burn_rate_kgs > 0 and current_fuel > 0:
                cap = min(cap, int(current_fuel / config.fuel_burn_rate_kgs))
            max_dur = cap
        else:
            min_dur = driver.min_stint_s or 60

        if max_dur < min_dur:
            return None

        duration = max(min_dur, min(max_dur, int(dynamic_ideal)))

        # Weather-aware nudging: shift pit boundaries to align with rain
        duration = _weather_adjusted_duration(
            config, clock, duration, min_dur, max_dur, config.pit_time_s,
        )

        return min_dur, duration

    def _solve(
        slot: int,
        clock: int,
        fuel: float,
        cumulative: dict[int, int],
        last_end: dict[int, int],
        prev_driver: int | None,
        assignments: list[tuple[int, int, int, float]],
        backtracks: list[int],
    ) -> bool:
        nonlocal best_result, best_violations

        if backtracks[0] > 5000:
            return False

        # Terminal: all slots filled
        if slot == n:
            violations = []
            for d in drivers:
                total = cumulative.get(d.id, 0)
                if d.min_cumulative_s and total < d.min_cumulative_s:
                    violations.append(
                        f"{d.name} cumulative {total}s < min {d.min_cumulative_s}s"
                    )
            if not violations:
                best_result[:] = assignments[:]
                best_violations[:] = []
                return True
            if len(violations) < len(best_violations) or not best_result:
                best_result[:] = assignments[:]
                best_violations[:] = violations[:]
            return False

        # Build candidate list; relax double-stint if nobody qualifies
        candidates = _eligible_candidates(
            clock, prev_driver, cumulative, last_end, relax_double=False,
        )
        if not candidates:
            candidates = _eligible_candidates(
                clock, prev_driver, cumulative, last_end, relax_double=True,
            )

        for _, driver in candidates:
            did = driver.id

            result = _feasible_duration(
                driver, slot, clock, fuel, cumulative, assignments,
            )
            if result is None:
                continue
            _min_dur, duration = result

            # Compute fuel after stint
            current_fuel = fuel
            if config.quick_change and slot > 0:
                current_fuel = config.fuel_capacity_kg
            fuel_after = current_fuel - config.fuel_burn_rate_kgs * duration

            # Decide refuel at next pit: refuel if remaining fuel
            # cannot sustain the expected next stint duration
            next_fuel = fuel_after
            if slot < n - 1 and config.fuel_capacity_kg > 0:
                remaining_after = drive_time - sum(
                    a[2] for a in assignments
                ) - duration
                remaining_slots = n - slot - 1
                expected_next = (
                    remaining_after / remaining_slots
                    if remaining_slots > 0
                    else 0
                )
                next_fuel_need = config.fuel_burn_rate_kgs * expected_next
                if fuel_after < next_fuel_need:
                    next_fuel = config.fuel_capacity_kg

            # Commit assignment and recurse
            new_cum = dict(cumulative)
            new_cum[did] = new_cum.get(did, 0) + duration
            new_last = dict(last_end)
            new_last[did] = clock + duration

            assignments.append((did, clock, duration, current_fuel))
            next_clock = clock + duration + (pit_time if slot < n - 1 else 0)

            if _solve(
                slot + 1, next_clock, next_fuel,
                new_cum, new_last, did, assignments, backtracks,
            ):
                return True

            assignments.pop()
            backtracks[0] += 1

        return False

    # -- Run the search --
    backtracks = [0]
    start_fuel = config.initial_fuel_kg if config.initial_fuel_kg > 0 else config.fuel_capacity_kg
    _solve(0, 0, start_fuel, {}, {}, None, [], backtracks)

    # -- Build structured result from best_result --
    stints: list[StintResult] = []
    pit_stops: list[PitStopResult] = []
    driver_map = {d.id: d for d in drivers}

    for i, (did, start, dur, fuel_start) in enumerate(best_result):
        d = driver_map[did]
        actual_fuel_start = fuel_start
        if config.quick_change and i > 0:
            actual_fuel_start = config.fuel_capacity_kg
        fuel_end = actual_fuel_start - config.fuel_burn_rate_kgs * dur

        stints.append(StintResult(
            stint_order=i + 1,
            driver_id=did,
            driver_name=d.name,
            start_s=start,
            duration_s=dur,
            fuel_at_start=actual_fuel_start,
            fuel_at_end=fuel_end,
        ))

        if i < len(best_result) - 1:
            next_did = best_result[i + 1][0]
            next_dur = best_result[i + 1][2]
            next_fuel_need = config.fuel_burn_rate_kgs * next_dur
            needs_refuel = (
                fuel_end < next_fuel_need and config.fuel_capacity_kg > 0
            )
            pit_stops.append(PitStopResult(
                after_stint=i + 1,
                at_s=start + dur,
                duration_s=config.pit_time_s,
                refuel=needs_refuel,
                driver_change=did != next_did,
            ))

    # Driver summary
    summary: dict[str, Any] = {}
    for d in drivers:
        d_stints = [s for s in stints if s.driver_id == d.id]
        summary[d.name] = {
            "total_drive_s": sum(s.duration_s for s in d_stints),
            "stints": len(d_stints),
        }

    return SolverResult(
        feasible=len(best_result) > 0 and len(best_violations) == 0,
        stints=stints,
        pit_stops=pit_stops,
        violations=best_violations,
        warnings=(
            [f"Backtracked {backtracks[0]} times"] if backtracks[0] > 0 else []
        ),
        driver_summary=summary,
    )
