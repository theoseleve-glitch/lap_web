"""Tests for the RaceStateEngine — fuel model, stint state, and cascade logic."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from race_state_engine import FuelModel, RaceStateEngine, StintState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine(
    quali_duration_s: int = 0,
    refuel_after_quali: int = 1,
    refueling_allowed: int = 1,
) -> RaceStateEngine:
    """
    Build a 3-stint engine:
      Alice (65 kg, 2360 s) -> Bob (75 kg, 2360 s) -> Alice (2360 s)
    with 60 s pit stops, 8 kg fuel (85 kg empty, 93 kg full), 2400 s autonomy,
    160 kg minimum kart weight.
    """
    config = {
        "race_duration_s": 7200,
        "empty_kart_kg": 85.0,
        "full_tank_kg": 93.0,          # fuel capacity = 93 - 85 = 8 kg
        "fuel_autonomy_s": 2400,
        "min_total_kart_kg": 160.0,
        "min_pit_stop_s": 60,
        "qualifying_duration_s": quali_duration_s,
        "refuel_after_quali": refuel_after_quali,
        "refueling_allowed": refueling_allowed,
    }
    drivers = {
        1: {"id": 1, "driver_name": "Alice", "weight_kg": 65.0},
        2: {"id": 2, "driver_name": "Bob", "weight_kg": 75.0},
    }
    raw_stints = [
        {
            "stint_order": 1,
            "driver_id": 1,
            "planned_duration_s": 2360,
            "planned_start_s": 0,
            "planned_end_s": 2360,
        },
        {
            "stint_order": 2,
            "driver_id": 2,
            "planned_duration_s": 2360,
            "planned_start_s": 2420,
            "planned_end_s": 4780,
        },
        {
            "stint_order": 3,
            "driver_id": 1,
            "planned_duration_s": 2360,
            "planned_start_s": 4840,
            "planned_end_s": 7200,
        },
    ]
    pit_stops = [
        {"after_stint": 1, "refuel": True, "driver_change": True},
        {"after_stint": 2, "refuel": True, "driver_change": True},
    ]
    return RaceStateEngine(config, drivers, raw_stints, pit_stops)


# ===========================================================================
# TestFuelModel
# ===========================================================================

class TestFuelModel:
    """FuelModel dataclass and derived properties."""

    def test_burn_rate_calculation(self):
        """8 kg / 2400 s = 0.003333..."""
        fm = FuelModel(full_tank_kg=8.0, fuel_autonomy_s=2400)
        assert abs(fm.burn_rate_kgs - 8.0 / 2400) < 1e-9

    def test_quali_fuel_bridge(self):
        """fuel_after_quali = full_tank - (burn_rate * quali_duration)."""
        fm = FuelModel(full_tank_kg=8.0, fuel_autonomy_s=2400, quali_fuel_used_kg=2.0)
        assert abs(fm.fuel_after_quali_kg - 6.0) < 1e-9

    def test_zero_autonomy_safe(self):
        """0 autonomy -> 0 burn rate, no crash."""
        fm = FuelModel(full_tank_kg=8.0, fuel_autonomy_s=0)
        assert fm.burn_rate_kgs == 0.0
        assert fm.fuel_after_quali_kg == 8.0

    def test_from_config(self):
        """from_config correctly extracts fuel_capacity = full_tank - empty."""
        config = {
            "empty_kart_kg": 85.0,
            "full_tank_kg": 93.0,
            "fuel_autonomy_s": 2400,
            "qualifying_duration_s": 600,
            "refuel_after_quali": 0,
        }
        fm = FuelModel.from_config(config)
        # fuel capacity = 93 - 85 = 8 kg
        assert abs(fm.full_tank_kg - 8.0) < 1e-9
        assert fm.fuel_autonomy_s == 2400
        # quali_fuel_used = (8/2400) * 600 = 2.0
        assert abs(fm.quali_fuel_used_kg - 2.0) < 1e-9


# ===========================================================================
# TestStintState
# ===========================================================================

class TestStintState:
    """StintState dataclass defaults."""

    def test_stint_state_creation(self):
        """Defaults are correct: fuel=0, ballast=0, violations=[], refueled_before=True."""
        s = StintState(
            stint_order=1,
            driver_id=1,
            driver_name="Alice",
            planned_duration_s=2360,
            planned_start_s=0,
            planned_end_s=2360,
        )
        assert s.fuel_at_start_kg == 0.0
        assert s.fuel_at_end_kg == 0.0
        assert s.refueled_before is True
        assert s.ballast_kg == 0.0
        assert s.ballast_base_kg == 0.0
        assert s.ballast_fuel_offset_kg == 0.0
        assert s.violations == []
        assert s.warnings == []
        assert s.status == "planned"
        assert s.actual_start_s is None
        assert s.actual_end_s is None
        assert s.actual_duration_s is None
        assert s.notes == ""


# ===========================================================================
# TestFuelCascade
# ===========================================================================

class TestFuelCascade:
    """Fuel cascade logic in RaceStateEngine."""

    def test_all_refueled_stints_start_full(self):
        """All stints start with 8.0 kg when all are refueled."""
        engine = _make_engine()
        for s in engine.stints:
            assert abs(s.fuel_at_start_kg - 8.0) < 1e-9

    def test_fuel_depletes_during_stint(self):
        """fuel_at_end = 8.0 - (8/2400 * 2360)."""
        engine = _make_engine()
        expected_end = 8.0 - (8.0 / 2400 * 2360)
        for s in engine.stints:
            assert abs(s.fuel_at_end_kg - expected_end) < 1e-6

    def test_qualifying_bridge_reduces_first_stint_fuel(self):
        """With 600 s quali, stint 1 starts with 8 - (8/2400 * 600) = 6.0."""
        engine = _make_engine(quali_duration_s=600, refuel_after_quali=0)
        s1 = engine.stints[0]
        assert abs(s1.fuel_at_start_kg - 6.0) < 1e-9
        # stint 2 and 3 should still be fully refueled
        assert abs(engine.stints[1].fuel_at_start_kg - 8.0) < 1e-9
        assert abs(engine.stints[2].fuel_at_start_kg - 8.0) < 1e-9

    def test_toggle_fuel_off_carries_fuel_from_previous(self):
        """toggle_fuel(2) -> stint 2 starts with stint 1's fuel_at_end."""
        engine = _make_engine()
        engine.toggle_fuel(2)
        s1 = engine.stints[0]
        s2 = engine.stints[1]
        assert abs(s2.fuel_at_start_kg - s1.fuel_at_end_kg) < 1e-9

    def test_toggle_fuel_cascades_downstream(self):
        """After toggle_fuel(2), stint 3 still starts full (refueled)."""
        engine = _make_engine()
        engine.toggle_fuel(2)
        s3 = engine.stints[2]
        assert abs(s3.fuel_at_start_kg - 8.0) < 1e-9

    def test_refueling_allowed_false_forces_no_refuel(self):
        """With refueling_allowed=0, all stints carry fuel from previous."""
        engine = _make_engine(refueling_allowed=0)
        s1 = engine.stints[0]
        s2 = engine.stints[1]
        s3 = engine.stints[2]
        # Stint 1 starts full
        assert abs(s1.fuel_at_start_kg - 8.0) < 1e-9
        # Stint 2 starts with stint 1's fuel_at_end
        assert abs(s2.fuel_at_start_kg - s1.fuel_at_end_kg) < 1e-9
        # Stint 3 starts with stint 2's fuel_at_end
        assert abs(s3.fuel_at_start_kg - s2.fuel_at_end_kg) < 1e-9


