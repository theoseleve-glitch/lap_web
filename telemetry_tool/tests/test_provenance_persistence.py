"""Tests for provenance persistence (dual-write to table + summary)."""
import sqlite3
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from provenance.persistence import get_provenance_by_session, insert_provenance
from provenance.run_context import ProvenanceRecord


def _create_provenance_table(conn):
    """Create the analysis_provenance table in SQLite for testing."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS analysis_provenance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            analysis_run_id TEXT NOT NULL UNIQUE,
            session_id TEXT,
            workspace_id INTEGER,
            input_fingerprint TEXT NOT NULL,
            file_hash TEXT,
            params_hash TEXT NOT NULL,
            pipeline_version TEXT NOT NULL,
            model_version TEXT NOT NULL,
            solver_version TEXT,
            method_used TEXT NOT NULL,
            training_data_hash TEXT,
            generated_at TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.commit()


@pytest.fixture
def prov_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _create_provenance_table(conn)
    yield conn
    conn.close()


@pytest.fixture
def sample_record():
    return ProvenanceRecord(
        analysis_run_id="550e8400-e29b-41d4-a716-446655440000",
        input_fingerprint="a" * 64,
        file_hash="b" * 64,
        params_hash="c" * 64,
        pipeline_version="v2-aabbccdd",
        model_version="none",
        solver_version=None,
        method_used="telemetry_tool_v2",
        generated_at="2026-03-07T12:00:00+00:00",
        training_data_hash=None,
    )


class TestInsertProvenance:
    def test_inserts_row(self, prov_db, sample_record):
        insert_provenance(prov_db, sample_record, session_id="s1")
        row = prov_db.execute(
            "SELECT * FROM analysis_provenance WHERE session_id = 's1'"
        ).fetchone()
        assert row is not None
        assert row["analysis_run_id"] == sample_record.analysis_run_id
        assert row["pipeline_version"] == "v2-aabbccdd"

    def test_idempotent_on_duplicate_run_id(self, prov_db, sample_record):
        insert_provenance(prov_db, sample_record, session_id="s1")
        insert_provenance(prov_db, sample_record, session_id="s1")  # no error
        count = prov_db.execute(
            "SELECT COUNT(*) as n FROM analysis_provenance"
        ).fetchone()["n"]
        assert count == 1


class TestGetProvenance:
    def test_returns_dict(self, prov_db, sample_record):
        insert_provenance(prov_db, sample_record, session_id="s1")
        result = get_provenance_by_session(prov_db, "s1")
        assert result is not None
        assert result["analysis_run_id"] == sample_record.analysis_run_id

    def test_returns_none_for_missing(self, prov_db):
        result = get_provenance_by_session(prov_db, "nonexistent")
        assert result is None
