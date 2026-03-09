"""Session repository — CRUD for the sessions table."""

from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path
from typing import Any, Optional

from db import queries as Q
from web.repos._helpers import _safe_float, _json_dumps


import logging

logger = logging.getLogger(__name__)


def upsert_session(
    conn: sqlite3.Connection,
    summary: dict[str, Any],
    driver_id: int,
) -> str:
    """Persist a pipeline summary to the sessions table."""
    meta = summary.get("session_meta", {})
    score = summary.get("score_result") or {}
    ctx = summary.get("session_context")

    session_id = ""
    if ctx and hasattr(ctx, "session_id"):
        session_id = ctx.session_id
    elif meta.get("session_id"):
        session_id = meta["session_id"]
    else:
        # Fallback: generate from CSV filename + timestamp.
        import datetime
        csv_name = str(summary.get("csv_path", "unknown"))
        session_id = f"{datetime.datetime.now():%Y-%m-%d_%H%M%S}"

    # Compute basic lap stats — EXCLUDING flagged laps (incomplete,
    # invalid, anomalous, deviated) so best/mean reflect valid data only.
    lap_times = summary.get("lap_times") or []
    resampled = summary.get("resampled_laps") or {}
    sorted_lap_keys = sorted(resampled.keys()) if resampled else list(range(len(lap_times)))

    # Gather all exclusion sets from pipeline analysis.
    _excluded: set = set()
    for _key in ("incomplete_lap_analysis", "invalid_lap_analysis",
                 "anomalous_lap_analysis", "line_deviation_analysis"):
        _analysis = summary.get(_key) or {}
        for _sub in ("incomplete_laps", "invalid_laps", "flagged_laps",
                     "dist_flagged", "time_flagged", "deviated_laps"):
            _s = _analysis.get(_sub)
            if _s:
                _excluded.update(_s)
    # Also check trim_report for outlaps/inlaps.
    _trim = summary.get("trim_report") or {}
    _outlap_a = _trim.get("outlap_analysis") or {}
    for _sub in ("outlap_numbers", "inlap_numbers", "flagged_only"):
        _s = _outlap_a.get(_sub)
        if _s:
            _excluded.update(_s)

    # Exclude the confirmed joker lap from stats.
    _joker_lap = summary.get("joker_lap_number")
    if _joker_lap is not None:
        _excluded.add(_joker_lap)

    valid_times = []
    for i, t in enumerate(lap_times):
        if not t or not math.isfinite(t) or t <= 0:
            continue
        lap_key = sorted_lap_keys[i] if i < len(sorted_lap_keys) else i
        if lap_key in _excluded:
            continue
        valid_times.append(t)

    n_laps = len(valid_times)
    best_s = min(valid_times) if valid_times else None
    mean_s = sum(valid_times) / n_laps if n_laps > 0 else None

    # Weather.
    weather_json = None
    weather = meta.get("weather")
    if weather is not None:
        if hasattr(weather, "__dict__"):
            weather_json = _json_dumps(vars(weather))
        else:
            weather_json = _json_dumps(weather)

    # HTML report path.
    html_path = summary.get("html_path")
    if html_path:
        html_path = str(html_path)

    theo_metrics = summary.get("theoretical_metrics") or {}

    # Channel inventory from column discovery.
    channel_discovery = summary.get("channel_discovery")
    channel_inventory_json = json.dumps(channel_discovery) if channel_discovery else None

    # Derive session_date: prefer telemetry start time > meta date > session_id prefix
    _telemetry_start = summary.get("telemetry_start_time")
    if _telemetry_start and isinstance(_telemetry_start, str) and len(_telemetry_start) >= 10:
        _session_date = _telemetry_start[:10]
    else:
        _session_date = meta.get("session_date") or meta.get("date") or session_id[:10]

    # Extract pipeline version info from pipeline status if available.
    _pipeline_info = summary.get("pipeline") or {}
    _pvh = _pipeline_info.get("pipeline_version", "unknown")
    _mv = _pipeline_info.get("model_version", "none")

    conn.execute(Q.INSERT_SESSION, {
        "session_id":        session_id,
        "csv_filename":      Path(str(summary.get("csv_path", ""))).name,
        "driver_id":         driver_id,
        "track_id":          summary.get("track_id") or "unknown_track",
        "session_type":      meta.get("session_type", "practice"),
        "track_state":       meta.get("track_state", "dry"),
        "session_date":      _session_date,
        "n_laps":            n_laps,
        "best_lap_time_s":   _safe_float(best_s),
        "mean_lap_time_s":   _safe_float(mean_s),
        "total_score":       _safe_float(score.get("total_score")),
        "grade":             score.get("grade"),
        "weather_json":      weather_json,
        "notes":             meta.get("notes"),
        "html_report_path":  html_path,
        "simulation_method": theo_metrics.get("simulation_method"),
        "joker_lap_number":  _joker_lap,
        "display_name":      meta.get("display_name") or Path(str(summary.get("csv_path", ""))).stem,
        "source_filename":   meta.get("source_filename") or Path(str(summary.get("csv_path", ""))).name,
        "source_path":       str(summary.get("csv_path", "")),
        "kart_id":           meta.get("kart_id"),
        "channel_inventory": channel_inventory_json,
        "data_tier":         summary.get("data_tier", 1),
        "available_channels": json.dumps(summary.get("available_channels", [])),
        "source_format":     summary.get("source_format", "racechrono"),
        "source_metadata":   json.dumps(summary.get("source_metadata", {})),
        "pipeline_version_hash": _pvh,
        "model_version":     _mv,
    })
    return session_id


