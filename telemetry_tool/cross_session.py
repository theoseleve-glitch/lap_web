"""
cross_session.py
----------------
Cross-session analysis: compare current session to historical data
on the same track, compute weekend summaries, and calculate
historical percentile rankings.

Design principles:
- Pure functions — take DB connection + session data, return dicts.
- No Flask dependency — usable from pipeline, CLI, or web routes.
- Graceful with missing data — returns partial results.
"""

from __future__ import annotations

import logging
import math
import sqlite3
from typing import Any, Optional

from db import queries as Q

logger = logging.getLogger(__name__)


# ── Cross-session comparison ─────────────────────────────────────

def find_comparable_sessions(
    conn: sqlite3.Connection,
    session_id: str,
    track_id: str,
    *,
    limit: int = 20,
    session_type: Optional[str] = None,
) -> list[dict]:
    """
    Find historical sessions on the same track for comparison.

    Returns list of session dicts ordered by date (most recent first),
    excluding the current session.
    """
    if session_type:
        rows = conn.execute(
            Q.SELECT_COMPARABLE_SESSIONS_TYPED,
            {"track_id": track_id, "session_id": session_id,
             "session_type": session_type, "limit": limit},
        ).fetchall()
    else:
        rows = conn.execute(
            Q.SELECT_COMPARABLE_SESSIONS,
            {"track_id": track_id, "session_id": session_id, "limit": limit},
        ).fetchall()
    return [dict(r) for r in rows]


def compute_historical_percentile(
    conn: sqlite3.Connection,
    track_id: str,
    best_time_s: float,
    *,
    session_type: Optional[str] = None,
) -> Optional[float]:
    """
    Compute where *best_time_s* ranks among all sessions on this track.

    Returns a percentile (0–100) where 100 = fastest ever.
    Returns None if no historical data.
    """
    if session_type:
        rows = conn.execute(
            Q.SELECT_HISTORICAL_BEST_TIMES_TYPED,
            {"track_id": track_id, "session_type": session_type},
        ).fetchall()
    else:
        rows = conn.execute(
            Q.SELECT_HISTORICAL_BEST_TIMES,
            {"track_id": track_id},
        ).fetchall()

    times = [r["best_lap_time_s"] for r in rows
             if r["best_lap_time_s"] is not None]
    if not times:
        return None

    # Count how many times are slower (higher) than ours.
    n_slower = sum(1 for t in times if t > best_time_s)
    percentile = (n_slower / len(times)) * 100
    return round(percentile, 1)


def compute_improvement_vs_last(
    conn: sqlite3.Connection,
    track_id: str,
    driver_id: int,
    current_best_s: float,
    current_session_id: str,
) -> Optional[dict]:
    """
    Compare current session to the driver's most recent session on
    the same track.

    Returns dict with delta_s, delta_pct, previous_session_id,
    or None if no previous session.
    """
    rows = conn.execute(
        """SELECT session_id, best_lap_time_s, session_date
           FROM sessions
           WHERE track_id = :track_id
             AND driver_id = :driver_id
             AND session_id != :session_id
             AND best_lap_time_s IS NOT NULL
             AND deleted_at IS NULL
           ORDER BY session_date DESC
           LIMIT 1""",
        {"track_id": track_id, "driver_id": driver_id,
         "session_id": current_session_id},
    ).fetchall()

    if not rows:
        return None

    prev = dict(rows[0])
    prev_time = prev["best_lap_time_s"]
    delta_s = current_best_s - prev_time
    delta_pct = (delta_s / prev_time) * 100 if prev_time > 0 else 0.0

    return {
        "previous_session_id": prev["session_id"],
        "previous_best_s": prev_time,
        "delta_s": round(delta_s, 3),
        "delta_pct": round(delta_pct, 2),
        "improved": delta_s < 0,
    }


def compute_cross_session_metrics(
    conn: sqlite3.Connection,
    session_id: str,
    track_id: str,
    driver_id: int,
    best_time_s: float,
    *,
    session_type: Optional[str] = None,
) -> dict[str, Any]:
    """
    Full cross-session analysis for a session.

    Returns dict with:
        historical_percentile, improvement, comparable_sessions,
        track_best_s, track_best_holder.
    """
    result: dict[str, Any] = {}

    # Historical percentile.
    result["historical_percentile"] = compute_historical_percentile(
        conn, track_id, best_time_s, session_type=session_type,
    )

    # Improvement vs last session.
    result["improvement"] = compute_improvement_vs_last(
        conn, track_id, driver_id, best_time_s, session_id,
    )

    # Track best.
    times_rows = conn.execute(
        Q.SELECT_HISTORICAL_BEST_TIMES,
        {"track_id": track_id},
    ).fetchall()
    if times_rows:
        best = dict(times_rows[0])
        result["track_best_s"] = best["best_lap_time_s"]
        result["track_best_holder"] = best["driver_name"]
        result["track_best_session_id"] = best["session_id"]
    else:
        result["track_best_s"] = None

    # Comparable sessions count.
    comps = find_comparable_sessions(
        conn, session_id, track_id, session_type=session_type,
    )
    result["comparable_count"] = len(comps)

    return result


