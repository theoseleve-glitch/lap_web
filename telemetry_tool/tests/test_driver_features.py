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


def _seed_two_drivers(db):
    """Helper: seed two drivers with sessions, profiles, and progression."""
    db.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Alice')")
    db.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (2, 'Bob')")
    db.execute(
        "INSERT INTO tracks (track_id, track_name, lap_length_m) "
        "VALUES ('t1', 'TestTrack', 500)"
    )
    # Alice: 3 sessions, faster, more consistent
    for i in range(1, 4):
        sid = f"a{i}"
        db.execute(
            "INSERT INTO sessions (session_id, csv_filename, driver_id, track_id, "
            "session_type, session_date, best_lap_time_s, n_laps, total_score) "
            "VALUES (?, ?, 1, 't1', 'practice', ?, ?, 10, ?)",
            (sid, f"a{i}.csv", f"2026-01-0{i}", 45.0 - i * 0.1, 70.0 + i * 5),
        )
        db.execute(
            "INSERT INTO driver_progression (driver_id, session_id, session_date, "
            "total_score, n_laps) VALUES (1, ?, ?, ?, 10)",
            (sid, f"2026-01-0{i}", 70.0 + i * 5),
        )
    # Bob: 2 sessions, slower, less consistent
    for i in range(1, 3):
        sid = f"b{i}"
        db.execute(
            "INSERT INTO sessions (session_id, csv_filename, driver_id, track_id, "
            "session_type, session_date, best_lap_time_s, n_laps, total_score) "
            "VALUES (?, ?, 2, 't1', 'practice', ?, ?, 8, ?)",
            (sid, f"b{i}.csv", f"2026-01-0{i}", 46.0 + i * 0.2, 60.0 + i * 2),
        )
        db.execute(
            "INSERT INTO driver_progression (driver_id, session_id, session_date, "
            "total_score, n_laps) VALUES (2, ?, ?, ?, 8)",
            (sid, f"2026-01-0{i}", 60.0 + i * 2),
        )
    # Alice profile with consistency
    db.execute(
        "INSERT INTO driver_profiles (driver_id, consistency_rating) VALUES (1, 2.5)"
    )
    db.execute(
        "INSERT INTO driver_profiles (driver_id, consistency_rating) VALUES (2, 5.1)"
    )
    db.commit()


class TestHeadToHead:
    def test_build_h2h_returns_five_metrics(self, db):
        from web.routes.comparisons import _driver_summary, _build_h2h

        _seed_two_drivers(db)
        a = _driver_summary(db, 1)
        b = _driver_summary(db, 2)
        rows = _build_h2h(a, b)
        assert len(rows) == 5
        keys = [r["key"] for r in rows]
        assert keys == ["pace", "consistency", "avg_score", "total_laps", "progression"]

    def test_pace_winner_is_lower(self, db):
        from web.routes.comparisons import _driver_summary, _build_h2h

        _seed_two_drivers(db)
        a = _driver_summary(db, 1)
        b = _driver_summary(db, 2)
        rows = _build_h2h(a, b)
        pace_row = rows[0]
        # Alice has lower best time → winner
        assert pace_row["winner"] == "a"

    def test_consistency_winner_is_lower_cv(self, db):
        from web.routes.comparisons import _driver_summary, _build_h2h

        _seed_two_drivers(db)
        a = _driver_summary(db, 1)
        b = _driver_summary(db, 2)
        rows = _build_h2h(a, b)
        cons_row = rows[1]
        # Alice has 2.5% CV vs Bob 5.1% → Alice wins
        assert cons_row["winner"] == "a"

    def test_avg_score_winner(self, db):
        from web.routes.comparisons import _driver_summary, _build_h2h

        _seed_two_drivers(db)
        a = _driver_summary(db, 1)
        b = _driver_summary(db, 2)
        rows = _build_h2h(a, b)
        score_row = rows[2]
        # Alice avg ~80 vs Bob avg ~63 → Alice
        assert score_row["winner"] == "a"

    def test_total_laps_winner(self, db):
        from web.routes.comparisons import _driver_summary, _build_h2h

        _seed_two_drivers(db)
        a = _driver_summary(db, 1)
        b = _driver_summary(db, 2)
        rows = _build_h2h(a, b)
        laps_row = rows[3]
        # Alice: 3*10=30, Bob: 2*8=16 → Alice
        assert laps_row["winner"] == "a"
        assert laps_row["val_a"] == 30
        assert laps_row["val_b"] == 16

    def test_progression_rate_computed(self, db):
        from web.routes.comparisons import _driver_summary, _build_h2h

        _seed_two_drivers(db)
        a = _driver_summary(db, 1)
        b = _driver_summary(db, 2)
        rows = _build_h2h(a, b)
        prog_row = rows[4]
        # Alice: 75→80→85, slope=5. Bob: 62→64, slope=2.
        assert prog_row["val_a"] is not None
        assert prog_row["val_b"] is not None
        assert prog_row["winner"] == "a"  # Higher slope is better


