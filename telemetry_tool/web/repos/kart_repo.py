"""Kart repository — kart CRUD and predefined kart catalog."""

from __future__ import annotations

import sqlite3
from typing import Optional

import logging

logger = logging.getLogger(__name__)


def create_kart(
    conn: sqlite3.Connection,
    kart_name: str,
    predefined_kart_id: Optional[int] = None,
    manufacturer: Optional[str] = None,
    model: Optional[str] = None,
    engine: Optional[str] = None,
    power_hp: Optional[float] = None,
    kart_weight_kg: Optional[float] = None,
    notes: Optional[str] = None,
) -> int:
    """Create a kart. If predefined_kart_id is set, auto-fill specs from reference."""
    if predefined_kart_id is not None:
        ref = conn.execute(
            "SELECT manufacturer, model, engine, power_hp, kart_weight_kg "
            "FROM predefined_karts WHERE predefined_kart_id = ?",
            (predefined_kart_id,),
        ).fetchone()
        if ref:
            manufacturer = manufacturer or ref["manufacturer"]
            model = model or ref["model"]
            engine = engine or ref["engine"]
            power_hp = power_hp if power_hp is not None else ref["power_hp"]
            kart_weight_kg = kart_weight_kg if kart_weight_kg is not None else ref["kart_weight_kg"]

    import os
    if os.environ.get("USE_PG", "0") == "1":
        row = conn.execute(
            "INSERT INTO karts (kart_name, predefined_kart_id, manufacturer, model, "
            "engine, power_hp, kart_weight_kg, notes) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
            "RETURNING kart_id",
            (kart_name, predefined_kart_id, manufacturer, model, engine,
             power_hp, kart_weight_kg, notes),
        ).fetchone()
        return row["kart_id"] if row else 0
    else:
        cur = conn.execute(
            "INSERT INTO karts (kart_name, predefined_kart_id, manufacturer, model, "
            "engine, power_hp, kart_weight_kg, notes) VALUES (?,?,?,?,?,?,?,?)",
            (kart_name, predefined_kart_id, manufacturer, model, engine,
             power_hp, kart_weight_kg, notes),
        )
        return cur.lastrowid


def upsert_kart_by_name(
    conn: sqlite3.Connection,
    kart_name: str,
    details: Optional[dict] = None,
) -> int:
    """Find a kart by name or create one. Returns kart_id.

    When creating, ``details`` may contain manufacturer, model, engine,
    power_hp, kart_weight_kg to populate the new kart record.
    """
    clean = kart_name.strip()
    row = conn.execute(
        "SELECT kart_id FROM karts WHERE kart_name = ?", (clean,)
    ).fetchone()
    if row:
        return row["kart_id"]
    d = details or {}
    return create_kart(
        conn, clean,
        manufacturer=d.get("manufacturer"),
        model=d.get("model"),
        engine=d.get("engine"),
        power_hp=d.get("power_hp"),
        kart_weight_kg=d.get("kart_weight_kg"),
    )


def get_kart_by_id(conn: sqlite3.Connection, kart_id: int) -> Optional[dict]:
    row = conn.execute("SELECT * FROM karts WHERE kart_id = ?", (kart_id,)).fetchone()
    return dict(row) if row else None


def get_all_karts(conn) -> list[dict]:
    import os
    if os.environ.get("USE_PG", "0") == "1":
        # PG uses kart_sessions junction table; explicit GROUP BY columns
        rows = conn.execute(
            "SELECT k.kart_id, k.kart_name, k.predefined_kart_id, k.manufacturer, "
            "k.model, k.engine, k.power_hp, k.kart_weight_kg, k.notes, k.created_at, "
            "COUNT(ks.session_id) as session_count "
            "FROM karts k LEFT JOIN kart_sessions ks ON k.kart_id = ks.kart_id "
            "GROUP BY k.kart_id, k.kart_name, k.predefined_kart_id, k.manufacturer, "
            "k.model, k.engine, k.power_hp, k.kart_weight_kg, k.notes, k.created_at "
            "ORDER BY k.kart_name",
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT k.*, COUNT(s.session_id) as session_count "
            "FROM karts k LEFT JOIN sessions s ON k.kart_id = s.kart_id "
            "GROUP BY k.kart_id ORDER BY k.kart_name",
        ).fetchall()
    return [dict(r) for r in rows]


def update_kart(conn: sqlite3.Connection, kart_id: int, data: dict) -> None:
    allowed = {"kart_name", "manufacturer", "model", "engine", "power_hp", "kart_weight_kg", "notes"}
    sets = []
    vals = []
    for field, value in data.items():
        if field in allowed:
            sets.append(f"{field} = ?")
            vals.append(value)
    if sets:
        vals.append(kart_id)
        conn.execute(f"UPDATE karts SET {', '.join(sets)} WHERE kart_id = ?", vals)


def delete_kart(conn: sqlite3.Connection, kart_id: int) -> None:
    """Delete a kart and unlink any sessions."""
    conn.execute("UPDATE sessions SET kart_id = NULL WHERE kart_id = ?", (kart_id,))
    conn.execute("DELETE FROM karts WHERE kart_id = ?", (kart_id,))


def get_predefined_karts_grouped(conn: sqlite3.Connection) -> dict:
    """Return predefined karts grouped by segment."""
    rows = conn.execute(
        "SELECT * FROM predefined_karts ORDER BY segment, manufacturer, model"
    ).fetchall()
    segments: dict[str, list] = {}
    for r in rows:
        d = dict(r)
        seg = d.get("segment") or "Other"
        segments.setdefault(seg, []).append(d)
    return segments


def link_session_kart(conn: sqlite3.Connection, session_id: str, kart_id: Optional[int]) -> None:
    """Link or unlink a session to a kart."""
    conn.execute(
        "UPDATE sessions SET kart_id = ? WHERE session_id = ?",
        (kart_id, session_id),
    )
