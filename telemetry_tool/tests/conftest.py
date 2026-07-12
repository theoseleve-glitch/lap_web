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


def pytest_addoption(parser):
    parser.addoption(
        "--update-snapshots",
        action="store_true",
        default=False,
        help="Update snapshot baselines instead of comparing",
    )


@pytest.fixture
def update_snapshots(request):
    """Return True when --update-snapshots was passed on the CLI."""
    return request.config.getoption("--update-snapshots")


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
    # ------------------------------------------------------------------
    # GPS traces for s1 (3 laps on a simulated oval)
    # ------------------------------------------------------------------
    n_points = 100
    lap_length = 1000.0
    for lap_num in [1, 2, 3]:
        distances = [i * lap_length / n_points for i in range(n_points)]
        speeds = [20.0 + 5.0 * math.sin(2 * math.pi * d / lap_length) for d in distances]
        latitudes = [45.0 + 0.001 * math.cos(2 * math.pi * d / lap_length) for d in distances]
        longitudes = [7.0 + 0.002 * math.sin(2 * math.pi * d / lap_length) for d in distances]
        # Synthetic acceleration data for GG diagram
        accel_lat = [1.5 * math.sin(4 * math.pi * d / lap_length) for d in distances]
        accel_long = [0.8 * math.cos(4 * math.pi * d / lap_length) for d in distances]
        # Column names use _json suffix per schema.py
        conn.execute(
            "INSERT INTO gps_traces (session_id, lap_number, "
            "latitudes_json, longitudes_json, distances_json, speeds_json, "
            "accel_lat_json, accel_long_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "s1", lap_num,
                json.dumps(latitudes), json.dumps(longitudes),
                json.dumps(distances), json.dumps(speeds),
                json.dumps(accel_lat), json.dumps(accel_long),
            ),
        )

    # ------------------------------------------------------------------
    # Theoretical data with corner coaching for s1
    # ------------------------------------------------------------------
    corner_coaching = [
        {"corner_id": 1, "corner_name": "T1", "s_start": 100.0,
         "s_end": 200.0, "s_apex": 150.0, "direction": "left"},
        {"corner_id": 2, "corner_name": "T2", "s_start": 400.0,
         "s_end": 500.0, "s_apex": 450.0, "direction": "right"},
        {"corner_id": 3, "corner_name": "T3", "s_start": 700.0,
         "s_end": 800.0, "s_apex": 750.0, "direction": "left"},
    ]
    theoretical_speeds = [
        22.0 + 3.0 * math.sin(2 * math.pi * d / lap_length)
        for d in distances
    ]
    conn.execute(
        "INSERT INTO theoretical_data (session_id, theoretical_time_s, "
        "actual_best_time_s, gap_pct, simulation_method, "
        "speed_profile_json, distance_json, corner_coaching_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "s1", 58.0, 60.0, 3.33, "envelope",
            json.dumps(theoretical_speeds), json.dumps(distances),
            json.dumps(corner_coaching),
        ),
    )

    # ------------------------------------------------------------------
    # Corner metrics (per-lap per-corner) for s1
    # ------------------------------------------------------------------
    for lap_num in [1, 2, 3]:
        for corner in corner_coaching:
            cid = corner["corner_id"]
            conn.execute(
                "INSERT INTO corner_metrics (session_id, lap_number, corner_id, "
                "entry_speed_mps, apex_speed_mps, exit_speed_mps, brake_point_m, "
                "time_loss_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "s1", lap_num, cid,
                    25.0 - cid * 2, 18.0 - cid, 22.0 - cid,
                    corner["s_start"] - 10.0,
                    50 + cid * 20 + lap_num * 5,
                ),
            )

    # ------------------------------------------------------------------
    # Reference line for s1
    # ------------------------------------------------------------------
    conn.execute(
        "INSERT INTO reference_lines (session_id, "
        "latitudes_json, longitudes_json, distances_json, speeds_json) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            "s1",
            json.dumps(latitudes), json.dumps(longitudes),
            json.dumps(distances), json.dumps(theoretical_speeds),
        ),
    )

    # ------------------------------------------------------------------
    # Analysis JSON (sector analysis, consistency metrics) for s1
    # ------------------------------------------------------------------
    analysis_blob = {
        "consistency_metrics": {
            "cv_pct": 0.43, "std_dev_s": 0.195,
            "best_to_median_delta_s": 0.015,
        },
        "robustness_metrics": {"early_mean_s": 60.5, "late_mean_s": 61.0},
        "sector_analysis": {
            "n_sectors": 3,
            "ideal_lap_time_s": 58.234,
            "sector_stats": [
                {"sector": 1, "best_s": 14.2, "mean_s": 14.5, "std_s": 0.3},
                {"sector": 2, "best_s": 15.1, "mean_s": 15.3, "std_s": 0.2},
                {"sector": 3, "best_s": 13.8, "mean_s": 14.0, "std_s": 0.2},
            ],
        },
        "data_quality_summary": {
            "overall_confidence": 0.88, "gps_quality": 0.92,
        },
    }
    conn.execute(
        "UPDATE sessions SET analysis_json = ? WHERE session_id = 's1'",
        (json.dumps(analysis_blob),),
    )

    # ------------------------------------------------------------------
    # Driving style features for s1
    # ------------------------------------------------------------------
    conn.execute(
        "INSERT INTO driving_style_features (driver_id, session_id, "
        "trail_braking_depth, brake_point_consistency, "
        "style_label, style_confidence, "
        "strengths_json, weaknesses_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            1, "s1", 0.7, 0.85,
            "smooth", 0.82,
            json.dumps(["consistent braking", "smooth inputs"]),
            json.dumps(["late throttle application"]),
        ),
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


# ── W9.T9.4 backfill fixture ──────────────────────────────────────────
# Only activates when TELEMETRY_PG_URL_TEST is set (disposable PG). Seeds
# two session rows with NULL source/data_profile/capabilities so the
# backfill script has something to update; cleans up on teardown.

import os as _os  # already imported by sections above; rebound locally


@pytest.fixture
def disposable_pg():
    """Seed 2 sessions with source=NULL on a disposable PG."""
    dsn = _os.environ.get("TELEMETRY_PG_URL_TEST")
    if not dsn:
        pytest.skip("TELEMETRY_PG_URL_TEST not set")
    import psycopg2
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE sessions ALTER COLUMN source DROP NOT NULL")
            cur.execute("ALTER TABLE sessions ALTER COLUMN data_profile DROP NOT NULL")
            cur.execute("ALTER TABLE sessions ALTER COLUMN capabilities DROP NOT NULL")
            cur.execute(
                "INSERT INTO sessions (session_id, workspace_id, source, "
                "data_profile, capabilities) "
                "VALUES (%s, %s, NULL, NULL, NULL), (%s, %s, NULL, NULL, NULL)",
                ("00000000-0000-0000-0000-0000000000a1", "ws-test",
                 "00000000-0000-0000-0000-0000000000a2", "ws-test"),
            )
        conn.commit()
    yield
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sessions WHERE workspace_id = 'ws-test'")
            cur.execute("ALTER TABLE sessions ALTER COLUMN source SET NOT NULL")
            cur.execute("ALTER TABLE sessions ALTER COLUMN data_profile SET NOT NULL")
            cur.execute("ALTER TABLE sessions ALTER COLUMN capabilities SET NOT NULL")
        conn.commit()
