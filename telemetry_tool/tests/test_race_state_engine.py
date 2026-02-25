"""Tests for the RaceStateEngine — fuel model, stint state, and cascade logic."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from race_state_engine import FuelModel, StintState, RaceStateEngine


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
