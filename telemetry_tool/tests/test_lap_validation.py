"""Tests for lap validation priority order and endurance pit detection."""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.migrate import ensure_schema
from web.models import insert_laps


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    # Insert a driver and session so FK constraints pass.
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


def _make_summary(
    n_laps=10,
    dist_flagged=None,
    time_flagged=None,
    outlap_numbers=None,
    inlap_numbers=None,
    flagged_only=None,
    deviated_laps=None,
    incomplete_laps=None,
    session_type="practice",
    drivers=None,
    joker_lap=None,
):
    """Build a minimal pipeline summary dict for testing insert_laps."""
    lap_metrics = [
        {
            "lap_number": i,
            "lap_time_s": 60.0 + i * 0.1,
            "speed_mean_mps": 20.0,
            "speed_max_mps": 30.0,
            "braking_max_mps2": 10.0,
            "accel_max_mps2": 5.0,
            "line_length_m": 500.0,
        }
        for i in range(1, n_laps + 1)
    ]
    return {
        "lap_metrics": lap_metrics,
        "best_lap_key": 1,
        "lap_to_phase": {},
        "trim_report": {
            "outlap_analysis": {
                "outlap_numbers": outlap_numbers or [],
                "inlap_numbers": inlap_numbers or [],
                "flagged_only": flagged_only or [],
            },
        },
        "incomplete_lap_analysis": {
            "incomplete_laps": incomplete_laps or [],
        },
        "anomalous_lap_analysis": {
            "flagged_laps": (dist_flagged or []) + (time_flagged or []),
            "dist_flagged": dist_flagged or [],
            "time_flagged": time_flagged or [],
        },
        "line_deviation_analysis": {
            "deviated_laps": deviated_laps or [],
        },
        "joker_lap_number": joker_lap,
        "session_meta": {
            "session_type": session_type,
            "drivers": drivers or [],
        },
    }


def _get_laps(conn, session_id="s1"):
    rows = conn.execute(
        "SELECT * FROM laps WHERE session_id = ? ORDER BY lap_number",
        (session_id,),
    ).fetchall()
    return {r["lap_number"]: dict(r) for r in rows}


class TestDistanceFirst:
    """Distance anomalies should be checked before time anomalies."""

    def test_dist_flagged_before_time(self, db):
        """A lap in both dist and time sets gets the distance label."""
        summary = _make_summary(
            dist_flagged=[3], time_flagged=[3], outlap_numbers=[3]
        )
        insert_laps(db, "s1", summary)
        laps = _get_laps(db)
        # Lap 3 is in dist (as outlap) AND time — distance wins
        assert laps[3]["is_valid"] == 0
        assert laps[3]["invalid_reason"] == "Outlap"

    def test_pure_time_anomaly(self, db):
        """A lap only in time_flagged gets 'Time anomaly'."""
        summary = _make_summary(time_flagged=[5])
        insert_laps(db, "s1", summary)
        laps = _get_laps(db)
        assert laps[5]["is_valid"] == 0
        assert laps[5]["invalid_reason"] == "Time anomaly"

    def test_dist_sub_labels_preserved(self, db):
        """Distance anomalies carry specific sub-labels."""
        summary = _make_summary(
            dist_flagged=[2, 4],
            outlap_numbers=[2],
            deviated_laps=[4],
        )
        insert_laps(db, "s1", summary)
        laps = _get_laps(db)
        assert laps[2]["invalid_reason"] == "Outlap"
        assert laps[4]["invalid_reason"] == "Track deviation"

    def test_inlap_label(self, db):
        summary = _make_summary(
            dist_flagged=[1],
            outlap_numbers=[1],
            inlap_numbers=[1],
        )
        insert_laps(db, "s1", summary)
        laps = _get_laps(db)
        assert laps[1]["invalid_reason"] == "Inlap"

    def test_pit_lap_label(self, db):
        summary = _make_summary(
            dist_flagged=[6],
            flagged_only=[6],
        )
        insert_laps(db, "s1", summary)
        laps = _get_laps(db)
        assert laps[6]["invalid_reason"] == "Pit lap"

    def test_valid_laps_untouched(self, db):
        """Laps not in any flagged set remain valid."""
        summary = _make_summary(dist_flagged=[1], time_flagged=[10])
        insert_laps(db, "s1", summary)
        laps = _get_laps(db)
        assert laps[5]["is_valid"] == 1
        assert laps[5]["invalid_reason"] is None


