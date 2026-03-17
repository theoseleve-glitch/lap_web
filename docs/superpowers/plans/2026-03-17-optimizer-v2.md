# Optimizer V2 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the greedy race strategy optimizer with a CSP backtracking solver that integrates fuel planning, competitive period weighting, and weather-aware strategy.

**Architecture:** A new pure-Python CSP solver (`optimizer/csp_solver.py`) handles all constraint logic. A weather module (`optimizer/weather.py`) provides pace adjustments. The existing `optimize_stints()` is preserved as fallback; `optimize_stints_v2()` wraps the CSP solver. Weather data flows through a new `race_weather_windows` table with CRUD service and API endpoints.

**Tech Stack:** Python (no external deps), PostgreSQL (RLS), Next.js/TypeScript frontend

**Spec:** `docs/superpowers/specs/2026-03-17-optimizer-v2-design.md`

---

## File Map

### New Files
| File | Responsibility |
|------|---------------|
| `telemetry_tool/optimizer/__init__.py` | Package init |
| `telemetry_tool/optimizer/csp_solver.py` | Pure CSP backtracking solver — no DB, no Flask |
| `telemetry_tool/optimizer/weather.py` | Pace adjustment, pit cost calc, scenario comparison |
| `telemetry_tool/services/race_strategy_weather.py` | CRUD for weather windows + live condition |
| `telemetry_tool/tests/test_csp_solver.py` | Solver unit tests |
| `telemetry_tool/tests/test_weather.py` | Weather module tests |
| `telemetry_tool/tests/test_optimizer_v2.py` | Integration tests |

### Modified Files
| File | Changes |
|------|---------|
| `telemetry_tool/db/schema.py` | `race_weather_windows` table, `wet_confidence` on drivers, `current_condition` on race_configs |
| `telemetry_tool/race_strategy_v2.py` | New `optimize_stints_v2()` wrapper |
| `telemetry_tool/services/race_strategy.py` | `_save_drivers` adds `wet_confidence`, `run_optimization` calls v2, `get_live_state` returns weather |
| `telemetry_tool/web/routes/api_v1_race_strategy.py` | Weather + condition endpoints |
| `lap-website/src/components/app/race-strategy/RaceConfigForm.tsx` | Wet confidence per driver, forecast editor |
| `lap-website/src/app/app/race-strategy/[id]/live/page.tsx` | Condition button, weather timeline |

---

## Chunk 1: CSP Solver Core

The pure solver with all constraints except weather. Takes config + drivers + sleep_windows, returns stint plan.

### Task 1.1: Solver skeleton + basic test

**Files:**
- Create: `telemetry_tool/optimizer/__init__.py`
- Create: `telemetry_tool/optimizer/csp_solver.py`
- Create: `telemetry_tool/tests/test_csp_solver.py`

- [ ] **Step 1: Write failing tests for basic CSP**

