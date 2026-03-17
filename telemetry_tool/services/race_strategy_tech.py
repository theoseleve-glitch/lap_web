"""Tech stop service functions for race strategy."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

_parent = str(Path(__file__).resolve().parents[1])
if _parent not in sys.path:
    sys.path.insert(0, _parent)

from services.race_strategy import get_race, _compute_elapsed_s

logger = logging.getLogger(__name__)


def tech_stop_in(conn, race_id: int) -> dict | None:
    """Car enters tech stop — does NOT end the active stint."""
    race = get_race(conn, race_id)
    if not race:
        return None
    if race.get("pit_in_at_s") is not None:
        return None  # already in pit/tech stop
    elapsed = _compute_elapsed_s(race.get("race_start_ts"), race)
    conn.execute(
        "UPDATE race_configs SET pit_in_at_s = ? WHERE race_id = ?",
        (elapsed, race_id),
    )
    conn.commit()
    return {"ok": True, "elapsed_s": elapsed, "tech_stop": True}


def tech_stop_out(conn, race_id: int) -> dict | None:
    """Car exits tech stop — validates minimum duration, records pit stop."""
    race = get_race(conn, race_id)
    if not race:
        return None
    pit_in_at = race.get("pit_in_at_s")
    if pit_in_at is None:
        return None
    elapsed = _compute_elapsed_s(race.get("race_start_ts"), race)
    duration = max(0, elapsed - pit_in_at)
    min_dur_val = race.get("tech_stop_duration_s")
    min_dur = min_dur_val if min_dur_val is not None else 360
    if duration < min_dur:
        return {"error": "too_early", "remaining_s": min_dur - duration}
    # Find active stint
    active = conn.execute(
        "SELECT stint_id FROM race_stints WHERE race_id = ? AND status = 'active'",
        (race_id,),
    ).fetchone()
    stint_id = None
    if active:
        stint_id = active["stint_id"] if isinstance(active, dict) else active[0]
    conn.execute(
        "INSERT INTO race_pit_stops (race_id, stint_id, actual_at_s, duration_s, "
        "driver_change, refueled, pit_type) VALUES (?,?,?,?,?,?,?)",
        (race_id, stint_id, pit_in_at, duration, False, False, "tech"),
    )
    conn.execute(
        "UPDATE race_configs SET pit_in_at_s = NULL WHERE race_id = ?",
        (race_id,),
    )
    conn.commit()
    return {"ok": True, "elapsed_s": elapsed, "tech_stop_duration_s": duration}
