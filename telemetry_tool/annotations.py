"""
annotations.py
--------------
Session annotation management -- CRUD, search, and tag autocomplete.

Features:
- Create/read/update/delete annotations on sessions
- Annotations can be tied to specific laps and distances
- Tag-based organization with autocomplete
- Full-text search across all annotations

Public API:
    create_annotation(conn, session_id, body, **kwargs)
    get_annotations(conn, session_id)
    get_annotation(conn, annotation_id)
    update_annotation(conn, annotation_id, **kwargs)
    delete_annotation(conn, annotation_id)
    search_annotations(conn, query, limit=50)
    get_all_tags(conn)
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def create_annotation(
    conn: Any,
    session_id: str,
    body: str,
    *,
    lap_number: Optional[int] = None,
    distance_m: Optional[float] = None,
    annotation_type: str = "note",
    title: Optional[str] = None,
    tags: Optional[list[str]] = None,
) -> dict[str, Any]:
    """
    Create a new annotation on a session.

    Parameters
    ----------
    conn : sqlite3.Connection
    session_id : str
    body : str -- the annotation text
    lap_number : int, optional -- specific lap reference
    distance_m : float, optional -- distance along track
    annotation_type : str -- "note", "issue", "insight", "todo"
    title : str, optional -- short title
    tags : list[str], optional -- tag list

    Returns
    -------
    dict with id, session_id, body, tags, created_at etc.
    """
    if not body or not body.strip():
        raise ValueError("Annotation body cannot be empty")

    valid_types = ("note", "issue", "insight", "todo")
    if annotation_type not in valid_types:
        annotation_type = "note"

    tags_json = json.dumps(tags) if tags else None

    cur = conn.execute(
        "INSERT INTO session_annotations "
        "(session_id, lap_number, distance_m, annotation_type, title, body, tags_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING id",
        (session_id, lap_number, distance_m, annotation_type, title, body.strip(), tags_json),
    )
    _row = cur.fetchone()
    if _row is None:
        conn.commit()
        raise RuntimeError("INSERT RETURNING id returned no row")
    annotation_id = _row[0] if not isinstance(_row, dict) else _row.get("id")
    conn.commit()

    logger.info("Created annotation #%d for session %s", annotation_id, session_id)

    return {
        "id": annotation_id,
        "session_id": session_id,
        "lap_number": lap_number,
        "distance_m": distance_m,
        "annotation_type": annotation_type,
        "title": title,
        "body": body.strip(),
        "tags": tags or [],
    }


def get_annotations(conn: Any, session_id: str) -> list[dict[str, Any]]:
    """Get all annotations for a session, newest first."""
    rows = conn.execute(
        "SELECT * FROM session_annotations WHERE session_id = ? ORDER BY created_at DESC",
        (session_id,),
    ).fetchall()

    result = []
    for row in rows:
        d = dict(row)
        d["tags"] = json.loads(d["tags_json"]) if d.get("tags_json") else []
        result.append(d)
    return result


def get_annotation(conn: Any, annotation_id: int) -> Optional[dict[str, Any]]:
    """Get a single annotation by ID."""
    row = conn.execute(
        "SELECT * FROM session_annotations WHERE id = ?",
        (annotation_id,),
    ).fetchone()

    if not row:
        return None

    d = dict(row)
    d["tags"] = json.loads(d["tags_json"]) if d.get("tags_json") else []
    return d


def update_annotation(
    conn: Any,
    annotation_id: int,
    **kwargs,
) -> Optional[dict[str, Any]]:
    """
    Update an existing annotation.

    Accepts keyword arguments: body, title, annotation_type, lap_number,
    distance_m, tags.
    """
    existing = get_annotation(conn, annotation_id)
    if not existing:
        return None

    body = kwargs.get("body", existing["body"])
    title = kwargs.get("title", existing.get("title"))
    annotation_type = kwargs.get("annotation_type", existing["annotation_type"])
    lap_number = kwargs.get("lap_number", existing.get("lap_number"))
    distance_m = kwargs.get("distance_m", existing.get("distance_m"))
    tags = kwargs.get("tags", existing.get("tags"))

    tags_json = json.dumps(tags) if tags else None

    conn.execute(
        "UPDATE session_annotations SET title=?, body=?, tags_json=?, "
        "annotation_type=?, lap_number=?, distance_m=?, updated_at=datetime('now') WHERE id=?",
        (title, body, tags_json, annotation_type, lap_number, distance_m, annotation_id),
    )
    conn.commit()

    logger.info("Updated annotation #%d", annotation_id)
    return get_annotation(conn, annotation_id)


def delete_annotation(conn: Any, annotation_id: int) -> bool:
    """Delete an annotation. Returns True if deleted, False if not found."""
    cur = conn.execute(
        "DELETE FROM session_annotations WHERE id = ?",
        (annotation_id,),
    )
    conn.commit()
    deleted = cur.rowcount > 0
    if deleted:
        logger.info("Deleted annotation #%d", annotation_id)
    return deleted


def search_annotations(
    conn: Any,
    query: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """
    Search annotations across all sessions.

    Searches title, body, and tags for the query string.
    Returns results with session metadata.
    """
    if not query or not query.strip():
        return []

    # Escape LIKE wildcards so user input like "100%" doesn't match "1000".
    sanitized = query.strip().replace("%", "\\%").replace("_", "\\_")
    like_q = f"%{sanitized}%"

    rows = conn.execute(
        "SELECT sa.*, s.session_date, d.driver_name, t.track_name "
        "FROM session_annotations sa "
        "JOIN sessions s ON sa.session_id = s.session_id "
        "LEFT JOIN drivers d ON s.driver_id = d.driver_id "
        "LEFT JOIN tracks t ON s.track_id = t.track_id "
        "WHERE sa.body LIKE ? ESCAPE '\\' "
        "OR sa.title LIKE ? ESCAPE '\\' "
        "OR sa.tags_json LIKE ? ESCAPE '\\' "
        "ORDER BY sa.created_at DESC LIMIT ?",
        (like_q, like_q, like_q, limit),
    ).fetchall()

    result = []
    for row in rows:
        d = dict(row)
        d["tags"] = json.loads(d["tags_json"]) if d.get("tags_json") else []
        result.append(d)
    return result


def get_all_tags(conn: Any) -> list[str]:
    """Get all unique tags used across all annotations."""
    rows = conn.execute(
        "SELECT DISTINCT json_each.value AS tag "
        "FROM session_annotations, json_each(session_annotations.tags_json) "
        "WHERE session_annotations.tags_json IS NOT NULL "
        "ORDER BY tag"
    ).fetchall()
    return [row[0] if isinstance(row, tuple) else row["tag"] for row in rows]


# -- Inline tests --------------------------------------------------------

def _run_tests() -> None:
    """Self-contained test suite for annotations."""
    import sqlite3
    import traceback as tb

    passed: list[str] = []
    failed: list[tuple[str, str]] = []

    def _test(name, fn):
        try:
            fn()
            passed.append(name)
        except Exception:
            failed.append((name, tb.format_exc()))

    def _make_db():
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("""CREATE TABLE IF NOT EXISTS drivers (
            driver_id INTEGER PRIMARY KEY AUTOINCREMENT,
            driver_name TEXT NOT NULL UNIQUE,
            created_at TEXT DEFAULT (datetime('now')), notes TEXT)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS tracks (
            track_id TEXT PRIMARY KEY, track_name TEXT NOT NULL,
            lap_length_m REAL NOT NULL, created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY, csv_filename TEXT NOT NULL,
            driver_id INTEGER NOT NULL, track_id TEXT,
            session_type TEXT DEFAULT 'practice', track_state TEXT DEFAULT 'dry',
            session_date TEXT NOT NULL, n_laps INTEGER, best_lap_time_s REAL,
            mean_lap_time_s REAL, total_score REAL, grade TEXT,
            weather_json TEXT, notes TEXT, html_report_path TEXT,
            simulation_method TEXT, created_at TEXT DEFAULT (datetime('now')))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS session_annotations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL, lap_number INTEGER, distance_m REAL,
            annotation_type TEXT DEFAULT 'note', title TEXT, body TEXT NOT NULL,
            tags_json TEXT, created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')))""")
        conn.execute("INSERT INTO drivers (driver_name) VALUES ('TestDriver')")
        conn.execute("INSERT INTO tracks (track_id, track_name, lap_length_m) VALUES ('t1', 'TestTrack', 1000)")
        conn.execute("INSERT INTO sessions (session_id, csv_filename, driver_id, track_id, session_date) VALUES ('s1', 'test.csv', 1, 't1', '2024-01-01')")
        conn.commit()
        return conn

    # Test 1: create annotation
    def t_create():
        conn = _make_db()
        ann = create_annotation(conn, "s1", "Great lap!", title="Lap 5", tags=["fast", "clean"])
        assert ann["id"] is not None
        assert ann["body"] == "Great lap!"
        assert ann["tags"] == ["fast", "clean"]
        assert ann["title"] == "Lap 5"
        conn.close()

    _test("create", t_create)

    # Test 2: get annotations
    def t_get_list():
        conn = _make_db()
        create_annotation(conn, "s1", "Note 1")
        create_annotation(conn, "s1", "Note 2", tags=["tag1"])
        anns = get_annotations(conn, "s1")
        assert len(anns) == 2
        conn.close()

    _test("get_list", t_get_list)

    # Test 3: update annotation
    def t_update():
        conn = _make_db()
        ann = create_annotation(conn, "s1", "Original")
        updated = update_annotation(conn, ann["id"], body="Modified", tags=["updated"])
        assert updated["body"] == "Modified"
        assert updated["tags"] == ["updated"]
        conn.close()

    _test("update", t_update)

    # Test 4: delete annotation
    def t_delete():
        conn = _make_db()
        ann = create_annotation(conn, "s1", "To delete")
        assert delete_annotation(conn, ann["id"]) is True
        assert get_annotation(conn, ann["id"]) is None
        assert delete_annotation(conn, 999) is False
        conn.close()

    _test("delete", t_delete)

    # Test 5: search
    def t_search():
        conn = _make_db()
        create_annotation(conn, "s1", "Brake issue in turn 3", tags=["braking"])
        create_annotation(conn, "s1", "Good throttle application")
        results = search_annotations(conn, "brake")
        assert len(results) == 1
        assert "Brake" in results[0]["body"]
        # Empty search
        assert search_annotations(conn, "") == []
        conn.close()

    _test("search", t_search)

    # Test 6: tags
    def t_tags():
        conn = _make_db()
        create_annotation(conn, "s1", "A", tags=["tag1", "tag2"])
        create_annotation(conn, "s1", "B", tags=["tag2", "tag3"])
        create_annotation(conn, "s1", "C")  # No tags
        tags = get_all_tags(conn)
        assert "tag1" in tags
        assert "tag2" in tags
        assert "tag3" in tags
        assert len(tags) == 3
        conn.close()

    _test("tags", t_tags)

    # Test 7: empty body validation
    def t_empty_body():
        conn = _make_db()
        try:
            create_annotation(conn, "s1", "")
            assert False, "Should have raised ValueError"
        except ValueError:
            pass
        try:
            create_annotation(conn, "s1", "   ")
            assert False, "Should have raised ValueError"
        except ValueError:
            pass
        conn.close()

    _test("empty_body", t_empty_body)

    # Test 8: annotation types
    def t_types():
        conn = _make_db()
        for atype in ("note", "issue", "insight", "todo"):
            ann = create_annotation(conn, "s1", f"Type {atype}", annotation_type=atype)
            assert ann["annotation_type"] == atype
        # Invalid type defaults to note
        ann = create_annotation(conn, "s1", "Bad type", annotation_type="invalid")
        assert ann["annotation_type"] == "note"
        conn.close()

    _test("types", t_types)

    total = len(passed) + len(failed)
    status_str = "PASS" if not failed else "FAIL"
    print(f"\nAnnotations Tests: {len(passed)}/{total} passed [{status_str}]")
    for n in passed:
        print(f"  OK {n}")
    for n, trace in failed:
        print(f"  FAIL {n}\n{trace}")
    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


if __name__ == "__main__":
    _run_tests()
