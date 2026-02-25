"""Test auto-tagging module."""
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from auto_tagging import (
    auto_tag_session, get_session_tags, add_manual_tag,
    remove_tag, get_all_unique_tags, get_sessions_by_tag,
)


@pytest.fixture
def tag_db(test_db):
    conn = test_db
    conn.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'D1')")
    conn.execute("INSERT INTO tracks (track_id, track_name, lap_length_m) VALUES ('t1', 'T', 500)")
    conn.commit()
    return conn


def _add_session(conn, sid, **kw):
    conn.execute(
        "INSERT INTO sessions (session_id, csv_filename, driver_id, track_id, "
        "session_type, track_state, session_date, n_laps, best_lap_time_s, notes) "
        "VALUES (?, 'x.csv', 1, 't1', ?, ?, '2024-01-01', ?, ?, ?)",
        (sid, kw.get("session_type", "practice"), kw.get("track_state", "dry"),
         kw.get("n_laps", 10), kw.get("best_lap_time_s"), kw.get("notes", "")),
    )
    conn.commit()


class TestAutoTagging:
    def test_rain_tag(self, tag_db):
        _add_session(tag_db, "s1", track_state="wet")
        tags = auto_tag_session(tag_db, "s1")
        assert any(t["tag"] == "rain_session" for t in tags)

    def test_qualifying_tag(self, tag_db):
        _add_session(tag_db, "s1", session_type="qualifying", n_laps=3)
        tags = auto_tag_session(tag_db, "s1")
        names = [t["tag"] for t in tags]
        assert "qualifying_run" in names
        assert "short_run" in names

    def test_manual_tag_preserved(self, tag_db):
        _add_session(tag_db, "s1", track_state="wet")
        add_manual_tag(tag_db, "s1", "important")
        auto_tag_session(tag_db, "s1")
        tags = get_session_tags(tag_db, "s1")
        names = [t["tag"] for t in tags]
        assert "important" in names
        assert "rain_session" in names

    def test_nonexistent_session(self, tag_db):
        assert auto_tag_session(tag_db, "nope") == []

    def test_long_run(self, tag_db):
        _add_session(tag_db, "s1", n_laps=25)
        tags = auto_tag_session(tag_db, "s1")
        assert any(t["tag"] == "long_run" for t in tags)
