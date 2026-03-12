"""Lap repository — insert/query per-lap rows."""

from __future__ import annotations

import math
import sqlite3
from typing import Any, Optional

from db import queries as Q
from web.repos._helpers import _safe_float

import logging

logger = logging.getLogger(__name__)


# ── Seed / stall tuning constants ────────────────────────────
_ROLLING_MIN_SEED = 3          # candidates before attempting partition
_ROLLING_MAX_COLLECT = 6       # hard cap — use median fallback
_ROLLING_STALL_THRESHOLD = 5   # consecutive rejects → window reset
_SEED_GAP_RATIO = 0.20         # relative gap threshold for partition


def _partition_seed_candidates(
    candidates: list[tuple[int, float, float | None]],
    min_gap_ratio: float = _SEED_GAP_RATIO,
) -> tuple[
    list[tuple[int, float, float | None]] | None,
    list[tuple[int, float, float | None]] | None,
]:
    """Split seed candidates into inliers and outliers via gap detection.

    Sorts by time, finds the largest relative gap between consecutive
    times.  If no gap exceeds *min_gap_ratio*, all candidates are a
    homogeneous group (all returned as inliers, empty outliers).

    When a gap is found and the faster (lower-time) group is at least
    as large as the slower group, the faster group is returned as
    inliers — in motorsport, outliers are almost always slow laps
    (traffic, spins, pit stops).  If the fast group is smaller, the
    split is ambiguous and ``(None, None)`` is returned to signal
    that the caller should collect more candidates.
    """
    if len(candidates) < 3:
        return candidates, []

    sorted_cands = sorted(candidates, key=lambda x: x[1])
    times = [t for _, t, _ in sorted_cands]

    best_idx = -1
    best_ratio = 0.0
    for i in range(len(times) - 1):
        ref = times[i] if times[i] > 0 else 1.0
        ratio = (times[i + 1] - times[i]) / ref
        if ratio > best_ratio:
            best_ratio = ratio
            best_idx = i

    if best_ratio < min_gap_ratio:
        return candidates, []  # homogeneous — all inliers

    fast_group = sorted_cands[: best_idx + 1]
    slow_group = sorted_cands[best_idx + 1 :]

    if len(fast_group) >= len(slow_group):
        return fast_group, slow_group
    return None, None  # ambiguous — caller should collect more


