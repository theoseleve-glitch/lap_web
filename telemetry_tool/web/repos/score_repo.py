"""Score/corner repository — score details and corner metrics."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Optional

from db import queries as Q
from web.repos._helpers import _safe_float, _json_dumps

import logging

logger = logging.getLogger(__name__)


def insert_score_details(
    conn: sqlite3.Connection,
    session_id: str,
    summary: dict[str, Any],
) -> None:
    score = summary.get("score_result")
    if not score:
        return

    subs = score.get("sub_scores", {})

    def _sub(key: str, field: str):
        return _safe_float(subs.get(key, {}).get(field))

    # Adaptive weighting can push individual sub-scores above 25 (the
    # original static max) when categories are suppressed and their
    # weight is redistributed.  Scores always sum to <= 100.
    # No clamping needed — the DB constraints (migration 039) allow up
    # to 50 per category.

    conn.execute(Q.INSERT_SCORE_DETAILS, {
        "session_id":        session_id,
        "pace_score":        _sub("pace", "score"),
        "pace_max":          _sub("pace", "max"),
        "consistency_score": _sub("consistency", "score"),
        "consistency_max":   _sub("consistency", "max"),
        "execution_score":   _sub("execution", "score"),
        "execution_max":     _sub("execution", "max"),
        "robustness_score":  _sub("robustness", "score"),
        "robustness_max":    _sub("robustness", "max"),
        "strengths_json":    _json_dumps(score.get("strengths")),
        "weaknesses_json":   _json_dumps(score.get("weaknesses")),
        "adaptation_score":  _safe_float(
            subs.get("adaptation", {}).get("score")
        ),
    })


def get_score_details(
    conn: sqlite3.Connection,
    session_id: str,
) -> Optional[dict]:
    row = conn.execute(
        Q.SELECT_SCORE_DETAILS, {"session_id": session_id}
    ).fetchone()
    if row is None:
        return None
    d = dict(row)
    # Parse JSON fields.
    for key in ("strengths_json", "weaknesses_json"):
        if d.get(key):
            try:
                d[key.replace("_json", "")] = json.loads(d[key])
            except (json.JSONDecodeError, TypeError):
                d[key.replace("_json", "")] = []
    return d


def insert_corner_metrics(
    conn: sqlite3.Connection,
    session_id: str,
    summary: dict[str, Any],
) -> int:
    """
    Extract per-lap corner metrics from the pipeline summary and persist them.

    The pipeline must populate ``summary["per_lap_corner_metrics"]`` as a
    list of dicts with keys matching the ``corner_metrics`` table columns.
    """
    metrics = summary.get("per_lap_corner_metrics")
    if not metrics:
        return 0

    count = 0
    for row in metrics:
        conn.execute(Q.INSERT_CORNER_METRIC, {
            "session_id":      session_id,
            "lap_number":      int(row.get("lap_number", 0)),
            "corner_id":       int(row.get("corner_id", 0)),
            "brake_point_m":   _safe_float(row.get("brake_point_m")
                                           or row.get("braking_point_actual_m")),
            "brake_intensity": _safe_float(row.get("brake_intensity")),
            "entry_speed_mps": _safe_float(row.get("entry_speed_mps")
                                           or row.get("actual_entry_speed_mps")),
            "apex_speed_mps":  _safe_float(row.get("apex_speed_mps")
                                           or row.get("actual_apex_speed_mps")),
            "exit_speed_mps":  _safe_float(row.get("exit_speed_mps")
                                           or row.get("actual_exit_speed_mps")),
            "throttle_onset_m": _safe_float(row.get("throttle_onset_m")),
            "exit_accel_mps2": _safe_float(row.get("exit_accel_mps2")),
            "grip_utilization": _safe_float(row.get("grip_utilization")
                                            or row.get("grip_utilisation_pct")),
            "time_loss_ms":    _safe_float(row.get("time_loss_ms")),
            "coaching_hint":   row.get("coaching_hint", ""),
            # TEXT columns pass through; the two NUMERIC ones go through
            # _safe_float like every neighbouring numeric above. These are the
            # only binds here fed by a public pure function -- grip_anchor
            # .decide_anchor's tier-2 path returns
            # `100.0 * abs(a_lat) / best`, which is a numpy.float64 whenever
            # a_lat came from an array, i.e. always, in the pipeline. psycopg2
            # raises "can't adapt type 'numpy.float64'" on such a bind, and
            # every writer swallows it (s15_persist.py, pipeline_tasks.py,
            # and endurance_tasks.py with a bare except and no log), so the
            # WHOLE session's corner metrics are lost -- brake points, apex
            # speeds, time loss, coaching hints and the legacy
            # grip_utilization included. _safe_float also nulls non-finite
            # values, so an inf/NaN pct becomes NULL instead of a poisoned row.
            "grip_anchor_tier":       row.get("grip_anchor_tier"),
            "grip_anchor_reason":     row.get("grip_anchor_reason"),
            "grip_anchor_pct":        _safe_float(row.get("grip_anchor_pct")),
            "grip_anchor_baseline_g": _safe_float(row.get("grip_anchor_baseline_g")),
        })
        count += 1

    return count


def get_corner_metrics_for_session(
    conn: sqlite3.Connection,
    session_id: str,
) -> list[dict]:
    """All corner metrics rows for a session, ordered by lap then corner."""
    rows = conn.execute(
        Q.SELECT_CORNER_METRICS_FOR_SESSION, {"session_id": session_id}
    ).fetchall()
    return [dict(r) for r in rows]


def get_corner_metrics_for_lap(
    conn: sqlite3.Connection,
    session_id: str,
    lap_number: int,
) -> list[dict]:
    """Corner metrics for a single lap."""
    rows = conn.execute(
        Q.SELECT_CORNER_METRICS_FOR_LAP,
        {"session_id": session_id, "lap_number": lap_number},
    ).fetchall()
    return [dict(r) for r in rows]


def get_corner_metrics_summary(
    conn: sqlite3.Connection,
    session_id: str,
) -> list[dict]:
    """Per-corner aggregates (avg entry/apex/exit speed, avg time loss, etc.)."""
    rows = conn.execute(
        Q.SELECT_CORNER_METRICS_SUMMARY, {"session_id": session_id}
    ).fetchall()
    return [dict(r) for r in rows]