class TestEndurancePitDetection:
    """In endurance mode, anomalous laps near stint boundaries → 'Pitted lap'."""

    def test_near_boundary_relabeled(self, db):
        """Dist anomaly within ±3 of stint boundary → 'Pitted lap'."""
        summary = _make_summary(
            n_laps=20,
            dist_flagged=[10],
            session_type="endurance",
            drivers=[
                {"name": "A", "lap_range": (1, 10)},
                {"name": "B", "lap_range": (11, 20)},
            ],
        )
        insert_laps(db, "s1", summary)
        laps = _get_laps(db)
        assert laps[10]["invalid_reason"] == "Pitted lap"

    def test_time_anomaly_near_boundary(self, db):
        """Time anomaly within ±3 of stint boundary → 'Pitted lap'."""
        summary = _make_summary(
            n_laps=20,
            time_flagged=[11],
            session_type="endurance",
            drivers=[
                {"name": "A", "lap_range": (1, 10)},
                {"name": "B", "lap_range": (11, 20)},
            ],
        )
        insert_laps(db, "s1", summary)
        laps = _get_laps(db)
        assert laps[11]["invalid_reason"] == "Pitted lap"

    def test_far_from_boundary_keeps_label(self, db):
        """Anomaly far from any boundary keeps original label."""
        summary = _make_summary(
            n_laps=20,
            dist_flagged=[5],
            session_type="endurance",
            drivers=[
                {"name": "A", "lap_range": (1, 10)},
                {"name": "B", "lap_range": (11, 20)},
            ],
        )
        insert_laps(db, "s1", summary)
        laps = _get_laps(db)
        assert laps[5]["invalid_reason"] == "Distance anomaly"

    def test_window_boundary_exactly_3(self, db):
        """Lap exactly 3 away from boundary is still relabeled."""
        summary = _make_summary(
            n_laps=20,
            time_flagged=[7],  # boundary at 10, distance = 3
            session_type="endurance",
            drivers=[
                {"name": "A", "lap_range": (1, 10)},
                {"name": "B", "lap_range": (11, 20)},
            ],
        )
        insert_laps(db, "s1", summary)
        laps = _get_laps(db)
        assert laps[7]["invalid_reason"] == "Pitted lap"

    def test_window_boundary_4_not_relabeled(self, db):
        """Lap 4 away from boundary is NOT relabeled."""
        summary = _make_summary(
            n_laps=20,
            time_flagged=[6],  # boundary at 10, distance = 4
            session_type="endurance",
            drivers=[
                {"name": "A", "lap_range": (1, 10)},
                {"name": "B", "lap_range": (11, 20)},
            ],
        )
        insert_laps(db, "s1", summary)
        laps = _get_laps(db)
        assert laps[6]["invalid_reason"] == "Time anomaly"

    def test_non_endurance_no_relabel(self, db):
        """Practice sessions don't get pit relabeling even with drivers."""
        summary = _make_summary(
            n_laps=20,
            dist_flagged=[10],
            session_type="practice",
            drivers=[
                {"name": "A", "lap_range": (1, 10)},
                {"name": "B", "lap_range": (11, 20)},
            ],
        )
        insert_laps(db, "s1", summary)
        laps = _get_laps(db)
        assert laps[10]["invalid_reason"] == "Distance anomaly"

    def test_joker_still_wins(self, db):
        """Joker lap stays 'Joker lap' even near a stint boundary."""
        summary = _make_summary(
            n_laps=20,
            joker_lap=10,
            session_type="endurance",
            drivers=[
                {"name": "A", "lap_range": (1, 10)},
                {"name": "B", "lap_range": (11, 20)},
            ],
        )
        insert_laps(db, "s1", summary)
        laps = _get_laps(db)
        assert laps[10]["invalid_reason"] == "Joker lap"
        assert laps[10]["is_joker"] == 1
