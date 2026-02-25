"""Tests for predefined data import (tracks + karts)."""
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


class TestPredefinedTracks:
    def test_table_exists(self, db):
        rows = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='predefined_tracks'"
        ).fetchall()
        assert len(rows) == 1

    def test_data_imported(self, db):
        count = db.execute("SELECT COUNT(*) FROM predefined_tracks").fetchone()[0]
        assert count > 100

    def test_columns_present(self, db):
        row = db.execute("SELECT * FROM predefined_tracks LIMIT 1").fetchone()
        keys = row.keys()
        for col in ("predefined_track_id", "country", "track_name", "layout_name", "layout_length_m"):
            assert col in keys

    def test_idempotent_import(self, db):
        count_before = db.execute("SELECT COUNT(*) FROM predefined_tracks").fetchone()[0]
        ensure_schema(db)
        count_after = db.execute("SELECT COUNT(*) FROM predefined_tracks").fetchone()[0]
        assert count_before == count_after

    def test_tracks_has_predefined_fk_column(self, db):
        info = db.execute("PRAGMA table_info(tracks)").fetchall()
        col_names = [r["name"] for r in info]
        assert "predefined_track_id" in col_names


class TestPredefinedKarts:
    def test_table_exists(self, db):
        rows = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='predefined_karts'"
        ).fetchall()
        assert len(rows) == 1

    def test_data_imported(self, db):
        count = db.execute("SELECT COUNT(*) FROM predefined_karts").fetchone()[0]
        assert count > 50

    def test_columns_present(self, db):
        row = db.execute("SELECT * FROM predefined_karts LIMIT 1").fetchone()
        keys = row.keys()
        for col in ("predefined_kart_id", "segment", "manufacturer", "model", "power_hp"):
            assert col in keys

    def test_na_values_are_null(self, db):
        """NA values in CSV should be stored as NULL, not the string 'NA'."""
        rows = db.execute(
            "SELECT zero_to_100_s FROM predefined_karts WHERE zero_to_100_s IS NOT NULL"
        ).fetchall()
        for r in rows:
            assert r[0] != "NA"


class TestNewTables:
    def test_karts_table_exists(self, db):
        rows = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='karts'"
        ).fetchall()
        assert len(rows) == 1

    def test_track_sectors_table_exists(self, db):
        rows = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='track_sectors'"
        ).fetchall()
        assert len(rows) == 1

    def test_sessions_has_kart_id_column(self, db):
        info = db.execute("PRAGMA table_info(sessions)").fetchall()
        col_names = [r["name"] for r in info]
        assert "kart_id" in col_names

    def test_tracks_has_original_start_columns(self, db):
        info = db.execute("PRAGMA table_info(tracks)").fetchall()
        col_names = [r["name"] for r in info]
        assert "original_start_lat" in col_names
        assert "original_start_lon" in col_names
