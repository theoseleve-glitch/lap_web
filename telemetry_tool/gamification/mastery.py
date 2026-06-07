"""Corner mastery — derive per-corner scores and upsert star tiers.

Pure functions over an open connection (PgConnectionWrapper in prod, sqlite3
in unit tests). Deterministic + idempotent: re-running the same session never
changes state or emits events (spec §6). Tiers only ever go UP (spec §2).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from gamification.catalog import (
    SILVER_SESSIONS_REQUIRED, STAR_BRONZE_SCORE, STAR_GOLD_SCORE,
    STAR_SILVER_SCORE, TIER_ORDER, TIME_LOSS_FULL_PENALTY_MS, XP_STAR, tier_rank,
)


def corner_score_from_time_loss(median_time_loss_ms: float) -> float:
    """100 at zero loss vs theoretical; 0 at TIME_LOSS_FULL_PENALTY_MS+."""
    frac = max(0.0, min(1.0, float(median_time_loss_ms) / TIME_LOSS_FULL_PENALTY_MS))
    return round(100.0 * (1.0 - frac), 1)


def compute_corner_scores(conn, session_id: str) -> dict[int, float]:
    """Per-corner scores for a session from corner_metrics (median across laps)."""
    rows = conn.execute(
        "SELECT corner_id, time_loss_ms FROM corner_metrics "
        "WHERE session_id = :sid AND time_loss_ms IS NOT NULL",
        {"sid": session_id},
    ).fetchall()
    by_corner: dict[int, list[float]] = {}
    for r in rows:
        cid = r["corner_id"] if isinstance(r, dict) else r[0]
        loss = r["time_loss_ms"] if isinstance(r, dict) else r[1]
        if cid is None or loss is None:
            continue
        by_corner.setdefault(int(cid), []).append(float(loss))
    scores: dict[int, float] = {}
    for cid, losses in by_corner.items():
        losses.sort()
        n = len(losses)
        median = losses[n // 2] if n % 2 else (losses[n // 2 - 1] + losses[n // 2]) / 2
        scores[cid] = corner_score_from_time_loss(median)
    return scores


def _target_tier(best_score: float, silver_sessions: list[str]) -> str:
    """The tier the driver QUALIFIES for given history."""
    if len(silver_sessions) >= SILVER_SESSIONS_REQUIRED:
        if best_score >= STAR_GOLD_SCORE:
            return "gold"
        return "silver"
    if best_score >= STAR_BRONZE_SCORE:
        return "bronze"
    return "none"


def update_corner_mastery(
    conn, driver_id: int, workspace_id: int, track_id: str, condition: str,
    corner_scores: dict[int, float], session_id: str,
) -> list[dict[str, Any]]:
    """Upsert star state for each corner; return NEW-star events only."""
    now = datetime.now(timezone.utc).isoformat()
    events: list[dict[str, Any]] = []

    for corner_id, score in sorted(corner_scores.items()):
        row = conn.execute(
            "SELECT tier, best_score, sessions_at_silver FROM corner_mastery "
            "WHERE workspace_id = :ws AND driver_id = :drv AND track_id = :trk "
            "AND corner_id = :cid AND condition = :cond",
            {"ws": workspace_id, "drv": driver_id, "trk": track_id,
             "cid": corner_id, "cond": condition},
        ).fetchone()

        if row is None:
            tier, best, silver_sessions = "none", 0.0, []
        else:
            tier = row["tier"] if isinstance(row, dict) else row[0]
            best = float((row["best_score"] if isinstance(row, dict) else row[1]) or 0)
            raw = (row["sessions_at_silver"] if isinstance(row, dict) else row[2]) or "[]"
            silver_sessions = json.loads(raw) if isinstance(raw, str) else list(raw)

        new_best = max(best, score)
        # Cap at the required count: only the first SILVER_SESSIONS_REQUIRED
        # distinct qualifying sessions matter. Capping the APPEND (not trimming)
        # keeps it idempotent — once full, an old session that isn't in the list
        # is never re-appended because the length guard short-circuits.
        if (
            score >= STAR_SILVER_SCORE
            and session_id not in silver_sessions
            and len(silver_sessions) < SILVER_SESSIONS_REQUIRED
        ):
            silver_sessions = silver_sessions + [session_id]
        new_tier = _target_tier(new_best, silver_sessions)
        # Tiers never go down.
        if tier_rank(new_tier) < tier_rank(tier):
            new_tier = tier
        # Tiers advance one step at a time (no skipping bronze→gold).
        if tier_rank(new_tier) > tier_rank(tier) + 1:
            new_tier = TIER_ORDER[tier_rank(tier) + 1]

        prev_raw = None if row is None else ((row["sessions_at_silver"] if isinstance(row, dict) else row[2]) or "[]")
        changed = (
            row is None
            or new_tier != tier
            or new_best != best
            or json.dumps(silver_sessions) != (prev_raw if isinstance(prev_raw, str) else json.dumps(list(prev_raw)))
        )

        if row is None:
            conn.execute(
                "INSERT INTO corner_mastery (workspace_id, driver_id, track_id, "
                "corner_id, condition, tier, best_score, sessions_at_silver, "
                "first_session_id, achieved_at, updated_at) "
                "VALUES (:ws, :drv, :trk, :cid, :cond, :tier, :best, :ss, :sid, :at, :at)",
                {"ws": workspace_id, "drv": driver_id, "trk": track_id,
                 "cid": corner_id, "cond": condition, "tier": new_tier,
                 "best": new_best, "ss": json.dumps(silver_sessions),
                 "sid": session_id, "at": now},  # first_session_id = session that CREATED this row (may be sub-bronze), not the first star
            )
        elif changed:
            conn.execute(
                "UPDATE corner_mastery SET tier = :tier, best_score = :best, "
                "sessions_at_silver = :ss, "
                "achieved_at = CASE WHEN :tier2 != tier THEN :at ELSE achieved_at END, "
                "updated_at = :at "
                "WHERE workspace_id = :ws AND driver_id = :drv AND track_id = :trk "
                "AND corner_id = :cid AND condition = :cond",
                {"tier": new_tier, "tier2": new_tier, "best": new_best,
                 "ss": json.dumps(silver_sessions), "at": now,
                 "ws": workspace_id, "drv": driver_id, "trk": track_id,
                 "cid": corner_id, "cond": condition},
            )

        if tier_rank(new_tier) > tier_rank(tier):
            events.append({
                "track_id": track_id, "corner_id": corner_id,
                "tier": new_tier, "xp": XP_STAR[new_tier], "score": score,
            })

    return events
