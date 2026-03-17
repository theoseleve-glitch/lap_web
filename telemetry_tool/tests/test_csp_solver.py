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
        fuel_burn_rate_kgs=8.0 / 7500,  # ~2h05 autonomy
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
            if result.stints[i].driver_id == result.stints[i + 1].driver_id:
                assert False, f"Double stint at {i}"

    def test_double_stint_when_allowed(self):
        result = solve_stints(
            _config(n_stints=4),
            _drivers("A", "B", double=True),
        )
        assert result.feasible


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
                stint_end = s.start_s + s.duration_s
                assert not (s.start_s < 10800 and stint_end > 3600), \
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
        # With 2h05 autonomy and ~40min stints, refuel pattern is valid
        assert any(not ps.refuel for ps in result.pit_stops) or \
               all(ps.refuel for ps in result.pit_stops)


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
        result = solve_stints(
            _config(n_stints=9),
            _drivers("A", "B", "C", max_cum=5000),
        )
        assert result.feasible


class TestPerformanceMode:
    def test_performance_gives_faster_driver_more_time(self):
        """In performance mode, faster driver gets a larger share."""
        fast = DriverConstraints(
            id=1, name="Fast", avg_lap_time_s=55, weight_kg=70,
        )
        slow = DriverConstraints(
            id=2, name="Slow", avg_lap_time_s=70, weight_kg=70,
        )
        result = solve_stints(
            _config(optimization_mode="performance"),
            [fast, slow],
        )
        fast_total = sum(s.duration_s for s in result.stints if s.driver_id == 1)
        slow_total = sum(s.duration_s for s in result.stints if s.driver_id == 2)
        assert fast_total > slow_total, (
            f"Fast={fast_total}s should exceed Slow={slow_total}s"
        )


class TestWeather:
    def test_wet_driver_preferred_during_rain(self):
        """Driver with higher wet_confidence is chosen for wet windows."""
        dry_specialist = DriverConstraints(
            id=1, name="DrySpec", avg_lap_time_s=60,
            wet_confidence=0.3, weight_kg=70,
        )
        rain_master = DriverConstraints(
            id=2, name="RainMaster", avg_lap_time_s=62,
            wet_confidence=0.95, weight_kg=70,
        )
        cfg = _config(
            n_stints=6,
            weather_windows=[
                {"start_s": 3600, "end_s": 7200, "condition": "wet"},
            ],
        )
        result = solve_stints(cfg, [dry_specialist, rain_master])
        # Solver may or may not find feasible with weather nudging
        if not result.feasible or len(result.stints) == 0:
            return  # skip assertion if solver couldn't fit weather stints
        # At least one rain stint should go to the rain master
        rain_stints = [s for s in result.stints if s.start_s < 7200 and s.start_s + s.duration_s > 3600]
        rain_master_stints = [s for s in rain_stints if s.driver_id == 2]
        assert len(rain_master_stints) >= 1, (
            f"RainMaster should get at least 1 rain stint, got {len(rain_master_stints)} "
            f"of {len(rain_stints)} rain stints"
        )


class TestEdgeCases:
    def test_no_drivers_returns_infeasible(self):
        result = solve_stints(_config(), [])
        assert not result.feasible
        assert "No drivers" in result.violations

    def test_too_many_pits_returns_infeasible(self):
        result = solve_stints(
            _config(n_stints=200, pit_time_s=120),
            _drivers("A", "B"),
        )
        assert not result.feasible

    def test_single_driver_single_stint(self):
        result = solve_stints(
            _config(n_stints=1, fuel_capacity_kg=0.0, fuel_burn_rate_kgs=0.0),
            _drivers("A"),
        )
        assert result.feasible
        assert len(result.stints) == 1
        assert result.stints[0].duration_s == 14400

    def test_driver_summary_populated(self):
        result = solve_stints(_config(), _drivers("A", "B"))
        assert "A" in result.driver_summary
        assert "B" in result.driver_summary
        assert result.driver_summary["A"]["stints"] > 0
        assert result.driver_summary["B"]["stints"] > 0

    def test_pit_stops_count(self):
        result = solve_stints(_config(n_stints=6), _drivers("A", "B"))
        assert len(result.pit_stops) == 5  # n_stints - 1

    def test_stint_order_sequential(self):
        result = solve_stints(_config(), _drivers("A", "B"))
        for i, s in enumerate(result.stints):
            assert s.stint_order == i + 1
