"""Quest engine — generate machine-verifiable quests from session facts and
verify them on later uploads. Pure functions over an open connection
(PgConnectionWrapper in prod, sqlite3 in tests). Deterministic + idempotent;
caller commits. Mirrors gamification/mastery.py."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from gamification.quest_metrics import (
    APEX_SPEED_DELTA_KMH, BEST_LAP_TARGET_PCT, CONSISTENCY_DELTA_PCT,
    LAPS_FALLBACK, METRICS, QUEST_XP, comparator_for, render_label,
)

_PLAUSIBLE_LAP_MAX_S = 600.0  # ignore obviously-bad lap rows


def _median(xs: list[float]) -> float:
    xs = sorted(xs)
    n = len(xs)
    if n == 0:
        return 0.0
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def extract_session_facts(conn, result: dict, session_id: str,
                          driver_id: int, workspace_id: int) -> dict[str, float]:
    """Flat metric map for a session. Per-corner keys are suffixed @<corner_id>."""
    facts: dict[str, float] = {}

    sr = result.get("score_result") or {}
    if sr.get("total") is not None:
        facts["session.score"] = float(sr["total"])

    cons = ((result.get("details") or {}).get("consistency") or {})
    if cons.get("cv_pct") is not None:
        facts["consistency_cv_pct"] = float(cons["cv_pct"])

    raw_laps = [t for t in (result.get("lap_times") or [])
               if isinstance(t, (int, float)) and 0 < t < _PLAUSIBLE_LAP_MAX_S]
    # Second pass: exclude laps more than 2× the fastest clean lap (formation /
    # cool-down laps that slipped through the absolute ceiling).
    if raw_laps:
        _min_lap = min(raw_laps)
        laps = [t for t in raw_laps if t < _min_lap * 2.0]
    else:
        laps = raw_laps
    facts["laps_completed"] = float(len(laps))

    # best-lap improvement vs the driver's prior best (excluding THIS session)
    cur_best = min(laps) if laps else None
    if cur_best is not None:
        row = conn.execute(
            "SELECT MIN(best_lap_time_s) AS pb FROM sessions "
            "WHERE driver_id = :drv AND workspace_id = :ws "
            "AND session_id != :sid AND best_lap_time_s IS NOT NULL AND best_lap_time_s > 0",
            {"drv": driver_id, "ws": workspace_id, "sid": session_id},
        ).fetchone()
        pb = (row["pb"] if isinstance(row, dict) else row[0]) if row else None
        if pb and pb > 0:
            facts["best_lap_improvement_pct"] = (pb - cur_best) / pb * 100.0

    # per-corner speeds + time loss (median across laps)
    rows = conn.execute(
        "SELECT corner_id, apex_speed_mps, exit_speed_mps, time_loss_ms "
        "FROM corner_metrics WHERE session_id = :sid",
        {"sid": session_id},
    ).fetchall()
    by_corner: dict[int, dict[str, list[float]]] = {}
    for r in rows:
        d = dict(r) if not isinstance(r, dict) else r
        cid = d.get("corner_id")
        if cid is None:
            continue
        b = by_corner.setdefault(int(cid), {"apex": [], "exit": [], "loss": []})
        if d.get("apex_speed_mps") is not None:
            b["apex"].append(float(d["apex_speed_mps"]))
        if d.get("exit_speed_mps") is not None:
            b["exit"].append(float(d["exit_speed_mps"]))
        if d.get("time_loss_ms") is not None:
            b["loss"].append(float(d["time_loss_ms"]))
    for cid, b in by_corner.items():
        if b["apex"]:
            facts[f"corner.apex_speed_kmh@{cid}"] = round(_median(b["apex"]) * 3.6, 1)
        if b["exit"]:
            facts[f"corner.exit_speed_kmh@{cid}"] = round(_median(b["exit"]) * 3.6, 1)
        if b["loss"]:
            facts[f"corner.time_loss_ms@{cid}"] = round(_median(b["loss"]), 1)

    # per-corner mastery score (Phase 1)
    mrows = conn.execute(
        "SELECT corner_id, best_score FROM corner_mastery "
        "WHERE driver_id = :drv AND workspace_id = :ws",
        {"drv": driver_id, "ws": workspace_id},
    ).fetchall()
    for r in mrows:
        d = dict(r) if not isinstance(r, dict) else r
        if d.get("corner_id") is not None and d.get("best_score") is not None:
            facts[f"corner.mastery_score@{int(d['corner_id'])}"] = float(d["best_score"])

    return facts