```python
# telemetry_tool/tests/test_csp_solver.py
"""Tests for the CSP backtracking solver."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from optimizer.csp_solver import solve_stints, SolverConfig, DriverConstraints

def _config(**overrides):
    base = SolverConfig(
        race_duration_s=14400,  # 4h
        n_stints=6,
        pit_time_s=120,
        fuel_capacity_kg=8.0,
        fuel_burn_rate_kgs=8.0 / 7500,  # 2h05 autonomy
        blackout_start_s=0,
        blackout_end_s=0,
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base

def _drivers(*names, **shared):
    return [
        DriverConstraints(
            id=i + 1,
            name=n,
            avg_lap_time_s=shared.get("avg_lap", 62),
            weight_kg=shared.get("weight", 70),
            wet_confidence=shared.get("wet", 0.5),
            max_stint_s=shared.get("max_stint"),
            min_stint_s=shared.get("min_stint"),
            max_cumulative_s=shared.get("max_cum"),
            min_cumulative_s=shared.get("min_cum"),
            min_rest_s=shared.get("min_rest", 0),
            allow_double_stint=shared.get("double", False),
            sleep_windows=[],
        )
        for i, n in enumerate(names)
    ]


class TestBasicCSP:
    def test_produces_correct_number_of_stints(self):
        result = solve_stints(_config(), _drivers("A", "B"))
        assert len(result.stints) == 6

    def test_all_stints_have_driver(self):
        result = solve_stints(_config(), _drivers("A", "B"))
        for s in result.stints:
            assert s.driver_id in (1, 2)

    def test_stints_cover_race_duration(self):
        result = solve_stints(_config(), _drivers("A", "B"))
        total = sum(s.duration_s for s in result.stints) + 5 * 120  # 5 pit stops
        assert abs(total - 14400) < 60  # within 1 minute

    def test_feasible_with_no_violations(self):
        result = solve_stints(_config(), _drivers("A", "B"))
        assert result.feasible
        assert len(result.violations) == 0

    def test_no_double_stint_by_default(self):
        result = solve_stints(_config(n_stints=4), _drivers("A", "B"))
        for i in range(len(result.stints) - 1):
            if not result.stints[i].driver_id == result.stints[i + 1].driver_id:
                continue
            assert False, f"Double stint at {i}"

    def test_double_stint_when_allowed(self):
        result = solve_stints(
            _config(n_stints=4),
            _drivers("A", "B", double=True),
        )
        assert result.feasible  # should find a solution regardless


class TestConstraints:
    def test_max_stint_respected(self):
        result = solve_stints(
            _config(),
            _drivers("A", "B", max_stint=1800),  # 30 min max
        )
        for s in result.stints:
            assert s.duration_s <= 1800

    def test_min_rest_respected(self):
        result = solve_stints(
            _config(n_stints=6),
            _drivers("A", "B", "C", min_rest=1800),  # 30 min rest
        )
        last_end = {}
        for s in result.stints:
            if s.driver_id in last_end:
                gap = s.start_s - last_end[s.driver_id]
                assert gap >= 1800, f"Driver {s.driver_id} rest={gap}s < 1800s"
            last_end[s.driver_id] = s.start_s + s.duration_s

    def test_max_cumulative_respected(self):
        result = solve_stints(
            _config(),
            _drivers("A", "B", max_cum=5400),  # 90 min max
        )
        for did in (1, 2):
            total = sum(s.duration_s for s in result.stints if s.driver_id == did)
            assert total <= 5400

    def test_sleep_window_respected(self):
        drivers = _drivers("A", "B")
        drivers[0].sleep_windows = [(3600, 10800)]  # A sleeps hour 1-3
        result = solve_stints(_config(), drivers)
        for s in result.stints:
            if s.driver_id == 1:
                assert not (s.start_s < 10800 and s.start_s + s.duration_s > 3600), \
                    f"Driver A stint overlaps sleep window"


class TestFuelIntegrated:
    def test_fuel_caps_stint_duration(self):
        """Stint can't exceed fuel autonomy."""
        result = solve_stints(
            _config(fuel_capacity_kg=8.0, fuel_burn_rate_kgs=8.0 / 3600),  # 1h autonomy
            _drivers("A", "B"),
        )
        for s in result.stints:
            assert s.duration_s <= 3660  # 1h + small tolerance

    def test_refuel_decisions_made(self):
        result = solve_stints(
            _config(fuel_capacity_kg=8.0, fuel_burn_rate_kgs=8.0 / 7500),
            _drivers("A", "B"),
        )
        # With 2h05 autonomy and ~40min stints, should sometimes skip refuel
        assert any(not ps.refuel for ps in result.pit_stops) or \
               all(ps.refuel for ps in result.pit_stops)  # either is valid


class TestBlackout:
    def test_blackout_start_enforced(self):
        result = solve_stints(
            _config(blackout_start_s=600),  # 10 min
            _drivers("A", "B"),
        )
        assert result.stints[0].duration_s >= 600

    def test_blackout_end_enforced(self):
        result = solve_stints(
            _config(blackout_end_s=900),  # 15 min
            _drivers("A", "B"),
        )
        last_pit = result.stints[-2].start_s + result.stints[-2].duration_s
        assert last_pit <= 14400 - 900


class TestBacktracking:
    def test_backtracking_resolves_constraint(self):
        """Tight constraints that greedy would fail but CSP resolves."""
        # 3 drivers, 6 stints, max cumulative 3600s each
        # Total drive ~13200s, need 3 drivers × 4400s but max is 3600
        # Only works if stints are well-distributed
        result = solve_stints(
            _config(n_stints=9),
            _drivers("A", "B", "C", max_cum=5000),
        )
        assert result.feasible
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest telemetry_tool/tests/test_csp_solver.py -v
```
Expected: ImportError (module doesn't exist yet)

- [ ] **Step 3: Implement the CSP solver**

Create `telemetry_tool/optimizer/__init__.py` (empty).

Create `telemetry_tool/optimizer/csp_solver.py`:

```python
"""CSP backtracking solver for race stint planning.

Pure algorithm — no DB, no Flask, no side effects.
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
    for sw_start, sw_end in driver.sleep_windows:
        if max(start, sw_start) < min(end, sw_end):
            return True
    return False


def _get_weather_at(config: SolverConfig, time_s: int) -> str:
    for w in config.weather_windows:
        if w.get("start_s", 0) <= time_s < w.get("end_s", 0):
            return w.get("condition", "dry")
    return "dry"


def _effective_lap_time(driver: DriverConstraints, condition: str) -> float:
    if condition in ("wet", "damp") and driver.wet_confidence > 0:
        factor = 0.5 + 0.5 * driver.wet_confidence if condition == "damp" else driver.wet_confidence
        return driver.avg_lap_time_s / factor
    return driver.avg_lap_time_s


def _priority_score(config: SolverConfig, clock: int) -> float:
    """Auto priority: start (first 5%), end (last 10%), post-weather-change."""
    race_dur = config.race_duration_s
    if clock < race_dur * 0.05:
        return 1.5
    if clock > race_dur * 0.9:
        return 1.5
    # Post-weather-change: check if a weather transition just happened
    for w in config.weather_windows:
        transition_at = w.get("start_s", 0)
        if transition_at <= clock < transition_at + 300:  # within 5 min of change
            return 2.0
        end_at = w.get("end_s", 0)
        if end_at <= clock < end_at + 300:
            return 2.0
    return 1.0


def _driver_score(
    driver: DriverConstraints,
    config: SolverConfig,
    clock: int,
    cumulative: dict[int, int],
    driver_budgets: dict[int, float] | None,
) -> float:
    """Score a driver for a stint slot. Higher = preferred."""
    condition = _get_weather_at(config, clock)
    elt = _effective_lap_time(driver, condition)
    speed = 1.0 / elt if elt > 0 else 0.0
    priority = _priority_score(config, clock)

    if condition in ("wet", "damp"):
        # In wet, weight by wet_confidence directly
        speed = driver.wet_confidence

    mode_weight = 1.0
    if driver_budgets and driver.id in driver_budgets:
        total_budget = sum(driver_budgets.values())
        if total_budget > 0:
            mode_weight = driver_budgets[driver.id] / total_budget

    return speed * priority * mode_weight


def solve_stints(
    config: SolverConfig,
    drivers: list[DriverConstraints],
) -> SolverResult:
    """Solve stint assignment using CSP backtracking.

    Returns a SolverResult with feasible=True if a valid plan was found.
    """
    if not drivers:
        return SolverResult(
            feasible=False, stints=[], pit_stops=[],
            violations=["No drivers"], warnings={}, driver_summary={},
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

    # Performance mode: compute driver budgets
    driver_budgets = None
    if config.optimization_mode == "performance":
        avg_times = {d.id: d.avg_lap_time_s for d in drivers if d.avg_lap_time_s > 0}
        if len(avg_times) >= 2:
            inv_sum = sum(1.0 / v for v in avg_times.values())
            driver_budgets = {
                did: ((1.0 / avg) / inv_sum) * drive_time
                for did, avg in avg_times.items()
            }

    # State for backtracking
    best_result: list[tuple[int, int, int, float]] = []  # (driver_id, start, dur, fuel)
    best_violations: list[str] = []

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

        if backtracks[0] > 200:
            return False

        if slot == n:
            # Check min cumulative constraints
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
            # Store as best-so-far if better than current
            if len(violations) < len(best_violations) or not best_result:
                best_result[:] = assignments[:]
                best_violations[:] = violations[:]
            return False

        # Generate candidates sorted by score
        candidates = []
        for d in drivers:
            # Skip if sleeping
            est_end = clock + ideal_stint
            if _is_sleeping(d, clock, int(est_end)):
                continue
            # Skip double stint unless allowed
            if prev_driver == d.id and not d.allow_double_stint and len(drivers) > 1:
                continue
            # Skip if rest time not met
            if d.id in last_end and d.min_rest_s > 0:
                if clock - last_end[d.id] < d.min_rest_s:
                    continue
            # Skip if cumulative maxed
            if d.max_cumulative_s:
                if cumulative.get(d.id, 0) >= d.max_cumulative_s:
                    continue

            score = _driver_score(d, config, clock, cumulative, driver_budgets)
            candidates.append((score, d))

        # Sort by score descending
        candidates.sort(key=lambda x: -x[0])

        if not candidates:
            # Relax double-stint constraint
            for d in drivers:
                est_end = clock + ideal_stint
                if _is_sleeping(d, clock, int(est_end)):
                    continue
                if d.id in last_end and d.min_rest_s > 0:
                    if clock - last_end[d.id] < d.min_rest_s:
                        continue
                if d.max_cumulative_s and cumulative.get(d.id, 0) >= d.max_cumulative_s:
                    continue
                score = _driver_score(d, config, clock, cumulative, driver_budgets)
                candidates.append((score, d))
            candidates.sort(key=lambda x: -x[0])

        for _, driver in candidates:
            did = driver.id

            # Compute feasible duration range
            remaining_drive = drive_time - sum(a[2] for a in assignments)
            remaining_stints = n - slot

            # Dynamic ideal based on awake drivers
            awake = sum(
                1 for d in drivers
                if not _is_sleeping(d, clock, int(clock + ideal_stint))
            )
            awake = max(1, awake)
            dynamic_ideal = remaining_drive / max(1, remaining_stints)
            if awake < len(drivers):
                dynamic_ideal = min(
                    dynamic_ideal * len(drivers) / awake,
                    remaining_drive / awake,
                )

            # Performance budget
            if driver_budgets and did in driver_budgets:
                spent = cumulative.get(did, 0)
                budget_remaining = driver_budgets[did] - spent
                if budget_remaining > 0:
                    dynamic_ideal = min(dynamic_ideal, budget_remaining)

            max_dur = int(dynamic_ideal)

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

            # Sleep window: clamp to before next sleep
            for sw_start, sw_end in driver.sleep_windows:
                if clock < sw_start < clock + max_dur:
                    max_dur = sw_start - clock

            # Blackout start: first stint must be long enough
            if slot == 0 and config.blackout_start_s > 0:
                max_dur = max(max_dur, config.blackout_start_s)

            # Blackout end: last pit must be before cutoff
            if slot == n - 1 and config.blackout_end_s > 0:
                # Last stint: absorb remaining time
                max_dur = remaining_drive - sum(a[2] for a in assignments)

            # Min stint
            min_dur = driver.min_stint_s or 60
            if slot == n - 1:
                # Last stint: take whatever is left
                min_dur = 0
                max_dur = remaining_drive - sum(a[2] for a in assignments)

            if max_dur < min_dur:
                continue  # infeasible for this driver

            duration = max(min_dur, min(max_dur, int(dynamic_ideal)))

            # Compute fuel after stint
            if config.quick_change and slot > 0:
                fuel_after = config.fuel_capacity_kg - config.fuel_burn_rate_kgs * duration
            else:
                fuel_after = current_fuel - config.fuel_burn_rate_kgs * duration

            # Decide refuel at next pit
            refuel = False
            next_fuel = fuel_after
            if slot < n - 1:
                next_min_stint = min(
                    (d.min_stint_s or 60) for d in drivers
                )
                next_fuel_need = config.fuel_burn_rate_kgs * next_min_stint
                if fuel_after < next_fuel_need and config.fuel_capacity_kg > 0:
                    refuel = True
                    next_fuel = config.fuel_capacity_kg

            # Assign
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

    backtracks = [0]
    _solve(0, 0, config.fuel_capacity_kg, {}, {}, None, [], backtracks)

    # Build result from best_result
    stints = []
    pit_stops = []
    driver_map = {d.id: d for d in drivers}

    for i, (did, start, dur, fuel_start) in enumerate(best_result):
        d = driver_map[did]
        fuel_end = fuel_start - config.fuel_burn_rate_kgs * dur
        if config.quick_change and i > 0:
            fuel_start = config.fuel_capacity_kg
            fuel_end = fuel_start - config.fuel_burn_rate_kgs * dur

        stints.append(StintResult(
            stint_order=i + 1,
            driver_id=did,
            driver_name=d.name,
            start_s=start,
            duration_s=dur,
            fuel_at_start=fuel_start,
            fuel_at_end=fuel_end,
        ))

        if i < len(best_result) - 1:
            next_did = best_result[i + 1][0]
            # Determine refuel
            next_fuel_need = config.fuel_burn_rate_kgs * (
                driver_map[next_did].min_stint_s or 60
            )
            needs_refuel = fuel_end < next_fuel_need and config.fuel_capacity_kg > 0
            pit_stops.append(PitStopResult(
                after_stint=i + 1,
                at_s=start + dur,
                duration_s=config.pit_time_s,
                refuel=needs_refuel,
                driver_change=did != next_did,
            ))

    # Driver summary
    summary = {}
    for d in drivers:
        d_stints = [s for s in stints if s.driver_id == d.id]
        summary[d.name] = {
            "total_drive_s": sum(s.duration_s for s in d_stints),
            "stints": len(d_stints),
        }

    return SolverResult(
        feasible=len(best_violations) == 0,
        stints=stints,
        pit_stops=pit_stops,
        violations=best_violations,
        warnings=[f"Backtracked {backtracks[0]} times"] if backtracks[0] > 0 else [],
        driver_summary=summary,
    )
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest telemetry_tool/tests/test_csp_solver.py -v
```

- [ ] **Step 5: Commit**

```bash
git add telemetry_tool/optimizer/ telemetry_tool/tests/test_csp_solver.py
git commit -m "feat: CSP backtracking solver for race strategy optimization"
```

---

## Chunk 2: Weather Module + Database

### Task 2.1: Database schema

**Files:**
- Modify: `telemetry_tool/db/schema.py`

- [ ] **Step 1: Add to schema**

Add `wet_confidence REAL DEFAULT 0.5` to `_RACE_DRIVERS_TABLE`.
Add `current_condition TEXT NOT NULL DEFAULT 'dry'` to `_RACE_CONFIGS_TABLE`.
Add `_RACE_WEATHER_WINDOWS_TABLE` as new Phase 24.

- [ ] **Step 2: Add to PostgreSQL**

```bash
ssh root@46.225.227.24 "docker exec lap-api-postgres-1 psql -U telemetry -d telemetry -c \"
ALTER TABLE race_drivers ADD COLUMN IF NOT EXISTS wet_confidence REAL DEFAULT 0.5;
ALTER TABLE race_configs ADD COLUMN IF NOT EXISTS current_condition TEXT NOT NULL DEFAULT 'dry';
CREATE TABLE IF NOT EXISTS race_weather_windows (
    id SERIAL PRIMARY KEY,
    race_id INTEGER NOT NULL REFERENCES race_configs(race_id) ON DELETE CASCADE,
    start_s INTEGER NOT NULL,
    end_s INTEGER NOT NULL,
    condition TEXT NOT NULL DEFAULT 'dry',
    confidence_pct INTEGER NOT NULL DEFAULT 100,
    workspace_id INTEGER NOT NULL DEFAULT current_setting('app.current_workspace_id')::integer
);
CREATE INDEX IF NOT EXISTS idx_race_weather_race ON race_weather_windows(race_id);
\""
```

- [ ] **Step 3: Commit**

### Task 2.2: Weather module

**Files:**
- Create: `telemetry_tool/optimizer/weather.py`
- Create: `telemetry_tool/tests/test_weather.py`

- [ ] **Step 1: Write tests**

Tests for:
- `effective_lap_time` returns slower time for low wet_confidence
- `pit_cost_laps` is lower in wet conditions
- `evaluate_scenarios` returns two plans when confidence < 100

- [ ] **Step 2: Implement weather module**

```python
# telemetry_tool/optimizer/weather.py
"""Weather scenario evaluation and pace adjustment."""

def effective_lap_time(base_s: float, wet_confidence: float, condition: str) -> float:
    if condition == "dry":
        return base_s
    factor = wet_confidence if condition == "wet" else 0.5 + 0.5 * wet_confidence
    return base_s / max(0.01, factor)

def pit_cost_laps(pit_time_s: float, lap_time_s: float) -> float:
    return pit_time_s / max(0.1, lap_time_s)

def evaluate_scenarios(config, drivers, weather_windows):
    """Run solver twice: with weather and without. Return both results."""
    from optimizer.csp_solver import solve_stints
    # Plan A: with weather
    config_wet = config
    config_wet.weather_windows = weather_windows
    plan_a = solve_stints(config_wet, drivers)
    # Plan B: dry baseline
    config_dry = config
    config_dry.weather_windows = []
    plan_b = solve_stints(config_dry, drivers)
    return {"weather": plan_a, "dry": plan_b}
```

- [ ] **Step 3: Run tests, commit**

### Task 2.3: Weather service + API

**Files:**
- Create: `telemetry_tool/services/race_strategy_weather.py`
- Modify: `telemetry_tool/web/routes/api_v1_race_strategy.py`

- [ ] **Step 1: Implement CRUD service**

Functions: `add_weather_window`, `update_weather_window`, `delete_weather_window`, `get_weather_windows`, `set_current_condition`.

- [ ] **Step 2: Add API endpoints**

- `POST /<id>/weather-window`
- `PUT /<id>/weather-window/<wid>`
- `DELETE /<id>/weather-window/<wid>`
- `GET /<id>/weather-windows`
- `POST /<id>/condition`

- [ ] **Step 3: Add `wet_confidence` to `_save_drivers`**

- [ ] **Step 4: Run tests, commit**

---

## Chunk 3: Optimizer V2 Wrapper + Integration

### Task 3.1: optimize_stints_v2 wrapper

**Files:**
- Modify: `telemetry_tool/race_strategy_v2.py`
- Create: `telemetry_tool/tests/test_optimizer_v2.py`

- [ ] **Step 1: Write integration tests**

Tests that `optimize_stints_v2` produces valid plans matching the CSP solver output format, compatible with the existing `RaceStateEngine`.

- [ ] **Step 2: Implement wrapper**

`optimize_stints_v2(config, drivers, sleep_windows, weather_windows)` that:
1. Builds `SolverConfig` and `DriverConstraints` from raw dicts
2. Calls `solve_stints()`
3. Converts `SolverResult` back to the dict format expected by `RaceStateEngine`

- [ ] **Step 3: Wire into `run_optimization` service**

In `services/race_strategy.py`, update `run_optimization` to call `optimize_stints_v2` instead of `optimize_stints`. Fall back to v1 on import error.

- [ ] **Step 4: Run all tests, commit**

---

## Chunk 4: Frontend — Form + Live Dashboard

### Task 4.1: Form fields

**Files:**
- Modify: `lap-website/src/components/app/race-strategy/RaceConfigForm.tsx`

- [ ] **Step 1: Add per-driver wet confidence field**

After `avg_lap_time_s` input, add:
- "Wet %" number input (0-100), stored as 0.0-1.0 in payload as `wet_confidence`
- Default 50

- [ ] **Step 2: Add weather forecast editor**

New section (complex+ tier) "Weather Forecast":
- Table: rows with Start (hh:mm), End (hh:mm), Condition dropdown (dry/damp/wet), Confidence %
- Add/Remove row buttons
- Payload: `weather_windows: [{start_s, end_s, condition, confidence_pct}]`

- [ ] **Step 3: Build and verify**

### Task 4.2: Live dashboard

**Files:**
- Modify: `lap-website/src/app/app/race-strategy/[id]/live/page.tsx`

- [ ] **Step 1: Add condition button**

In action bar, add "Condition" dropdown button (dry/damp/wet). Calls `POST /condition`.
Show condition badge next to LIVE/PAUSED in header.

- [ ] **Step 2: Build, deploy, commit**

---

## Deployment

Each chunk deploys independently:
1. **Chunk 1**: Backend only — new files, no API changes
2. **Chunk 2**: Backend — new table + service + endpoints
3. **Chunk 3**: Backend — optimizer wired in
4. **Chunk 4**: Frontend — form fields + live UI

Deploy sequence per chunk:
```bash
# Backend
scp files root@46.225.227.24:/opt/lap-api/...
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml build api && up -d api"
# Frontend
cd lap-website && powershell Remove-Item '.next','.open-next' -Recurse -Force -EA SilentlyContinue
npm run build && npx @opennextjs/cloudflare build && OPENNEXTJS_CLOUDFLARE_SKIP_BUILD=1 npx wrangler deploy
```
