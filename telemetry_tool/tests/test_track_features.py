"""Tests for track management features: S/F editing, sectors, deletion."""
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


def _insert_track(db, track_id="t1", name="Test Track", length=500.0, lat=48.0, lon=2.0):
    """Helper: insert a minimal track row."""
    db.execute(
        "INSERT INTO tracks (track_id, track_name, lap_length_m, start_lat, start_lon, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
        (track_id, name, length, lat, lon),
    )
    db.commit()


def _insert_session(db, session_id, track_id="t1", driver_id=1):
    """Helper: insert a minimal session row."""
    db.execute(
        "INSERT OR IGNORE INTO drivers (driver_id, driver_name) VALUES (?, ?)",
        (driver_id, "TestDriver"),
    )
    db.execute(
        "INSERT INTO sessions (session_id, csv_filename, driver_id, track_id, session_date) "
        "VALUES (?, 'test.csv', ?, ?, '2025-01-01')",
        (session_id, driver_id, track_id),
    )
    db.commit()


# ── Task 2: Start/Finish Editing ─────────────────────────────
class TestStartFinishEdit:
    def test_update_start_finish(self, db):
        from web.models import update_track_start_finish

        _insert_track(db, lat=48.0, lon=2.0)
        update_track_start_finish(db, "t1", 48.1, 2.1)
        db.commit()

        row = dict(db.execute("SELECT * FROM tracks WHERE track_id = 't1'").fetchone())
        assert row["start_lat"] == 48.1
        assert row["start_lon"] == 2.1
        assert row["original_start_lat"] == 48.0
        assert row["original_start_lon"] == 2.0

    def test_original_preserved_on_second_edit(self, db):
        from web.models import update_track_start_finish

        _insert_track(db, lat=48.0, lon=2.0)
        update_track_start_finish(db, "t1", 48.1, 2.1)
        db.commit()
        update_track_start_finish(db, "t1", 48.2, 2.2)
        db.commit()

        row = dict(db.execute("SELECT * FROM tracks WHERE track_id = 't1'").fetchone())
        assert row["start_lat"] == 48.2
        assert row["original_start_lat"] == 48.0  # Still the original

    def test_reset_to_original(self, db):
        from web.models import reset_track_start_finish, update_track_start_finish

        _insert_track(db, lat=48.0, lon=2.0)
        update_track_start_finish(db, "t1", 48.5, 2.5)
        db.commit()
        reset_track_start_finish(db, "t1")
        db.commit()

        row = dict(db.execute("SELECT * FROM tracks WHERE track_id = 't1'").fetchone())
        assert row["start_lat"] == 48.0
        assert row["start_lon"] == 2.0

    def test_nonexistent_track_no_error(self, db):
        from web.models import update_track_start_finish

        update_track_start_finish(db, "nonexistent", 1.0, 1.0)  # Should not raise


# ── Task 3: Track Sectors ────────────────────────────────────
class TestTrackSectors:
    def test_add_sector(self, db):
        from web.models import get_track_sectors, upsert_track_sector

        _insert_track(db)
        upsert_track_sector(db, "t1", 48.1, 2.1)
        db.commit()

        sectors = get_track_sectors(db, "t1")
        assert len(sectors) == 1
        assert sectors[0]["sector_index"] == 0
        assert sectors[0]["label"] == "S1"

    def test_multiple_sectors(self, db):
        from web.models import get_track_sectors, upsert_track_sector

        _insert_track(db)
        upsert_track_sector(db, "t1", 48.1, 2.1)
        upsert_track_sector(db, "t1", 48.2, 2.2)
        upsert_track_sector(db, "t1", 48.3, 2.3)
        db.commit()

        sectors = get_track_sectors(db, "t1")
        assert len(sectors) == 3
        assert [s["label"] for s in sectors] == ["S1", "S2", "S3"]

    def test_auto_reindex_on_delete(self, db):
        from web.models import delete_track_sector, get_track_sectors, upsert_track_sector

        _insert_track(db)
        upsert_track_sector(db, "t1", 48.1, 2.1)
        upsert_track_sector(db, "t1", 48.2, 2.2)
        upsert_track_sector(db, "t1", 48.3, 2.3)
        db.commit()

        sectors = get_track_sectors(db, "t1")
        # Delete middle sector
        delete_track_sector(db, "t1", sectors[1]["id"])
        db.commit()

        sectors = get_track_sectors(db, "t1")
        assert len(sectors) == 2
        assert sectors[0]["sector_index"] == 0
        assert sectors[1]["sector_index"] == 1
        assert sectors[0]["label"] == "S1"
        assert sectors[1]["label"] == "S2"

    def test_empty_sectors(self, db):
        from web.models import get_track_sectors

        _insert_track(db)
        assert get_track_sectors(db, "t1") == []


# ── Task 4: Track Deletion (Cascade) ─────────────────────────
class TestTrackDeletion:
    def test_cascade_deletes_track(self, db):
        from web.models import delete_track_cascade

        _insert_track(db)
        counts = delete_track_cascade(db, "t1")
        db.commit()

        assert counts["tracks"] == 1
        row = db.execute("SELECT COUNT(*) FROM tracks WHERE track_id = 't1'").fetchone()[0]
        assert row == 0

    def test_cascade_deletes_sessions_and_laps(self, db):
        from web.models import delete_track_cascade

        _insert_track(db)
        _insert_session(db, "s1", "t1")
        db.execute(
            "INSERT INTO laps (session_id, lap_number, lap_time_s) VALUES ('s1', 1, 65.0)"
        )
        db.commit()

        counts = delete_track_cascade(db, "t1")
        db.commit()

        assert counts["sessions"] == 1
        assert counts["laps"] == 1
        assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM laps").fetchone()[0] == 0

    def test_cascade_deletes_sectors(self, db):
        from web.models import delete_track_cascade, upsert_track_sector

        _insert_track(db)
        upsert_track_sector(db, "t1", 48.1, 2.1)
        db.commit()

        delete_track_cascade(db, "t1")
        db.commit()

        assert db.execute("SELECT COUNT(*) FROM track_sectors").fetchone()[0] == 0

    def test_other_tracks_untouched(self, db):
        from web.models import delete_track_cascade

        _insert_track(db, "t1", "Track 1")
        _insert_track(db, "t2", "Track 2")
        _insert_session(db, "s1", "t1")
        _insert_session(db, "s2", "t2")
        db.commit()

        delete_track_cascade(db, "t1")
        db.commit()

        assert db.execute("SELECT COUNT(*) FROM tracks").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
        assert db.execute("SELECT track_id FROM tracks").fetchone()[0] == "t2"