def get_sessions(
    conn: sqlite3.Connection,
    limit: int = 25,
    offset: int = 0,
    filters: Optional[dict] = None,
    sort_by: Optional[str] = None,
    sort_dir: str = "desc",
) -> list[dict]:
    """List sessions with optional filtering and sorting.

    Supported filter keys:
        driver, track, session_type, track_state, search,
        date_from, date_to, min_score, max_score
    """
    if not filters:
        rows = conn.execute(
            Q.SELECT_SESSIONS, {"limit": limit, "offset": offset}
        ).fetchall()
        return [dict(r) for r in rows]

    # Build dynamic WHERE clauses
    clauses = []
    params: dict = {"limit": limit, "offset": offset}

    if filters.get("driver"):
        clauses.append("d.driver_name = :f_driver")
        params["f_driver"] = filters["driver"]
    if filters.get("track"):
        clauses.append("t.track_name = :f_track")
        params["f_track"] = filters["track"]
    if filters.get("session_type"):
        clauses.append("s.session_type = :f_type")
        params["f_type"] = filters["session_type"]
    if filters.get("track_state"):
        clauses.append("s.track_state = :f_state")
        params["f_state"] = filters["track_state"]
    if filters.get("date_from"):
        clauses.append("s.session_date >= :f_date_from")
        params["f_date_from"] = filters["date_from"]
    if filters.get("date_to"):
        clauses.append("s.session_date <= :f_date_to")
        params["f_date_to"] = filters["date_to"]
    if filters.get("min_score") is not None:
        clauses.append("s.total_score >= :f_min_score")
        params["f_min_score"] = filters["min_score"]
    if filters.get("max_score") is not None:
        clauses.append("s.total_score <= :f_max_score")
        params["f_max_score"] = filters["max_score"]
    if filters.get("search"):
        clauses.append(
            "(d.driver_name LIKE :f_search OR t.track_name LIKE :f_search "
            "OR s.csv_filename LIKE :f_search)"
        )
        params["f_search"] = f"%{filters['search']}%"
    if filters.get("favorite"):
        clauses.append("s.is_favorite = 1")
    if "archived" in (filters or {}):
        if filters["archived"]:
            clauses.append("COALESCE(s.archived, 0) = 1")
        else:
            clauses.append("COALESCE(s.archived, 0) = 0")

    # Always exclude soft-deleted sessions
    clauses.append("s.deleted_at IS NULL")
    where = " AND ".join(clauses)

    # Validate sort column to prevent injection
    _SORT_COLUMNS = {
        "date": "s.session_date",
        "track_name": "t.track_name",
        "driver_name": "d.driver_name",
        "session_type": "s.session_type",
        "track_state": "s.track_state",
        "lap_count": "s.n_laps",
        "best_lap_time": "s.best_lap_time_s",
        "mean_lap_time": "s.mean_lap_time_s",
        "total_score": "s.total_score",
        "grade": "s.grade",
        "favorite": "s.is_favorite",
    }
    order_col = _SORT_COLUMNS.get(sort_by, "s.session_date") if sort_by else "s.session_date"
    order_dir = "ASC" if sort_dir == "asc" else "DESC"

    sql = f"""
        SELECT s.*, d.driver_name, t.track_name, k.kart_name
        FROM sessions s
        JOIN drivers d ON s.driver_id = d.driver_id
        LEFT JOIN tracks t ON s.track_id = t.track_id
        LEFT JOIN karts k ON s.kart_id = k.kart_id
        WHERE {where}
        ORDER BY {order_col} {order_dir}
        LIMIT :limit OFFSET :offset;
    """
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def count_sessions_filtered(
    conn: sqlite3.Connection,
    filters: Optional[dict] = None,
) -> int:
    """Count sessions matching filters."""
    if not filters:
        return count_sessions(conn)

    clauses = []
    params: dict = {}

    if filters.get("driver"):
        clauses.append("d.driver_name = :f_driver")
        params["f_driver"] = filters["driver"]
    if filters.get("track"):
        clauses.append("t.track_name = :f_track")
        params["f_track"] = filters["track"]
    if filters.get("session_type"):
        clauses.append("s.session_type = :f_type")
        params["f_type"] = filters["session_type"]
    if filters.get("track_state"):
        clauses.append("s.track_state = :f_state")
        params["f_state"] = filters["track_state"]
    if filters.get("date_from"):
        clauses.append("s.session_date >= :f_date_from")
        params["f_date_from"] = filters["date_from"]
    if filters.get("date_to"):
        clauses.append("s.session_date <= :f_date_to")
        params["f_date_to"] = filters["date_to"]
    if filters.get("min_score") is not None:
        clauses.append("s.total_score >= :f_min_score")
        params["f_min_score"] = filters["min_score"]
    if filters.get("max_score") is not None:
        clauses.append("s.total_score <= :f_max_score")
        params["f_max_score"] = filters["max_score"]
    if filters.get("search"):
        clauses.append(
            "(d.driver_name LIKE :f_search OR t.track_name LIKE :f_search "
            "OR s.csv_filename LIKE :f_search)"
        )
        params["f_search"] = f"%{filters['search']}%"
    if "archived" in (filters or {}):
        if filters["archived"]:
            clauses.append("COALESCE(s.archived, 0) = 1")
        else:
            clauses.append("COALESCE(s.archived, 0) = 0")

    # Always exclude soft-deleted sessions
    clauses.append("s.deleted_at IS NULL")
    where = " AND ".join(clauses)
    sql = f"""
        SELECT COUNT(*) FROM sessions s
        JOIN drivers d ON s.driver_id = d.driver_id
        LEFT JOIN tracks t ON s.track_id = t.track_id
        LEFT JOIN karts k ON s.kart_id = k.kart_id
        WHERE {where};
    """
    row = conn.execute(sql, params).fetchone()
    if not row:
        return 0
    # Support both tuple-style (SQLite) and dict-style (PG RealDictCursor)
    if isinstance(row, dict):
        return row.get("count", 0) or 0
    return row[0]


