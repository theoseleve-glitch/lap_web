"""Weather forecast CRUD and live condition management."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

_parent = str(Path(__file__).resolve().parents[1])
if _parent not in sys.path:
    sys.path.insert(0, _parent)

from services.race_strategy import get_race, _compute_elapsed_s  # noqa: E402

logger = logging.getLogger(__name__)


def add_weather_window(conn, race_id, start_s, end_s, condition, confidence_pct=100):
    """Add a weather forecast window to a race."""
    race = get_race(conn, race_id)
    if not race:
        return None
    conn.execute(
        "INSERT INTO race_weather_windows (race_id, start_s, end_s, condition, confidence_pct) "
        "VALUES (?,?,?,?,?)",
        (race_id, start_s, end_s, condition, confidence_pct),
    )
    conn.commit()
    return {"ok": True}


def update_weather_window(conn, race_id, window_id, **fields):
    """Update fields on an existing weather window."""
    sets = []
    vals = []
    for k in ("start_s", "end_s", "condition", "confidence_pct"):
        if k in fields:
            sets.append(f"{k} = ?")
            vals.append(fields[k])
    if not sets:
        return None
    vals.extend([window_id, race_id])
    conn.execute(
        f"UPDATE race_weather_windows SET {', '.join(sets)} WHERE id = ? AND race_id = ?",
        vals,
    )
    conn.commit()
    return {"ok": True}


def delete_weather_window(conn, race_id, window_id):
    """Delete a weather window by id."""
    conn.execute(
        "DELETE FROM race_weather_windows WHERE id = ? AND race_id = ?",
        (window_id, race_id),
    )
    conn.commit()
    return {"ok": True}


def get_weather_windows(conn, race_id):
    """Return all weather windows for a race, ordered by start_s."""
    rows = conn.execute(
        "SELECT * FROM race_weather_windows WHERE race_id = ? ORDER BY start_s",
        (race_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def set_current_condition(conn, race_id, condition):
    """Set the current weather condition on the race config."""
    if condition not in ("dry", "damp", "wet"):
        return None
    conn.execute(
        "UPDATE race_configs SET current_condition = ? WHERE race_id = ?",
        (condition, race_id),
    )
    conn.commit()
    return {"ok": True, "condition": condition}