# ── Weekend summary ──────────────────────────────────────────────

def compute_weekend_summary(
    conn: sqlite3.Connection,
    weekend_id: int,
) -> dict[str, Any]:
    """
    Compute aggregate statistics for a weekend.

    Returns dict with session count, best time, score progression,
    total laps, pace improvement from first to last session.
    """
    rows = conn.execute(
        Q.SELECT_WEEKEND_SESSIONS,
        {"weekend_id": weekend_id},
    ).fetchall()
    sessions = [dict(r) for r in rows]

    if not sessions:
        return {
            "session_count": 0,
            "total_laps": 0,
            "sessions": [],
            "best_time_s": None,
            "worst_time_s": None,
            "mean_time_s": None,
            "best_score": None,
            "mean_score": None,
            "score_progression": [],
            "pace_delta_s": None,
            "pace_improved": None,
        }

    valid_times = [
        s["best_lap_time_s"] for s in sessions
        if s.get("best_lap_time_s") is not None
    ]
    valid_scores = [
        s["total_score"] for s in sessions
        if s.get("total_score") is not None
    ]

    summary: dict[str, Any] = {
        "session_count": len(sessions),
        "total_laps": sum(s.get("n_laps") or 0 for s in sessions),
        "sessions": sessions,
    }

    if valid_times:
        summary["best_time_s"] = min(valid_times)
        summary["worst_time_s"] = max(valid_times)
        summary["mean_time_s"] = sum(valid_times) / len(valid_times)

    if valid_scores:
        summary["best_score"] = max(valid_scores)
        summary["mean_score"] = sum(valid_scores) / len(valid_scores)
        summary["score_progression"] = valid_scores

    # Pace improvement: compare first and last session.
    first_time = sessions[0].get("best_lap_time_s")
    last_time = sessions[-1].get("best_lap_time_s")
    if first_time and last_time and len(sessions) > 1:
        summary["pace_delta_s"] = round(last_time - first_time, 3)
        summary["pace_improved"] = last_time < first_time
    else:
        summary["pace_delta_s"] = None
        summary["pace_improved"] = None

    return summary


def compute_weekend_insights(
    conn: sqlite3.Connection,
    weekend_id: int,
) -> dict[str, Any]:
    """
    Compute enhanced insights for a weekend: consistency breakdown per session,
    lap-time heatmap data, and improvement summary.
    """
    import numpy as np

    # Get ordered session IDs.
    ws_rows = conn.execute(
        Q.SELECT_WEEKEND_SESSIONS,
        {"weekend_id": weekend_id},
    ).fetchall()

    consistency_breakdown: list[dict] = []
    heatmap_data: list[dict] = []
    avg_times: list[float] = []

    for ws_row in ws_rows:
        ws = dict(ws_row)
        sid = ws["session_id"]
        laps = conn.execute(
            "SELECT lap_number, lap_time_s FROM laps "
            "WHERE session_id = ? AND is_valid = 1 ORDER BY lap_number",
            (sid,),
        ).fetchall()

        times = [l["lap_time_s"] for l in laps if l["lap_time_s"]]
        if not times:
            consistency_breakdown.append({
                "session_id": sid,
                "session_date": ws.get("session_date"),
                "driver_name": ws.get("driver_name"),
                "n_laps": 0,
                "mean_time": None,
                "cv_pct": None,
                "best": None,
                "worst": None,
            })
            continue

        mean_t = float(np.mean(times))
        std_t = float(np.std(times))
        cv_pct = (std_t / mean_t * 100) if mean_t > 0 else 0
        best_t = min(times)

        consistency_breakdown.append({
            "session_id": sid,
            "session_date": ws.get("session_date"),
            "driver_name": ws.get("driver_name"),
            "n_laps": len(times),
            "mean_time": round(mean_t, 3),
            "cv_pct": round(cv_pct, 2),
            "best": round(best_t, 3),
            "worst": round(max(times), 3),
        })

        # Heatmap row: delta from session best.
        row = []
        for l in laps:
            if l["lap_time_s"]:
                row.append(round(l["lap_time_s"] - best_t, 3))
            else:
                row.append(None)
        heatmap_data.append({"session_id": sid, "deltas": row})

        avg_times.append(mean_t)

    # Improvement summary.
    improvement_pct = None
    if len(avg_times) >= 2:
        first_avg = avg_times[0]
        last_avg = avg_times[-1]
        if first_avg > 0:
            improvement_pct = round(((first_avg - last_avg) / first_avg) * 100, 2)

    # Best / worst session by average time.
    best_session_idx = None
    worst_session_idx = None
    if avg_times:
        best_session_idx = int(np.argmin(avg_times))
        worst_session_idx = int(np.argmax(avg_times))

    return {
        "consistency_breakdown": consistency_breakdown,
        "heatmap_data": heatmap_data,
        "improvement_pct": improvement_pct,
        "avg_times": [round(t, 3) for t in avg_times],
        "best_session_idx": best_session_idx,
        "worst_session_idx": worst_session_idx,
    }


