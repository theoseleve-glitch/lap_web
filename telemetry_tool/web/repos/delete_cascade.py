"""Generic cascade delete — declarative config-driven entity deletion."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any, Union

logger = logging.getLogger(__name__)


class CascadeDeleteError(RuntimeError):
    """Raised when the parent row could not be deleted after cascading children."""
    pass

# ── Cascade Configuration ──────────────────────────────────────────
#
# Each entity defines:
#   parent_table  — the main table name
#   parent_pk     — the primary key column
#   pre_cascade   — (optional) raw SQL to run before child deletion (breaks circular FKs)
#   children      — list of child entries to process before deleting the parent
#
# Child entry types:
#   "table_name"                     — DELETE FROM table_name WHERE {parent_pk} = :id
#   {"entity": "x", "fk": "col"}    — recursive: find IDs, call delete_entity_cascade for each
#   {"table": "t", "fk": "c", "action": "unlink"} — SET fk = NULL instead of DELETE

# CRITICAL: Every table that has a FK referencing a parent entity MUST be
# listed here. If a child table is missing, PostgreSQL's default RESTRICT
# will silently block the parent DELETE, _safe_delete will swallow the
# error, and CascadeDeleteError will fire — but close_pg may commit the
# orphaned child deletes, causing data corruption. When adding new FK
# tables (Alembic migrations), ALWAYS update the matching cascade config.
CASCADE_CONFIG: dict[str, dict[str, Any]] = {
    "workspace": {
        # Full teardown of a workspace (GDPR account purge). Most workspace
        # children are ON DELETE CASCADE and are removed by the parent DELETE,
        # so they are NOT listed here. We must explicitly handle:
        #   1. sessions — cascade each so session-tier RESTRICT children
        #      (e.g. user_corners, which FK sessions, not workspaces) are
        #      cleared before the parent DELETE would CASCADE the session away;
        #   2. the workspace-tier children whose FK is RESTRICT / NO ACTION and
        #      would otherwise FK-block DELETE FROM workspaces (authoritative
        #      list from pg_constraint, schema head 066).
        # delete_entity_cascade RAISES if the workspace row survives, so any
        # future RESTRICT child added without being listed here surfaces loudly
        # instead of silently stalling the purge.
        "parent_table": "workspaces",
        "parent_pk": "id",
        "children": [
            {"entity": "session", "fk": "workspace_id"},
            {"table": "corner_mastery", "fk": "workspace_id"},
            {"table": "quests", "fk": "workspace_id"},
            {"table": "weekly_recap", "fk": "workspace_id"},
            {"table": "usage_events", "fk": "workspace_id"},
            {"table": "usage_monthly", "fk": "workspace_id"},
            {"table": "entitlement_overrides", "fk": "workspace_id"},
            {"table": "audit_log", "fk": "workspace_id"},
            {"table": "exports", "fk": "workspace_id"},
            {"table": "driver_stats_rollup", "fk": "workspace_id"},
            {"table": "track_stats_rollup", "fk": "workspace_id"},
            {"table": "driver_xp", "fk": "workspace_id"},
            {"table": "achievements", "fk": "workspace_id"},
            {"table": "drill_executions", "fk": "workspace_id"},
            {"table": "device_pairings", "fk": "workspace_id"},
            {"table": "workspace_members", "fk": "workspace_id"},
        ],
    },
    "session": {
        "parent_table": "sessions",
        "parent_pk": "session_id",
        "children": [
            "score_details",
            "corner_metrics",
            "driving_events",
            "condition_phases",
            "laps",
            "gps_traces",
            "theoretical_data",
            "reference_lines",
            "session_sectors",
            "session_tags",
            "session_weather",
            "session_weather_laps",
            "data_health",
            "driver_progression",
            "driving_style_features",
            "condition_markers",
            "vehicle_setups",
            "what_if_scenarios",
            "session_annotations",
            "stint_analysis",
            "user_corners",
            "plan_drill_sessions",
            "weekend_sessions",
        ],
    },
    "driver": {
        "parent_table": "drivers",
        "parent_pk": "driver_id",
        "children": [
            {"entity": "session", "fk": "driver_id"},
            "development_plans",
            "driver_badges",
            "driver_profiles",
            "driver_stats_rollup",   # PG-only (migration 028) — no ON DELETE, blocks parent
        ],
    },
    "track": {
        "parent_table": "tracks",
        "parent_pk": "track_id",
        "pre_cascade": [
            {
                "sql": "UPDATE tracks SET dry_ref_session_id = NULL, "
                       "wet_ref_session_id = NULL WHERE track_id = :id"
            },
        ],
        "children": [
            {"entity": "session", "fk": "track_id"},
            {"table": "weekends", "fk": "track_id", "action": "unlink"},
            "track_sectors",
            "track_records",
            "track_key_corners",
            "corner_best_practices",
            "track_stats_rollup",    # PG-only (migration 028) — no ON DELETE, blocks parent
        ],
    },
    "kart": {
        "parent_table": "karts",
        "parent_pk": "kart_id",
        "children": [
            {"table": "sessions", "fk": "kart_id", "action": "unlink"},
        ],
    },
    "weekend": {
        "parent_table": "weekends",
        "parent_pk": "weekend_id",
        "children": [
            "weekend_sessions",
        ],
    },
    "race_strategy": {
        "parent_table": "race_configs",
        "parent_pk": "race_id",
        "children": [
            "race_rival_events",
            "race_rivals",
            "race_stints",
            "race_pit_stops",
            "race_drivers",
            "race_windows",
            "race_sleep_windows",
            "race_messages",
            "race_neutralizations",
        ],
    },
    "dev_plan": {
        "parent_table": "development_plans",
        "parent_pk": "id",
        "children": [
            "plan_drill_sessions",
            {"table": "driver_badges", "fk": "plan_id", "action": "unlink"},
        ],
    },
}


def _safe_delete(conn: sqlite3.Connection, sql: str, params: dict) -> int:
    """Execute a DELETE/UPDATE and return rowcount, 0 on missing table.

    Uses SAVEPOINT so a failure (e.g. missing table in PG) doesn't
    abort the entire transaction — without this, PostgreSQL enters
    InFailedSqlTransaction and all subsequent statements silently fail.
    """
    sp = f"sp_{id(sql) % 100000}"
    try:
        conn.execute(f"SAVEPOINT {sp}")
        cur = conn.execute(sql, params)
        rc = cur.rowcount
        conn.execute(f"RELEASE SAVEPOINT {sp}")
        return rc if isinstance(rc, int) else 0
    except Exception as exc:
        logger.debug("Skipping: %s — %s", sql[:80], exc)
        try:
            conn.execute(f"ROLLBACK TO SAVEPOINT {sp}")
            conn.execute(f"RELEASE SAVEPOINT {sp}")
        except Exception:
            pass
        return 0


def _safe_count(conn: sqlite3.Connection, sql: str, params: dict) -> int:
    """Execute a COUNT query and return the count, 0 on error."""
    sp = f"sp_{id(sql) % 100000}"
    try:
        conn.execute(f"SAVEPOINT {sp}")
        row = conn.execute(sql, params).fetchone()
        conn.execute(f"RELEASE SAVEPOINT {sp}")
        if row is None:
            return 0
        if isinstance(row, dict):
            return row.get("c", 0)
        return row[0]
    except Exception as exc:
        logger.debug("Skipping count: %s — %s", sql[:80], exc)
        try:
            conn.execute(f"ROLLBACK TO SAVEPOINT {sp}")
            conn.execute(f"RELEASE SAVEPOINT {sp}")
        except Exception:
            pass
        return 0


def _process_children(
    conn: sqlite3.Connection,
    config: dict,
    entity_id: Union[int, str],
    *,
    dry_run: bool = False,
) -> dict[str, int]:
    """Process all children for an entity. If dry_run, count instead of delete."""
    impact: dict[str, int] = {}
    parent_pk = config["parent_pk"]

    # Run pre_cascade hooks (only on actual delete, not dry_run)
    if not dry_run:
        for hook in config.get("pre_cascade", []):
            _safe_delete(conn, hook["sql"], {"id": entity_id})

    for child in config["children"]:
        if isinstance(child, str):
            # Simple table — same FK as parent_pk
            if dry_run:
                count = _safe_count(
                    conn,
                    f"SELECT COUNT(*) AS c FROM {child} WHERE {parent_pk} = :id",
                    {"id": entity_id},
                )
            else:
                count = _safe_delete(
                    conn,
                    f"DELETE FROM {child} WHERE {parent_pk} = :id",
                    {"id": entity_id},
                )
            if count > 0:
                impact[child] = impact.get(child, 0) + count

        elif isinstance(child, dict) and "entity" in child:
            # Recursive cascade — find child entity IDs, cascade each
            child_entity = child["entity"]
            fk_col = child["fk"]
            child_config = CASCADE_CONFIG[child_entity]
            child_table = child_config["parent_table"]
            child_pk = child_config["parent_pk"]

            rows = conn.execute(
                f"SELECT {child_pk} FROM {child_table} WHERE {fk_col} = :id",
                {"id": entity_id},
            ).fetchall()

            child_ids = []
            for r in rows:
                cid = r[child_pk] if isinstance(r, dict) else r[0]
                child_ids.append(cid)

            for cid in child_ids:
                sub_impact = _process_children(conn, child_config, cid, dry_run=dry_run)
                for k, v in sub_impact.items():
                    impact[k] = impact.get(k, 0) + v

                if dry_run:
                    impact[child_table] = impact.get(child_table, 0) + 1
                else:
                    _safe_delete(
                        conn,
                        f"DELETE FROM {child_table} WHERE {child_pk} = :id",
                        {"id": cid},
                    )
                    impact[child_table] = impact.get(child_table, 0) + 1

        elif isinstance(child, dict) and child.get("action") == "unlink":
            # Unlink — set FK to NULL
            table = child["table"]
            fk_col = child["fk"]
            if dry_run:
                count = _safe_count(
                    conn,
                    f"SELECT COUNT(*) AS c FROM {table} WHERE {fk_col} = :id",
                    {"id": entity_id},
                )
            else:
                count = _safe_delete(
                    conn,
                    f"UPDATE {table} SET {fk_col} = NULL WHERE {fk_col} = :id",
                    {"id": entity_id},
                )
            if count > 0:
                impact[f"{table} (unlinked)"] = count

        elif isinstance(child, dict) and "table" in child and "fk" in child:
            # Direct child table whose FK column name differs from the parent's
            # PK (e.g. workspace children key on ``workspace_id``, not ``id``).
            table = child["table"]
            fk_col = child["fk"]
            if dry_run:
                count = _safe_count(
                    conn,
                    f"SELECT COUNT(*) AS c FROM {table} WHERE {fk_col} = :id",
                    {"id": entity_id},
                )
            else:
                count = _safe_delete(
                    conn,
                    f"DELETE FROM {table} WHERE {fk_col} = :id",
                    {"id": entity_id},
                )
            if count > 0:
                impact[table] = impact.get(table, 0) + count

    return impact


def delete_entity_cascade(
    conn: sqlite3.Connection,
    entity_type: str,
    entity_id: Union[int, str],
) -> dict:
    """Delete an entity and all its children per CASCADE_CONFIG.

    Returns:
        {"deleted": True, "impact": {"sessions": 12, "laps": 47, ...}}

    Raises:
        CascadeDeleteError: if the parent row was not actually removed
            (e.g. FK constraint from an unlisted child table, RLS policy
            filtering, or any silent DB-level rejection).
    """
    if entity_type not in CASCADE_CONFIG:
        raise ValueError(f"Unknown entity type: {entity_type!r}")

    config = CASCADE_CONFIG[entity_type]
    impact = _process_children(conn, config, entity_id, dry_run=False)

    # Delete the parent itself
    parent_table = config["parent_table"]
    parent_pk = config["parent_pk"]
    deleted_count = _safe_delete(
        conn,
        f"DELETE FROM {parent_table} WHERE {parent_pk} = :id",
        {"id": entity_id},
    )

    # CRITICAL: Verify the parent row was actually removed. If rowcount is 0,
    # a FK constraint from an unlisted child table blocked the DELETE (PG
    # RESTRICT default). The caller MUST rollback to undo child deletes.
    if deleted_count == 0:
        logger.error(
            "Cascade delete failed: %s %s was NOT removed from %s "
            "(rowcount=0 — likely FK constraint or RLS policy)",
            entity_type, entity_id, parent_table,
        )
        raise CascadeDeleteError(
            f"Failed to delete {entity_type} {entity_id}: "
            f"row still exists in {parent_table} after cascading children"
        )

    return {"deleted": True, "impact": impact}


def get_delete_impact(
    conn: sqlite3.Connection,
    entity_type: str,
    entity_id: Union[int, str],
) -> dict:
    """Count affected rows without deleting.

    Same traversal as cascade but SELECT COUNT(*) instead of DELETE.

    Returns:
        {"impact": {"sessions": 12, "laps": 47, ...}}
    """
    if entity_type not in CASCADE_CONFIG:
        raise ValueError(f"Unknown entity type: {entity_type!r}")

    config = CASCADE_CONFIG[entity_type]
    impact = _process_children(conn, config, entity_id, dry_run=True)

    return {"impact": impact}