# ===========================================================================
# TestBallastCascade
# ===========================================================================

class TestBallastCascade:
    """Ballast cascade logic in RaceStateEngine."""

    def test_full_tank_ballast_base_only(self):
        """Alice: 160 - 85 - 8 - 65 = 2.0 kg base, 0 offset."""
        engine = _make_engine()
        s1 = engine.stints[0]
        assert abs(s1.ballast_base_kg - 2.0) < 1e-9
        assert abs(s1.ballast_fuel_offset_kg - 0.0) < 1e-9
        assert abs(s1.ballast_kg - 2.0) < 1e-9

    def test_heavier_driver_less_ballast(self):
        """Bob: 160 - 85 - 8 - 75 = -8 -> clamped to 0."""
        engine = _make_engine()
        s2 = engine.stints[1]  # Bob's stint
        assert abs(s2.ballast_base_kg - 0.0) < 1e-9
        assert abs(s2.ballast_kg - 0.0) < 1e-9

    def test_no_refuel_adds_fuel_offset(self):
        """toggle_fuel(2) -> stint 2 has fuel_offset > 0."""
        engine = _make_engine()
        engine.toggle_fuel(2)
        s2 = engine.stints[1]
        # fuel_at_start < full_tank -> offset = full_tank - fuel_at_start
        fuel_cap = 8.0
        expected_offset = max(0.0, fuel_cap - s2.fuel_at_start_kg)
        assert expected_offset > 0.0
        assert abs(s2.ballast_fuel_offset_kg - expected_offset) < 1e-6

    def test_ballast_cascade_on_driver_change(self):
        """Manually change driver and re-cascade to verify ballast updates."""
        engine = _make_engine()
        # Change stint 2 driver from Bob (75 kg) to Alice (65 kg)
        engine.stints[1].driver_id = 1
        engine.stints[1].driver_name = "Alice"
        engine._cascade_from(2)
        s2 = engine.stints[1]
        # Alice: 160 - 85 - 8 - 65 = 2.0 base
        assert abs(s2.ballast_base_kg - 2.0) < 1e-9

    def test_real_time_ballast_during_stint(self):
        """current_ballast(1200) shows fuel_offset > 0 (fuel depleted mid-stint)."""
        engine = _make_engine()
        ballast_info = engine.current_ballast(1200)
        # At 1200 s into stint 1, fuel has depleted from 8.0
        fuel_cap = 8.0
        fuel_at_1200 = 8.0 - (8.0 / 2400 * 1200)
        expected_offset = max(0.0, fuel_cap - fuel_at_1200)
        assert expected_offset > 0.0
        assert abs(ballast_info["ballast_fuel_offset_kg"] - expected_offset) < 1e-6
        # Total ballast = base + fuel_offset
        assert ballast_info["ballast_kg"] > 0.0


# ===========================================================================
# TestCurrentFuel
# ===========================================================================

class TestCurrentFuel:
    """Real-time fuel interpolation."""

    def test_current_fuel_at_start(self):
        """At t=0 fuel should be full start amount."""
        engine = _make_engine()
        assert abs(engine.current_fuel_kg(0) - 8.0) < 1e-9

    def test_current_fuel_mid_stint(self):
        """At t=1200 fuel should be 8 - (8/2400 * 1200) = 4.0."""
        engine = _make_engine()
        assert abs(engine.current_fuel_kg(1200) - 4.0) < 1e-6

    def test_current_fuel_at_stint_end(self):
        """At end of stint 1, fuel matches fuel_at_end."""
        engine = _make_engine()
        s1 = engine.stints[0]
        assert abs(engine.current_fuel_kg(2360) - s1.fuel_at_end_kg) < 1e-6


# ===========================================================================
# TestConstraintValidation  (Task 4)
# ===========================================================================

