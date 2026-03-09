"""Tests for cursor-based keyset pagination utilities."""
import base64
import json
import sqlite3
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from web.pagination import (
    build_keyset_clause,
    decode_cursor,
    encode_cursor,
    paginate_query,
    pagination_meta,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def mem_db():
    """In-memory SQLite with a simple 'items' table seeded with 10 rows."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE items (id INTEGER PRIMARY KEY, score REAL, name TEXT)"
    )
    for i in range(1, 11):
        conn.execute(
            "INSERT INTO items (id, score, name) VALUES (?, ?, ?)",
            (i, 100.0 - i, f"item_{i}"),
        )
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# encode / decode round-trip
# ---------------------------------------------------------------------------

class TestEncodeDecode:
    def test_round_trip_string_sort(self):
        cursor = encode_cursor("2026-01-15T10:30:00", 125)
        result = decode_cursor(cursor)
        assert result == {"s": "2026-01-15T10:30:00", "id": 125}

    def test_round_trip_numeric_sort(self):
        cursor = encode_cursor(99.5, 42)
        result = decode_cursor(cursor)
        assert result["s"] == 99.5
        assert result["id"] == 42

    def test_round_trip_integer_sort(self):
        cursor = encode_cursor(100, 1)
        result = decode_cursor(cursor)
        assert result == {"s": 100, "id": 1}

    def test_decode_none_for_invalid_base64(self):
        assert decode_cursor("!!!not-base64!!!") is None

    def test_decode_none_for_invalid_json(self):
        # Valid base64 but not valid JSON
        raw = base64.urlsafe_b64encode(b"not json at all").decode()
        assert decode_cursor(raw) is None

    def test_decode_none_for_missing_keys(self):
        raw = base64.urlsafe_b64encode(json.dumps({"x": 1}).encode()).decode()
        assert decode_cursor(raw) is None

    def test_decode_none_for_empty_string(self):
        assert decode_cursor("") is None

    def test_decode_none_for_none_input(self):
        assert decode_cursor(None) is None


# ---------------------------------------------------------------------------
# build_keyset_clause
# ---------------------------------------------------------------------------

class TestBuildKeysetClause:
    def test_descending_produces_less_than(self):
        cursor = encode_cursor(99.0, 5)
        clause, params = build_keyset_clause(
            decode_cursor(cursor), "score", "id", descending=True
        )
        assert "<" in clause
        assert params["cursor_sort"] == 99.0
        assert params["cursor_id"] == 5

    def test_ascending_produces_greater_than(self):
        cursor = encode_cursor(10.0, 3)
        clause, params = build_keyset_clause(
            decode_cursor(cursor), "score", "id", descending=False
        )
        assert ">" in clause
        assert params["cursor_sort"] == 10.0
        assert params["cursor_id"] == 3

    def test_none_cursor_returns_empty(self):
        clause, params = build_keyset_clause(None, "score", "id", descending=True)
        assert clause == ""
        assert params == {}

    def test_custom_id_col(self):
        cursor = encode_cursor(50, 7)
        clause, params = build_keyset_clause(
            decode_cursor(cursor), "created_at", "row_id", descending=True
        )
        assert "row_id" in clause
        assert "created_at" in clause


# ---------------------------------------------------------------------------
# pagination_meta
# ---------------------------------------------------------------------------

class TestPaginationMeta:
    def test_format_with_next_cursor(self):
        meta = pagination_meta("abc123", True, 25)
        assert meta == {
            "next_cursor": "abc123",
            "has_more": True,
            "limit": 25,
        }

    def test_format_no_more(self):
        meta = pagination_meta(None, False, 10)
        assert meta == {
            "next_cursor": None,
            "has_more": False,
            "limit": 10,
        }


# ---------------------------------------------------------------------------
# paginate_query — integration with SQLite
# ---------------------------------------------------------------------------

class TestPaginateQuery:
    def test_first_page_no_cursor(self, mem_db):
        rows, next_cursor, has_more = paginate_query(
            mem_db,
            "SELECT id, score, name FROM items",
            {},
            sort_col="score",
            id_col="id",
            cursor_str=None,
            limit=3,
            descending=True,
        )
        assert len(rows) == 3
        assert has_more is True
        assert next_cursor is not None

    def test_cursor_applies_keyset(self, mem_db):
        # Get first page
        rows1, cursor1, _ = paginate_query(
            mem_db,
            "SELECT id, score, name FROM items",
            {},
            sort_col="score",
            id_col="id",
            cursor_str=None,
            limit=3,
            descending=True,
        )
        # Get second page using cursor
        rows2, cursor2, has_more2 = paginate_query(
            mem_db,
            "SELECT id, score, name FROM items",
            {},
            sort_col="score",
            id_col="id",
            cursor_str=cursor1,
            limit=3,
            descending=True,
        )
        assert len(rows2) == 3
        # Second page scores must be lower than last item on first page
        first_page_last_score = rows1[-1]["score"]
        for row in rows2:
            assert row["score"] <= first_page_last_score

    def test_has_more_true_when_more_rows(self, mem_db):
        _, _, has_more = paginate_query(
            mem_db,
            "SELECT id, score, name FROM items",
            {},
            sort_col="score",
            id_col="id",
            cursor_str=None,
            limit=5,
            descending=True,
        )
        assert has_more is True

    def test_has_more_false_on_last_page(self, mem_db):
        _, _, has_more = paginate_query(
            mem_db,
            "SELECT id, score, name FROM items",
            {},
            sort_col="score",
            id_col="id",
            cursor_str=None,
            limit=10,
            descending=True,
        )
        assert has_more is False

    def test_limit_clamped_to_max_100(self, mem_db):
        rows, _, _ = paginate_query(
            mem_db,
            "SELECT id, score, name FROM items",
            {},
            sort_col="score",
            id_col="id",
            cursor_str=None,
            limit=500,
            descending=True,
        )
        # Only 10 rows exist, but limit should have been clamped to 100
        assert len(rows) <= 100

    def test_ascending_order(self, mem_db):
        rows, _, _ = paginate_query(
            mem_db,
            "SELECT id, score, name FROM items",
            {},
            sort_col="score",
            id_col="id",
            cursor_str=None,
            limit=3,
            descending=False,
        )
        scores = [r["score"] for r in rows]
        assert scores == sorted(scores)

    def test_paginate_all_rows_across_pages(self, mem_db):
        """Walk through all pages and collect every row exactly once."""
        all_ids = []
        cursor = None
        for _ in range(10):  # safety cap
            rows, cursor, has_more = paginate_query(
                mem_db,
                "SELECT id, score, name FROM items",
                {},
                sort_col="score",
                id_col="id",
                cursor_str=cursor,
                limit=3,
                descending=True,
            )
            all_ids.extend(r["id"] for r in rows)
            if not has_more:
                break
        assert sorted(all_ids) == list(range(1, 11))

    def test_empty_table(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE empty (id INTEGER PRIMARY KEY, score REAL)")
        rows, next_cursor, has_more = paginate_query(
            conn,
            "SELECT id, score FROM empty",
            {},
            sort_col="score",
            id_col="id",
            cursor_str=None,
            limit=10,
            descending=True,
        )
        assert rows == []
        assert next_cursor is None
        assert has_more is False

    def test_limit_default_clamped_minimum(self, mem_db):
        """Limit of 0 or negative is treated as 1."""
        rows, _, _ = paginate_query(
            mem_db,
            "SELECT id, score, name FROM items",
            {},
            sort_col="score",
            id_col="id",
            cursor_str=None,
            limit=0,
            descending=True,
        )
        assert len(rows) >= 1

    def test_base_params_preserved(self, mem_db):
        """Extra WHERE conditions in base_sql + params still work."""
        rows, _, _ = paginate_query(
            mem_db,
            "SELECT id, score, name FROM items WHERE name LIKE :prefix",
            {"prefix": "item_%"},
            sort_col="score",
            id_col="id",
            cursor_str=None,
            limit=25,
            descending=True,
        )
        assert len(rows) == 10