class TestSessionEditing:
    def test_update_session_type(self, db):
        from web.models import update_session_field, get_session_by_id

        db.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Test')")
        db.execute(
            "INSERT INTO sessions (session_id, csv_filename, driver_id, "
            "session_type, session_date) VALUES ('s1', 'f.csv', 1, 'practice', '2026-01-01')"
        )
        db.commit()

        update_session_field(db, "s1", "session_type", "race")
        db.commit()

        session = get_session_by_id(db, "s1")
        assert session["session_type"] == "race"

    def test_update_track_state(self, db):
        from web.models import update_session_field, get_session_by_id

        db.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Test')")
        db.execute(
            "INSERT INTO sessions (session_id, csv_filename, driver_id, "
            "session_type, session_date, track_state) "
            "VALUES ('s1', 'f.csv', 1, 'practice', '2026-01-01', 'dry')"
        )
        db.commit()

        update_session_field(db, "s1", "track_state", "wet")
        db.commit()

        session = get_session_by_id(db, "s1")
        assert session["track_state"] == "wet"

    def test_update_session_date(self, db):
        from web.models import update_session_field, get_session_by_id

        db.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Test')")
        db.execute(
            "INSERT INTO sessions (session_id, csv_filename, driver_id, "
            "session_type, session_date) VALUES ('s1', 'f.csv', 1, 'practice', '2026-01-01')"
        )
        db.commit()

        update_session_field(db, "s1", "session_date", "2026-03-15")
        db.commit()

        session = get_session_by_id(db, "s1")
        assert session["session_date"] == "2026-03-15"

    def test_update_driver_id(self, db):
        from web.models import update_session_field, get_session_by_id

        db.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Old')")
        db.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (2, 'New')")
        db.execute(
            "INSERT INTO sessions (session_id, csv_filename, driver_id, "
            "session_type, session_date) VALUES ('s1', 'f.csv', 1, 'practice', '2026-01-01')"
        )
        db.commit()

        update_session_field(db, "s1", "driver_id", "2")
        db.commit()

        session = get_session_by_id(db, "s1")
        assert session["driver_id"] == 2

    def test_reject_disallowed_field(self, db):
        from web.models import update_session_field

        db.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'T')")
        db.execute(
            "INSERT INTO sessions (session_id, csv_filename, driver_id, "
            "session_type, session_date) VALUES ('s1', 'f.csv', 1, 'practice', '2026-01-01')"
        )
        db.commit()

        with pytest.raises(ValueError, match="not editable"):
            update_session_field(db, "s1", "total_score", "99")


class TestDriverContactFields:
    def test_contact_fields_saved(self, db):
        from web.models import update_driver_profile_field, get_driver_profile, upsert_driver_profile

        db.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Test')")
        upsert_driver_profile(db, 1, {})
        db.commit()

        update_driver_profile_field(db, 1, "email", "test@example.com")
        update_driver_profile_field(db, 1, "phone", "+1 234 567")
        update_driver_profile_field(db, 1, "id_code", "DRV-001")
        db.commit()

        profile = get_driver_profile(db, 1)
        assert profile["email"] == "test@example.com"
        assert profile["phone"] == "+1 234 567"
        assert profile["id_code"] == "DRV-001"

    def test_contact_fields_in_upsert(self, db):
        from web.models import upsert_driver_profile, get_driver_profile

        db.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Test')")
        db.commit()

        upsert_driver_profile(db, 1, {
            "email": "mgr@team.com",
            "phone": "+33 6 12 34",
            "id_code": "FR-1234",
        })
        db.commit()

        profile = get_driver_profile(db, 1)
        assert profile["email"] == "mgr@team.com"
        assert profile["id_code"] == "FR-1234"


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