# ── Condition-adjusted scoring enrichment ────────────────────────

def enrich_with_historical(
    conn: sqlite3.Connection,
    session_id: str,
    track_id: str,
    driver_id: int,
    score_result: dict[str, Any],
) -> dict[str, Any]:
    """
    Enrich a score_result dict with historical context.

    Adds:
        historical_percentile: where this score ranks among all sessions
        improvement_vs_last: delta from previous session
        conditions_adjusted_score: score adjusted for track conditions

    Returns the enriched dict (mutated in place for convenience).
    """
    best_s = None
    # Try to get best time from the session.
    sess = conn.execute(
        Q.SELECT_SESSION_BY_ID, {"session_id": session_id},
    ).fetchone()
    if sess:
        best_s = sess["best_lap_time_s"]

    if best_s and track_id:
        cross = compute_cross_session_metrics(
            conn, session_id, track_id, driver_id, best_s,
        )
        score_result["historical_percentile"] = cross.get("historical_percentile")
        score_result["improvement"] = cross.get("improvement")
        score_result["track_best_s"] = cross.get("track_best_s")
    else:
        score_result["historical_percentile"] = None
        score_result["improvement"] = None

    # Historical score percentile.
    total_score = score_result.get("total_score")
    if total_score is not None and track_id:
        all_scores = conn.execute(
            """SELECT total_score FROM sessions
               WHERE track_id = :track_id
                 AND total_score IS NOT NULL
                 AND deleted_at IS NULL""",
            {"track_id": track_id},
        ).fetchall()
        scores = [r[0] for r in all_scores if r[0] is not None]
        if scores:
            n_lower = sum(1 for s in scores if s < total_score)
            score_result["score_percentile"] = round(
                (n_lower / len(scores)) * 100, 1,
            )

    return score_result


# ── Inline tests ─────────────────────────────────────────────────

