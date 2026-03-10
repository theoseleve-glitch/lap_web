"""Tests for rolling-average lap validity detection."""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.migrate import ensure_schema
from web.models import insert_laps
from web.repos.lap_repo import _rolling_avg_validity


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    conn.execute(
        "INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Test')"
    )
    conn.execute(
        "INSERT INTO sessions (session_id, csv_filename, driver_id, session_type, session_date) "
        "VALUES ('s1', 'test.csv', 1, 'practice', '2026-01-01')"
    )
    conn.commit()
    yield conn
    conn.close()


def _make_laps(
    n=10,
    base_time=60.0,
    base_dist=500.0,
    time_overrides=None,
    dist_overrides=None,
):
    """Build lap_metrics list with optional per-lap time/distance overrides."""
    time_overrides = time_overrides or {}
    dist_overrides = dist_overrides or {}
    return [
        {
            "lap_number": i,
            "lap_time_s": time_overrides.get(i, base_time + (i - 1) * 0.05),
            "speed_mean_mps": 20.0,
            "speed_max_mps": 30.0,
            "braking_max_mps2": 10.0,
            "accel_max_mps2": 5.0,
            "line_length_m": dist_overrides.get(i, base_dist),
        }
        for i in range(1, n + 1)
    ]


def _make_summary(lap_metrics, best_key=1, joker_lap=None):
    """Build a minimal pipeline summary for insert_laps."""
    return {
        "lap_metrics": lap_metrics,
        "best_lap_key": best_key,
        "lap_to_phase": {},
        "joker_lap_number": joker_lap,
    }


def _get_laps(conn, session_id="s1"):
    rows = conn.execute(
        "SELECT * FROM laps WHERE session_id = ? ORDER BY lap_number",
        (session_id,),
    ).fetchall()
    return {r["lap_number"]: dict(r) for r in rows}


