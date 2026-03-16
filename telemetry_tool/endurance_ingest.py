"""Quick lap detection for endurance sessions.

Reads only lap boundaries from a CSV — no full pipeline, no GPS,
no feature engineering. Memory: ~10MB regardless of file size.
"""
from __future__ import annotations

import csv
import logging
import statistics
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def detect_laps_quick(
    csv_path: str | Path,
    pit_threshold_s: float = 120.0,
) -> dict[str, Any]:
    """Fast first-pass: extract lap times and detect pit stops.

    Reads the CSV row-by-row, tracking only the Lap # column and
    elapsed time. Memory usage is O(n_laps), not O(n_rows).
    """
    csv_path = Path(csv_path)
    laps: dict[int, dict[str, Any]] = {}
    current_lap: int | None = None
    lap_start_time: float | None = None
    last_time: float = 0.0

    with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        header: list[str] = []
        for row in reader:
            if not row:
                continue
            joined = ",".join(row).lower()
            if "lap" in joined and ("time" in joined or "speed" in joined):
                header = [c.strip() for c in row]
                break

        if not header:
            return {"laps": [], "auto_stints": [], "error": "No header found"}

        lap_col = _find_col(header, ["lap #", "lap", "lap number"])
        time_col = _find_col(header, ["time (s)", "time(s)", "elapsed (s)", "time"])

        if lap_col is None or time_col is None:
            return {"laps": [], "auto_stints": [], "error": f"Missing columns: lap={lap_col}, time={time_col}"}

        for row in reader:
            if len(row) <= max(lap_col, time_col):
                continue
            try:
                lap_num = int(float(row[lap_col]))
                elapsed = float(row[time_col])
            except (ValueError, TypeError):
                continue

            if current_lap is None or lap_num != current_lap:
                if current_lap is not None and lap_start_time is not None:
                    lap_time = last_time - lap_start_time
                    if lap_time > 0:
                        laps[current_lap] = {
                            "lap_number": current_lap,
                            "lap_time_s": round(lap_time, 3),
                        }
                current_lap = lap_num
                lap_start_time = elapsed

            last_time = elapsed

        # Final lap
        if current_lap is not None and lap_start_time is not None:
            lap_time = last_time - lap_start_time
            if lap_time > 0:
                laps[current_lap] = {
                    "lap_number": current_lap,
                    "lap_time_s": round(lap_time, 3),
                }

    # Classify laps
    lap_list = sorted(laps.values(), key=lambda l: l["lap_number"])
    valid_times = [l["lap_time_s"] for l in lap_list if l["lap_time_s"] < pit_threshold_s]
    median_time = statistics.median(valid_times) if valid_times else 0

    for lap in lap_list:
        if lap["lap_time_s"] > pit_threshold_s:
            lap["status"] = "pit"
        elif median_time > 0 and lap["lap_time_s"] > median_time * 2:
            lap["status"] = "anomaly"
        else:
            lap["status"] = "valid"

    stints = _build_stints(lap_list)

    return {
        "laps": lap_list,
        "auto_stints": stints,
        "median_lap_time_s": round(median_time, 3),
        "pit_threshold_s": pit_threshold_s,
        "total_laps": len(lap_list),
    }


def _build_stints(laps: list[dict]) -> list[dict]:
    """Group consecutive valid/anomaly laps into stints."""
    stints: list[dict] = []
    current: list[int] = []

    for lap in laps:
        if lap["status"] == "pit":
            if current:
                stints.append({
                    "stint_number": len(stints) + 1,
                    "start_lap": current[0],
                    "end_lap": current[-1],
                    "lap_count": len(current),
                    "pit_lap_number": lap["lap_number"],
                    "pit_lap_time_s": lap["lap_time_s"],
                })
                current = []
        else:
            current.append(lap["lap_number"])

    if current:
        stints.append({
            "stint_number": len(stints) + 1,
            "start_lap": current[0],
            "end_lap": current[-1],
            "lap_count": len(current),
            "pit_lap_number": None,
            "pit_lap_time_s": None,
        })

    return stints


def _find_col(header: list[str], candidates: list[str]) -> int | None:
    """Find column index matching any candidate name (case-insensitive)."""
    lower = [h.lower().strip() for h in header]
    for c in candidates:
        if c.lower() in lower:
            return lower.index(c.lower())
    return None
