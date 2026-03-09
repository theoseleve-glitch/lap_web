"""Tests for session-kart linking via kart_id column."""
import sqlite3

import pytest

from db.migrate import ensure_schema


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    conn.execute("INSERT INTO drivers (driver_name) VALUES ('Test')")
    conn.commit()
    return conn


def test_session_kart_id_column_exists(db):
    """sessions table has kart_id column after schema creation."""
    cols = [r[1] for r in db.execute("PRAGMA table_info(sessions)").fetchall()]
    assert "kart_id" in cols


def test_session_kart_id_fk_links(db):
    """kart_id on session correctly references karts table."""
    db.execute("INSERT INTO karts (kart_name) VALUES ('K1')")
    kart_id = db.execute("SELECT kart_id FROM karts WHERE kart_name='K1'").fetchone()[0]
    db.execute(
        "INSERT INTO sessions (session_id, csv_filename, driver_id, session_date, kart_id) "
        "VALUES ('s1', 'test.csv', 1, '2026-01-01', ?)",
        (kart_id,),
    )
    db.commit()
    row = db.execute("SELECT kart_id FROM sessions WHERE session_id='s1'").fetchone()
    assert row["kart_id"] == kart_id


def test_session_kart_id_nullable(db):
    """kart_id is nullable -- sessions without karts are fine."""
    db.execute(
        "INSERT INTO sessions (session_id, csv_filename, driver_id, session_date) "
        "VALUES ('s2', 'test.csv', 1, '2026-01-01')"
    )
    db.commit()
    row = db.execute("SELECT kart_id FROM sessions WHERE session_id='s2'").fetchone()
    assert row["kart_id"] is None


def test_insert_session_query_includes_kart_id(db):
    """INSERT_SESSION named query includes kart_id column."""
    from db.queries import INSERT_SESSION

    assert "kart_id" in INSERT_SESSION
    assert ":kart_id" in INSERT_SESSION


def test_update_session_field_accepts_kart_id(db):
    """update_session_field allows kart_id as an editable field."""
    from web.models import update_session_field

    db.execute("INSERT INTO karts (kart_name) VALUES ('K2')")
    kart_id = db.execute("SELECT kart_id FROM karts WHERE kart_name='K2'").fetchone()[0]
    db.execute(
        "INSERT INTO sessions (session_id, csv_filename, driver_id, session_date) "
        "VALUES ('s3', 'test.csv', 1, '2026-01-01')"
    )
    db.commit()
    update_session_field(db, "s3", "kart_id", kart_id)
    db.commit()
    row = db.execute("SELECT kart_id FROM sessions WHERE session_id='s3'").fetchone()
    assert row["kart_id"] == kart_id


def test_update_session_field_rejects_invalid_field(db):
    """update_session_field rejects fields not in the allowed set."""
    from web.models import update_session_field

    db.execute(
        "INSERT INTO sessions (session_id, csv_filename, driver_id, session_date) "
        "VALUES ('s4', 'test.csv', 1, '2026-01-01')"
    )
    db.commit()
    with pytest.raises(ValueError):
        update_session_field(db, "s4", "csv_filename", "hacked.csv")
