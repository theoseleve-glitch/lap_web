"""Tests for the batch corner replay endpoint helper.

Tests ``_build_corner_replay_response`` and ``_has_variance`` from
``web.routes.api_v1_data`` using an in-memory SQLite database with
the real schema.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

# Ensure project root is on path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from web.routes.api_v1_data import _build_corner_replay_response, _has_variance


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_conn() -> sqlite3.Connection:
    """Create an in-memory SQLite connection with the required tables."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS drivers (
            driver_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            driver_name TEXT NOT NULL UNIQUE,
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            notes       TEXT
        );

        CREATE TABLE IF NOT EXISTS tracks (
            track_id     TEXT PRIMARY KEY,
            track_name   TEXT NOT NULL,
            lap_length_m REAL NOT NULL,
            bbox_lat_min REAL,
            bbox_lat_max REAL,
            bbox_lon_min REAL,
            bbox_lon_max REAL,
            start_lat    REAL,
            start_lon    REAL,
            sample_count INTEGER,
            lap_count    INTEGER,
            has_joker    INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS sessions (
            session_id      TEXT PRIMARY KEY,
            csv_filename    TEXT NOT NULL,
            driver_id       INTEGER NOT NULL REFERENCES drivers(driver_id),
            track_id        TEXT REFERENCES tracks(track_id),
            session_type    TEXT NOT NULL DEFAULT 'practice',
            track_state     TEXT NOT NULL DEFAULT 'dry',
            session_date    TEXT NOT NULL,
            n_laps          INTEGER,
            best_lap_time_s REAL,
            mean_lap_time_s REAL,
            total_score     REAL,
            grade           TEXT,
            weather_json    TEXT,
            notes           TEXT,
            html_report_path TEXT,
            simulation_method TEXT,
            joker_lap_number INTEGER,
            created_at      TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS laps (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id       TEXT NOT NULL REFERENCES sessions(session_id),
            lap_number       INTEGER NOT NULL,
            lap_time_s       REAL,
            speed_mean_mps   REAL,
            speed_max_mps    REAL,
            braking_max_mps2 REAL,
            accel_max_mps2   REAL,
            line_length_m    REAL,
            is_valid         INTEGER NOT NULL DEFAULT 1,
            is_best          INTEGER NOT NULL DEFAULT 0,
            phase_id         INTEGER,
            invalid_reason   TEXT,
            is_joker         INTEGER NOT NULL DEFAULT 0,
            UNIQUE(session_id, lap_number)
        );

        CREATE TABLE IF NOT EXISTS gps_traces (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id      TEXT NOT NULL REFERENCES sessions(session_id),
            lap_number      INTEGER NOT NULL,
            latitudes_json  TEXT NOT NULL,
            longitudes_json TEXT NOT NULL,
            distances_json  TEXT NOT NULL,
            speeds_json     TEXT NOT NULL,
            accel_lat_json  TEXT,
            accel_long_json TEXT,
            UNIQUE(session_id, lap_number)
        );

        CREATE TABLE IF NOT EXISTS track_key_corners (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            track_id  TEXT NOT NULL REFERENCES tracks(track_id),
            corner_id INTEGER NOT NULL,
            label     TEXT,
            lat       REAL,
            lon       REAL,
            dist_m    REAL,
            UNIQUE(track_id, corner_id)
        );

        CREATE TABLE IF NOT EXISTS corner_metrics (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id       TEXT NOT NULL REFERENCES sessions(session_id),
            lap_number       INTEGER NOT NULL,
            corner_id        INTEGER NOT NULL,
            brake_point_m    REAL,
            brake_intensity  REAL,
            entry_speed_mps  REAL,
            apex_speed_mps   REAL,
            exit_speed_mps   REAL,
            throttle_onset_m REAL,
            exit_accel_mps2  REAL,
            grip_utilization REAL,
            time_loss_ms     REAL,
            coaching_hint    TEXT,
            UNIQUE(session_id, lap_number, corner_id)
        );
    """)
    conn.commit()
    return conn


def _make_gps_trace(n_points: int = 300, lap_length_m: float = 1000.0):
    """Generate synthetic GPS trace arrays.

    Returns (latitudes, longitudes, distances, speeds, accel_lat, accel_lon).
    """
    import math

    lats = [45.0 + i * 0.0001 for i in range(n_points)]
    lons = [7.0 + i * 0.00015 for i in range(n_points)]
    distances = [i * (lap_length_m / n_points) for i in range(n_points)]
    speeds = [15.0 + 5.0 * math.sin(i * 0.05) for i in range(n_points)]
    accel_lat = [0.5 * math.sin(i * 0.1) for i in range(n_points)]
    accel_lon = [0.3 * math.cos(i * 0.1) for i in range(n_points)]
    return lats, lons, distances, speeds, accel_lat, accel_lon


def _seed_full_session(
    conn: sqlite3.Connection,
    session_id: str = "s1",
    track_id: str = "t1",
    n_laps: int = 3,
    n_corners: int = 3,
    n_gps_points: int = 300,
    lap_length_m: float = 1000.0,
    include_key_corners: bool = True,
    include_corner_metrics: bool = True,
):
    """Seed a complete session with driver, track, laps, GPS, corners, metrics."""
    # Driver
    conn.execute(
        "INSERT OR IGNORE INTO drivers (driver_id, driver_name) VALUES (1, 'TestDriver')"
    )
    # Track
    conn.execute(
        "INSERT OR IGNORE INTO tracks (track_id, track_name, lap_length_m) "
        "VALUES (?, ?, ?)",
        (track_id, "TestTrack", lap_length_m),
    )
    # Session
    conn.execute(
        "INSERT INTO sessions (session_id, csv_filename, driver_id, track_id, "
        "session_type, track_state, session_date, n_laps, best_lap_time_s) "
        "VALUES (?, 'test.csv', 1, ?, 'practice', 'dry', '2024-06-01', ?, ?)",
        (session_id, track_id, n_laps, 58.5),
    )

    # Laps
    for i in range(1, n_laps + 1):
        conn.execute(
            "INSERT INTO laps (session_id, lap_number, lap_time_s, is_valid) "
            "VALUES (?, ?, ?, 1)",
            (session_id, i, 58.5 + i * 0.2),
        )

    # GPS traces
    for i in range(1, n_laps + 1):
        lats, lons, dists, speeds, alat, alon = _make_gps_trace(
            n_gps_points, lap_length_m
        )
        conn.execute(
            "INSERT INTO gps_traces "
            "(session_id, lap_number, latitudes_json, longitudes_json, "
            "distances_json, speeds_json, accel_lat_json, accel_long_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id,
                i,
                json.dumps(lats),
                json.dumps(lons),
                json.dumps(dists),
                json.dumps(speeds),
                json.dumps(alat),
                json.dumps(alon),
            ),
        )

    # Key corners
    if include_key_corners:
        for c in range(1, n_corners + 1):
            dist = c * (lap_length_m / (n_corners + 1))
            conn.execute(
                "INSERT INTO track_key_corners "
                "(track_id, corner_id, label, lat, lon, dist_m) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (track_id, c, f"Turn {c}", 45.0 + c * 0.001, 7.0 + c * 0.001, dist),
            )

    # Corner metrics
    if include_corner_metrics:
        for lap in range(1, n_laps + 1):
            for c in range(1, n_corners + 1):
                dist = c * (lap_length_m / (n_corners + 1))
                conn.execute(
                    "INSERT INTO corner_metrics "
                    "(session_id, lap_number, corner_id, brake_point_m, "
                    "entry_speed_mps, apex_speed_mps, exit_speed_mps, "
                    "time_loss_ms, coaching_hint) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        session_id,
                        lap,
                        c,
                        dist - 20.0,  # brake point 20m before corner
                        20.0 - c * 1.5,
                        15.0 - c * 1.0,
                        18.0 - c * 1.2,
                        30.0 + c * 5.0,
                        f"Brake later into Turn {c}",
                    ),
                )

    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Tests for _has_variance
# ---------------------------------------------------------------------------


class TestHasVariance:
    def test_empty_list(self):
        assert _has_variance([]) is False

    def test_all_same(self):
        assert _has_variance([5.0] * 100) is False

    def test_has_variance(self):
        assert _has_variance([1.0, 2.0, 1.0]) is True

    def test_single_element(self):
        assert _has_variance([7.0]) is False

    def test_variance_beyond_50(self):
        # First 50 same, then different — should return False (only checks first 50)
        arr = [1.0] * 50 + [2.0] * 10
        assert _has_variance(arr) is False


# ---------------------------------------------------------------------------
# Tests for _build_corner_replay_response
# ---------------------------------------------------------------------------


class TestBuildCornerReplayResponse:
    def test_returns_none_for_missing_session(self):
        conn = _make_conn()
        result = _build_corner_replay_response(conn, "nonexistent")
        assert result is None
        conn.close()

    def test_returns_409_signal_when_no_key_corners(self):
        conn = _make_conn()
        _seed_full_session(conn, include_key_corners=False)
        result = _build_corner_replay_response(conn, "s1")
        assert result == "NO_KEY_CORNERS"
        conn.close()

    def test_returns_422_signal_when_fewer_than_2_laps(self):
        conn = _make_conn()
        _seed_full_session(conn, n_laps=1)
        result = _build_corner_replay_response(conn, "s1")
        assert result == "INSUFFICIENT_LAPS"
        conn.close()

    def test_full_response_structure(self):
        conn = _make_conn()
        _seed_full_session(conn)
        result = _build_corner_replay_response(conn, "s1")
        assert isinstance(result, dict)
        expected_keys = {
            "session_id",
            "track_id",
            "has_pedal_data",
            "has_steering_data",
            "corners",
            "laps",
            "traces",
            "replay_windows",
            "corner_metrics",
        }
        assert set(result.keys()) == expected_keys
        assert result["session_id"] == "s1"
        assert result["track_id"] == "t1"
        conn.close()

    def test_corners_sorted_by_dist_m(self):
        conn = _make_conn()
        _seed_full_session(conn, n_corners=4)
        result = _build_corner_replay_response(conn, "s1")
        corners = result["corners"]
        dists = [c["dist_m"] for c in corners]
        assert dists == sorted(dists), "Corners should be sorted by dist_m ascending"
        conn.close()

    def test_has_pedal_data_false_when_no_brake_throttle(self):
        conn = _make_conn()
        _seed_full_session(conn)
        result = _build_corner_replay_response(conn, "s1")
        # GPS-only data (gps_traces schema has no brake/throttle columns)
        assert result["has_pedal_data"] is False
        conn.close()

    def test_has_steering_data_false_when_no_steering(self):
        conn = _make_conn()
        _seed_full_session(conn)
        result = _build_corner_replay_response(conn, "s1")
        assert result["has_steering_data"] is False
        conn.close()

    def test_trace_keys_omit_pedal_when_not_available(self):
        conn = _make_conn()
        _seed_full_session(conn)
        result = _build_corner_replay_response(conn, "s1")
        for lap_key, trace in result["traces"].items():
            assert "brake" not in trace, "brake should not be in trace without pedal data"
            assert "throttle" not in trace, "throttle should not be in trace without pedal data"
            assert "steering" not in trace, "steering should not be in trace without steering data"
            # Core keys should always be present
            assert "lat" in trace
            assert "lon" in trace
            assert "dist_m" in trace
            assert "speed_mps" in trace
        conn.close()

    def test_replay_window_indices_within_bounds(self):
        conn = _make_conn()
        n_points = 300
        _seed_full_session(conn, n_gps_points=n_points)
        result = _build_corner_replay_response(conn, "s1")
        for cid, window in result["replay_windows"].items():
            assert window["start_idx"] >= 0, f"start_idx negative for corner {cid}"
            assert window["end_idx"] < n_points, (
                f"end_idx ({window['end_idx']}) >= n_points ({n_points}) for corner {cid}"
            )
            assert window["start_idx"] <= window["end_idx"], (
                f"start_idx > end_idx for corner {cid}"
            )
        conn.close()

    def test_laps_have_correct_structure(self):
        conn = _make_conn()
        _seed_full_session(conn, n_laps=4)
        result = _build_corner_replay_response(conn, "s1")
        assert len(result["laps"]) == 4
        for lap in result["laps"]:
            assert "lap_number" in lap
            assert "lap_time_s" in lap
            assert isinstance(lap["lap_number"], int)
            assert isinstance(lap["lap_time_s"], float)
        conn.close()

    def test_corner_metrics_keyed_by_corner_id(self):
        conn = _make_conn()
        n_corners = 3
        _seed_full_session(conn, n_corners=n_corners)
        result = _build_corner_replay_response(conn, "s1")
        cm = result["corner_metrics"]
        # Keys should be string corner IDs
        for c in range(1, n_corners + 1):
            assert str(c) in cm, f"corner_id '{c}' missing from corner_metrics keys"
            metrics_list = cm[str(c)]
            assert isinstance(metrics_list, list)
            assert len(metrics_list) > 0
            # Each metric entry should have the expected fields
            for m in metrics_list:
                assert "lap_number" in m
                assert "brake_point_m" in m
                assert "entry_speed_mps" in m
                assert "apex_speed_mps" in m
                assert "exit_speed_mps" in m
                assert "time_loss_ms" in m
                assert "coaching_hint" in m
        conn.close()