class TestConstraintValidation:
    """Constraint validation logic in _validate_constraints."""

    def _make_engine(self, drivers=None, config_overrides=None, stints=None, pit_stops=None):
        config = {
            "race_duration_s": 7200, "desired_stints": 3, "min_pit_stop_s": 60,
            "fuel_autonomy_s": 2400, "empty_kart_kg": 85.0, "full_tank_kg": 93.0,
            "min_total_kart_kg": 160.0, "qualifying_duration_s": 0, "refuel_after_quali": 0,
            "refueling_allowed": 1, "mandatory_driver_change": 0,
            **(config_overrides or {}),
        }
        if drivers is None:
            drivers = [
                {"id": 1, "driver_name": "Alice", "driver_order": 1, "weight_kg": 65.0,
                 "min_stint_s": None, "max_stint_s": None, "min_cumulative_s": None,
                 "max_cumulative_s": None, "min_rest_s": 0},
                {"id": 2, "driver_name": "Bob", "driver_order": 2, "weight_kg": 75.0,
                 "min_stint_s": None, "max_stint_s": None, "min_cumulative_s": None,
                 "max_cumulative_s": None, "min_rest_s": 0},
            ]
        if stints is None:
            stints = [
                {"stint_order": 1, "driver_id": 1, "driver_name": "Alice",
                 "planned_start_s": 0, "planned_end_s": 2360, "planned_duration_s": 2360},
                {"stint_order": 2, "driver_id": 2, "driver_name": "Bob",
                 "planned_start_s": 2420, "planned_end_s": 4780, "planned_duration_s": 2360},
                {"stint_order": 3, "driver_id": 1, "driver_name": "Alice",
                 "planned_start_s": 4840, "planned_end_s": 7200, "planned_duration_s": 2360},
            ]
        if pit_stops is None:
            pit_stops = [
                {"after_stint": 1, "at_s": 2360, "duration_s": 60, "refuel": True,
                 "driver_change": True, "pit_type": "full"},
                {"after_stint": 2, "at_s": 4780, "duration_s": 60, "refuel": True,
                 "driver_change": True, "pit_type": "full"},
            ]
        return RaceStateEngine(config, drivers, stints, pit_stops)

    def test_fuel_exhaustion_violation(self):
        engine = self._make_engine(config_overrides={"fuel_autonomy_s": 1000})
        assert any("Fuel runs out" in v for v in engine.stints[0].violations)

    def test_mandatory_driver_change_violation(self):
        stints = [
            {"stint_order": 1, "driver_id": 1, "driver_name": "Alice",
             "planned_start_s": 0, "planned_end_s": 2360, "planned_duration_s": 2360},
            {"stint_order": 2, "driver_id": 1, "driver_name": "Alice",
             "planned_start_s": 2420, "planned_end_s": 4780, "planned_duration_s": 2360},
            {"stint_order": 3, "driver_id": 2, "driver_name": "Bob",
             "planned_start_s": 4840, "planned_end_s": 7200, "planned_duration_s": 2360},
        ]
        engine = self._make_engine(
            config_overrides={"mandatory_driver_change": 1}, stints=stints
        )
        assert any("Mandatory driver change" in v for v in engine.stints[1].violations)

    def test_min_rest_time_violation(self):
        drivers = [
            {"id": 1, "driver_name": "Alice", "driver_order": 1, "weight_kg": 65.0,
             "min_stint_s": None, "max_stint_s": None, "min_cumulative_s": None,
             "max_cumulative_s": None, "min_rest_s": 300},
            {"id": 2, "driver_name": "Bob", "driver_order": 2, "weight_kg": 75.0,
             "min_stint_s": None, "max_stint_s": None, "min_cumulative_s": None,
             "max_cumulative_s": None, "min_rest_s": 0},
        ]
        stints = [
            {"stint_order": 1, "driver_id": 1, "driver_name": "Alice",
             "planned_start_s": 0, "planned_end_s": 3000, "planned_duration_s": 3000},
            {"stint_order": 2, "driver_id": 2, "driver_name": "Bob",
             "planned_start_s": 3060, "planned_end_s": 3180, "planned_duration_s": 120},
            {"stint_order": 3, "driver_id": 1, "driver_name": "Alice",
             "planned_start_s": 3240, "planned_end_s": 7200, "planned_duration_s": 3960},
        ]
        engine = self._make_engine(drivers=drivers, stints=stints)
        # Alice rest: 3240 - 3000 = 240s < 300s -> violation
        assert any("rest" in v.lower() for v in engine.stints[2].violations)

    def test_cumulative_max_exceeded_violation(self):
        drivers = [
            {"id": 1, "driver_name": "Alice", "driver_order": 1, "weight_kg": 65.0,
             "min_stint_s": None, "max_stint_s": None, "min_cumulative_s": None,
             "max_cumulative_s": 3000, "min_rest_s": 0},
            {"id": 2, "driver_name": "Bob", "driver_order": 2, "weight_kg": 75.0,
             "min_stint_s": None, "max_stint_s": None, "min_cumulative_s": None,
             "max_cumulative_s": None, "min_rest_s": 0},
        ]
        engine = self._make_engine(drivers=drivers)
        # Alice: 2360 + 2360 = 4720 > 3000
        assert any("exceeds max" in v.lower() for v in engine.stints[2].violations)

    def test_cumulative_90_percent_warning(self):
        drivers = [
            {"id": 1, "driver_name": "Alice", "driver_order": 1, "weight_kg": 65.0,
             "min_stint_s": None, "max_stint_s": None, "min_cumulative_s": None,
             "max_cumulative_s": 5000, "min_rest_s": 0},
            {"id": 2, "driver_name": "Bob", "driver_order": 2, "weight_kg": 75.0,
             "min_stint_s": None, "max_stint_s": None, "min_cumulative_s": None,
             "max_cumulative_s": None, "min_rest_s": 0},
        ]
        engine = self._make_engine(drivers=drivers)
        # Alice: 2360 + 2360 = 4720, 90% of 5000 = 4500 -> warning
        assert any("90%" in w for w in engine.stints[2].warnings)

    def test_no_violations_on_valid_plan(self):
        engine = self._make_engine()
        for s in engine.stints:
            assert s.violations == [], f"Stint {s.stint_order}: {s.violations}"

    def test_set_driver_recascades_ballast(self):
        engine = self._make_engine()
        original = engine.stints[1].ballast_kg
        engine.set_driver(2, 1)  # Stint 2 -> Alice (lighter, so more ballast)
        assert engine.stints[1].ballast_kg != original

    def test_set_duration_rebuilds_timeline(self):
        engine = self._make_engine()
        engine.set_duration(1, 1800)  # Shorten stint 1
        assert engine.stints[0].planned_end_s == 1800
        assert engine.stints[1].planned_start_s == 1860  # 1800 + 60 pit

    def test_set_pit_type_quick_disables_refuel(self):
        engine = self._make_engine()
        engine.set_pit_type(2, "quick")
        assert engine.stints[1].refueled_before is False


