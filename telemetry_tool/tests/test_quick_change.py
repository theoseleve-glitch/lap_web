"""Tests for quick change mode (new kart at every pit stop)."""

import sqlite3
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


@pytest.fixture
def strategy_db():
    """In-memory DB with full schema including race strategy tables."""
    from db.migrate import ensure_schema
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    yield conn
    conn.close()


class TestQuickChangeFuel:
    """Quick change mode sets fuel_at_start to full_tank for stints > 1."""

    def test_quick_change_fuel_always_full(self, strategy_db):
        """When quick_change_enabled=1, every stint after the first starts
        with a full tank (as if swapping to a new kart)."""
        from race_state_engine import RaceStateEngine

        config = {
            "race_duration_s": 10800,
            "fuel_autonomy_s": 3600,
            "full_tank_kg": 5.0,
            "empty_kart_kg": 70.0,
            "min_pit_stop_s": 60,
            "quick_change_enabled": 1,
            "refueling_allowed": 1,
        }
        drivers = {1: {"id": 1, "driver_name": "Alice", "weight_kg": 60.0}}
        raw_stints = [
            {"stint_order": 1, "driver_id": 1, "planned_duration_s": 3600,
             "planned_start_s": 0, "planned_end_s": 3600},
            {"stint_order": 2, "driver_id": 1, "planned_duration_s": 3600,
             "planned_start_s": 3660, "planned_end_s": 7260},
            {"stint_order": 3, "driver_id": 1, "planned_duration_s": 3540,
             "planned_start_s": 7320, "planned_end_s": 10860},
        ]
        pit_stops = [
            {"after_stint": 1, "refuel": True, "pit_type": "full"},
            {"after_stint": 2, "refuel": True, "pit_type": "full"},
        ]

        engine = RaceStateEngine(config, drivers, raw_stints, pit_stops)

        # Stint 1 starts with full fuel (post-quali = full since no quali)
        assert engine.stints[0].fuel_at_start_kg == pytest.approx(5.0, abs=0.01)

        # Stint 2 and 3 should also start full (quick change bypass)
        assert engine.stints[1].fuel_at_start_kg == pytest.approx(5.0, abs=0.01)
        assert engine.stints[2].fuel_at_start_kg == pytest.approx(5.0, abs=0.01)

        # Verify fuel_at_end is correctly computed (burn for 3600s with 5kg tank / 3600s autonomy)
        burn_rate = 5.0 / 3600
        expected_end_s2 = 5.0 - burn_rate * 3600
        assert engine.stints[1].fuel_at_end_kg == pytest.approx(expected_end_s2, abs=0.01)

    def test_quick_change_disabled_normal_fuel(self, strategy_db):
        """Without quick_change_enabled, fuel carries over normally
        when refueled, or from previous stint when not."""
        from race_state_engine import RaceStateEngine

        config = {
            "race_duration_s": 10800,
            "fuel_autonomy_s": 3600,
            "full_tank_kg": 5.0,
            "empty_kart_kg": 70.0,
            "min_pit_stop_s": 60,
            "quick_change_enabled": 0,
            "refueling_allowed": 1,
        }
        drivers = {1: {"id": 1, "driver_name": "Alice", "weight_kg": 60.0}}
        raw_stints = [
            {"stint_order": 1, "driver_id": 1, "planned_duration_s": 3600,
             "planned_start_s": 0, "planned_end_s": 3600},
            {"stint_order": 2, "driver_id": 1, "planned_duration_s": 3600,
             "planned_start_s": 3660, "planned_end_s": 7260},
        ]
        pit_stops = [
            {"after_stint": 1, "refuel": False, "pit_type": "quick"},
        ]

        engine = RaceStateEngine(config, drivers, raw_stints, pit_stops)

        # Stint 1 uses all fuel (3600s autonomy, 3600s stint)
        assert engine.stints[0].fuel_at_end_kg == pytest.approx(0.0, abs=0.01)

        # Stint 2 should NOT be refueled (pit_type=quick, refuel=False)
        # So it carries over from stint 1's end fuel (0.0)
        assert engine.stints[1].fuel_at_start_kg == pytest.approx(0.0, abs=0.01)


class TestKartNumberOnPitOut:
    """kart_number is stored on the next stint when provided at pit-out."""

    def test_pit_out_stores_kart_number(self, strategy_db):
        """pit_out with kart_number sets it on the activated stint."""
        from services.race_strategy import create_race, go_live, pit_in, pit_out
        from datetime import datetime, timezone

        race_id = create_race(strategy_db, {
            "race": {
                "race_name": "Test Kart",
                "race_duration_s": 7200,
                "desired_stints": 2,
            },
            "drivers": [
                {"driver_name": "Alice", "weight_kg": 60},
            ],
        })

        # Insert two stints manually
        strategy_db.execute(
            "INSERT INTO race_stints (race_id, stint_order, driver_id, "
            "planned_start_s, planned_end_s, planned_duration_s, status) "
            "VALUES (?,?,?,?,?,?,?)",
            (race_id, 1, 1, 0, 3600, 3600, "planned"),
        )
        strategy_db.execute(
            "INSERT INTO race_stints (race_id, stint_order, driver_id, "
            "planned_start_s, planned_end_s, planned_duration_s, status) "
            "VALUES (?,?,?,?,?,?,?)",
            (race_id, 2, 1, 3660, 7200, 3540, "planned"),
        )

        # Go live and simulate pit cycle
        go_live(strategy_db, race_id)
        pit_in(strategy_db, race_id)
        result = pit_out(strategy_db, race_id, kart_number="K42")

        assert result is not None
        assert result["ok"] is True

        # Check that stint 2 has the kart_number
        row = strategy_db.execute(
            "SELECT kart_number FROM race_stints WHERE race_id = ? AND stint_order = 2",
            (race_id,),
        ).fetchone()
        assert row["kart_number"] == "K42"
