"""Generic cascade delete — declarative config-driven entity deletion."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any, Union

logger = logging.getLogger(__name__)

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

CASCADE_CONFIG: dict[str, dict[str, Any]] = {
    "session": {
        "parent_table": "sessions",
        "parent_pk": "session_id",
        "children": [
            "score_details",
            "corner_metrics",
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
            "track_sectors",
            "track_records",
            "track_key_corners",
            "corner_best_practices",
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
    """Execute a DELETE/UPDATE and return rowcount, 0 on missing table."""
    try:
        cur = conn.execute(sql, params)
        return cur.rowcount
    except Exception as exc:
        # Table may not exist in all DB versions (SQLite vs PG, schema version)
        logger.debug("Skipping: %s — %s", sql[:80], exc)
        return 0


def _safe_count(conn: sqlite3.Connection, sql: str, params: dict) -> int:
    """Execute a COUNT query and return the count, 0 on error."""
    try:
        row = conn.execute(sql, params).fetchone()
        if row is None:
            return 0
        # Handle both dict-like and tuple rows
        if isinstance(row, dict):
            return row.get("c", 0)
        return row[0]
    except Exception as exc:
        logger.debug("Skipping count: %s — %s", sql[:80], exc)
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

    return impact


def delete_entity_cascade(
    conn: sqlite3.Connection,
    entity_type: str,
    entity_id: Union[int, str],
) -> dict:
    """Delete an entity and all its children per CASCADE_CONFIG.

    Returns:
        {"deleted": True, "impact": {"sessions": 12, "laps": 47, ...}}
    """
    if entity_type not in CASCADE_CONFIG:
        raise ValueError(f"Unknown entity type: {entity_type!r}")

    config = CASCADE_CONFIG[entity_type]
    impact = _process_children(conn, config, entity_id, dry_run=False)

    # Delete the parent itself
    parent_table = config["parent_table"]
    parent_pk = config["parent_pk"]
    _safe_delete(
        conn,
        f"DELETE FROM {parent_table} WHERE {parent_pk} = :id",
        {"id": entity_id},
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
