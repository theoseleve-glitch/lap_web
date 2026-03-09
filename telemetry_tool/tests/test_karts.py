"""Tests for kart CRUD operations."""
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


class TestKartCRUD:
    def test_create_from_predefined(self, db):
        from web.models import create_kart, get_kart_by_id

        pk = db.execute("SELECT * FROM predefined_karts LIMIT 1").fetchone()
        kart_id = create_kart(db, kart_name="My Sodi", predefined_kart_id=pk["predefined_kart_id"])
        db.commit()

        kart = get_kart_by_id(db, kart_id)
        assert kart["kart_name"] == "My Sodi"
        assert kart["manufacturer"] == pk["manufacturer"]
        assert kart["power_hp"] == pk["power_hp"]

    def test_create_custom(self, db):
        from web.models import create_kart, get_kart_by_id

        kart_id = create_kart(
            db, kart_name="Custom Beast",
            manufacturer="DIY", model="V1", engine="Rotax", power_hp=30,
        )
        db.commit()

        kart = get_kart_by_id(db, kart_id)
        assert kart["kart_name"] == "Custom Beast"
        assert kart["predefined_kart_id"] is None
        assert kart["manufacturer"] == "DIY"

    def test_list_karts(self, db):
        from web.models import create_kart, get_all_karts

        create_kart(db, kart_name="K1")
        create_kart(db, kart_name="K2")
        db.commit()

        karts = get_all_karts(db)
        assert len(karts) == 2

    def test_update_kart(self, db):
        from web.models import create_kart, get_kart_by_id, update_kart

        kid = create_kart(db, kart_name="Old Name")
        db.commit()

        update_kart(db, kid, {"kart_name": "New Name", "notes": "Fast"})
        db.commit()

        kart = get_kart_by_id(db, kid)
        assert kart["kart_name"] == "New Name"
        assert kart["notes"] == "Fast"

    def test_delete_kart_unlinks_sessions(self, db):
        from web.models import create_kart, delete_kart

        kid = create_kart(db, kart_name="Temp")
        db.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Test')")
        db.execute(
            "INSERT INTO sessions (session_id, csv_filename, driver_id, session_type, "
            "session_date, kart_id) VALUES ('s1', 'f.csv', 1, 'practice', '2026-01-01', ?)",
            (kid,),
        )
        db.commit()

        delete_kart(db, kid)
        db.commit()

        assert db.execute("SELECT COUNT(*) FROM karts WHERE kart_id = ?", (kid,)).fetchone()[0] == 0
        sess = db.execute("SELECT kart_id FROM sessions WHERE session_id = 's1'").fetchone()
        assert sess["kart_id"] is None

    def test_session_count_in_list(self, db):
        from web.models import create_kart, get_all_karts

        kid = create_kart(db, kart_name="Counted")
        db.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Test')")
        db.execute(
            "INSERT INTO sessions (session_id, csv_filename, driver_id, session_type, "
            "session_date, kart_id) VALUES ('s1', 'f.csv', 1, 'practice', '2026-01-01', ?)",
            (kid,),
        )
        db.execute(
            "INSERT INTO sessions (session_id, csv_filename, driver_id, session_type, "
            "session_date, kart_id) VALUES ('s2', 'g.csv', 1, 'practice', '2026-01-02', ?)",
            (kid,),
        )
        db.commit()

        karts = get_all_karts(db)
        assert karts[0]["session_count"] == 2


class TestSessionKartLink:
    def test_link_session_to_kart(self, db):
        from web.models import create_kart, link_session_kart

        kid = create_kart(db, kart_name="Linked")
        db.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Test')")
        db.execute(
            "INSERT INTO sessions (session_id, csv_filename, driver_id, session_type, "
            "session_date) VALUES ('s1', 'f.csv', 1, 'practice', '2026-01-01')"
        )
        db.commit()

        link_session_kart(db, "s1", kid)
        db.commit()

        sess = db.execute("SELECT kart_id FROM sessions WHERE session_id = 's1'").fetchone()
        assert sess["kart_id"] == kid

    def test_unlink_session_from_kart(self, db):
        from web.models import create_kart, link_session_kart

        kid = create_kart(db, kart_name="Linked")
        db.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'Test')")
        db.execute(
            "INSERT INTO sessions (session_id, csv_filename, driver_id, session_type, "
            "session_date, kart_id) VALUES ('s1', 'f.csv', 1, 'practice', '2026-01-01', ?)",
            (kid,),
        )
        db.commit()

        link_session_kart(db, "s1", None)
        db.commit()

        sess = db.execute("SELECT kart_id FROM sessions WHERE session_id = 's1'").fetchone()
        assert sess["kart_id"] is None


class TestPredefinedKarts:
    def test_grouped_by_segment(self, db):
        from web.models import get_predefined_karts_grouped

        groups = get_predefined_karts_grouped(db)
        assert len(groups) > 0
        for segment, karts in groups.items():
            assert len(karts) > 0
            for k in karts:
                assert "model" in k
