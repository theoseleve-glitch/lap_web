"""
dashboard_builder.py
--------------------
Custom dashboard management with a widget registry.

Supports creating personalized dashboards with selectable widgets,
arranged in a grid layout. Each widget renders a specific data
visualization (pace chart, G-G diagram, leaderboard, trends, etc.).

Public API:
    get_widget_registry() -> list[dict]
    create_dashboard(conn, name, layout, driver_id=None) -> dict
    get_dashboards(conn, driver_id=None) -> list[dict]
    get_dashboard(conn, dashboard_id) -> dict | None
    update_dashboard(conn, dashboard_id, **kwargs) -> dict | None
    delete_dashboard(conn, dashboard_id) -> bool
    get_widget_data(conn, widget_type, params) -> dict
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ── Widget Registry ─────────────────────────────────────────────

_WIDGET_REGISTRY = [
    {
        "type": "pace_chart",
        "name": "Lap Pace Chart",
        "description": "Line chart showing lap times across a session.",
        "category": "session",
        "default_size": {"w": 6, "h": 3},
        "params": ["session_id"],
    },
    {
        "type": "gg_diagram",
        "name": "G-G Diagram",
        "description": "Lateral vs longitudinal acceleration scatter.",
        "category": "session",
        "default_size": {"w": 4, "h": 4},
        "params": ["session_id", "lap_number"],
    },
    {
        "type": "speed_trace",
        "name": "Speed Trace",
        "description": "Speed vs distance overlay for selected laps.",
        "category": "session",
        "default_size": {"w": 8, "h": 3},
        "params": ["session_id"],
    },
    {
        "type": "leaderboard",
        "name": "Track Leaderboard",
        "description": "Best lap times for a track across all drivers.",
        "category": "global",
        "default_size": {"w": 4, "h": 4},
        "params": ["track_id"],
    },
    {
        "type": "trend_line",
        "name": "Pace Trend",
        "description": "Multi-session pace trend with confidence band.",
        "category": "driver",
        "default_size": {"w": 6, "h": 3},
        "params": ["driver_id", "track_id"],
    },
    {
        "type": "consistency_gauge",
        "name": "Consistency Gauge",
        "description": "Current consistency rating as a gauge chart.",
        "category": "driver",
        "default_size": {"w": 3, "h": 3},
        "params": ["driver_id"],
    },
    {
        "type": "score_breakdown",
        "name": "Score Breakdown",
        "description": "Radar chart of pace, consistency, execution, robustness scores.",
        "category": "session",
        "default_size": {"w": 4, "h": 4},
        "params": ["session_id"],
    },
    {
        "type": "weather_scatter",
        "name": "Weather vs Pace",
        "description": "Temperature/humidity scatter vs lap pace.",
        "category": "global",
        "default_size": {"w": 5, "h": 3},
        "params": ["track_id", "driver_id"],
    },
    {
        "type": "corner_heatmap",
        "name": "Corner Performance Heatmap",
        "description": "Laps x corners time loss heatmap.",
        "category": "session",
        "default_size": {"w": 6, "h": 4},
        "params": ["session_id"],
    },
    {
        "type": "recent_sessions",
        "name": "Recent Sessions",
        "description": "Table of most recent sessions with grades.",
        "category": "global",
        "default_size": {"w": 6, "h": 3},
        "params": [],
    },
    {
        "type": "data_health_summary",
        "name": "Data Health Summary",
        "description": "Quality scores for recent sessions.",
        "category": "global",
        "default_size": {"w": 4, "h": 3},
        "params": [],
    },
    {
        "type": "personal_bests",
        "name": "Personal Bests",
        "description": "Personal best times per track for a driver.",
        "category": "driver",
        "default_size": {"w": 5, "h": 3},
        "params": ["driver_id"],
    },
]


def get_widget_registry() -> list[dict[str, Any]]:
    """Return all available widget definitions."""
    return [dict(w) for w in _WIDGET_REGISTRY]


def create_dashboard(
    conn: Any,
    name: str,
    layout: list[dict],
    *,
    driver_id: Optional[int] = None,
    is_default: bool = False,
) -> dict[str, Any]:
    """
    Create a new custom dashboard.

    Parameters
    ----------
    conn : sqlite3.Connection
    name : str — dashboard name
    layout : list[dict] — list of widget placement dicts, each with:
        type, x, y, w, h, params
    driver_id : int, optional — owner driver
    is_default : bool — set as default dashboard

    Returns
    -------
    dict with id, name, layout, etc.
    """
    if not name or not name.strip():
        raise ValueError("Dashboard name cannot be empty")

    # Validate layout
    validated = _validate_layout(layout)
    layout_json = json.dumps(validated)

    # If setting as default, unset existing defaults
    if is_default:
        conn.execute(
            "UPDATE custom_dashboards SET is_default = 0 WHERE driver_id IS ? OR ? IS NULL",
            (driver_id, driver_id),
        )

    cur = conn.execute(
        "INSERT INTO custom_dashboards (driver_id, dashboard_name, layout_json, is_default) "
        "VALUES (?, ?, ?, ?) RETURNING id",
        (driver_id, name.strip(), layout_json, 1 if is_default else 0),
    )
    _row = cur.fetchone()
    if _row is None:
        conn.commit()
        raise RuntimeError("INSERT RETURNING id returned no row")
    _new_id = _row[0] if not isinstance(_row, dict) else _row.get("id")
    conn.commit()

    logger.info("Created dashboard '%s' (id=%s)", name, _new_id)

    return {
        "id": _new_id,
        "driver_id": driver_id,
        "dashboard_name": name.strip(),
        "layout": validated,
        "is_default": is_default,
    }


def get_dashboards(conn: Any, driver_id: Optional[int] = None) -> list[dict[str, Any]]:
    """Get all dashboards, optionally filtered by driver."""
    if driver_id is not None:
        rows = conn.execute(
            "SELECT * FROM custom_dashboards WHERE driver_id = ? OR driver_id IS NULL "
            "ORDER BY is_default DESC, updated_at DESC",
            (driver_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM custom_dashboards ORDER BY is_default DESC, updated_at DESC"
        ).fetchall()

    result = []
    for row in rows:
        d = dict(row)
        d["layout"] = json.loads(d["layout_json"]) if d.get("layout_json") else []
        d["is_default"] = bool(d.get("is_default", 0))
        result.append(d)
    return result


def get_dashboard(conn: Any, dashboard_id: int) -> Optional[dict[str, Any]]:
    """Get a single dashboard by ID."""
    row = conn.execute(
        "SELECT * FROM custom_dashboards WHERE id = ?",
        (dashboard_id,),
    ).fetchone()

    if not row:
        return None

    d = dict(row)
    d["layout"] = json.loads(d["layout_json"]) if d.get("layout_json") else []
    d["is_default"] = bool(d.get("is_default", 0))
    return d


def update_dashboard(
    conn: Any,
    dashboard_id: int,
    **kwargs,
) -> Optional[dict[str, Any]]:
    """
    Update a dashboard.

    Accepts: name, layout, is_default.
    """
    existing = get_dashboard(conn, dashboard_id)
    if not existing:
        return None

    name = kwargs.get("name", existing["dashboard_name"])
    layout = kwargs.get("layout", existing["layout"])
    is_default = kwargs.get("is_default", existing["is_default"])

    validated = _validate_layout(layout)
    layout_json = json.dumps(validated)

    if is_default and not existing["is_default"]:
        conn.execute(
            "UPDATE custom_dashboards SET is_default = 0 WHERE driver_id IS ? OR ? IS NULL",
            (existing.get("driver_id"), existing.get("driver_id")),
        )

    conn.execute(
        "UPDATE custom_dashboards SET dashboard_name=?, layout_json=?, is_default=?, "
        "updated_at=datetime('now') WHERE id=?",
        (name, layout_json, 1 if is_default else 0, dashboard_id),
    )
    conn.commit()

    return get_dashboard(conn, dashboard_id)


def delete_dashboard(conn: Any, dashboard_id: int) -> bool:
    """Delete a dashboard."""
    cur = conn.execute("DELETE FROM custom_dashboards WHERE id = ?", (dashboard_id,))
    conn.commit()
    return cur.rowcount > 0


def get_widget_data(
    conn: Any,
    widget_type: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    """
    Fetch data for a specific widget type.

    This is a dispatcher that calls the appropriate data-fetching
    logic for each widget type.

    Parameters
    ----------
    conn : database connection
    widget_type : str — one of the registered widget types
    params : dict — widget-specific parameters

    Returns
    -------
    dict with widget-specific data
    """
    valid_types = {w["type"] for w in _WIDGET_REGISTRY}
    if widget_type not in valid_types:
        return {"error": f"Unknown widget type: {widget_type}"}

    try:
        if widget_type == "recent_sessions":
            return _widget_recent_sessions(conn, params)
        elif widget_type == "leaderboard":
            return _widget_leaderboard(conn, params)
        elif widget_type == "personal_bests":
            return _widget_personal_bests(conn, params)
        elif widget_type == "pace_chart":
            return _widget_pace_chart(conn, params)
        elif widget_type == "score_breakdown":
            return _widget_score_breakdown(conn, params)
        elif widget_type == "consistency_gauge":
            return _widget_consistency_gauge(conn, params)
        elif widget_type == "data_health_summary":
            return _widget_data_health_summary(conn, params)
        else:
            # Other widget types return placeholder data
            return {"widget_type": widget_type, "status": "placeholder", "params": params}
    except Exception as exc:
        logger.error("Widget data error (%s): %s", widget_type, exc)
        return {"error": str(exc)}


# ── Widget data fetchers ────────────────────────────────────────

def _widget_recent_sessions(conn: Any, params: dict) -> dict:
    limit = params.get("limit", 10)
    rows = conn.execute(
        "SELECT s.session_id, s.session_date, s.n_laps, s.best_lap_time_s, "
        "s.total_score, s.grade, d.driver_name, t.track_name "
        "FROM sessions s "
        "LEFT JOIN drivers d ON s.driver_id = d.driver_id "
        "LEFT JOIN tracks t ON s.track_id = t.track_id "
        "WHERE s.deleted_at IS NULL "
        "ORDER BY s.session_date DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return {"sessions": [dict(r) for r in rows]}


def _widget_leaderboard(conn: Any, params: dict) -> dict:
    track_id = params.get("track_id")
    if not track_id:
        return {"entries": [], "error": "track_id required"}
    rows = conn.execute(
        "SELECT d.driver_name, MIN(s.best_lap_time_s) as best_time, "
        "COUNT(s.session_id) as n_sessions "
        "FROM sessions s "
        "LEFT JOIN drivers d ON s.driver_id = d.driver_id "
        "WHERE s.track_id = ? AND s.best_lap_time_s IS NOT NULL AND s.deleted_at IS NULL "
        "GROUP BY d.driver_id "
        "ORDER BY best_time ASC",
        (track_id,),
    ).fetchall()
    return {"entries": [dict(r) for r in rows]}


def _widget_personal_bests(conn: Any, params: dict) -> dict:
    driver_id = params.get("driver_id")
    if not driver_id:
        return {"bests": [], "error": "driver_id required"}
    rows = conn.execute(
        "SELECT t.track_name, MIN(s.best_lap_time_s) as best_time, "
        "COUNT(s.session_id) as n_sessions "
        "FROM sessions s "
        "LEFT JOIN tracks t ON s.track_id = t.track_id "
        "WHERE s.driver_id = ? AND s.best_lap_time_s IS NOT NULL AND s.deleted_at IS NULL "
        "GROUP BY s.track_id "
        "ORDER BY t.track_name",
        (driver_id,),
    ).fetchall()
    return {"bests": [dict(r) for r in rows]}


def _widget_pace_chart(conn: Any, params: dict) -> dict:
    session_id = params.get("session_id")
    if not session_id:
        return {"laps": [], "error": "session_id required"}
    rows = conn.execute(
        "SELECT lap_number, lap_time_s FROM laps "
        "WHERE session_id = ? AND is_valid = 1 ORDER BY lap_number",
        (session_id,),
    ).fetchall()
    return {"laps": [{"lap": r["lap_number"], "time": r["lap_time_s"]} for r in rows]}


def _widget_score_breakdown(conn: Any, params: dict) -> dict:
    session_id = params.get("session_id")
    if not session_id:
        return {"error": "session_id required"}
    row = conn.execute(
        "SELECT pace_score, pace_max, consistency_score, consistency_max, "
        "execution_score, execution_max, robustness_score, robustness_max "
        "FROM score_details WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if not row:
        return {"error": "no score data"}
    return dict(row)


def _widget_consistency_gauge(conn: Any, params: dict) -> dict:
    driver_id = params.get("driver_id")
    if not driver_id:
        return {"error": "driver_id required"}
    row = conn.execute(
        "SELECT AVG(consistency_score / consistency_max * 100) as avg_consistency "
        "FROM score_details sd "
        "JOIN sessions s ON sd.session_id = s.session_id "
        "WHERE s.driver_id = ? AND sd.consistency_max > 0 AND s.deleted_at IS NULL",
        (driver_id,),
    ).fetchone()
    return {"consistency_pct": round(row["avg_consistency"] or 0, 1) if row else 0}


def _widget_data_health_summary(conn: Any, params: dict) -> dict:
    rows = conn.execute(
        "SELECT dh.session_id, dh.overall_score, dh.gps_quality, dh.accel_quality "
        "FROM data_health dh ORDER BY dh.created_at DESC LIMIT 10"
    ).fetchall()
    return {"health": [dict(r) for r in rows]}


# ── Layout validation ───────────────────────────────────────────

def _validate_layout(layout: list[dict]) -> list[dict]:
    """Validate and normalize widget layout."""
    if not isinstance(layout, list):
        raise ValueError("Layout must be a list")

    valid_types = {w["type"] for w in _WIDGET_REGISTRY}
    validated = []

    for i, widget in enumerate(layout):
        if not isinstance(widget, dict):
            raise ValueError(f"Widget {i} must be a dict")

        wtype = widget.get("type")
        if not wtype:
            raise ValueError(f"Widget {i} missing 'type'")

        if wtype not in valid_types:
            raise ValueError(f"Widget {i} has unknown type: {wtype}")

        # Get default size from registry
        reg = next(w for w in _WIDGET_REGISTRY if w["type"] == wtype)
        default_size = reg["default_size"]

        validated.append({
            "type": wtype,
            "x": widget.get("x", 0),
            "y": widget.get("y", i * 3),
            "w": widget.get("w", default_size["w"]),
            "h": widget.get("h", default_size["h"]),
            "params": widget.get("params", {}),
        })

    return validated


# ── Default dashboard ───────────────────────────────────────────

def get_default_layout() -> list[dict]:
    """Return a sensible default dashboard layout."""
    return [
        {"type": "recent_sessions", "x": 0, "y": 0, "w": 6, "h": 3, "params": {}},
        {"type": "data_health_summary", "x": 6, "y": 0, "w": 4, "h": 3, "params": {}},
        {"type": "leaderboard", "x": 0, "y": 3, "w": 4, "h": 4, "params": {}},
        {"type": "personal_bests", "x": 4, "y": 3, "w": 5, "h": 3, "params": {}},
    ]


# ── Inline tests ────────────────────────────────────────────────

def _run_tests() -> None:
    """Self-contained test suite for dashboard builder."""
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
            lap_time_s REAL, is_valid INTEGER DEFAULT 1, is_best INTEGER DEFAULT 0,
            UNIQUE(session_id, lap_number))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS score_details (
            session_id TEXT PRIMARY KEY,
            pace_score REAL, pace_max REAL,
            consistency_score REAL, consistency_max REAL,
            execution_score REAL, execution_max REAL,
            robustness_score REAL, robustness_max REAL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS data_health (
            session_id TEXT PRIMARY KEY,
            gps_quality REAL, accel_quality REAL,
            overall_score REAL, created_at TEXT DEFAULT (datetime('now')))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS custom_dashboards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            driver_id INTEGER, dashboard_name TEXT NOT NULL,
            layout_json TEXT NOT NULL, is_default INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')))""")
        conn.execute("INSERT INTO drivers (driver_name) VALUES ('TestDriver')")
        conn.execute("INSERT INTO tracks (track_id, track_name, lap_length_m) VALUES ('t1', 'TestTrack', 1000)")
        conn.execute("INSERT INTO sessions (session_id, csv_filename, driver_id, track_id, session_date, n_laps, best_lap_time_s, total_score, grade) VALUES ('s1', 'test.csv', 1, 't1', '2024-01-01', 10, 60.5, 85.0, 'A')")
        for i in range(1, 11):
            conn.execute("INSERT INTO laps (session_id, lap_number, lap_time_s, is_valid) VALUES ('s1', ?, ?, 1)", (i, 60.0 + i * 0.1))
        conn.execute("INSERT INTO score_details (session_id, pace_score, pace_max, consistency_score, consistency_max, execution_score, execution_max, robustness_score, robustness_max) VALUES ('s1', 20, 25, 18, 25, 22, 25, 20, 25)")
        conn.commit()
        return conn

    # Test 1: widget registry
    def t_registry():
        widgets = get_widget_registry()
        assert len(widgets) == 12
        types = {w["type"] for w in widgets}
        assert "pace_chart" in types
        assert "gg_diagram" in types
        assert "leaderboard" in types
        for w in widgets:
            assert "name" in w
            assert "category" in w
            assert "default_size" in w

    _test("registry", t_registry)

    # Test 2: create dashboard
    def t_create():
        conn = _make_db()
        layout = [
            {"type": "pace_chart", "x": 0, "y": 0, "params": {"session_id": "s1"}},
            {"type": "recent_sessions", "x": 6, "y": 0},
        ]
        db = create_dashboard(conn, "My Dashboard", layout, driver_id=1)
        assert db["id"] is not None
        assert db["dashboard_name"] == "My Dashboard"
        assert len(db["layout"]) == 2
        conn.close()

    _test("create", t_create)

    # Test 3: get dashboards
    def t_get_list():
        conn = _make_db()
        create_dashboard(conn, "Dashboard 1", [{"type": "recent_sessions"}], driver_id=1)
        create_dashboard(conn, "Dashboard 2", [{"type": "leaderboard", "params": {"track_id": "t1"}}], driver_id=1)
        dbs = get_dashboards(conn, driver_id=1)
        assert len(dbs) == 2
        conn.close()

    _test("get_list", t_get_list)

    # Test 4: update dashboard
    def t_update():
        conn = _make_db()
        db = create_dashboard(conn, "Original", [{"type": "recent_sessions"}])
        updated = update_dashboard(conn, db["id"], name="Updated", is_default=True)
        assert updated["dashboard_name"] == "Updated"
        assert updated["is_default"] is True
        conn.close()

    _test("update", t_update)

    # Test 5: delete dashboard
    def t_delete():
        conn = _make_db()
        db = create_dashboard(conn, "To Delete", [{"type": "recent_sessions"}])
        assert delete_dashboard(conn, db["id"]) is True
        assert get_dashboard(conn, db["id"]) is None
        assert delete_dashboard(conn, 999) is False
        conn.close()

    _test("delete", t_delete)

    # Test 6: layout validation
    def t_validation():
        # Bad type
        try:
            _validate_layout([{"type": "nonexistent_widget"}])
            assert False, "Should raise ValueError"
        except ValueError:
            pass
        # Not a list
        try:
            _validate_layout("not a list")
            assert False, "Should raise ValueError"
        except ValueError:
            pass
        # Missing type
        try:
            _validate_layout([{"x": 0}])
            assert False, "Should raise ValueError"
        except ValueError:
            pass
        # Valid layout with defaults
        validated = _validate_layout([{"type": "pace_chart"}])
        assert validated[0]["w"] == 6  # default width
        assert validated[0]["h"] == 3  # default height

    _test("validation", t_validation)

    # Test 7: widget data
    def t_widget_data():
        conn = _make_db()
        # Recent sessions
        data = get_widget_data(conn, "recent_sessions", {})
        assert "sessions" in data
        assert len(data["sessions"]) > 0
        # Pace chart
        data = get_widget_data(conn, "pace_chart", {"session_id": "s1"})
        assert "laps" in data
        assert len(data["laps"]) == 10
        # Score breakdown
        data = get_widget_data(conn, "score_breakdown", {"session_id": "s1"})
        assert "pace_score" in data
        # Unknown type
        data = get_widget_data(conn, "nonexistent", {})
        assert "error" in data
        # Placeholder types
        data = get_widget_data(conn, "gg_diagram", {"session_id": "s1"})
        assert data["status"] == "placeholder"
        conn.close()

    _test("widget_data", t_widget_data)

    # Test 8: default layout
    def t_default_layout():
        layout = get_default_layout()
        assert len(layout) == 4
        validated = _validate_layout(layout)
        assert len(validated) == 4

    _test("default_layout", t_default_layout)

    # Test 9: empty name
    def t_empty_name():
        conn = _make_db()
        try:
            create_dashboard(conn, "", [{"type": "recent_sessions"}])
            assert False, "Should raise ValueError"
        except ValueError:
            pass
        conn.close()

    _test("empty_name", t_empty_name)

    total = len(passed) + len(failed)
    status_str = "PASS" if not failed else "FAIL"
    print(f"\nDashboard Builder Tests: {len(passed)}/{total} passed [{status_str}]")
    for n in passed:
        print(f"  OK {n}")
    for n, trace in failed:
        print(f"  FAIL {n}\n{trace}")
    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


if __name__ == "__main__":
    _run_tests()