class TestRollingAvgUnit:
    """Unit tests for _rolling_avg_validity() directly."""

    def test_all_consistent_laps_valid(self):
        metrics = _make_laps(n=10)
        result = _rolling_avg_validity(metrics)
        for i in range(1, 11):
            assert result[i][0] is True, f"Lap {i} should be valid"

    def test_time_anomaly_detected(self):
        """A lap with 2x the normal time → flagged."""
        metrics = _make_laps(n=8, time_overrides={6: 120.0})
        result = _rolling_avg_validity(metrics)
        assert result[6][0] is False
        assert "Time" in result[6][1]

    def test_distance_anomaly_detected(self):
        """A lap with half the normal distance → flagged."""
        metrics = _make_laps(n=8, dist_overrides={5: 250.0})
        result = _rolling_avg_validity(metrics)
        assert result[5][0] is False
        assert "Distance" in result[5][1]

    def test_both_anomalies(self):
        """A lap with both time and distance anomaly → both reasons."""
        metrics = _make_laps(n=8, time_overrides={5: 120.0}, dist_overrides={5: 250.0})
        result = _rolling_avg_validity(metrics)
        assert result[5][0] is False
        assert "Time" in result[5][1]
        assert "Distance" in result[5][1]

    def test_invalid_doesnt_poison_window(self):
        """After one bad lap, the next normal lap should still be valid."""
        metrics = _make_laps(n=10, time_overrides={5: 120.0})
        result = _rolling_avg_validity(metrics)
        assert result[5][0] is False
        assert result[6][0] is True  # normal lap after anomaly
        assert result[7][0] is True

    def test_first_two_laps_always_accepted(self):
        """First 2 laps seed the window — always valid."""
        metrics = _make_laps(n=5)
        result = _rolling_avg_validity(metrics)
        assert result[1][0] is True
        assert result[2][0] is True

    def test_missing_time_invalid(self):
        """Lap with no time → invalid."""
        metrics = _make_laps(n=5, time_overrides={3: None})
        result = _rolling_avg_validity(metrics)
        assert result[3][0] is False
        assert result[3][1] == "No lap time"

    def test_zero_time_invalid(self):
        """Lap with 0 time → invalid."""
        metrics = _make_laps(n=5, time_overrides={3: 0.0})
        result = _rolling_avg_validity(metrics)
        assert result[3][0] is False

    def test_slightly_fast_lap_valid(self):
        """A lap 5% faster than average is still valid (within 90-110%)."""
        # Base ~60s, 5% faster = 57s → within [54, 66]
        metrics = _make_laps(n=8, time_overrides={6: 57.0})
        result = _rolling_avg_validity(metrics)
        assert result[6][0] is True

    def test_borderline_slow_invalid(self):
        """A lap 12% slower than average → invalid (>110%)."""
        # Base ~60s, 12% slower = 67.2s → outside [54, 66]
        metrics = _make_laps(n=8, time_overrides={6: 67.2})
        result = _rolling_avg_validity(metrics)
        assert result[6][0] is False

    def test_missing_distance_uses_time_only(self):
        """When distance is None/0, only time is checked."""
        metrics = _make_laps(n=6, dist_overrides={i: None for i in range(1, 7)})
        result = _rolling_avg_validity(metrics)
        for i in range(1, 7):
            assert result[i][0] is True  # all times are normal

    def test_pit_lap_both_anomalous(self):
        """A pit lap (very slow + short distance) → caught by both checks."""
        metrics = _make_laps(
            n=8,
            time_overrides={5: 180.0},  # 3x normal time (pit stop)
            dist_overrides={5: 200.0},  # cut through pit lane
        )
        result = _rolling_avg_validity(metrics)
        assert result[5][0] is False
        assert "Time" in result[5][1]
        assert "Distance" in result[5][1]

    def test_crash_lap_time_anomaly(self):
        """A crash lap (very long time) → caught by time check."""
        metrics = _make_laps(n=8, time_overrides={4: 300.0})
        result = _rolling_avg_validity(metrics)
        assert result[4][0] is False
        assert "Time" in result[4][1]

    def test_multiple_consecutive_bad_laps(self):
        """Multiple bad laps in a row don't cascade — good laps after stay valid."""
        metrics = _make_laps(
            n=10,
            time_overrides={5: 120.0, 6: 130.0, 7: 150.0},
        )
        result = _rolling_avg_validity(metrics)
        assert result[5][0] is False
        assert result[6][0] is False
        assert result[7][0] is False
        assert result[8][0] is True  # back to normal
        assert result[9][0] is True


class TestInsertLapsIntegration:
    """Integration tests: insert_laps writes correct validity to DB."""

    def test_normal_session_all_valid(self, db):
        metrics = _make_laps(n=8)
        insert_laps(db, "s1", _make_summary(metrics))
        laps = _get_laps(db)
        for n in range(1, 9):
            assert laps[n]["is_valid"] == 1, f"Lap {n} should be valid"
            assert laps[n]["invalid_reason"] is None

    def test_anomalous_lap_flagged(self, db):
        metrics = _make_laps(n=8, time_overrides={5: 120.0})
        insert_laps(db, "s1", _make_summary(metrics))
        laps = _get_laps(db)
        assert laps[5]["is_valid"] == 0
        assert laps[5]["invalid_reason"] is not None
        # Other laps remain valid
        assert laps[4]["is_valid"] == 1
        assert laps[6]["is_valid"] == 1

    def test_joker_overrides_rolling_avg(self, db):
        """Joker lap is always invalid regardless of rolling avg."""
        metrics = _make_laps(n=8)
        insert_laps(db, "s1", _make_summary(metrics, joker_lap=3))
        laps = _get_laps(db)
        assert laps[3]["is_valid"] == 0
        assert laps[3]["invalid_reason"] == "Joker lap"
        assert laps[3]["is_joker"] == 1

    def test_best_lap_flag(self, db):
        metrics = _make_laps(n=5)
        insert_laps(db, "s1", _make_summary(metrics, best_key=2))
        laps = _get_laps(db)
        assert laps[2]["is_best"] == 1
        assert laps[1]["is_best"] == 0

    def test_count_returned(self, db):
        metrics = _make_laps(n=6)
        count = insert_laps(db, "s1", _make_summary(metrics))
        assert count == 6