class TestAutoTrackReference:
    def _seed_track_and_session(self, db, session_id="s1", track_state="dry"):
        db.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Test')")
        db.execute(
            "INSERT INTO tracks (track_id, track_name, lap_length_m) "
            "VALUES ('t1', 'TestTrack', 500)"
        )
        db.execute(
            "INSERT INTO sessions (session_id, csv_filename, driver_id, track_id, "
            "session_type, session_date, track_state) "
            "VALUES (?, 'f.csv', 1, 't1', 'practice', '2026-01-01', ?)",
            (session_id, track_state),
        )
        # Insert a reference line for this session.
        db.execute(
            "INSERT INTO reference_lines (session_id, latitudes_json, "
            "longitudes_json, distances_json) VALUES (?, '[1]', '[2]', '[0]')",
            (session_id,),
        )
        db.commit()

    def test_dry_ref_auto_set(self, db):
        from web.models import auto_set_track_reference

        self._seed_track_and_session(db, "s1", "dry")
        result = auto_set_track_reference(db, "s1")
        db.commit()

        assert result == "dry"
        track = db.execute("SELECT dry_ref_session_id FROM tracks WHERE track_id = 't1'").fetchone()
        assert track["dry_ref_session_id"] == "s1"

    def test_wet_ref_auto_set(self, db):
        from web.models import auto_set_track_reference

        self._seed_track_and_session(db, "s1", "wet")
        result = auto_set_track_reference(db, "s1")
        db.commit()

        assert result == "wet"
        track = db.execute("SELECT wet_ref_session_id FROM tracks WHERE track_id = 't1'").fetchone()
        assert track["wet_ref_session_id"] == "s1"

    def test_no_overwrite_existing(self, db):
        from web.models import auto_set_track_reference

        self._seed_track_and_session(db, "s1", "dry")
        auto_set_track_reference(db, "s1")
        db.commit()

        # Add second dry session.
        db.execute(
            "INSERT INTO sessions (session_id, csv_filename, driver_id, track_id, "
            "session_type, session_date, track_state) "
            "VALUES ('s2', 'g.csv', 1, 't1', 'practice', '2026-01-02', 'dry')"
        )
        db.execute(
            "INSERT INTO reference_lines (session_id, latitudes_json, "
            "longitudes_json, distances_json) VALUES ('s2', '[3]', '[4]', '[0]')"
        )
        db.commit()

        result = auto_set_track_reference(db, "s2")
        assert result is None  # Should NOT overwrite

        track = db.execute("SELECT dry_ref_session_id FROM tracks WHERE track_id = 't1'").fetchone()
        assert track["dry_ref_session_id"] == "s1"  # Still the first session

    def test_mixed_maps_to_wet(self, db):
        from web.models import auto_set_track_reference

        self._seed_track_and_session(db, "s1", "mixed")
        result = auto_set_track_reference(db, "s1")
        db.commit()

        assert result == "wet"
        track = db.execute("SELECT wet_ref_session_id FROM tracks WHERE track_id = 't1'").fetchone()
        assert track["wet_ref_session_id"] == "s1"


