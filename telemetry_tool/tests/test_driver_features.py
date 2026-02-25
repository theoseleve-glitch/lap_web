"""Tests for driver management features."""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.migrate import ensure_schema


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    yield conn
    conn.close()


def _seed_driver_with_session(db, driver_id=1, driver_name="Doomed"):
    """Helper: insert a driver with a session, profile, and progression."""
    db.execute(
        "INSERT INTO drivers (driver_id, driver_name) VALUES (?, ?)",
        (driver_id, driver_name),
    )
    db.execute(
        "INSERT INTO sessions (session_id, csv_filename, driver_id, session_type, "
        "session_date) VALUES ('s1', 'f.csv', ?, 'practice', '2026-01-01')",
        (driver_id,),
    )
    db.execute(
        "INSERT INTO laps (session_id, lap_number, lap_time_s) VALUES ('s1', 1, 45.0)"
    )
    db.execute(
        "INSERT INTO driver_profiles (driver_id) VALUES (?)", (driver_id,)
    )
    db.execute(
        "INSERT INTO driver_progression (driver_id, session_id, session_date, "
        "total_score) VALUES (?, 's1', '2026-01-01', 75.0)",
        (driver_id,),
    )
    db.commit()


class TestDriverDeletion:
    def test_cascade_deletes_sessions_and_profile(self, db):
        from web.models import delete_driver_cascade

        _seed_driver_with_session(db)
        counts = delete_driver_cascade(db, 1)
        db.commit()

        assert db.execute("SELECT COUNT(*) FROM drivers WHERE driver_id = 1").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM sessions WHERE driver_id = 1").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM driver_profiles WHERE driver_id = 1").fetchone()[0] == 0
        assert counts["sessions"] >= 1

    def test_cascade_deletes_laps(self, db):
        from web.models import delete_driver_cascade

        _seed_driver_with_session(db)
        delete_driver_cascade(db, 1)
        db.commit()

        assert db.execute("SELECT COUNT(*) FROM laps WHERE session_id = 's1'").fetchone()[0] == 0

    def test_cascade_deletes_progression(self, db):
        from web.models import delete_driver_cascade

        _seed_driver_with_session(db)
        delete_driver_cascade(db, 1)
        db.commit()

        assert db.execute(
            "SELECT COUNT(*) FROM driver_progression WHERE driver_id = 1"
        ).fetchone()[0] == 0

    def test_other_drivers_untouched(self, db):
        from web.models import delete_driver_cascade

        _seed_driver_with_session(db, driver_id=1, driver_name="Doomed")
        # Add second driver.
        db.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (2, 'Survivor')")
        db.execute(
            "INSERT INTO sessions (session_id, csv_filename, driver_id, session_type, "
            "session_date) VALUES ('s2', 'g.csv', 2, 'practice', '2026-01-02')"
        )
        db.commit()

        delete_driver_cascade(db, 1)
        db.commit()

        assert db.execute("SELECT COUNT(*) FROM drivers WHERE driver_id = 2").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM sessions WHERE driver_id = 2").fetchone()[0] == 1

    def test_returns_counts(self, db):
        from web.models import delete_driver_cascade

        _seed_driver_with_session(db)
        counts = delete_driver_cascade(db, 1)
        db.commit()

        assert "sessions" in counts
        assert "drivers" in counts
        assert counts["drivers"] == 1


class TestBestEverRelative:
    def test_relative_performance(self, db):
        from web.models import compute_best_ever_relative

        # Create track with record.
        db.execute(
            "INSERT INTO tracks (track_id, track_name, lap_length_m) "
            "VALUES ('t1', 'Track A', 500)"
        )
        db.execute(
            "INSERT INTO track_records (track_id, record_time_s, vehicle_class) "
            "VALUES ('t1', 60.0, 'default')"
        )
        db.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Racer')")
        db.execute(
            "INSERT INTO sessions (session_id, csv_filename, driver_id, track_id, "
            "session_type, session_date, best_lap_time_s) "
            "VALUES ('s1', 'f.csv', 1, 't1', 'practice', '2026-01-01', 61.5)"
        )
        db.commit()

        result = compute_best_ever_relative(db, 1)
        assert result["best_pct"] is not None
        assert abs(result["best_pct"] - 102.5) < 0.1  # 61.5/60.0 * 100
        assert result["best_track_name"] == "Track A"

    def test_no_records_fallback(self, db):
        from web.models import compute_best_ever_relative

        db.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Racer')")
        db.execute(
            "INSERT INTO tracks (track_id, track_name, lap_length_m) VALUES ('t1', 'T', 500)"
        )
        db.execute(
            "INSERT INTO sessions (session_id, csv_filename, driver_id, track_id, "
            "session_type, session_date, best_lap_time_s) "
            "VALUES ('s1', 'f.csv', 1, 't1', 'practice', '2026-01-01', 61.5)"
        )
        db.commit()

        result = compute_best_ever_relative(db, 1)
        assert result["best_pct"] is None
        assert result["best_absolute_s"] == 61.5

    def test_records_held(self, db):
        from web.models import compute_best_ever_relative

        db.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Champ')")
        db.execute(
            "INSERT INTO tracks (track_id, track_name, lap_length_m) VALUES ('t1', 'Track A', 500)"
        )
        db.execute(
            "INSERT INTO track_records (track_id, record_time_s, record_holder, vehicle_class) "
            "VALUES ('t1', 60.0, 'Champ', 'Senior')"
        )
        db.commit()

        result = compute_best_ever_relative(db, 1)
        assert len(result["records_held"]) == 1
        assert result["records_held"][0]["track_name"] == "Track A"


class TestConsistencyRating:
    def test_consistency_stored_as_pct(self, db):
        """consistency_rating should be raw CV% (e.g. 2.5 meaning 2.5%)."""
        from web.models import upsert_driver_profile, get_driver_profile

        db.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Test')")
        db.commit()

        upsert_driver_profile(db, 1, {"consistency_rating": 2.5})
        db.commit()

        profile = get_driver_profile(db, 1)
        # Should be 2.5 (percent), not 0.025 (ratio).
        assert profile["consistency_rating"] == 2.5