# ===========================================================================
# TestEnginePersistence  (Task 5)
# ===========================================================================

@pytest.fixture
def engine_db():
    from db.migrate import ensure_schema
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    yield conn
    conn.close()


class TestEnginePersistence:
    """Engine save/load round-trip, snapshot, and export."""

    def _seed_race(self, conn):
        conn.execute(
            "INSERT INTO race_configs (race_name, race_duration_s, fuel_autonomy_s, "
            "empty_kart_kg, full_tank_kg, min_total_kart_kg, min_pit_stop_s) "
            "VALUES ('Test 2h', 7200, 2400, 85, 93, 160, 60)"
        )
        conn.execute(
            "INSERT INTO race_drivers (race_id, driver_name, driver_order, weight_kg) "
            "VALUES (1, 'Alice', 1, 65)"
        )
        conn.execute(
            "INSERT INTO race_drivers (race_id, driver_name, driver_order, weight_kg) "
            "VALUES (1, 'Bob', 2, 75)"
        )
        conn.commit()
        return 1

    def test_save_and_load_round_trip(self, engine_db):
        race_id = self._seed_race(engine_db)
        config = dict(
            engine_db.execute(
                "SELECT * FROM race_configs WHERE race_id = 1"
            ).fetchone()
        )
        drivers = [
            dict(r) for r in engine_db.execute(
                "SELECT * FROM race_drivers WHERE race_id = 1 ORDER BY driver_order"
            ).fetchall()
        ]
        raw_stints = [
            {"stint_order": 1, "driver_id": drivers[0]["id"], "driver_name": "Alice",
             "planned_start_s": 0, "planned_end_s": 2360, "planned_duration_s": 2360},
            {"stint_order": 2, "driver_id": drivers[1]["id"], "driver_name": "Bob",
             "planned_start_s": 2420, "planned_end_s": 4780, "planned_duration_s": 2360},
        ]
        pit_stops = [
            {"after_stint": 1, "at_s": 2360, "duration_s": 60, "refuel": True,
             "driver_change": True, "pit_type": "full"},
        ]
        engine = RaceStateEngine(config, drivers, raw_stints, pit_stops)
        engine.save(engine_db, race_id)
        loaded = RaceStateEngine.load(engine_db, race_id)
        assert len(loaded.stints) == 2
        assert abs(
            loaded.stints[0].fuel_at_start_kg - engine.stints[0].fuel_at_start_kg
        ) < 0.01
        assert loaded.stints[0].ballast_kg == engine.stints[0].ballast_kg

    def test_snapshot_returns_full_state(self):
        config = {
            "race_duration_s": 3600, "fuel_autonomy_s": 2400, "empty_kart_kg": 85,
            "full_tank_kg": 93, "min_total_kart_kg": 160, "min_pit_stop_s": 60,
            "refuel_after_quali": 0, "qualifying_duration_s": 0, "refueling_allowed": 1,
        }
        drivers = [{"id": 1, "driver_name": "A", "driver_order": 1, "weight_kg": 65}]
        stints = [
            {"stint_order": 1, "driver_id": 1, "driver_name": "A",
             "planned_start_s": 0, "planned_end_s": 3600, "planned_duration_s": 3600},
        ]
        engine = RaceStateEngine(config, drivers, stints, [])
        snap = engine.snapshot()
        assert "stints" in snap
        assert "fuel_model" in snap
        assert snap["stints"][0]["ballast_base_kg"] is not None

    def test_stint_plan_export_format(self):
        config = {
            "race_duration_s": 3600, "fuel_autonomy_s": 2400, "empty_kart_kg": 85,
            "full_tank_kg": 93, "min_total_kart_kg": 160, "min_pit_stop_s": 60,
            "refuel_after_quali": 0, "qualifying_duration_s": 0, "refueling_allowed": 1,
        }
        drivers = [{"id": 1, "driver_name": "A", "driver_order": 1, "weight_kg": 65}]
        stints = [
            {"stint_order": 1, "driver_id": 1, "driver_name": "A",
             "planned_start_s": 0, "planned_end_s": 3600, "planned_duration_s": 3600},
        ]
        engine = RaceStateEngine(config, drivers, stints, [])
        export = engine.stint_plan_export("Test Race")
        assert export["format"] == "stint-plan-v1"
        assert export["race_name"] == "Test Race"
        assert len(export["stints"]) == 1
        assert "ballast_kg" in export["stints"][0]


# ===========================================================================
# TestWindowValidation  (Tasks 2-4)
# ===========================================================================