def _run_tests() -> None:
    """Self-contained test suite."""
    import tempfile
    import traceback as tb
    from pathlib import Path

    passed: list[str] = []
    failed: list[tuple[str, str]] = []

    def _test(name, fn):
        try:
            fn()
            passed.append(name)
        except Exception:
            failed.append((name, tb.format_exc()))

    def _make_db():
        """Create a temp DB with schema."""
        import sqlite3 as s3

        from db.migrate import ensure_schema
        tmp = tempfile.mktemp(suffix=".db")
        conn = s3.connect(tmp)
        conn.row_factory = s3.Row
        conn.execute("PRAGMA journal_mode=DELETE;")  # avoid WAL lock on Windows
        conn.execute("PRAGMA foreign_keys=ON;")
        ensure_schema(conn)
        return conn, tmp

    def _cleanup(conn, tmp):
        """Close conn and remove temp file (best-effort on Windows)."""
        try:
            conn.close()
        except Exception:
            pass
        try:
            Path(tmp).unlink(missing_ok=True)
        except PermissionError:
            pass  # Windows WAL lock; temp dir will clean up

    # Test 1: comparable sessions on empty DB
    def t_comparable_empty():
        conn, tmp = _make_db()
        try:
            result = find_comparable_sessions(conn, "s1", "t1")
            assert result == []
        finally:
            _cleanup(conn, tmp)

    _test("comparable_empty", t_comparable_empty)

    # Test 2: historical percentile
    def t_percentile_empty():
        conn, tmp = _make_db()
        try:
            p = compute_historical_percentile(conn, "t1", 60.0)
            assert p is None
        finally:
            _cleanup(conn, tmp)

    _test("percentile_empty", t_percentile_empty)

    # Test 3: weekend summary empty
    def t_weekend_empty():
        conn, tmp = _make_db()
        try:
            s = compute_weekend_summary(conn, 999)
            assert s["session_count"] == 0
        finally:
            _cleanup(conn, tmp)

    _test("weekend_summary_empty", t_weekend_empty)

    # Test 4: cross-session metrics with data
    def t_cross_session():
        conn, tmp = _make_db()
        try:
            # Insert test data.
            conn.execute(
                "INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'A')"
            )
            conn.execute(
                "INSERT INTO tracks (track_id, track_name, lap_length_m) "
                "VALUES ('t1', 'Test', 1000)"
            )
            for i, (sid, best) in enumerate([
                ("s1", 60.0), ("s2", 59.5), ("s3", 61.0),
            ]):
                conn.execute(
                    "INSERT INTO sessions "
                    "(session_id, csv_filename, driver_id, track_id, "
                    " session_date, best_lap_time_s, total_score) "
                    "VALUES (?, 'x.csv', 1, 't1', ?, ?, ?)",
                    (sid, f"2024-01-0{i+1}", best, 70 + i * 5),
                )
            conn.commit()

            metrics = compute_cross_session_metrics(
                conn, "s2", "t1", 1, 59.5,
            )
            # s2 is the fastest -> percentile should be high
            assert metrics["historical_percentile"] is not None
            # There should be 2 comparable sessions (s1, s3)
            assert metrics["comparable_count"] == 2
            assert metrics["track_best_s"] == 59.5
        finally:
            _cleanup(conn, tmp)

    _test("cross_session_metrics", t_cross_session)

    # Test 5: improvement vs last
    def t_improvement():
        conn, tmp = _make_db()
        try:
            conn.execute(
                "INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'A')"
            )
            conn.execute(
                "INSERT INTO tracks (track_id, track_name, lap_length_m) "
                "VALUES ('t1', 'Test', 1000)"
            )
            conn.execute(
                "INSERT INTO sessions "
                "(session_id, csv_filename, driver_id, track_id, "
                " session_date, best_lap_time_s) "
                "VALUES ('s1', 'x.csv', 1, 't1', '2024-01-01', 61.0)"
            )
            conn.execute(
                "INSERT INTO sessions "
                "(session_id, csv_filename, driver_id, track_id, "
                " session_date, best_lap_time_s) "
                "VALUES ('s2', 'x.csv', 1, 't1', '2024-01-02', 59.5)"
            )
            conn.commit()

            imp = compute_improvement_vs_last(conn, "t1", 1, 59.5, "s2")
            assert imp is not None
            assert imp["improved"] is True
            assert imp["delta_s"] < 0
            assert imp["previous_best_s"] == 61.0
        finally:
            _cleanup(conn, tmp)

    _test("improvement_vs_last", t_improvement)

    # Test 6: type-filtered comparable sessions
    def t_type_filter():
        conn, tmp = _make_db()
        try:
            conn.execute(
                "INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'A')"
            )
            conn.execute(
                "INSERT INTO tracks (track_id, track_name, lap_length_m) "
                "VALUES ('t1', 'Test', 1000)"
            )
            # Insert sessions with different types
            for sid, stype, best in [
                ("s1", "practice", 60.0),
                ("s2", "qualifying", 58.0),
                ("s3", "practice", 59.5),
                ("s4", "race", 61.0),
            ]:
                conn.execute(
                    "INSERT INTO sessions "
                    "(session_id, csv_filename, driver_id, track_id, "
                    " session_date, best_lap_time_s, session_type) "
                    "VALUES (?, 'x.csv', 1, 't1', '2024-01-01', ?, ?)",
                    (sid, best, stype),
                )
            conn.commit()

            # Filter by practice: should only get s1, s3 (excluding current)
            practice_comps = find_comparable_sessions(
                conn, "s1", "t1", session_type="practice",
            )
            practice_ids = {c["session_id"] for c in practice_comps}
            assert "s3" in practice_ids, f"Expected s3, got {practice_ids}"
            assert "s2" not in practice_ids, f"s2 should be filtered out"
            assert "s4" not in practice_ids, f"s4 should be filtered out"

            # Type-filtered percentile
            pct = compute_historical_percentile(
                conn, "t1", 59.5, session_type="practice",
            )
            assert pct is not None
        finally:
            _cleanup(conn, tmp)

    _test("type_filtered_sessions", t_type_filter)

    total = len(passed) + len(failed)
    status = "PASS" if not failed else "FAIL"
    print(f"\nCross-Session Tests: {len(passed)}/{total} passed [{status}]")
    for n in passed:
        print(f"  OK {n}")
    for n, trace in failed:
        print(f"  FAIL {n}\n{trace}")
    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


if __name__ == "__main__":
    _run_tests()
