"""Quest engine — generate machine-verifiable quests from session facts and
verify them on later uploads. Pure functions over an open connection
(PgConnectionWrapper in prod, sqlite3 in tests). Deterministic + idempotent;
caller commits. Mirrors gamification/mastery.py."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from gamification.quest_metrics import (
    APEX_SPEED_DELTA_KMH, BEST_LAP_TARGET_PCT, CLEAN_LAP_MAX_RATIO,
    CONSISTENCY_DELTA_PCT, LAPS_FALLBACK, METRICS, QUEST_XP,
    comparator_for, render_label,
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
    # "clean laps" — stricter than the pipeline's canonical n_laps (which counts every t>0 lap).
    # We drop out/cool-down laps (> CLEAN_LAP_MAX_RATIO × fastest) so the "complete N clean laps" quest can't be gamed by slow laps. Intentionally diverges from the session-card lap count.
    if raw_laps:
        _min_lap = min(raw_laps)
        laps = [t for t in raw_laps if t < _min_lap * CLEAN_LAP_MAX_RATIO]
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
            facts["best_lap_improvement_pct"] = round((pb - cur_best) / pb * 100.0, 1)

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


def _active_metric_scopes(conn, driver_id: int, workspace_id: int) -> set[str]:
    rows = conn.execute(
        "SELECT metric, spec FROM quests WHERE driver_id = :drv "
        "AND workspace_id = :ws AND status = 'active'",
        {"drv": driver_id, "ws": workspace_id},
    ).fetchall()
    out: set[str] = set()
    for r in rows:
        d = dict(r) if not isinstance(r, dict) else r
        spec = json.loads(d["spec"]) if isinstance(d.get("spec"), str) else (d.get("spec") or {})
        cid = (spec.get("scope") or {}).get("corner_id")
        out.add(f"{d['metric']}@{cid}" if cid is not None else str(d["metric"]))
    return out


def _insert_quest(conn, driver_id, workspace_id, session_id, metric, target,
                  baseline, corner_id, xp) -> dict:
    comparator = comparator_for(metric)
    scope = {"corner_id": int(corner_id)} if corner_id is not None else {}
    spec = {"metric": metric, "comparator": comparator, "target": target,
            "baseline": baseline, "scope": scope}
    human = render_label(metric, target, corner_id)
    now = datetime.now(timezone.utc).isoformat()
    expires = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
    conn.execute(
        "INSERT INTO quests (workspace_id, driver_id, spec, metric, comparator, "
        "target, baseline, human_text, xp, status, focused, source_session_id, "
        "created_at, expires_at) VALUES (:ws, :drv, :spec, :metric, :cmp, :tgt, "
        ":base, :human, :xp, 'active', false, :sid, :now, :exp)",
        {"ws": workspace_id, "drv": driver_id, "spec": json.dumps(spec),
         "metric": metric, "cmp": comparator, "tgt": target, "base": baseline,
         "human": human, "xp": xp, "sid": session_id, "now": now, "exp": expires},
    )
    return {"metric": metric, "comparator": comparator, "target": target,
            "baseline": baseline, "scope": scope, "human_text": human, "xp": xp}


def generate_quests(conn, facts: dict[str, float], driver_id: int,
                    workspace_id: int, session_id: str, max_quests: int = 3) -> list[dict]:
    """Emit up to ``max_quests`` machine-verifiable quests derived from session
    facts (the coaching 'findings' are the weak corners / high CV the facts
    capture). Skips metric@scope that already has an active quest. Guarantees
    at least one quest (activity fallback)."""
    active = _active_metric_scopes(conn, driver_id, workspace_id)
    created: list[dict] = []

    def _take(metric, target, baseline, corner_id, bucket):
        key = f"{metric}@{corner_id}" if corner_id is not None else metric
        if key in active or len(created) >= max_quests:
            return
        active.add(key)
        created.append(_insert_quest(conn, driver_id, workspace_id, session_id,
                                     metric, target, baseline, corner_id, QUEST_XP[bucket]))

    # 1. Weakest corner (highest median time loss) → carry more apex speed there.
    corner_losses = {
        int(k.split("@")[1]): v for k, v in facts.items()
        if k.startswith("corner.time_loss_ms@")
    }
    if corner_losses:
        weakest = max(corner_losses, key=corner_losses.get)
        apex_key = f"corner.apex_speed_kmh@{weakest}"
        if apex_key in facts:
            base = facts[apex_key]
            _take("corner.apex_speed_kmh", round(base + APEX_SPEED_DELTA_KMH, 1), base, weakest, "corner")

    # 2. Consistency, if loose (CV > 5%).
    cv = facts.get("consistency_cv_pct")
    if cv is not None and cv > 5.0:
        _take("consistency_cv_pct", round(cv - CONSISTENCY_DELTA_PCT, 1), cv, None, "session")

    # 3. Beat the personal best by a bit (only if we have a PB baseline).
    if "best_lap_improvement_pct" in facts:
        _take("best_lap_improvement_pct", BEST_LAP_TARGET_PCT, 0.0, None, "session")

    # 4. Activity fallback — always leave the driver one target.
    # Activity fallback guarantees the driver is never left with ZERO active quests: when "active" is empty, laps_completed can't dedup-skip, so this always fires.
    # When the driver is already saturated (all relevant metrics have active quests), returning [] new quests is intentional — they still have quests to pursue, and we avoid piling on duplicates.
    if not created:
        base = facts.get("laps_completed", 0.0)
        _take("laps_completed", float(int(base) + LAPS_FALLBACK), base, None, "activity")

    return created


def _passes(value: float, comparator: str, target: float) -> bool:
    if value is None:
        return False
    return value >= target if comparator == ">=" else value <= target


def verify_quests(conn, facts: dict[str, float], driver_id: int,
                  workspace_id: int, session_id: str) -> list[dict]:
    """Evaluate the driver's active quests against this session's facts; mark
    passers completed and return them (with xp). Idempotent: completed/expired
    quests are not evaluated."""
    rows = conn.execute(
        "SELECT id, spec, metric, comparator, target, human_text, xp FROM quests "
        "WHERE driver_id = :drv AND workspace_id = :ws AND status = 'active'",
        {"drv": driver_id, "ws": workspace_id},
    ).fetchall()
    now = datetime.now(timezone.utc).isoformat()
    done: list[dict] = []
    for r in rows:
        d = dict(r) if not isinstance(r, dict) else r
        spec = json.loads(d["spec"]) if isinstance(d.get("spec"), str) else (d.get("spec") or {})
        cid = (spec.get("scope") or {}).get("corner_id")
        fact_key = f"{d['metric']}@{int(cid)}" if cid is not None else d["metric"]
        if _passes(facts.get(fact_key), d["comparator"], float(d["target"])):
            conn.execute(
                "UPDATE quests SET status = 'completed', completed_at = :now WHERE id = :id",
                {"now": now, "id": d["id"]},
            )
            done.append({"id": d["id"], "metric": d["metric"], "xp": int(d["xp"]),
                         "human_text": d["human_text"]})
    return done


def expire_stale_quests(conn, driver_id: int, workspace_id: int, now_iso: str | None = None) -> int:
    """Mark active quests past expires_at as 'expired'. Returns count."""
    now_iso = now_iso or datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "UPDATE quests SET status = 'expired' WHERE driver_id = :drv AND workspace_id = :ws "
        "AND status = 'active' AND expires_at IS NOT NULL AND expires_at < :now",
        {"drv": driver_id, "ws": workspace_id, "now": now_iso},
    )
    return cur.rowcount if hasattr(cur, "rowcount") and isinstance(cur.rowcount, int) else 0


def weeks_since_last_session(conn, driver_id: int, workspace_id: int,
                             session_id: str, session_date: str) -> int:
    """Whole weeks between this session and the driver's previous one.
    0 if there is no prior session."""
    from datetime import date
    row = conn.execute(
        "SELECT MAX(session_date) AS prev FROM sessions "
        "WHERE driver_id = :drv AND workspace_id = :ws AND session_id != :sid "
        "AND session_date IS NOT NULL",
        {"drv": driver_id, "ws": workspace_id, "sid": session_id},
    ).fetchone()
    prev = (row["prev"] if isinstance(row, dict) else row[0]) if row else None
    if not prev:
        return 0
    try:
        d_prev = date.fromisoformat(str(prev)[:10])
        d_now = date.fromisoformat(str(session_date)[:10])
    except (ValueError, TypeError):
        return 0
    return max(0, (d_now - d_prev).days // 7)