class TestGGConversion:
    """G-G scatter API must return values in G, not raw m/s squared."""

    def test_gg_data_converts_to_g(self, db, tmp_path):
        """Raw accel stored as m/s squared should be divided by 9.80665."""
        import json
        import math

        db.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'GG Tester')")
        db.execute(
            "INSERT INTO tracks (track_id, track_name, lap_length_m) VALUES ('t1', 'Oval', 500)"
        )
        db.execute(
            "INSERT INTO sessions (session_id, csv_filename, driver_id, track_id, session_date) "
            "VALUES ('s1', 'f.csv', 1, 't1', '2025-01-01')"
        )
        raw_lat = [9.80665, -9.80665, 0.0]
        raw_long = [4.903325, -4.903325, 0.0]
        db.execute(
            "INSERT INTO gps_traces (session_id, lap_number, latitudes_json, longitudes_json, "
            "distances_json, speeds_json, accel_lat_json, accel_long_json) "
            "VALUES ('s1', 1, '[]', '[]', '[]', '[]', :lat, :lon)",
            {"lat": json.dumps(raw_lat), "lon": json.dumps(raw_long)},
        )
        db.execute(
            "INSERT INTO laps (session_id, lap_number, lap_time_s) VALUES ('s1', 1, 30.0)"
        )
        db.commit()

        # Build a file-backed DB copy so the Flask app can use it.
        db_path = tmp_path / "test_gg.db"
        src_conn = db
        dst_conn = sqlite3.connect(str(db_path))
        src_conn.backup(dst_conn)
        dst_conn.close()

        from web.app import create_app
        from web.config import Config

        cfg = Config()
        cfg.DB_PATH = db_path
        cfg.DATA_RAW_DIR = tmp_path / "raw"
        cfg.RESULTS_DIR = tmp_path / "results"
        cfg.UPLOAD_DIR = tmp_path / "uploads"

        app = create_app(cfg)
        app.config["TESTING"] = True

        with app.test_client() as client:
            resp = client.get("/api/session/s1/gg_data")
            assert resp.status_code == 200
            data = resp.get_json()
            assert math.isclose(data["accel_lat"][0], 1.0, rel_tol=0.01)
            assert math.isclose(data["accel_lat"][1], -1.0, rel_tol=0.01)
            assert math.isclose(data["accel_long"][0], 0.5, rel_tol=0.01)


class TestCoachingSchema:
    """Tables for coaching linking exist after migration."""

    def test_plan_drill_sessions_table_exists(self, db):
        row = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='plan_drill_sessions'"
        ).fetchone()
        assert row is not None

    def test_driver_badges_table_exists(self, db):
        row = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='driver_badges'"
        ).fetchone()
        assert row is not None

    def test_completed_at_column_exists(self, db):
        db.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'D')")
        db.execute(
            "INSERT INTO development_plans (driver_id, plan_name, weeks_json) "
            "VALUES (1, 'P', '[]')"
        )
        row = db.execute("SELECT completed_at FROM development_plans WHERE id = 1").fetchone()
        assert row is not None


class TestDrillSessionLinking:
    """Link analyzed sessions to specific drills in a dev plan."""

    def _seed_plan(self, db):
        """Create a driver with a 1-week, 2-drill plan and 2 sessions."""
        db.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Linker')")
        db.execute(
            "INSERT INTO tracks (track_id, track_name, lap_length_m) VALUES ('t1', 'Oval', 500)"
        )
        import json
        weeks = [{"week": 1, "title": "Basics", "drills": [
            {"name": "Drill A", "metric": "consistency_cv_pct", "target": "< 5"},
            {"name": "Drill B"},
        ]}]
        progress = [[False, False]]
        db.execute(
            "INSERT INTO development_plans (id, driver_id, plan_name, weeks_json, progress_json) "
            "VALUES (1, 1, 'Test Plan', :weeks, :progress)",
            {"weeks": json.dumps(weeks), "progress": json.dumps(progress)},
        )
        for i, (sid, score) in enumerate([("s1", 75.0), ("s2", 82.0)]):
            db.execute(
                "INSERT INTO sessions (session_id, csv_filename, driver_id, track_id, "
                "session_date, n_laps, best_lap_time_s, total_score) "
                "VALUES (:sid, 'f.csv', 1, 't1', '2025-01-0' || :d, :laps, 30.0, :score)",
                {"sid": sid, "d": i + 1, "laps": 10 + i * 5, "score": score},
            )
        db.commit()

    def test_link_session_creates_record(self, db):
        self._seed_plan(db)
        from development_plan import link_drill_session
        result = link_drill_session(db, plan_id=1, week_index=0, drill_index=0, session_id="s1")
        assert result is not None
        assert result["session_id"] == "s1"

    def test_link_auto_completes_drill(self, db):
        self._seed_plan(db)
        from development_plan import link_drill_session, get_plan
        link_drill_session(db, plan_id=1, week_index=0, drill_index=0, session_id="s1")
        plan = get_plan(db, 1)
        assert plan["progress"][0][0] is True

    def test_unlink_session(self, db):
        self._seed_plan(db)
        from development_plan import link_drill_session, unlink_drill_session, get_drill_sessions
        link_drill_session(db, plan_id=1, week_index=0, drill_index=0, session_id="s1")
        unlink_drill_session(db, plan_id=1, week_index=0, drill_index=0, session_id="s1")
        sessions = get_drill_sessions(db, plan_id=1)
        assert len(sessions) == 0

    def test_get_drill_sessions(self, db):
        self._seed_plan(db)
        from development_plan import link_drill_session, get_drill_sessions
        link_drill_session(db, plan_id=1, week_index=0, drill_index=0, session_id="s1")
        link_drill_session(db, plan_id=1, week_index=0, drill_index=1, session_id="s2")
        sessions = get_drill_sessions(db, plan_id=1)
        assert len(sessions) == 2

    def test_duplicate_link_ignored(self, db):
        self._seed_plan(db)
        from development_plan import link_drill_session, get_drill_sessions
        link_drill_session(db, plan_id=1, week_index=0, drill_index=0, session_id="s1")
        link_drill_session(db, plan_id=1, week_index=0, drill_index=0, session_id="s1")
        sessions = get_drill_sessions(db, plan_id=1)
        assert len(sessions) == 1


