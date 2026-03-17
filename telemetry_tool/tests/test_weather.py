"""Tests for weather helper module and weather service CRUD."""
import sqlite3
import sys
from pathlib import Path

import pytest

# Ensure project root is on sys.path (same pattern as conftest.py)
_root = str(Path(__file__).resolve().parents[1])
if _root not in sys.path:
    sys.path.insert(0, _root)

from optimizer.weather import effective_lap_time, pit_cost_laps


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def weather_db():
    """In-memory SQLite with schema for weather-related tables."""
    from db.migrate import ensure_schema
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    # Seed a race config
    conn.execute(
        "INSERT INTO race_configs (race_name, race_duration_s) VALUES (?, ?)",
        ("Test Race", 7200),
    )
    conn.commit()
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# effective_lap_time tests
# ---------------------------------------------------------------------------

def test_effective_lap_time_dry():
    """Dry condition returns base time unchanged."""
    assert effective_lap_time(60.0, 0.8, "dry") == 60.0


def test_effective_lap_time_wet_high_confidence():
    """Wet with high confidence: slightly slower than dry."""
    result = effective_lap_time(60.0, 0.9, "wet")
    # factor = 0.9, so effective = 60 / 0.9 = ~66.67
    assert result == pytest.approx(66.667, rel=0.01)


def test_effective_lap_time_wet_low_confidence():
    """Wet with low confidence: much slower than dry."""
    result = effective_lap_time(60.0, 0.3, "wet")
    # factor = 0.3, so effective = 60 / 0.3 = 200.0
    assert result == pytest.approx(200.0, rel=0.01)


def test_effective_lap_time_damp():
    """Damp condition: moderate penalty."""
    result = effective_lap_time(60.0, 0.8, "damp")
    # factor = 0.5 + 0.5 * 0.8 = 0.9, so effective = 60 / 0.9 = ~66.67
    assert result == pytest.approx(66.667, rel=0.01)


# ---------------------------------------------------------------------------
# pit_cost_laps tests
# ---------------------------------------------------------------------------

def test_pit_cost_lower_in_wet():
    """Pit cost (in laps) is lower when lap times are longer (wet)."""
    pit_s = 60.0
    dry_lap = 60.0
    wet_lap = effective_lap_time(60.0, 0.5, "wet")  # 120s
    cost_dry = pit_cost_laps(pit_s, dry_lap)
    cost_wet = pit_cost_laps(pit_s, wet_lap)
    assert cost_dry == pytest.approx(1.0)
    assert cost_wet == pytest.approx(0.5)
    assert cost_wet < cost_dry


# ---------------------------------------------------------------------------
# Weather service CRUD tests
# ---------------------------------------------------------------------------

def test_add_get_weather_window(weather_db):
    """Round-trip: add a window then retrieve it."""
    from services.race_strategy_weather import add_weather_window, get_weather_windows
    result = add_weather_window(weather_db, 1, 1800, 3600, "wet", confidence_pct=80)
    assert result == {"ok": True}
    windows = get_weather_windows(weather_db, 1)
    assert len(windows) == 1
    w = windows[0]
    assert w["start_s"] == 1800
    assert w["end_s"] == 3600
    assert w["condition"] == "wet"
    assert w["confidence_pct"] == 80


def test_add_weather_window_missing_race(weather_db):
    """Adding a window for a non-existent race returns None."""
    from services.race_strategy_weather import add_weather_window
    result = add_weather_window(weather_db, 999, 0, 100, "wet")
    assert result is None


def test_update_weather_window(weather_db):
    """Update changes the specified fields."""
    from services.race_strategy_weather import (
        add_weather_window,
        get_weather_windows,
        update_weather_window,
    )
    add_weather_window(weather_db, 1, 0, 1000, "damp", 50)
    windows = get_weather_windows(weather_db, 1)
    wid = windows[0]["id"]
    update_weather_window(weather_db, 1, wid, condition="wet", confidence_pct=90)
    updated = get_weather_windows(weather_db, 1)
    assert updated[0]["condition"] == "wet"
    assert updated[0]["confidence_pct"] == 90


def test_delete_weather_window(weather_db):
    """Delete removes the window."""
    from services.race_strategy_weather import (
        add_weather_window,
        delete_weather_window,
        get_weather_windows,
    )
    add_weather_window(weather_db, 1, 0, 500, "wet")
    windows = get_weather_windows(weather_db, 1)
    assert len(windows) == 1
    delete_weather_window(weather_db, 1, windows[0]["id"])
    assert len(get_weather_windows(weather_db, 1)) == 0


def test_set_condition(weather_db):
    """set_current_condition updates current_condition on race_configs."""
    from services.race_strategy_weather import set_current_condition
    result = set_current_condition(weather_db, 1, "wet")
    assert result == {"ok": True, "condition": "wet"}
    row = weather_db.execute(
        "SELECT current_condition FROM race_configs WHERE race_id = 1"
    ).fetchone()
    assert row["current_condition"] == "wet"


def test_set_condition_invalid(weather_db):
    """set_current_condition rejects invalid condition values."""
    from services.race_strategy_weather import set_current_condition
    result = set_current_condition(weather_db, 1, "snow")
    assert result is None