class TestWindowValidation:
    """Tests for race window validation in RaceStateEngine."""

    def _make_engine_with_windows(self, windows=None):
        """Create a 3-stint engine with optional race windows."""
        config = {
            "race_duration_s": 3600,
            "empty_kart_kg": 85,
            "full_tank_kg": 93,
            "min_total_kart_kg": 160,
            "fuel_autonomy_s": 2400,
            "min_pit_stop_s": 60,
            "mandatory_driver_change": 0,
            "refueling_allowed": 1,
            "pit_open_s": None,
            "pit_close_s": None,
        }
        drivers = [
            {"id": 1, "driver_name": "Alice", "driver_order": 1, "weight_kg": 65},
            {"id": 2, "driver_name": "Bob", "driver_order": 2, "weight_kg": 75},
        ]
        raw_stints = [
            {"stint_order": 1, "driver_id": 1, "driver_name": "Alice",
             "planned_start_s": 0, "planned_end_s": 1200, "planned_duration_s": 1200},
            {"stint_order": 2, "driver_id": 2, "driver_name": "Bob",
             "planned_start_s": 1260, "planned_end_s": 2460, "planned_duration_s": 1200},
            {"stint_order": 3, "driver_id": 1, "driver_name": "Alice",
             "planned_start_s": 2520, "planned_end_s": 3600, "planned_duration_s": 1080},
        ]
        pit_stops = [
            {"after_stint": 1, "refuel": True, "driver_change": True, "pit_type": "full"},
            {"after_stint": 2, "refuel": True, "driver_change": True, "pit_type": "full"},
        ]
        engine = RaceStateEngine(config, drivers, raw_stints, pit_stops)
        if windows:
            engine.windows = windows
            engine._cascade_from(1)  # Re-cascade to apply window validation
        return engine

    # Task 2 tests: _is_in_any_window helper
    def test_no_windows_means_no_restriction(self):
        engine = self._make_engine_with_windows(windows=[])
        for s in engine.stints:
            assert not any("window" in v.lower() for v in s.violations)
            assert not any("window" in w.lower() for w in s.warnings)

    def test_is_in_any_window_true_when_inside(self):
        engine = self._make_engine_with_windows(windows=[
            {"window_type": "pitlane", "start_s": 1000, "end_s": 3000},
        ])
        assert engine._is_in_any_window("pitlane", 1500) is True

    def test_is_in_any_window_false_when_outside(self):
        engine = self._make_engine_with_windows(windows=[
            {"window_type": "pitlane", "start_s": 1000, "end_s": 3000},
        ])
        assert engine._is_in_any_window("pitlane", 500) is False

    def test_is_in_any_window_true_when_no_windows_of_type(self):
        engine = self._make_engine_with_windows(windows=[
            {"window_type": "refuel", "start_s": 1000, "end_s": 3000},
        ])
        assert engine._is_in_any_window("pitlane", 500) is True

    def test_is_in_any_window_multiple_windows(self):
        engine = self._make_engine_with_windows(windows=[
            {"window_type": "refuel", "start_s": 500, "end_s": 1000},
            {"window_type": "refuel", "start_s": 2000, "end_s": 3000},
        ])
        assert engine._is_in_any_window("refuel", 800) is True
        assert engine._is_in_any_window("refuel", 2500) is True
        assert engine._is_in_any_window("refuel", 1500) is False

    # Task 3 tests: pit window warnings + refuel violations
    def test_pitlane_window_warning_when_pit_outside(self):
        engine = self._make_engine_with_windows(windows=[
            {"window_type": "pitlane", "start_s": 2000, "end_s": 3500},
        ])
        stint2 = engine.stints[1]  # starts at 1260, outside 2000-3500
        assert any("pit" in w.lower() and "window" in w.lower() for w in stint2.warnings)

    def test_pitlane_window_no_warning_when_inside(self):
        engine = self._make_engine_with_windows(windows=[
            {"window_type": "pitlane", "start_s": 1000, "end_s": 3500},
        ])
        stint2 = engine.stints[1]
        assert not any("pit" in w.lower() and "window" in w.lower() for w in stint2.warnings)

    def test_refuel_window_violation_when_refuel_outside(self):
        engine = self._make_engine_with_windows(windows=[
            {"window_type": "refuel", "start_s": 2000, "end_s": 3500},
        ])
        stint2 = engine.stints[1]  # starts at 1260, refueled, outside 2000-3500
        assert any("refuel" in v.lower() and "window" in v.lower() for v in stint2.violations)

    def test_refuel_window_no_violation_when_not_refueled(self):
        engine = self._make_engine_with_windows(windows=[
            {"window_type": "refuel", "start_s": 2000, "end_s": 3500},
        ])
        engine.toggle_fuel(2)  # Turn off refueling for stint 2
        stint2 = engine.stints[1]
        assert not any("refuel" in v.lower() and "window" in v.lower() for v in stint2.violations)

    def test_refuel_window_no_violation_when_inside(self):
        engine = self._make_engine_with_windows(windows=[
            {"window_type": "refuel", "start_s": 1000, "end_s": 3500},
        ])
        stint2 = engine.stints[1]
        assert not any("refuel" in v.lower() and "window" in v.lower() for v in stint2.violations)

    # Task 4 tests: tech stop validation + legacy migration
    def test_tech_stop_violation_when_no_stop_in_window(self):
        engine = self._make_engine_with_windows(windows=[
            {"window_type": "tech_stop", "label": "Tech 1",
             "start_s": 100, "end_s": 200},
        ])
        all_violations = []
        for s in engine.stints:
            all_violations.extend(s.violations)
        assert any("tech" in v.lower() for v in all_violations)

    def test_tech_stop_no_violation_when_stop_in_window(self):
        engine = self._make_engine_with_windows(windows=[
            {"window_type": "tech_stop", "label": "Tech 1",
             "start_s": 1200, "end_s": 1400},
        ])
        all_violations = []
        for s in engine.stints:
            all_violations.extend(s.violations)
        assert not any("tech" in v.lower() for v in all_violations)

    def test_legacy_pit_open_close_creates_virtual_window(self):
        config = {
            "race_duration_s": 3600,
            "empty_kart_kg": 85, "full_tank_kg": 93,
            "min_total_kart_kg": 160, "fuel_autonomy_s": 2400,
            "min_pit_stop_s": 60, "mandatory_driver_change": 0,
            "refueling_allowed": 1,
            "pit_open_s": 600,
            "pit_close_s": 300,
        }
        drivers = [
            {"id": 1, "driver_name": "Alice", "driver_order": 1, "weight_kg": 65},
        ]
        raw_stints = [
            {"stint_order": 1, "driver_id": 1, "driver_name": "Alice",
             "planned_start_s": 0, "planned_end_s": 3600, "planned_duration_s": 3600},
        ]
        engine = RaceStateEngine(config, drivers, raw_stints, [])
        assert len(engine.windows) == 1
        assert engine.windows[0]["window_type"] == "pitlane"
        assert engine.windows[0]["start_s"] == 600
        assert engine.windows[0]["end_s"] == 3300  # 3600 - 300