class TestPlanCompletion:
    """Plan completion triggers badge creation and status update."""

    def _seed_single_drill_plan(self, db):
        """Create a driver with a 1-week, 1-drill plan."""
        db.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Finisher')")
        db.execute(
            "INSERT INTO tracks (track_id, track_name, lap_length_m) VALUES ('t1', 'Oval', 500)"
        )
        import json
        weeks = [{"week": 1, "title": "Fundamentals", "drills": [{"name": "Only Drill"}]}]
        progress = [[False]]
        db.execute(
            "INSERT INTO development_plans (id, driver_id, plan_name, level, weeks_json, progress_json) "
            "VALUES (1, 1, 'Quick Plan', 'beginner', :w, :p)",
            {"w": json.dumps(weeks), "p": json.dumps(progress)},
        )
        db.execute(
            "INSERT INTO sessions (session_id, csv_filename, driver_id, track_id, "
            "session_date, n_laps, total_score) VALUES ('s1', 'f.csv', 1, 't1', '2025-01-01', 15, 80.0)"
        )
        db.commit()

    def test_completion_sets_status(self, db):
        self._seed_single_drill_plan(db)
        from development_plan import link_drill_session, get_plan
        link_drill_session(db, plan_id=1, week_index=0, drill_index=0, session_id="s1")
        plan = get_plan(db, 1)
        assert plan["status"] == "completed"
        assert plan["completed_at"] is not None

    def test_completion_creates_badge(self, db):
        self._seed_single_drill_plan(db)
        from development_plan import link_drill_session
        link_drill_session(db, plan_id=1, week_index=0, drill_index=0, session_id="s1")
        row = db.execute(
            "SELECT * FROM driver_badges WHERE driver_id = 1 AND plan_id = 1"
        ).fetchone()
        assert row is not None
        assert dict(row)["badge_type"] == "plan_completion"
        assert dict(row)["badge_name"] == "Quick Plan"

    def test_badge_metadata_has_stats(self, db):
        self._seed_single_drill_plan(db)
        import json
        from development_plan import link_drill_session
        link_drill_session(db, plan_id=1, week_index=0, drill_index=0, session_id="s1")
        row = db.execute("SELECT metadata_json FROM driver_badges WHERE plan_id = 1").fetchone()
        meta = json.loads(dict(row)["metadata_json"])
        assert meta["drills_completed"] == 1
        assert meta["sessions_linked"] >= 1

    def test_no_duplicate_badge(self, db):
        self._seed_single_drill_plan(db)
        from development_plan import link_drill_session, update_plan_progress
        link_drill_session(db, plan_id=1, week_index=0, drill_index=0, session_id="s1")
        # Uncomplete and re-complete.
        update_plan_progress(db, 1, 0, 0, completed=False)
        update_plan_progress(db, 1, 0, 0, completed=True)
        count = db.execute("SELECT COUNT(*) FROM driver_badges WHERE plan_id = 1").fetchone()[0]
        assert count == 1