def _commit_seed_fallback(
    seed_pool: list[tuple[int, float, float | None]],
    result: dict[int, tuple[bool, str | None]],
    valid_times: list[float],
    valid_dists: list[float],
) -> None:
    """Median-based fallback when gap partitioning fails at MAX_COLLECT.

    Accepts candidates within 15% of the median time; flags the rest.
    If no candidates pass, accepts all (degenerate session).
    """
    all_t = sorted(ts for _, ts, _ in seed_pool)
    median_t = all_t[len(all_t) // 2]

    accepted_any = False
    for ln, ts, dm in seed_pool:
        dev = abs(ts - median_t) / median_t if median_t > 0 else 0
        if dev <= 0.15:
            result[ln] = (True, None)
            valid_times.append(ts)
            if dm is not None:
                valid_dists.append(dm)
            accepted_any = True
        else:
            result[ln] = (False, "Time anomaly")

    if not accepted_any:
        # All candidates are spread out — accept all as last resort
        for ln, ts, dm in seed_pool:
            result[ln] = (True, None)
            valid_times.append(ts)
            if dm is not None:
                valid_dists.append(dm)


def _rolling_avg_validity(
    lap_metrics: list[dict[str, Any]],
    window: int = 5,
    lo: float = 0.90,
    hi: float = 1.10,
    exclude_laps: set[int] | None = None,
) -> dict[int, tuple[bool, str | None]]:
    """Determine lap validity using rolling average of valid laps.

    For each lap (processed in lap_number order), compute the rolling
    average of time and distance from the last ``window`` *valid* laps.
    A lap is valid if both its time AND distance fall within [lo, hi]
    of the rolling average.  Invalid laps are excluded from the rolling
    window so one bad lap cannot cascade-invalidate subsequent good laps.

    Seed hardening
    ~~~~~~~~~~~~~~
    Instead of blindly accepting the first 2 laps, collects up to
    ``_ROLLING_MIN_SEED`` candidates and uses gap-based outlier
    detection to reject anomalous early laps before they can poison
    the window.

    Stall recovery
    ~~~~~~~~~~~~~~
    If ``_ROLLING_STALL_THRESHOLD`` consecutive laps are rejected, the
    window is likely poisoned despite defenses.  The window resets to
    the median of all post-seed times seen so far.

    Parameters
    ----------
    exclude_laps : set[int] | None
        Lap numbers already flagged by the pipeline.  Skipped entirely
        so a known-bad lap cannot contaminate the seed or rolling window.

    Returns {lap_number: (is_valid, invalid_reason)}.
    """
    ordered = sorted(lap_metrics, key=lambda lm: lm.get("lap_number", 0))
    exclude_laps = exclude_laps or set()

    valid_times: list[float] = []
    valid_dists: list[float] = []
    result: dict[int, tuple[bool, str | None]] = {}

    seed_pool: list[tuple[int, float, float | None]] = []
    seed_committed = False
    consecutive_rejects = 0
    all_post_seed_times: list[float] = []  # for stall recovery

    for lm in ordered:
        lap_num = lm.get("lap_number")
        if lap_num is None:
            continue

        if lap_num in exclude_laps:
            continue

        time_s = _safe_float(lm.get("lap_time_s"))
        dist_m = _safe_float(lm.get("line_length_m"))

        if time_s is None or time_s <= 0:
            result[lap_num] = (False, "No lap time")
            continue
        if dist_m is None or dist_m <= 0:
            dist_m = None

        # ── Seed collection phase ──────────────────────────────
        if not seed_committed:
            seed_pool.append((lap_num, time_s, dist_m))

            if len(seed_pool) >= _ROLLING_MIN_SEED:
                inliers, outliers = _partition_seed_candidates(seed_pool)

                if inliers is not None and len(inliers) >= 2:
                    # Clean partition or homogeneous group
                    for ln, ts, dm in inliers:
                        result[ln] = (True, None)
                        valid_times.append(ts)
                        if dm is not None:
                            valid_dists.append(dm)
                    if outliers:
                        for ln, ts, dm in outliers:
                            result[ln] = (False, "Time anomaly")
                    seed_committed = True
                elif len(seed_pool) >= _ROLLING_MAX_COLLECT:
                    _commit_seed_fallback(
                        seed_pool, result, valid_times, valid_dists,
                    )
                    seed_committed = True
            continue

        all_post_seed_times.append(time_s)

        # ── Rolling average validation ──────────────────────────
        recent_times = valid_times[-window:]
        avg_time = sum(recent_times) / len(recent_times)

        time_ok = (avg_time * lo) <= time_s <= (avg_time * hi)

        dist_ok = True
        reason_parts: list[str] = []

        if dist_m is not None and len(valid_dists) >= 2:
            recent_dists = valid_dists[-window:]
            avg_dist = sum(recent_dists) / len(recent_dists)
            dist_ok = (avg_dist * lo) <= dist_m <= (avg_dist * hi)

        if not time_ok:
            reason_parts.append("Time anomaly")
        if not dist_ok:
            reason_parts.append("Distance anomaly")

        if time_ok and dist_ok:
            result[lap_num] = (True, None)
            valid_times.append(time_s)
            if dist_m is not None:
                valid_dists.append(dist_m)
            consecutive_rejects = 0
        else:
            result[lap_num] = (False, " + ".join(reason_parts))
            consecutive_rejects += 1

            # Stall recovery — window likely poisoned
            if (consecutive_rejects >= _ROLLING_STALL_THRESHOLD
                    and all_post_seed_times):
                stall_sorted = sorted(all_post_seed_times)
                median_reset = stall_sorted[len(stall_sorted) // 2]
                valid_times.clear()
                valid_times.append(median_reset)
                consecutive_rejects = 0
                logger.info(
                    "Rolling-avg stall: resetting window to median %.2fs "
                    "after %d consecutive rejects.",
                    median_reset, _ROLLING_STALL_THRESHOLD,
                )

    # Very short session — seed never committed
    if not seed_committed:
        for ln, ts, dm in seed_pool:
            if ln not in result:
                result[ln] = (True, None)

    return result


def _pipeline_validity(
    summary: dict[str, Any],
) -> dict[int, tuple[bool, str]]:
    """Build lap validity from pipeline analysis dicts.

    Priority order (highest wins):
    1. Joker lap
    2. Invalid lap analysis (track cuts, incidents, manual exclusions)
    3. Incomplete lap analysis
    4. Distance anomalies (outlaps, inlaps, pit laps, track deviation)
    5. Time anomalies
    6. Endurance pit relabeling (near stint boundary → "Pitted lap")

    Returns {lap_number: (is_valid, invalid_reason)} for flagged laps only.
    Laps not in the dict are considered valid.
    """
    result: dict[int, tuple[bool, str]] = {}

    # ── Extract pipeline analysis dicts ──────────────────────────
    trim_report = summary.get("trim_report") or {}
    outlap_analysis = trim_report.get("outlap_analysis") or {}
    outlap_set = set(outlap_analysis.get("outlap_numbers") or [])
    inlap_set = set(outlap_analysis.get("inlap_numbers") or [])
    flagged_set = set(outlap_analysis.get("flagged_only") or [])

    invalid_analysis = summary.get("invalid_lap_analysis") or {}
    invalid_set = set(invalid_analysis.get("invalid_laps") or [])
    track_cut_set = set(invalid_analysis.get("track_cuts") or [])
    incident_set = set(invalid_analysis.get("incidents") or [])
    manual_set = set(invalid_analysis.get("manual") or [])

    incomplete_analysis = summary.get("incomplete_lap_analysis") or {}
    incomplete_set = set(incomplete_analysis.get("incomplete_laps") or [])

    anomalous_analysis = summary.get("anomalous_lap_analysis") or {}
    anomalous_dist = set(anomalous_analysis.get("dist_flagged") or [])
    anomalous_time = set(anomalous_analysis.get("time_flagged") or [])

    deviation_analysis = summary.get("line_deviation_analysis") or {}
    deviated_set = set(deviation_analysis.get("deviated_laps") or [])

    # ── Distance-based anomalies with sub-labels ─────────────────
    # Priority within distance: outlap/inlap > pit lap > track deviation
    #                           > incomplete > generic distance anomaly
    dist_labels: dict[int, str] = {}
    for lap_num in anomalous_dist:
        dist_labels[lap_num] = "Distance anomaly"
    for lap_num in incomplete_set:
        dist_labels[lap_num] = "Incomplete"
    for lap_num in deviated_set:
        dist_labels[lap_num] = "Track deviation"
    for lap_num in flagged_set:
        dist_labels[lap_num] = "Pit lap"
    for lap_num in outlap_set:
        if lap_num in inlap_set:
            dist_labels[lap_num] = "Inlap"
        else:
            dist_labels[lap_num] = "Outlap"

    all_dist_flagged = set(dist_labels.keys())

    # ── Endurance pit detection ──────────────────────────────────
    meta = summary.get("session_meta") or {}
    session_type = meta.get("session_type", "practice")
    endurance_types = {"endurance", "endurance_race", "endurance_stint"}
    stint_boundary_laps: set[int] = set()

    if session_type in endurance_types:
        drivers = meta.get("drivers") or []
        for drv in drivers:
            lr = drv.get("lap_range")
            if lr and len(lr) == 2:
                stint_boundary_laps.add(lr[1])
                stint_boundary_laps.add(lr[0])

    def _near_stint_boundary(lap: int) -> bool:
        for boundary in stint_boundary_laps:
            if abs(lap - boundary) <= 3:
                return True
        return False

    # ── Build per-lap results ────────────────────────────────────
    all_flagged = invalid_set | all_dist_flagged | anomalous_time | incomplete_set
    for lap_num in all_flagged:
        if lap_num in invalid_set:
            if stint_boundary_laps and _near_stint_boundary(lap_num):
                result[lap_num] = (False, "Pitted lap")
            elif lap_num in manual_set:
                result[lap_num] = (False, "Manual exclusion")
            elif lap_num in track_cut_set:
                result[lap_num] = (False, "Track cut")
            elif lap_num in incident_set:
                result[lap_num] = (False, "Incident")
            else:
                result[lap_num] = (False, "Invalid")
        elif lap_num in all_dist_flagged:
            if stint_boundary_laps and _near_stint_boundary(lap_num):
                result[lap_num] = (False, "Pitted lap")
            else:
                result[lap_num] = (False, dist_labels[lap_num])
        elif lap_num in anomalous_time:
            if stint_boundary_laps and _near_stint_boundary(lap_num):
                result[lap_num] = (False, "Pitted lap")
            else:
                result[lap_num] = (False, "Time anomaly")

    return result


def _has_pipeline_analysis(summary: dict[str, Any]) -> bool:
    """Check if the summary contains any populated pipeline analysis dicts."""
    for key in ("invalid_lap_analysis", "incomplete_lap_analysis",
                "anomalous_lap_analysis", "line_deviation_analysis"):
        analysis = summary.get(key) or {}
        for v in analysis.values():
            if isinstance(v, (list, set)) and len(v) > 0:
                return True
    trim = summary.get("trim_report") or {}
    outlap = trim.get("outlap_analysis") or {}
    for v in outlap.values():
        if isinstance(v, (list, set)) and len(v) > 0:
            return True
    return False


def insert_laps(
    conn: sqlite3.Connection,
    session_id: str,
    summary: dict[str, Any],
) -> int:
    """Insert per-lap rows from the pipeline summary. Returns count."""
    lap_metrics = summary.get("lap_metrics") or []
    best_key = summary.get("best_lap_key")
    lap_to_phase = summary.get("lap_to_phase") or {}
    joker_lap_number = summary.get("joker_lap_number")

    # ── Blended validity detection ──────────────────────────────
    # Layer 1: Pipeline analysis dicts (outlaps, track cuts,
    # incidents, anomalous laps) — rich, label-specific.
    # Layer 2: Rolling-average catches anything the pipeline missed
    # (e.g. laps that slipped through pipeline detection).
    # Pipeline labels take priority; rolling-avg fills gaps.
    # Pipeline-flagged laps are excluded from the rolling-avg seed
    # so a known-bad lap cannot poison the rolling window.
    pipeline_validity = _pipeline_validity(summary)
    pipeline_flagged = set(pipeline_validity.keys())
    rolling_validity = _rolling_avg_validity(
        lap_metrics, exclude_laps=pipeline_flagged,
    )

    # Merge: pipeline wins where it has data, rolling-avg fills rest
    validity: dict[int, tuple[bool, str | None]] = {}
    all_lap_nums = {lm.get("lap_number") for lm in lap_metrics if lm.get("lap_number") is not None}
    for lap_num in all_lap_nums:
        if lap_num in pipeline_validity:
            # Pipeline flagged this lap — use its label
            validity[lap_num] = pipeline_validity[lap_num]
        elif lap_num in rolling_validity:
            # Rolling-avg caught something the pipeline didn't
            validity[lap_num] = rolling_validity[lap_num]
        else:
            validity[lap_num] = (True, None)

    count = 0
    for lm in lap_metrics:
        lap_num = lm.get("lap_number")
        if lap_num is None:
            continue

        is_joker = False
        is_valid, invalid_reason = validity.get(lap_num, (True, None))

        # Joker laps override — always invalid with specific reason
        if joker_lap_number is not None and lap_num == joker_lap_number:
            is_joker = True
            is_valid = False
            invalid_reason = "Joker lap"

        conn.execute(Q.INSERT_LAP, {
            "session_id":       session_id,
            "lap_number":       lap_num,
            "lap_time_s":       _safe_float(lm.get("lap_time_s")),
            "speed_mean_mps":   _safe_float(lm.get("speed_mean_mps")),
            "speed_max_mps":    _safe_float(lm.get("speed_max_mps")),
            "braking_max_mps2": _safe_float(lm.get("braking_max_mps2")),
            "accel_max_mps2":   _safe_float(lm.get("accel_max_mps2")),
            "line_length_m":    _safe_float(lm.get("line_length_m")),
            "is_valid":         is_valid,
            "is_best":          lap_num == best_key,
            "phase_id":         lap_to_phase.get(lap_num),
            "invalid_reason":   invalid_reason,
            "is_joker":         is_joker,
        })
        count += 1
    return count


def revalidate_session_laps(
    conn: sqlite3.Connection,
    session_id: str,
) -> dict[str, Any]:
    """Re-run blended validity on an existing session's laps.

    Reads stored lap metrics + analysis_json, reconstructs the summary,
    and re-applies pipeline + rolling-avg validation with seed hardening.
    Updates laps table in-place.  Returns change summary.
    """
    from web.repos.analysis_repo import get_analysis_json

    laps = conn.execute(
        Q.SELECT_LAPS_FOR_SESSION, {"session_id": session_id}
    ).fetchall()
    if not laps:
        return {"updated": 0, "changes": []}

    # Reconstruct lap_metrics from stored rows
    lap_metrics = []
    for r in laps:
        lap_metrics.append({
            "lap_number": r["lap_number"],
            "lap_time_s": r["lap_time_s"],
            "line_length_m": r["line_length_m"],
        })

    # Reconstruct partial summary from analysis_json
    analysis = get_analysis_json(conn, session_id) or {}
    summary: dict[str, Any] = {
        "lap_metrics": lap_metrics,
    }
    for key in ("invalid_lap_analysis", "incomplete_lap_analysis",
                "anomalous_lap_analysis", "line_deviation_analysis",
                "trim_report"):
        if key in analysis:
            summary[key] = analysis[key]

    # Re-run blended validity
    pipeline_validity = _pipeline_validity(summary)
    pipeline_flagged = set(pipeline_validity.keys())
    rolling_validity = _rolling_avg_validity(
        lap_metrics, exclude_laps=pipeline_flagged,
    )

    all_lap_nums = {lm["lap_number"] for lm in lap_metrics}
    validity: dict[int, tuple[bool, str | None]] = {}
    for lap_num in all_lap_nums:
        if lap_num in pipeline_validity:
            validity[lap_num] = pipeline_validity[lap_num]
        elif lap_num in rolling_validity:
            validity[lap_num] = rolling_validity[lap_num]
        else:
            validity[lap_num] = (True, None)

    # Compare and update changed laps
    changes = []
    for r in laps:
        ln = r["lap_number"]
        old_valid = bool(r["is_valid"])
        old_reason = r["invalid_reason"]
        new_valid, new_reason = validity.get(ln, (True, None))

        # Preserve joker status
        if r.get("is_joker"):
            continue

        if old_valid != new_valid or old_reason != new_reason:
            conn.execute(
                "UPDATE laps SET is_valid = :valid, invalid_reason = :reason "
                "WHERE session_id = :sid AND lap_number = :ln",
                {"valid": new_valid, "reason": new_reason,
                 "sid": session_id, "ln": ln},
            )
            changes.append({
                "lap": ln,
                "was": {"valid": old_valid, "reason": old_reason},
                "now": {"valid": new_valid, "reason": new_reason},
            })

    conn.commit()
    return {"updated": len(changes), "changes": changes}


def get_laps_for_session(
    conn: sqlite3.Connection,
    session_id: str,
) -> list[dict]:
    rows = conn.execute(
        Q.SELECT_LAPS_FOR_SESSION, {"session_id": session_id}
    ).fetchall()
    return [dict(r) for r in rows]


def get_gps_lap_numbers(
    conn: sqlite3.Connection,
    session_id: str,
) -> list[int]:
    rows = conn.execute(
        Q.SELECT_GPS_LAPS_FOR_SESSION, {"session_id": session_id}
    ).fetchall()
    return [r["lap_number"] for r in rows]