# ===========================================================================
# TestWindowStatus  (Task 5)
# ===========================================================================

class TestWindowStatus:
    """Tests for window_status() query method."""

    def _make_engine_with_windows(self, windows):
        config = {
            "race_duration_s": 3600, "empty_kart_kg": 85, "full_tank_kg": 93,
            "min_total_kart_kg": 160, "fuel_autonomy_s": 2400,
            "min_pit_stop_s": 60, "mandatory_driver_change": 0,
            "refueling_allowed": 1, "pit_open_s": None, "pit_close_s": None,
        }
        drivers = [{"id": 1, "driver_name": "A", "driver_order": 1, "weight_kg": 65}]
        stints = [{"stint_order": 1, "driver_id": 1, "driver_name": "A",
                   "planned_start_s": 0, "planned_end_s": 3600, "planned_duration_s": 3600}]
        engine = RaceStateEngine(config, drivers, stints, [])
        engine.windows = windows
        return engine

    def test_empty_windows_returns_all_none_status(self):
        engine = self._make_engine_with_windows([])
        status = engine.window_status(1000)
        types = {s['type'] for s in status}
        assert 'pitlane' in types
        assert 'refuel' in types
        assert 'tech_stop' in types
        for s in status:
            assert s['status'] == 'none'

    def test_window_before_open(self):
        engine = self._make_engine_with_windows([
            {"window_type": "pitlane", "start_s": 600, "end_s": 3000, "label": "Pit"},
        ])
        status = engine.window_status(300)
        pit = next(s for s in status if s['type'] == 'pitlane')
        assert pit['status'] == 'before'
        assert pit['countdown_s'] == 300

    def test_window_open(self):
        engine = self._make_engine_with_windows([
            {"window_type": "pitlane", "start_s": 600, "end_s": 3000, "label": "Pit"},
        ])
        status = engine.window_status(1000)
        pit = next(s for s in status if s['type'] == 'pitlane')
        assert pit['status'] == 'open'
        assert pit['countdown_s'] == 2000

    def test_window_closing_within_5_min(self):
        engine = self._make_engine_with_windows([
            {"window_type": "refuel", "start_s": 600, "end_s": 3000, "label": "R1"},
        ])
        status = engine.window_status(2800)
        refuel = next(s for s in status if s['type'] == 'refuel')
        assert refuel['status'] == 'closing'
        assert refuel['countdown_s'] == 200

    def test_window_closed(self):
        engine = self._make_engine_with_windows([
            {"window_type": "refuel", "start_s": 600, "end_s": 3000, "label": "R1"},
        ])
        status = engine.window_status(3100)
        refuel = next(s for s in status if s['type'] == 'refuel')
        assert refuel['status'] == 'closed'

    def test_multiple_windows_same_type_picks_active_or_next(self):
        engine = self._make_engine_with_windows([
            {"window_type": "refuel", "start_s": 300, "end_s": 900, "label": "R1"},
            {"window_type": "refuel", "start_s": 1800, "end_s": 2700, "label": "R2"},
        ])
        status = engine.window_status(1200)
        refuel = next(s for s in status if s['type'] == 'refuel')
        assert refuel['status'] == 'before'
        assert refuel['label'] == 'R2'
        assert refuel['countdown_s'] == 600

    def test_snapshot_includes_windows(self):
        engine = self._make_engine_with_windows([
            {"window_type": "pitlane", "start_s": 600, "end_s": 3000, "label": "Pit"},
        ])
        snap = engine.snapshot()
        assert "windows" in snap
        assert len(snap["windows"]) == 1
        assert snap["windows"][0]["window_type"] == "pitlane"


# ===========================================================================
# TestWindowPersistence  (Task 6)
# ===========================================================================