class TestDrillLinkingAPI:
    """API endpoints for linking sessions to drills."""

    def _seed(self, db):
        import json
        db.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'API Tester')")
        db.execute("INSERT INTO tracks (track_id, track_name, lap_length_m) VALUES ('t1', 'T', 500)")
        weeks = [{"week": 1, "title": "W1", "drills": [{"name": "D1"}, {"name": "D2"}]}]
        progress = [[False, False]]
        db.execute(
            "INSERT INTO development_plans (id, driver_id, plan_name, weeks_json, progress_json) "
            "VALUES (1, 1, 'P', :w, :p)",
            {"w": json.dumps(weeks), "p": json.dumps(progress)},
        )
        db.execute(
            "INSERT INTO sessions (session_id, csv_filename, driver_id, track_id, session_date, n_laps) "
            "VALUES ('s1', 'f.csv', 1, 't1', '2025-01-01', 10)"
        )
        db.commit()

    def _make_app(self, db, tmp_path):
        """Back up in-memory DB to file and create a Flask test app."""
        db_path = tmp_path / "test_drill_api.db"
        dst_conn = sqlite3.connect(str(db_path))
        db.backup(dst_conn)
        dst_conn.close()

        from web.app import create_app
        from web.config import Config

        cfg = Config()
        cfg.DB_PATH = db_path
        cfg.DATA_RAW_DIR = tmp_path / "raw"
        cfg.RESULTS_DIR = tmp_path / "results"
        cfg.UPLOAD_DIR = tmp_path / "uploads"

        app = create_app(cfg)
        app.config["TESTING"] = True
        return app

    def test_link_session_api(self, db, tmp_path):
        self._seed(db)
        app = self._make_app(db, tmp_path)
        with app.test_client() as client:
            resp = client.post(
                "/api/dev-plans/plan/1/link-session",
                json={"week_index": 0, "drill_index": 0, "session_id": "s1"},
            )
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["session_id"] == "s1"
            assert "completion_pct" in data

    def test_unlink_session_api(self, db, tmp_path):
        self._seed(db)
        app = self._make_app(db, tmp_path)
        with app.test_client() as client:
            # Link first
            client.post(
                "/api/dev-plans/plan/1/link-session",
                json={"week_index": 0, "drill_index": 0, "session_id": "s1"},
            )
            # Unlink
            resp = client.delete(
                "/api/dev-plans/plan/1/unlink-session",
                json={"week_index": 0, "drill_index": 0, "session_id": "s1"},
            )
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["success"] is True

    def test_get_drill_sessions_api(self, db, tmp_path):
        self._seed(db)
        app = self._make_app(db, tmp_path)
        with app.test_client() as client:
            # Link a session first
            client.post(
                "/api/dev-plans/plan/1/link-session",
                json={"week_index": 0, "drill_index": 0, "session_id": "s1"},
            )
            resp = client.get("/api/dev-plans/plan/1/drill-sessions")
            assert resp.status_code == 200
            data = resp.get_json()
            assert len(data["sessions"]) == 1


class TestDriverBadgesOnProfile:
    """Driver profile page includes earned badges."""

    def test_badges_passed_to_template(self, db, tmp_path):
        import json

        db.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Badge Boy')")
        db.execute(
            "INSERT INTO tracks (track_id, track_name, lap_length_m) VALUES ('t1', 'Oval', 500)"
        )
        db.execute(
            "INSERT INTO sessions (session_id, csv_filename, driver_id, track_id, "
            "session_date, n_laps, best_lap_time_s) "
            "VALUES ('s1', 'f.csv', 1, 't1', '2025-01-01', 10, 30.0)"
        )
        db.execute(
            "INSERT INTO driver_badges (driver_id, badge_type, badge_name, badge_level, "
            "metadata_json, plan_id) VALUES (1, 'plan_completion', 'Speed Plan', 'advanced', "
            ":meta, 99)",
            {"meta": json.dumps({"drills_completed": 6, "sessions_linked": 3})},
        )
        db.commit()

        # Build a file-backed DB copy so the Flask app can use it.
        db_path = tmp_path / "test_badges.db"
        dst_conn = sqlite3.connect(str(db_path))
        db.backup(dst_conn)
        dst_conn.close()

        from web.app import create_app
        from web.config import Config

        cfg = Config()
        cfg.DB_PATH = db_path
        cfg.DATA_RAW_DIR = tmp_path / "raw"
        cfg.RESULTS_DIR = tmp_path / "results"
        cfg.UPLOAD_DIR = tmp_path / "uploads"

        app = create_app(cfg)
        app.config["TESTING"] = True

        with app.test_client() as client:
            resp = client.get("/drivers/1")
            assert resp.status_code == 200
            assert b"Speed Plan" in resp.data


