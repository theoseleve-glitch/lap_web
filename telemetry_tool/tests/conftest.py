"""Shared fixtures for the comprehensive test suite."""

import json
import math
import sqlite3
import sys
from pathlib import Path

import pytest

# Ensure project root is on path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


@pytest.fixture
def test_db():
    """Create an in-memory SQLite database with full schema."""
    from db.migrate import ensure_schema
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def seeded_db(test_db):
    """Database with sample driver, track, and sessions."""
    conn = test_db
    conn.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'TestDriver')")
    conn.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (2, 'RivalDriver')")
    conn.execute(
        "INSERT INTO tracks (track_id, track_name, lap_length_m) "
        "VALUES ('t1', 'TestTrack', 1000.0)"
    )
    # Session 1: 10 laps, practice
    conn.execute(
        "INSERT INTO sessions (session_id, csv_filename, driver_id, track_id, "
        "session_type, track_state, session_date, n_laps, best_lap_time_s, "
        "mean_lap_time_s, total_score, grade) "
        "VALUES ('s1', 'test1.csv', 1, 't1', 'practice', 'dry', '2024-01-01', "
        "10, 60.0, 61.5, 75.0, 'B')"
    )
    for i in range(1, 11):
        conn.execute(
            "INSERT INTO laps (session_id, lap_number, lap_time_s, is_valid) "
            "VALUES ('s1', ?, ?, 1)",
            (i, 60.0 + i * 0.3),
        )
    # Session 2: 15 laps, qualifying
    conn.execute(
        "INSERT INTO sessions (session_id, csv_filename, driver_id, track_id, "
        "session_type, track_state, session_date, n_laps, best_lap_time_s, "
        "mean_lap_time_s, total_score, grade) "
        "VALUES ('s2', 'test2.csv', 1, 't1', 'qualifying', 'dry', '2024-01-02', "
        "15, 58.5, 59.5, 85.0, 'A')"
    )
    for i in range(1, 16):
        conn.execute(
            "INSERT INTO laps (session_id, lap_number, lap_time_s, is_valid) "
            "VALUES ('s2', ?, ?, 1)",
            (i, 58.5 + i * 0.2),
        )
    # Score details
    conn.execute(
        "INSERT INTO score_details (session_id, pace_score, pace_max, consistency_score, "
        "consistency_max, execution_score, execution_max, robustness_score, robustness_max) "
        "VALUES ('s1', 18, 25, 15, 25, 20, 25, 22, 25)"
    )
    conn.execute(
        "INSERT INTO score_details (session_id, pace_score, pace_max, consistency_score, "
        "consistency_max, execution_score, execution_max, robustness_score, robustness_max) "
        "VALUES ('s2', 23, 25, 22, 25, 20, 25, 20, 25)"
    )
    conn.commit()
    return conn


def make_corner_metrics(n_laps=5, n_corners=4):
    """Generate synthetic corner metrics for testing."""
    metrics = {}
    for lap in range(1, n_laps + 1):
        lap_metrics = []
        for corner in range(1, n_corners + 1):
            lap_metrics.append({
                "corner_id": corner,
                "brake_point_m": 50.0 + corner * 10 + (lap % 3) * 0.5,
                "brake_intensity": 0.8 + corner * 0.05,
                "entry_speed_mps": 25.0 - corner * 2,
                "apex_speed_mps": 18.0 - corner * 1.5,
                "exit_speed_mps": 22.0 - corner * 1.5,
                "throttle_onset_m": 10.0 + corner * 2 + (lap % 2) * 0.3,
                "exit_accel_mps2": 5.0 + corner * 0.5,
                "grip_utilization": 0.85 + corner * 0.02,
                "time_loss_ms": 20 + corner * 10 + lap * 2,
            })
        metrics[lap] = lap_metrics
    return metrics