class TestWindowPersistence:
    """Tests for window save/load round-trip."""

    def _seed_race(self, conn):
        conn.execute(
            "INSERT INTO race_configs (race_name, race_duration_s, fuel_autonomy_s, "
            "empty_kart_kg, full_tank_kg, min_total_kart_kg, min_pit_stop_s) "
            "VALUES ('Test 1h', 3600, 2400, 85, 93, 160, 60)"
        )
        conn.execute(
            "INSERT INTO race_drivers (race_id, driver_name, driver_order, weight_kg) "
            "VALUES (1, 'Alice', 1, 65)"
        )
        conn.commit()
        return 1

    def _make_engine(self, conn):
        config = dict(
            conn.execute(
                "SELECT * FROM race_configs WHERE race_id = 1"
            ).fetchone()
        )
        drivers = [
            dict(r) for r in conn.execute(
                "SELECT * FROM race_drivers WHERE race_id = 1 ORDER BY driver_order"
            ).fetchall()
        ]
        raw_stints = [
            {"stint_order": 1, "driver_id": drivers[0]["id"], "driver_name": "Alice",
             "planned_start_s": 0, "planned_end_s": 3600, "planned_duration_s": 3600},
        ]
        return RaceStateEngine(config, drivers, raw_stints, [])

    def test_save_and_load_preserves_windows(self, engine_db):
        """Windows survive a save/load round-trip."""
        race_id = self._seed_race(engine_db)
        engine = self._make_engine(engine_db)
        engine.windows = [
            {"window_type": "pitlane", "label": "Pit 1",
             "start_s": 600, "end_s": 3000, "refuel_allowed": 1,
             "driver_change_allowed": 1, "window_order": 1},
            {"window_type": "refuel", "label": "Refuel 1",
             "start_s": 600, "end_s": 1800, "refuel_allowed": 1,
             "driver_change_allowed": 1, "window_order": 2},
        ]
        engine.save(engine_db, race_id)

        loaded = RaceStateEngine.load(engine_db, race_id)
        assert len(loaded.windows) == 2
        assert loaded.windows[0]["window_type"] == "pitlane"
        assert loaded.windows[1]["window_type"] == "refuel"

    def test_save_overwrites_previous_windows(self, engine_db):
        """Saving twice replaces previous windows, not appends."""
        race_id = self._seed_race(engine_db)
        engine = self._make_engine(engine_db)

        engine.windows = [
            {"window_type": "pitlane", "label": "Pit 1",
             "start_s": 600, "end_s": 3000, "window_order": 1},
        ]
        engine.save(engine_db, race_id)

        engine.windows = [
            {"window_type": "refuel", "label": "Refuel Only",
             "start_s": 900, "end_s": 2700, "window_order": 1},
        ]
        engine.save(engine_db, race_id)

        loaded = RaceStateEngine.load(engine_db, race_id)
        assert len(loaded.windows) == 1
        assert loaded.windows[0]["window_type"] == "refuel"

    def test_save_with_no_windows(self, engine_db):
        """Saving with empty windows list clears any previously stored."""
        race_id = self._seed_race(engine_db)
        engine = self._make_engine(engine_db)

        engine.windows = [
            {"window_type": "pitlane", "label": "Pit 1",
             "start_s": 600, "end_s": 3000, "window_order": 1},
        ]
        engine.save(engine_db, race_id)

        engine.windows = []
        engine.save(engine_db, race_id)

        loaded = RaceStateEngine.load(engine_db, race_id)
        assert len(loaded.windows) == 0


# ===========================================================================
# TestNeutralization  (Tier 6 Task 2)
# ===========================================================================

class TestNeutralization:
    """Safety car / neutralization — fuel burn pause during cascade."""

    def test_neutralized_overlap_no_periods(self):
        engine = _make_engine()
        engine.neutralizations = []
        assert engine._neutralized_overlap(0, 2360) == 0.0

    def test_neutralized_overlap_full_overlap(self):
        engine = _make_engine()
        engine.neutralizations = [{"start_s": 500, "end_s": 1000}]
        assert engine._neutralized_overlap(0, 2360) == 500.0

    def test_neutralized_overlap_partial_overlap(self):
        engine = _make_engine()
        engine.neutralizations = [{"start_s": 2000, "end_s": 3000}]
        assert engine._neutralized_overlap(0, 2360) == 360.0

    def test_neutralized_overlap_no_overlap(self):
        engine = _make_engine()
        engine.neutralizations = [{"start_s": 3000, "end_s": 4000}]
        assert engine._neutralized_overlap(0, 2360) == 0.0

    def test_neutralized_overlap_open_period(self):
        engine = _make_engine()
        engine.neutralizations = [{"start_s": 1000}]
        assert engine._neutralized_overlap(0, 2360) == 1360.0

    def test_neutralized_overlap_multiple_periods(self):
        engine = _make_engine()
        engine.neutralizations = [
            {"start_s": 100, "end_s": 200},
            {"start_s": 500, "end_s": 700},
        ]
        assert engine._neutralized_overlap(0, 2360) == 300.0

    def test_fuel_cascade_with_neutralization(self):
        engine = _make_engine()
        fuel_no_sc = engine.stints[0].fuel_at_end_kg
        engine.neutralizations = [{"start_s": 500, "end_s": 1100}]
        engine._cascade_from(1)
        fuel_with_sc = engine.stints[0].fuel_at_end_kg
        saved = engine.fuel_model.burn_rate_kgs * 600
        assert abs(fuel_with_sc - (fuel_no_sc + saved)) < 0.001

    def test_start_neutralization(self):
        engine = _make_engine()
        engine.neutralizations = []
        engine.start_neutralization(1000.0, "safety_car")
        assert len(engine.neutralizations) == 1
        assert engine.neutralizations[0]["start_s"] == 1000
        assert engine.neutralizations[0].get("end_s") is None
        assert engine.neutralizations[0]["reason"] == "safety_car"

    def test_end_neutralization(self):
        engine = _make_engine()
        engine.neutralizations = [{"start_s": 1000, "reason": "safety_car"}]
        engine.end_neutralization(1500.0)
        assert engine.neutralizations[0]["end_s"] == 1500

    def test_end_neutralization_noop_when_none_open(self):
        engine = _make_engine()
        engine.neutralizations = [{"start_s": 1000, "end_s": 1500, "reason": "safety_car"}]
        engine.end_neutralization(2000.0)
        assert engine.neutralizations[0]["end_s"] == 1500

    def test_is_neutralized_true_when_open(self):
        engine = _make_engine()
        engine.neutralizations = [{"start_s": 1000, "reason": "safety_car"}]
        assert engine.is_neutralized is True

    def test_is_neutralized_false_when_all_closed(self):
        engine = _make_engine()
        engine.neutralizations = [{"start_s": 1000, "end_s": 1500, "reason": "safety_car"}]
        assert engine.is_neutralized is False

    def test_snapshot_includes_neutralizations(self):
        engine = _make_engine()
        engine.neutralizations = [{"start_s": 500, "end_s": 800, "reason": "safety_car"}]
        snap = engine.snapshot()
        assert "neutralizations" in snap
        assert "is_neutralized" in snap
        assert snap["is_neutralized"] is False
        assert len(snap["neutralizations"]) == 1


