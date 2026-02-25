"""
csv_tables.py
-------------
Write ``corner_table.csv`` and ``delta_map.csv`` output files.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from kart_envelope.coaching.corner_coaching import CornerPerformance

logger = logging.getLogger(__name__)


def write_corner_table(
    corner_perfs: list[CornerPerformance],
    path: Path,
) -> None:
    """Write a CSV with one row per corner."""
    if not corner_perfs:
        logger.warning("No corner data to write.")
        return

    rows = []
    for cp in corner_perfs:
        rows.append({
            "corner_id": cp.corner_id,
            "s_start_m": round(cp.s_start, 1),
            "s_end_m": round(cp.s_end, 1),
            "s_apex_m": round(cp.s_apex, 1),
            "direction": cp.direction,
            "entry_speed_actual_mps": round(cp.entry_speed_actual, 2),
            "entry_speed_theory_mps": round(cp.entry_speed_theory, 2),
            "apex_speed_actual_mps": round(cp.apex_speed_actual, 2),
            "apex_speed_theory_mps": round(cp.apex_speed_theory, 2),
            "exit_speed_actual_mps": round(cp.exit_speed_actual, 2),
            "exit_speed_theory_mps": round(cp.exit_speed_theory, 2),
            "brake_point_actual_m": round(cp.brake_point_actual_m, 1),
            "brake_point_theory_m": round(cp.brake_point_theory_m, 1),
            "brake_delta_m": round(cp.brake_delta_m, 1),
            "time_loss_total_ms": round(cp.time_loss_total_s * 1000, 1),
            "time_loss_entry_ms": round(cp.time_loss_entry_s * 1000, 1),
            "time_loss_apex_ms": round(cp.time_loss_apex_s * 1000, 1),
            "time_loss_exit_ms": round(cp.time_loss_exit_s * 1000, 1),
            "primary_cause": cp.primary_cause,
            "coaching_hint": cp.coaching_hint,
        })

    df = pd.DataFrame(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    logger.info("Wrote corner_table.csv (%d corners) to %s", len(rows), path)


def write_delta_map(delta_map: pd.DataFrame, path: Path) -> None:
    """Write the distance-aligned delta map CSV."""
    if delta_map.empty:
        logger.warning("Empty delta map; nothing to write.")
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    delta_map.to_csv(path, index=False)
    logger.info("Wrote delta_map.csv (%d rows) to %s", len(delta_map), path)
