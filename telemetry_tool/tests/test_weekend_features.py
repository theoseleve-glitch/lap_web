"""Tests for weekend management features."""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.migrate import ensure_schema
from web.models import add_session_to_weekend, create_weekend


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    conn.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Test')")
    conn.execute(
        "INSERT INTO tracks (track_id, track_name, lap_length_m) VALUES ('t1', 'T', 500)"
    )
    for i in range(1, 4):
        conn.execute(
            "INSERT INTO sessions (session_id, csv_filename, driver_id, track_id, "
            "session_type, session_date) VALUES (?, ?, 1, 't1', 'practice', '2026-01-0' || ?)",
            (f"s{i}", f"f{i}.csv", str(i)),
        )
    conn.commit()
    yield conn
    conn.close()


class TestSessionReorder:
    def test_swap_down(self, db):
        from web.models import get_weekend_sessions, swap_weekend_session_order

        wid = create_weekend(db, name="W1")
        add_session_to_weekend(db, wid, "s1", 0)
        add_session_to_weekend(db, wid, "s2", 1)
        add_session_to_weekend(db, wid, "s3", 2)
        db.commit()

        swap_weekend_session_order(db, wid, "s1", "down")
        db.commit()

        sessions = get_weekend_sessions(db, wid)
        assert sessions[0]["session_id"] == "s2"
        assert sessions[1]["session_id"] == "s1"
        assert sessions[2]["session_id"] == "s3"

    def test_swap_up(self, db):
        from web.models import get_weekend_sessions, swap_weekend_session_order

        wid = create_weekend(db, name="W1")
        add_session_to_weekend(db, wid, "s1", 0)
        add_session_to_weekend(db, wid, "s2", 1)
        add_session_to_weekend(db, wid, "s3", 2)
        db.commit()

        swap_weekend_session_order(db, wid, "s3", "up")
        db.commit()

        sessions = get_weekend_sessions(db, wid)
        assert sessions[0]["session_id"] == "s1"
        assert sessions[1]["session_id"] == "s3"
        assert sessions[2]["session_id"] == "s2"

    def test_swap_at_boundary_noop(self, db):
        from web.models import get_weekend_sessions, swap_weekend_session_order

        wid = create_weekend(db, name="W1")
        add_session_to_weekend(db, wid, "s1", 0)
        add_session_to_weekend(db, wid, "s2", 1)
        db.commit()

        # Try moving first item up — should be no-op.
        swap_weekend_session_order(db, wid, "s1", "up")
        db.commit()

        sessions = get_weekend_sessions(db, wid)
        assert sessions[0]["session_id"] == "s1"
        assert sessions[1]["session_id"] == "s2"

    def test_reorder_all(self, db):
        from web.models import get_weekend_sessions, reorder_weekend_sessions

        wid = create_weekend(db, name="W1")
        add_session_to_weekend(db, wid, "s1", 0)
        add_session_to_weekend(db, wid, "s2", 1)
        add_session_to_weekend(db, wid, "s3", 2)
        db.commit()

        reorder_weekend_sessions(db, wid, ["s3", "s1", "s2"])
        db.commit()

        sessions = get_weekend_sessions(db, wid)
        assert sessions[0]["session_id"] == "s3"
        assert sessions[1]["session_id"] == "s1"
        assert sessions[2]["session_id"] == "s2"


def _seed_weekend_with_laps(db):
    """Helper: create a weekend with 3 sessions, each having 5 laps."""
    wid = create_weekend(db, name="W1")
    for sess_idx in range(1, 4):
        sid = f"s{sess_idx}"
        add_session_to_weekend(db, wid, sid, sess_idx - 1)
        # Insert 5 valid laps per session (times improve across sessions).
        for lap_num in range(1, 6):
            db.execute(
                "INSERT INTO laps (session_id, lap_number, lap_time_s, is_valid) "
                "VALUES (?, ?, ?, 1)",
                (sid, lap_num, 60.0 + lap_num * 0.1 - sess_idx * 0.5),
            )
    db.commit()
    return wid


class TestWeekendInsights:
    def test_insights_has_consistency_breakdown(self, db):
        from cross_session import compute_weekend_insights

        wid = _seed_weekend_with_laps(db)
        insights = compute_weekend_insights(db, wid)
        assert "consistency_breakdown" in insights
        assert len(insights["consistency_breakdown"]) == 3
        # Each entry should have meaningful data.
        for cb in insights["consistency_breakdown"]:
            assert cb["n_laps"] == 5
            assert cb["mean_time"] is not None
            assert cb["cv_pct"] is not None

    def test_insights_has_improvement_summary(self, db):
        from cross_session import compute_weekend_insights

        wid = _seed_weekend_with_laps(db)
        insights = compute_weekend_insights(db, wid)
        assert "improvement_pct" in insights
        # Sessions get faster (lower times) → positive improvement.
        assert insights["improvement_pct"] > 0

    def test_insights_heatmap_data(self, db):
        from cross_session import compute_weekend_insights

        wid = _seed_weekend_with_laps(db)
        insights = compute_weekend_insights(db, wid)
        assert "heatmap_data" in insights
        assert len(insights["heatmap_data"]) == 3
        # Each row should have 5 deltas.
        for row in insights["heatmap_data"]:
            assert len(row["deltas"]) == 5
            # First lap (best) delta should be 0 since it's closest to best.
            assert row["deltas"][0] == 0.0  # lap 1 is the best in each session

    def test_insights_empty_weekend(self, db):
        from cross_session import compute_weekend_insights

        wid = create_weekend(db, name="Empty")
        db.commit()
        insights = compute_weekend_insights(db, wid)
        assert insights["consistency_breakdown"] == []
        assert insights["improvement_pct"] is None
