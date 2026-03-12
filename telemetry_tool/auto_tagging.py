"""
auto_tagging.py
---------------
Automatic session tagging based on rule-based analysis.

Tags are stored in the session_tags table with confidence scores.
Tags help organize sessions and enable quick filtering.

Rules:
- rain_session: track_state in ('wet', 'damp')
- tire_test: notes contain tire/tyre keywords
- race_simulation: race type + >10 laps
- improvement_session: pace >1% better vs previous on same track
- consistency_session: CV% < 1.0
- degradation_session: late stint >3% slower than early stint
- personal_best: new PB on track for this driver
- high_quality_data: data health score > 80
- low_quality_data: data health score < 40
- qualifying_run: session_type = 'qualifying'
- long_run: n_laps > 20
- short_run: n_laps <= 5

Public API:
    auto_tag_session(conn, session_id) -> list[dict]
    get_session_tags(conn, session_id) -> list[dict]
    add_manual_tag(conn, session_id, tag) -> dict
    remove_tag(conn, session_id, tag) -> bool
    get_all_unique_tags(conn) -> list[str]
    get_sessions_by_tag(conn, tag) -> list[dict]
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def auto_tag_session(conn: Any, session_id: str) -> list[dict[str, Any]]:
    """
    Automatically tag a session based on its data.

    Analyzes session metadata, lap data, and scoring to assign
    relevant tags. Existing auto-generated tags are replaced;
    manual tags are preserved.

    Returns list of applied tags with confidence scores.
    """
    # Get session info
    row = conn.execute(
        "SELECT s.*, d.driver_name, t.track_name "
        "FROM sessions s "
        "LEFT JOIN drivers d ON s.driver_id = d.driver_id "
        "LEFT JOIN tracks t ON s.track_id = t.track_id "
        "WHERE s.session_id = ?",
        (session_id,),
    ).fetchone()

    if not row:
        return []

    sess = dict(row)
    tags_to_apply = []

    # Rule 1: Rain session
    track_state = (sess.get("track_state") or "").lower()
    if track_state in ("wet", "damp"):
        tags_to_apply.append(("rain_session", 1.0))

    # Rule 2: Tire test
    notes = (sess.get("notes") or "").lower()
    if any(kw in notes for kw in ("tire", "tyre", "compound", "rubber")):
        tags_to_apply.append(("tire_test", 0.8))

    # Rule 3: Race simulation
    session_type = (sess.get("session_type") or "").lower()
    n_laps = sess.get("n_laps") or 0
    if session_type in ("race", "sprint_race", "feature_race", "endurance_race") and n_laps > 10:
        tags_to_apply.append(("race_simulation", 0.9))

    # Rule 4: Improvement session (pace >1% better vs previous)
    if sess.get("best_lap_time_s") and sess.get("track_id") and sess.get("driver_id"):
        prev = conn.execute(
            "SELECT best_lap_time_s FROM sessions "
            "WHERE driver_id = ? AND track_id = ? AND session_id != ? "
            "AND best_lap_time_s IS NOT NULL AND deleted_at IS NULL "
            "ORDER BY session_date DESC LIMIT 1",
            (sess["driver_id"], sess["track_id"], session_id),
        ).fetchone()
        if prev and prev[0]:
            improvement_pct = (prev[0] - sess["best_lap_time_s"]) / prev[0] * 100
            if improvement_pct > 1.0:
                tags_to_apply.append(("improvement_session", min(1.0, improvement_pct / 5.0)))

    # Rule 5: Consistency session (CV% < 1.0)
    laps = conn.execute(
        "SELECT lap_time_s FROM laps WHERE session_id = ? AND is_valid = 1 AND lap_time_s IS NOT NULL",
        (session_id,),
    ).fetchall()
    if len(laps) >= 3:
        times = [l[0] if isinstance(l, tuple) else l["lap_time_s"] for l in laps]
        mean_t = sum(times) / len(times)
        if mean_t > 0:
            std_t = (sum((t - mean_t) ** 2 for t in times) / len(times)) ** 0.5
            cv_pct = (std_t / mean_t) * 100
            if cv_pct < 1.0:
                tags_to_apply.append(("consistency_session", min(1.0, (1.0 - cv_pct) + 0.5)))

    # Rule 6: Degradation session (late stint >3% slower)
    if len(laps) >= 6:
        times = [l[0] if isinstance(l, tuple) else l["lap_time_s"] for l in laps]
        half = len(times) // 2
        early_mean = sum(times[:half]) / half
        late_mean = sum(times[half:]) / (len(times) - half)
        if early_mean > 0:
            fade_pct = (late_mean - early_mean) / early_mean * 100
            if fade_pct > 3.0:
                tags_to_apply.append(("degradation_session", min(1.0, fade_pct / 10.0)))

    # Rule 7: Personal best
    if sess.get("best_lap_time_s") and sess.get("track_id") and sess.get("driver_id"):
        pb = conn.execute(
            "SELECT MIN(best_lap_time_s) FROM sessions "
            "WHERE driver_id = ? AND track_id = ? AND best_lap_time_s IS NOT NULL AND deleted_at IS NULL",
            (sess["driver_id"], sess["track_id"]),
        ).fetchone()
        if pb and pb[0] and abs(sess["best_lap_time_s"] - pb[0]) < 0.001:
            tags_to_apply.append(("personal_best", 1.0))

    # Rule 8/9: Data health quality
    dh = conn.execute(
        "SELECT overall_score FROM data_health WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if dh:
        score = dh[0] if isinstance(dh, tuple) else dh["overall_score"]
        if score is not None:
            if score > 80:
                tags_to_apply.append(("high_quality_data", score / 100.0))
            elif score < 40:
                tags_to_apply.append(("low_quality_data", 1.0 - score / 100.0))

    # Rule 10: Qualifying run
    if session_type == "qualifying":
        tags_to_apply.append(("qualifying_run", 1.0))

    # Rule 11: Long run
    if n_laps > 20:
        tags_to_apply.append(("long_run", 0.9))

    # Rule 12: Short run
    if 0 < n_laps <= 5:
        tags_to_apply.append(("short_run", 0.9))

    # Remove existing auto tags, keep manual
    conn.execute(
        "DELETE FROM session_tags WHERE session_id = ? AND source = 'auto'",
        (session_id,),
    )

    # Insert new tags
    applied = []
    for tag, confidence in tags_to_apply:
        conn.execute(
            "INSERT OR REPLACE INTO session_tags (session_id, tag, confidence, source) "
            "VALUES (?, ?, ?, 'auto')",
            (session_id, tag, round(confidence, 3)),
        )
        applied.append({"tag": tag, "confidence": round(confidence, 3), "source": "auto"})

    conn.commit()
    logger.info("Auto-tagged session %s: %d tags applied", session_id, len(applied))
    return applied


def get_session_tags(conn: Any, session_id: str) -> list[dict[str, Any]]:
    """Get all tags for a session."""
    rows = conn.execute(
        "SELECT tag, confidence, source, created_at FROM session_tags "
        "WHERE session_id = ? ORDER BY source, tag",
        (session_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def add_manual_tag(conn: Any, session_id: str, tag: str) -> dict[str, Any]:
    """Add a manual tag to a session."""
    if not tag or not tag.strip():
        raise ValueError("Tag cannot be empty")

    tag = tag.strip().lower().replace(" ", "_")

    conn.execute(
        "INSERT OR REPLACE INTO session_tags (session_id, tag, confidence, source) "
        "VALUES (?, ?, ?, 'manual')",
        (session_id, tag, 1.0),
    )
    conn.commit()
    return {"tag": tag, "confidence": 1.0, "source": "manual"}


def remove_tag(conn: Any, session_id: str, tag: str) -> bool:
    """Remove a tag from a session."""
    cur = conn.execute(
        "DELETE FROM session_tags WHERE session_id = ? AND tag = ?",
        (session_id, tag),
    )
    conn.commit()
    return cur.rowcount > 0


def get_all_unique_tags(conn: Any) -> list[str]:
    """Get all unique tags across all sessions."""
    rows = conn.execute(
        "SELECT DISTINCT tag FROM session_tags ORDER BY tag"
    ).fetchall()
    return [r[0] if isinstance(r, tuple) else r["tag"] for r in rows]


def get_sessions_by_tag(conn: Any, tag: str) -> list[dict[str, Any]]:
    """Get all sessions with a specific tag."""
    rows = conn.execute(
        "SELECT st.session_id, st.confidence, st.source, "
        "s.session_date, s.session_type, s.n_laps, s.best_lap_time_s, s.grade, "
        "d.driver_name, t.track_name "
        "FROM session_tags st "
        "JOIN sessions s ON st.session_id = s.session_id "
        "LEFT JOIN drivers d ON s.driver_id = d.driver_id "
        "LEFT JOIN tracks t ON s.track_id = t.track_id "
        "WHERE st.tag = ? "
        "ORDER BY s.session_date DESC",
        (tag,),
    ).fetchall()
    return [dict(r) for r in rows]


# ── Inline tests ────────────────────────────────────────────────

def _run_tests() -> None:
    """Self-contained test suite for auto-tagging."""
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
        conn.execute("""CREATE TABLE IF NOT EXISTS laps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL, lap_number INTEGER NOT NULL,
            lap_time_s REAL, is_valid INTEGER DEFAULT 1,
            UNIQUE(session_id, lap_number))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS data_health (
            session_id TEXT PRIMARY KEY, overall_score REAL,
            gps_quality REAL, accel_quality REAL,
            created_at TEXT DEFAULT (datetime('now')))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS session_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL, tag TEXT NOT NULL,
            confidence REAL, source TEXT DEFAULT 'auto',
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(session_id, tag))""")
        conn.execute("INSERT INTO drivers (driver_name) VALUES ('TestDriver')")
        conn.execute("INSERT INTO tracks (track_id, track_name, lap_length_m) VALUES ('t1', 'TestTrack', 1000)")
        conn.commit()
        return conn

    def _insert_session(conn, sid, **kw):
        conn.execute(
            "INSERT INTO sessions (session_id, csv_filename, driver_id, track_id, "
            "session_type, track_state, session_date, n_laps, best_lap_time_s, notes) "
            "VALUES (?, 'test.csv', 1, 't1', ?, ?, '2024-01-01', ?, ?, ?)",
            (sid, kw.get("session_type", "practice"), kw.get("track_state", "dry"),
             kw.get("n_laps", 10), kw.get("best_lap_time_s"), kw.get("notes", "")),
        )
        conn.commit()

    def _insert_laps(conn, sid, times):
        for i, t in enumerate(times, 1):
            conn.execute(
                "INSERT INTO laps (session_id, lap_number, lap_time_s, is_valid) VALUES (?, ?, ?, 1)",
                (sid, i, t),
            )
        conn.commit()

    # Test 1: rain session
    def t_rain():
        conn = _make_db()
        _insert_session(conn, "s1", track_state="wet")
        tags = auto_tag_session(conn, "s1")
        tag_names = [t["tag"] for t in tags]
        assert "rain_session" in tag_names
        conn.close()

    _test("rain", t_rain)

    # Test 2: tire test
    def t_tire():
        conn = _make_db()
        _insert_session(conn, "s1", notes="Testing new tire compound")
        tags = auto_tag_session(conn, "s1")
        tag_names = [t["tag"] for t in tags]
        assert "tire_test" in tag_names
        conn.close()

    _test("tire_test", t_tire)

    # Test 3: race simulation
    def t_race_sim():
        conn = _make_db()
        _insert_session(conn, "s1", session_type="race", n_laps=15)
        tags = auto_tag_session(conn, "s1")
        tag_names = [t["tag"] for t in tags]
        assert "race_simulation" in tag_names
        conn.close()

    _test("race_simulation", t_race_sim)

    # Test 4: consistency session (CV < 1%)
    def t_consistency():
        conn = _make_db()
        _insert_session(conn, "s1", n_laps=10)
        _insert_laps(conn, "s1", [60.0, 60.1, 60.0, 59.9, 60.05, 60.02, 59.98, 60.01, 60.03, 59.97])
        tags = auto_tag_session(conn, "s1")
        tag_names = [t["tag"] for t in tags]
        assert "consistency_session" in tag_names
        conn.close()

    _test("consistency", t_consistency)

    # Test 5: degradation session
    def t_degradation():
        conn = _make_db()
        _insert_session(conn, "s1", n_laps=10)
        # Early laps fast, late laps 5% slower
        _insert_laps(conn, "s1", [60, 60, 60, 60, 60, 63.5, 63.5, 63.5, 63.5, 63.5])
        tags = auto_tag_session(conn, "s1")
        tag_names = [t["tag"] for t in tags]
        assert "degradation_session" in tag_names
        conn.close()

    _test("degradation", t_degradation)

    # Test 6: personal best
    def t_pb():
        conn = _make_db()
        _insert_session(conn, "s1", best_lap_time_s=62.0)
        _insert_session(conn, "s2", best_lap_time_s=60.0)
        # s2 is the PB (60.0), s1 is not (62.0)
        tags = auto_tag_session(conn, "s2")
        tag_names = [t["tag"] for t in tags]
        assert "personal_best" in tag_names
        # Also improvement_session because s2 is better than s1
        assert "improvement_session" in tag_names
        conn.close()

    _test("personal_best", t_pb)

    # Test 7: data health tags
    def t_data_health():
        conn = _make_db()
        _insert_session(conn, "s1")
        conn.execute("INSERT INTO data_health (session_id, overall_score) VALUES ('s1', 90)")
        conn.commit()
        tags = auto_tag_session(conn, "s1")
        tag_names = [t["tag"] for t in tags]
        assert "high_quality_data" in tag_names

        # Low quality
        _insert_session(conn, "s2")
        conn.execute("INSERT INTO data_health (session_id, overall_score) VALUES ('s2', 20)")
        conn.commit()
        tags = auto_tag_session(conn, "s2")
        tag_names = [t["tag"] for t in tags]
        assert "low_quality_data" in tag_names
        conn.close()

    _test("data_health_tags", t_data_health)

    # Test 8: manual tag + get/remove
    def t_manual():
        conn = _make_db()
        _insert_session(conn, "s1")
        tag = add_manual_tag(conn, "s1", "my_custom_tag")
        assert tag["source"] == "manual"

        tags = get_session_tags(conn, "s1")
        assert len(tags) == 1
        assert tags[0]["tag"] == "my_custom_tag"

        # Remove
        assert remove_tag(conn, "s1", "my_custom_tag") is True
        assert remove_tag(conn, "s1", "nonexistent") is False
        assert len(get_session_tags(conn, "s1")) == 0
        conn.close()

    _test("manual_tags", t_manual)

    # Test 9: auto-tags don't replace manual tags
    def t_preserve_manual():
        conn = _make_db()
        _insert_session(conn, "s1", track_state="wet")
        add_manual_tag(conn, "s1", "important")
        # Run auto-tagging
        auto_tag_session(conn, "s1")
        tags = get_session_tags(conn, "s1")
        tag_names = [t["tag"] for t in tags]
        assert "important" in tag_names  # Manual preserved
        assert "rain_session" in tag_names  # Auto added
        conn.close()

    _test("preserve_manual", t_preserve_manual)

    # Test 10: get_all_unique_tags and get_sessions_by_tag
    def t_tag_queries():
        conn = _make_db()
        _insert_session(conn, "s1", track_state="wet")
        _insert_session(conn, "s2", track_state="wet")
        auto_tag_session(conn, "s1")
        auto_tag_session(conn, "s2")

        all_tags = get_all_unique_tags(conn)
        assert "rain_session" in all_tags

        sessions = get_sessions_by_tag(conn, "rain_session")
        assert len(sessions) == 2
        conn.close()

    _test("tag_queries", t_tag_queries)

    # Test 11: long/short run + qualifying
    def t_special_types():
        conn = _make_db()
        _insert_session(conn, "s1", session_type="qualifying", n_laps=3)
        tags = auto_tag_session(conn, "s1")
        tag_names = [t["tag"] for t in tags]
        assert "qualifying_run" in tag_names
        assert "short_run" in tag_names

        _insert_session(conn, "s2", n_laps=25)
        tags = auto_tag_session(conn, "s2")
        tag_names = [t["tag"] for t in tags]
        assert "long_run" in tag_names
        conn.close()

    _test("special_types", t_special_types)

    # Test 12: nonexistent session
    def t_nonexistent():
        conn = _make_db()
        tags = auto_tag_session(conn, "nonexistent")
        assert tags == []
        conn.close()

    _test("nonexistent", t_nonexistent)

    total = len(passed) + len(failed)
    status_str = "PASS" if not failed else "FAIL"
    print(f"\nAuto-Tagging Tests: {len(passed)}/{total} passed [{status_str}]")
    for n in passed:
        print(f"  OK {n}")
    for n, trace in failed:
        print(f"  FAIL {n}\n{trace}")
    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


if __name__ == "__main__":
    _run_tests()