class TestMeteoSchema:
    """Task 1: predefined_track_coords table exists after migration."""

    def test_predefined_track_coords_table_exists(self, db):
        row = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='predefined_track_coords'"
        ).fetchone()
        assert row is not None, "predefined_track_coords table not created"

    def test_predefined_track_coords_columns(self, db):
        cols = {r[1] for r in db.execute("PRAGMA table_info(predefined_track_coords)").fetchall()}
        assert "track_name" in cols
        assert "city" in cols
        assert "country" in cols
        assert "latitude" in cols
        assert "longitude" in cols
        assert "geocoded_at" in cols

    def test_schema_version_19(self, db):
        row = db.execute("SELECT version FROM schema_version WHERE version = 19").fetchone()
        assert row is not None


class TestTrackGeocoder:
    """Task 2: geocoding predefined track venues."""

    def test_parse_predefined_csv_unique_venues(self, db):
        # Cache all pre-existing CSV-imported tracks so they don't pollute our test.
        from track_geocoder import get_ungeocoded_venues, cache_geocode_result
        for v in get_ungeocoded_venues(db):
            cache_geocode_result(db, v["track_name"], v.get("city", ""), "FR", 0.0, 0.0)
        db.commit()

        # Now insert our test tracks — duplicates should collapse via DISTINCT.
        db.execute(
            "INSERT INTO predefined_tracks (track_name, city, country) VALUES (?, ?, ?)",
            ("Kartland Paris", "Moissy-Cramayel", "France"),
        )
        db.execute(
            "INSERT INTO predefined_tracks (track_name, city, country) VALUES (?, ?, ?)",
            ("Kartland Paris", "Moissy-Cramayel", "France"),
        )
        db.execute(
            "INSERT INTO predefined_tracks (track_name, city, country) VALUES (?, ?, ?)",
            ("Solokart", "Plessé", "France"),
        )
        db.commit()
        venues = get_ungeocoded_venues(db)
        names = [v["track_name"] for v in venues]
        assert len(venues) == 2
        assert "Kartland Paris" in names
        assert "Solokart" in names

    def test_cache_geocode_result(self, db):
        from track_geocoder import cache_geocode_result
        cache_geocode_result(db, "Kartland Paris", "Moissy-Cramayel", "FR", 48.5926, 2.5741)
        db.commit()
        row = db.execute(
            "SELECT latitude, longitude FROM predefined_track_coords WHERE track_name = ?",
            ("Kartland Paris",),
        ).fetchone()
        assert row is not None
        assert abs(row["latitude"] - 48.5926) < 0.001
        assert abs(row["longitude"] - 2.5741) < 0.001

    def test_cache_is_idempotent(self, db):
        from track_geocoder import cache_geocode_result
        cache_geocode_result(db, "Kartland Paris", "Moissy-Cramayel", "FR", 48.5926, 2.5741)
        cache_geocode_result(db, "Kartland Paris", "Moissy-Cramayel", "FR", 48.5926, 2.5741)
        db.commit()
        count = db.execute(
            "SELECT COUNT(*) FROM predefined_track_coords WHERE track_name = ?",
            ("Kartland Paris",),
        ).fetchone()[0]
        assert count == 1

    def test_get_cached_coords(self, db):
        from track_geocoder import cache_geocode_result, get_cached_coords
        cache_geocode_result(db, "Kartland Paris", "Moissy-Cramayel", "FR", 48.59, 2.57)
        cache_geocode_result(db, "Solokart", "Plessé", "FR", 47.53, -1.86)
        db.commit()
        coords = get_cached_coords(db)
        assert len(coords) == 2
        by_name = {c["track_name"]: c for c in coords}
        assert abs(by_name["Kartland Paris"]["latitude"] - 48.59) < 0.01
