"""
track_surface/racing_line_repo.py
----------------------------------
CRUD over the ``track_racing_lines`` global table (migration 078).

Consumes the racing_line_dto.racing_line_from_solution DTO:
    {"points": [{"d": float, "n": float, "v": float}, ...],
     "condition": str,
     "solver_meta": {"status": str, "solve_time_s": float, "lap_time_s": float}}

Produced by: Task 2.2 (racing_line_dto)
Consumed by: Task 2.5 (Celery compute task) and Task 3.5 (Race Brief endpoint)

Connection-agnostic: accepts a raw psycopg2 connection (used in tests) or a
PgConnectionWrapper (used in production via get_maint_connection /
get_pg_connection).  Callers are responsible for commit/rollback.

JSONB idiom: points is stored via ``json.dumps(dto["points"])`` + ``::jsonb``
cast in the SQL.  This matches the codebase's existing pattern of passing
json.dumps() strings to psycopg2 and is safe for both the raw psycopg2 driver
and the PgConnectionWrapper (translate_params preserves ``::`` casts).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_LINE_KIND = "optimal"  # v1 only produces optimal lines


def upsert_racing_line(
    conn: Any,
    track_id: str,
    vehicle_class: str,
    condition: str,
    dto: dict,
    *,
    solver_version: str,
    grip_snapshot_hash: str,
    n_laps_used: int,
    status: str = "ok",
    geometry_source: str | None = None,
    tier: str | None = None,
    provenance: dict | None = None,
) -> None:
    """INSERT or UPDATE track_racing_lines for one (track, class, condition).

    Uses ON CONFLICT (track_id, vehicle_class, condition, line_kind) DO UPDATE
    so repeated solver runs overwrite the previous result rather than
    accumulating rows.  ``line_kind`` is always ``'optimal'`` for v1.

    Parameters
    ----------
    conn               Database connection (raw psycopg2 or PgConnectionWrapper).
    track_id           Track identifier string.
    vehicle_class      Vehicle class string (e.g. ``"generic"``, ``"gt3"``).
    condition          Track condition string (e.g. ``"dry"``, ``"wet"``).
    dto                Dict from ``racing_line_from_solution()``.  Must contain
                       ``"points"`` (list of ``{d, n, v}`` dicts) and optionally
                       ``"solver_meta"`` (dict with ``"lap_time_s"``).
    solver_version     Solver version tag (e.g. ``"v1"``).
    grip_snapshot_hash Hash of the grip data used for this solve.
    n_laps_used        Number of laps that contributed to the grip model.
    status             Row status; default ``"ok"``.
    """
    points_json = json.dumps(dto["points"])
    lap_time_s = (dto.get("solver_meta") or {}).get("lap_time_s")
    provenance_json = json.dumps(provenance) if provenance is not None else None
    now = datetime.now(timezone.utc)

    sql = """
        INSERT INTO track_racing_lines (
            track_id, vehicle_class, condition, line_kind,
            points, solver_version, grip_snapshot_hash,
            n_laps_used, lap_time_s, status, computed_at,
            geometry_source, tier, provenance
        ) VALUES (
            %(track_id)s, %(vehicle_class)s, %(condition)s, %(line_kind)s,
            %(points)s::jsonb, %(solver_version)s, %(grip_snapshot_hash)s,
            %(n_laps_used)s, %(lap_time_s)s, %(status)s, %(computed_at)s,
            %(geometry_source)s, %(tier)s, %(provenance)s::jsonb
        )
        ON CONFLICT (track_id, vehicle_class, condition, line_kind)
        DO UPDATE SET
            points             = EXCLUDED.points,
            solver_version     = EXCLUDED.solver_version,
            grip_snapshot_hash = EXCLUDED.grip_snapshot_hash,
            n_laps_used        = EXCLUDED.n_laps_used,
            lap_time_s         = EXCLUDED.lap_time_s,
            status             = EXCLUDED.status,
            computed_at        = EXCLUDED.computed_at,
            geometry_source    = EXCLUDED.geometry_source,
            tier               = EXCLUDED.tier,
            provenance         = EXCLUDED.provenance
    """
    params = {
        "track_id": track_id,
        "vehicle_class": vehicle_class,
        "condition": condition,
        "line_kind": _LINE_KIND,
        "points": points_json,
        "solver_version": solver_version,
        "grip_snapshot_hash": grip_snapshot_hash,
        "n_laps_used": n_laps_used,
        "lap_time_s": lap_time_s,
        "status": status,
        "computed_at": now,
        "geometry_source": geometry_source,
        "tier": tier,
        "provenance": provenance_json,
    }
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
    finally:
        cur.close()
    logger.debug(
        "Upserted racing line: track=%s vc=%s cond=%s points=%d status=%s",
        track_id, vehicle_class, condition, len(dto["points"]), status,
    )


def get_racing_lines(
    conn: Any,
    track_id: str,
    vehicle_class: str,
) -> list[dict]:
    """Return all rows from ``track_racing_lines`` for (track_id, vehicle_class).

    Returns a list of dicts with keys::

        condition, status, grip_snapshot_hash, solver_version,
        n_laps_used, lap_time_s, computed_at, points

    ``points`` is always returned as a Python list (not a JSON string).
    psycopg2 with ``RealDictCursor`` decodes JSONB automatically; if the
    driver returns a raw JSON string, ``json.loads()`` is applied as a
    fallback.

    Works with both dict-keyed rows (psycopg2 ``RealDictCursor``, used in
    tests) and plain tuple rows (``PgConnectionWrapper.cursor()`` plain
    cursor, used in production).

    Rows are ordered by ``computed_at`` DESC (newest first).
    """
    sql = """
        SELECT condition, status, grip_snapshot_hash, solver_version,
               n_laps_used, lap_time_s, computed_at, points,
               tier, geometry_source, provenance
        FROM track_racing_lines
        WHERE track_id = %(track_id)s
          AND vehicle_class = %(vehicle_class)s
        ORDER BY computed_at DESC
    """
    params = {"track_id": track_id, "vehicle_class": vehicle_class}
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        raw_rows = cur.fetchall()
    finally:
        cur.close()

    result: list[dict] = []
    for row in raw_rows:
        if isinstance(row, dict):
            # RealDictCursor (psycopg2 connection with cursor_factory or via
            # PgConnectionWrapper.execute() which uses the connection-level factory)
            d = {
                "condition":          row["condition"],
                "status":             row["status"],
                "grip_snapshot_hash": row["grip_snapshot_hash"],
                "solver_version":     row["solver_version"],
                "n_laps_used":        row["n_laps_used"],
                "lap_time_s":         row["lap_time_s"],
                "computed_at":        row["computed_at"],
                "points":             row["points"],
                "tier":               row.get("tier"),
                "geometry_source":    row.get("geometry_source"),
                "provenance":         row.get("provenance"),
            }
        else:
            # Plain tuple cursor (PgConnectionWrapper.cursor() in production).
            # Column order must match the SELECT above exactly.
            cond, stat, snap_hash, sv, nlaps, lt, cat, pts, tier, geom_src, prov = row
            d = {
                "condition":          cond,
                "status":             stat,
                "grip_snapshot_hash": snap_hash,
                "solver_version":     sv,
                "n_laps_used":        nlaps,
                "lap_time_s":         lt,
                "computed_at":        cat,
                "points":             pts,
                "tier":               tier,
                "geometry_source":    geom_src,
                "provenance":         prov,
            }

        # Normalise JSONB: psycopg2 RealDictCursor auto-decodes to list/dict;
        # plain cursor may return a raw JSON string — handle both.
        pts = d["points"]
        if isinstance(pts, str):
            pts = json.loads(pts)
        d["points"] = pts
        prov = d.get("provenance")
        if isinstance(prov, str):
            d["provenance"] = json.loads(prov)
        result.append(d)
    return result


def set_racing_line_status(
    conn: Any,
    track_id: str,
    vehicle_class: str,
    condition: str,
    status: str,
    *,
    reason: str | None = None,
    tier: str | None = None,
) -> None:
    """Set the ``status`` column, inserting a placeholder row if none exists.

    Uses ON CONFLICT so a solver failure *before* any successful line still
    records the ``"failed"`` status.  The placeholder row gets an empty
    ``points`` array (``'[]'::jsonb``); a later successful
    ``upsert_racing_line()`` call will overwrite all columns.

    Parameters
    ----------
    reason  Optional machine-readable refusal reason (honesty taxonomy). Now
            persisted into ``provenance`` (migration 080) as ``{"reason": ...}``
            in addition to being logged, so a refused line is self-describing.
    tier    Optional honesty tier (typically ``"refused"`` on failure). NULL
            leaves the column untouched-by-default on insert.
    """
    if reason is not None:
        logger.debug(
            "Racing line status change: track=%s vc=%s cond=%s "
            "status=%s reason=%s",
            track_id, vehicle_class, condition, status, reason,
        )
    provenance_json = json.dumps({"reason": reason}) if reason is not None else None
    now = datetime.now(timezone.utc)
    sql = """
        INSERT INTO track_racing_lines (
            track_id, vehicle_class, condition, line_kind,
            points, status, computed_at, tier, provenance
        ) VALUES (
            %(track_id)s, %(vehicle_class)s, %(condition)s, %(line_kind)s,
            '[]'::jsonb, %(status)s, %(computed_at)s,
            %(tier)s, %(provenance)s::jsonb
        )
        ON CONFLICT (track_id, vehicle_class, condition, line_kind)
        DO UPDATE SET
            status     = EXCLUDED.status,
            tier       = EXCLUDED.tier,
            provenance = EXCLUDED.provenance
    """
    params = {
        "track_id": track_id,
        "vehicle_class": vehicle_class,
        "condition": condition,
        "line_kind": _LINE_KIND,
        "status": status,
        "computed_at": now,
        "tier": tier,
        "provenance": provenance_json,
    }
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
    finally:
        cur.close()
    logger.debug(
        "Set racing line status: track=%s vc=%s cond=%s status=%s",
        track_id, vehicle_class, condition, status,
    )