def get_session_by_id(
    conn: sqlite3.Connection,
    session_id: str,
) -> Optional[dict]:
    row = conn.execute(
        Q.SELECT_SESSION_BY_ID, {"session_id": session_id}
    ).fetchone()
    return dict(row) if row else None


def update_session_field(
    conn: sqlite3.Connection,
    session_id: str,
    field_name: str,
    value: Any,
) -> None:
    """Update a single editable field on a session."""
    allowed = {
        "session_date", "driver_id", "track_id",
        "session_type", "track_state", "notes",
        "display_name", "kart_id", "is_favorite",
    }
    if field_name not in allowed:
        raise ValueError(f"Field {field_name!r} not editable on sessions.")
    # driver_id / kart_id should be int; track_id stays as text.
    if field_name in ("driver_id", "kart_id") and value is not None:
        value = int(value)
    sql = f"UPDATE sessions SET {field_name} = :value WHERE session_id = :session_id"
    conn.execute(sql, {"session_id": session_id, "value": value or None})


def count_sessions(conn: sqlite3.Connection) -> int:
    row = conn.execute(Q.COUNT_SESSIONS).fetchone()
    if not row:
        return 0
    # Support both tuple-style (SQLite) and dict-style (PostgreSQL RealDictCursor)
    if isinstance(row, dict):
        return row.get("count", 0) or 0
    return row[0]


def soft_delete_session(conn: sqlite3.Connection, session_id: str) -> bool:
    """Mark a session as soft-deleted. Returns True if a row was updated."""
    result = conn.execute(
        "UPDATE sessions SET deleted_at = datetime('now') "
        "WHERE session_id = :session_id AND deleted_at IS NULL",
        {"session_id": session_id},
    )
    return result.rowcount > 0


def restore_session(conn: sqlite3.Connection, session_id: str) -> bool:
    """Restore a soft-deleted session. Returns True if a row was updated."""
    result = conn.execute(
        "UPDATE sessions SET deleted_at = NULL "
        "WHERE session_id = :session_id AND deleted_at IS NOT NULL",
        {"session_id": session_id},
    )
    return result.rowcount > 0


def purge_deleted_sessions(conn: sqlite3.Connection, retention_days: int = 30) -> int:
    """Permanently delete sessions that were soft-deleted more than retention_days ago.

    Returns the number of sessions purged.
    """
    # Find sessions to purge
    rows = conn.execute(
        "SELECT session_id FROM sessions "
        "WHERE deleted_at IS NOT NULL "
        "AND deleted_at < datetime('now', :interval)",
        {"interval": f"-{retention_days} days"},
    ).fetchall()

    if not rows:
        return 0

    purged = 0
    for row in rows:
        sid = row["session_id"] if isinstance(row, dict) else row[0]
        # Delete related data first (same tables as hard delete)
        for table in (
            "laps", "scores", "score_details", "features",
            "resampled_data", "corner_analysis", "gps_traces",
            "gg_data", "speed_traces", "session_tags",
            "session_annotations", "corner_metrics",
            "consistency_metrics", "condition_markers",
            "session_weather", "driving_style_features",
            "data_health", "weekend_sessions",
        ):
            try:
                conn.execute(
                    f"DELETE FROM {table} WHERE session_id = :sid",
                    {"sid": sid},
                )
            except Exception:
                pass  # Table may not exist in older schemas
        conn.execute(
            "DELETE FROM sessions WHERE session_id = :sid",
            {"sid": sid},
        )
        purged += 1

    return purged


def get_dashboard_stats(conn: sqlite3.Connection) -> dict:
    row = conn.execute(Q.DASHBOARD_STATS).fetchone()
    return dict(row) if row else {}