# ===========================================================================
# TestNeutralizationPersistence  (Tier 6 Task 3)
# ===========================================================================

class TestNeutralizationPersistence:
    """Neutralization save/load round-trip."""

    @pytest.fixture
    def engine_db(self):
        from db.schema import ALL_TABLES
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        for _, ddl in ALL_TABLES:
            conn.executescript(ddl)
        yield conn
        conn.close()

    def _seed_race(self, conn):
        conn.execute(
            "INSERT INTO race_configs (race_name, race_duration_s, fuel_autonomy_s, "
            "empty_kart_kg, full_tank_kg, min_total_kart_kg, min_pit_stop_s) "
            "VALUES ('Test 2h', 7200, 2400, 85, 93, 160, 60)"
        )
        conn.execute(
            "INSERT INTO race_drivers (race_id, driver_name, driver_order, weight_kg) "
            "VALUES (1, 'Alice', 1, 65)"
        )
        conn.execute(
            "INSERT INTO race_drivers (race_id, driver_name, driver_order, weight_kg) "
            "VALUES (1, 'Bob', 2, 75)"
        )
        conn.commit()
        return 1

    def test_save_stores_neutralizations(self, engine_db):
        race_id = self._seed_race(engine_db)
        config = dict(engine_db.execute("SELECT * FROM race_configs WHERE race_id = 1").fetchone())
        drivers = [dict(r) for r in engine_db.execute(
            "SELECT * FROM race_drivers WHERE race_id = 1 ORDER BY driver_order"
        ).fetchall()]
        raw_stints = [
            {"stint_order": 1, "driver_id": drivers[0]["id"], "driver_name": "Alice",
             "planned_start_s": 0, "planned_end_s": 3600, "planned_duration_s": 3600},
        ]
        engine = RaceStateEngine(config, drivers, raw_stints)
        engine.neutralizations = [
            {"start_s": 500, "end_s": 800, "reason": "safety_car"},
            {"start_s": 2000, "end_s": 2300, "reason": "red_flag"},
        ]
        engine.save(engine_db, race_id)
        rows = engine_db.execute(
            "SELECT * FROM race_neutralizations WHERE race_id = ? ORDER BY start_s", (race_id,)
        ).fetchall()
        assert len(rows) == 2
        assert rows[0]["start_s"] == 500
        assert rows[0]["end_s"] == 800
        assert rows[0]["reason"] == "safety_car"
        assert rows[1]["reason"] == "red_flag"

    def test_load_restores_neutralizations(self, engine_db):
        race_id = self._seed_race(engine_db)
        config = dict(engine_db.execute("SELECT * FROM race_configs WHERE race_id = 1").fetchone())
        drivers = [dict(r) for r in engine_db.execute(
            "SELECT * FROM race_drivers WHERE race_id = 1 ORDER BY driver_order"
        ).fetchall()]
        raw_stints = [
            {"stint_order": 1, "driver_id": drivers[0]["id"], "driver_name": "Alice",
             "planned_start_s": 0, "planned_end_s": 3600, "planned_duration_s": 3600},
        ]
        engine = RaceStateEngine(config, drivers, raw_stints)
        engine.neutralizations = [{"start_s": 500, "end_s": 800, "reason": "safety_car"}]
        engine.save(engine_db, race_id)
        loaded = RaceStateEngine.load(engine_db, race_id)
        assert len(loaded.neutralizations) == 1
        assert loaded.neutralizations[0]["start_s"] == 500
        assert loaded.neutralizations[0]["end_s"] == 800

    def test_load_applies_neutralization_to_fuel(self, engine_db):
        race_id = self._seed_race(engine_db)
        config = dict(engine_db.execute("SELECT * FROM race_configs WHERE race_id = 1").fetchone())
        drivers = [dict(r) for r in engine_db.execute(
            "SELECT * FROM race_drivers WHERE race_id = 1 ORDER BY driver_order"
        ).fetchall()]
        raw_stints = [
            {"stint_order": 1, "driver_id": drivers[0]["id"], "driver_name": "Alice",
             "planned_start_s": 0, "planned_end_s": 3600, "planned_duration_s": 3600},
        ]
        engine = RaceStateEngine(config, drivers, raw_stints)
        engine.save(engine_db, race_id)
        loaded_no_sc = RaceStateEngine.load(engine_db, race_id)
        fuel_no_sc = loaded_no_sc.stints[0].fuel_at_end_kg

        engine_db.execute(
            "INSERT INTO race_neutralizations (race_id, start_s, end_s, reason) "
            "VALUES (?, 500, 1100, 'safety_car')", (race_id,)
        )
        engine_db.commit()
        loaded_sc = RaceStateEngine.load(engine_db, race_id)
        fuel_sc = loaded_sc.stints[0].fuel_at_end_kg
        assert fuel_sc > fuel_no_sc
