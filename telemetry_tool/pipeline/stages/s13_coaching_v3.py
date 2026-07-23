"""Pipeline stages S13e–S13g2: Coaching V3 analyzers, multi-session lookup, assembly, persist.

Each function is designed to be called via _safe_step() — returns None on failure
without crashing the pipeline. The orchestrator wires these after existing S13d.

Feature-flagged: COACHING_V3 env var (default ON, set =0 to disable).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def run_coaching_analyzers(
    corner_perfs: list[dict] | None,
    best_lap_df: Any | None,
    theoretical_result: Any | None,
    friction_model: Any | None,
    resampled_laps: dict | None,
    available_columns: set | None,
) -> dict:
    """S13e: Run all 6 physics analyzers for each corner.

    Returns dict with keys: trail_brakes, exit_cascades, traction_budgets,
    symptoms, throttle_lifts, weight_transfers. Values may be empty lists
    if data is insufficient.
    """
    from coaching.analyzers.trail_brake import analyze_trail_braking
    from coaching.analyzers.exit_speed import analyze_exit_cascades
    from coaching.analyzers.traction_budget import analyze_traction_budget
    from coaching.analyzers.symptom_detector import detect_symptoms
    from coaching.analyzers.throttle_lift import detect_throttle_lifts
    from coaching.analyzers.weight_transfer import compute_weight_transfer

    bundle: dict[str, list] = {
        "trail_brakes": [],
        "exit_cascades": [],
        "traction_budgets": [],
        "symptoms": [],
        "throttle_lifts": [],
        "weight_transfers": [],
    }

    if not corner_perfs:
        return bundle

    cols = available_columns or set()

    for cp in corner_perfs:
        cid = cp["corner_id"]

        # Get best lap data for this corner
        lap_df = _get_corner_lap_slice(best_lap_df, cp)

        # Trail brake
        try:
            if lap_df is not None:
                tb = analyze_trail_braking(cp, lap_df)
                bundle["trail_brakes"].append(tb)
        except Exception:
            logger.debug("Trail brake analysis failed for corner %s", cid, exc_info=True)

        # Traction budget
        try:
            if lap_df is not None and "s_apex" in cp:
                friction_max = _estimate_friction(friction_model, cp)
                tb = analyze_traction_budget(cp, lap_df, friction_max)
                bundle["traction_budgets"].append(tb)
        except Exception:
            logger.debug("Traction budget failed for corner %s", cid, exc_info=True)

        # Symptom detection
        try:
            if lap_df is not None:
                sd = detect_symptoms(cp, lap_df)
                bundle["symptoms"].append(sd)
        except Exception:
            logger.debug("Symptom detection failed for corner %s", cid, exc_info=True)

        # Throttle lifts
        try:
            if lap_df is not None:
                friction_max = _estimate_friction(friction_model, cp)
                lifts = detect_throttle_lifts(cp, lap_df, friction_max)
                bundle["throttle_lifts"].extend(lifts)
        except Exception:
            logger.debug("Throttle lift detection failed for corner %s", cid, exc_info=True)

        # Weight transfer
        try:
            braking_decel = abs(cp.get("braking_decel_mps2", 0) or 6.0)
            cornering_accel = abs(cp.get("cornering_accel_mps2", 0) or 5.0)
            exit_accel = abs(cp.get("exit_accel_mps2", 0) or 3.0)
            wt = compute_weight_transfer(
                corner_id=cid,
                braking_decel_mps2=braking_decel,
                cornering_accel_mps2=cornering_accel,
                exit_accel_mps2=exit_accel,
                vehicle_class=cp.get("vehicle_class", "car"),
            )
            bundle["weight_transfers"].append(wt)
        except Exception:
            logger.debug("Weight transfer failed for corner %s", cid, exc_info=True)

    # Exit cascades (needs all corners + theoretical)
    try:
        if best_lap_df is not None and theoretical_result is not None:
            if isinstance(theoretical_result, dict):
                track_length = theoretical_result.get("track_length_m", 0)
            elif hasattr(theoretical_result, "columns") and "Distance (m)" in theoretical_result.columns:
                track_length = float(theoretical_result["Distance (m)"].iloc[-1])
            else:
                track_length = 0
            if track_length > 0:
                cascades = analyze_exit_cascades(
                    corner_perfs, best_lap_df, theoretical_result, track_length,
                )
                bundle["exit_cascades"] = cascades
    except Exception:
        logger.debug("Exit cascade analysis failed", exc_info=True)

    return bundle


def run_multi_session_lookup(
    driver_id: int | None,
    track_id: int | None,
    corner_ids: list[int] | None,
) -> dict | None:
    """S13f: Query corner_progression for historical data.

    Returns None if USE_PG=0 or driver/track not available.
    """
    if os.environ.get("USE_PG", "0") == "0":
        return None
    if not driver_id or not track_id or not corner_ids:
        return None

    try:
        from coaching.persistence.queries import get_driver_corner_trends
        from web.db_pg import get_pg_connection

        conn = get_pg_connection()
        return get_driver_corner_trends(conn, driver_id, track_id, corner_ids)
    except Exception:
        logger.debug("Multi-session lookup failed", exc_info=True)
        return None


def run_enhanced_coaching(
    corner_perfs: list[dict] | None,
    coaching_v2: dict | None,
    scores: dict | None,
    lap_metrics: list | None,
    driving_style: dict | None,
    analyzer_bundle: dict | None,
    driver_history: dict | None,
    vehicle_class: str = "car",
    previous_goals: list[str] | None = None,
) -> dict | None:
    """S13g: Assemble full V3 coaching output.

    Falls back to coaching_v2 on any exception.
    """
    if not corner_perfs or not scores:
        return coaching_v2

    # Fail-loud (but non-fatal) vocabulary drift guard: every cause id that
    # _resolve_cause can emit must exist in BOTH the taxonomy and DRILL_LIBRARY,
    # else corners silently collapse to "Unknown cause". Log it, never kill a
    # real session. The hard CI gate is test_cause_vocabulary.py.
    try:
        from coaching.vocabulary_check import assert_cause_vocabulary_integrity
        assert_cause_vocabulary_integrity()
    except ValueError as exc:
        logger.error("coaching vocabulary drift: %s", exc)

    try:
        from coaching.composers.session_composer import compose_session_coaching
        from coaching.taxonomy.causes import CauseTaxonomy

        taxonomy = CauseTaxonomy()
        result = compose_session_coaching(
            corner_perfs=corner_perfs,
            coaching_v2=coaching_v2,
            scores=scores,
            lap_metrics=lap_metrics,
            driving_style=driving_style,
            analyzer_results=analyzer_bundle or {},
            taxonomy=taxonomy,
            vehicle_class=vehicle_class,
            driver_history=driver_history,
            previous_goals=previous_goals,
        )
        return result.to_dict()
    except Exception:
        logger.warning("Enhanced coaching assembly failed, falling back to V2",
                        exc_info=True)
        return coaching_v2


def persist_coaching_v3(
    coaching_dict: dict | None,
    analysis_json: dict | None,
    conn: Any | None,
    session_id: int | str | None,
    driver_id: int | None,
    track_id: int | None,
    corner_coaching: list[dict] | None,
) -> None:
    """S13g2: Write coaching_v3 to analysis_json and persist corner progression."""
    if coaching_dict is None:
        return

    # Store in analysis_json blob
    if analysis_json is not None:
        analysis_json["coaching_v3"] = coaching_dict

    # Persist corner progression to DB
    if (conn is not None and session_id and driver_id and track_id
            and corner_coaching and os.environ.get("USE_PG", "0") != "0"):
        try:
            from coaching.persistence.queries import store_corner_progression

            corners_data = []
            for cc in corner_coaching:
                corners_data.append({
                    "corner_id": cc.get("corner_id"),
                    "apex_speed_mps": _kmh_to_mps(cc.get("apex_speed_target_kmh")),
                    "entry_speed_mps": _kmh_to_mps(cc.get("entry_speed_target_kmh")),
                    "exit_speed_mps": _kmh_to_mps(cc.get("exit_speed_target_kmh")),
                    "braking_point_m": None,
                    "time_loss_s": cc.get("time_loss_corner_s"),
                    "grip_utilisation_pct": None,
                    "trail_brake_score": (
                        cc.get("trail_brake", {}).get("overall_score")
                        if cc.get("trail_brake") else None
                    ),
                    "primary_cause": cc.get("primary_cause"),
                    "theoretical_apex_mps": _kmh_to_mps(cc.get("apex_speed_target_kmh")),
                    "theoretical_entry_mps": _kmh_to_mps(cc.get("entry_speed_target_kmh")),
                    "theoretical_exit_mps": _kmh_to_mps(cc.get("exit_speed_target_kmh")),
                })

            import datetime
            store_corner_progression(
                conn=conn,
                workspace_id=getattr(conn, "_workspace_id", 1),
                driver_id=driver_id,
                track_id=track_id,
                session_id=session_id,
                session_date=datetime.date.today().isoformat(),
                corners=corners_data,
            )
        except Exception:
            logger.warning("Failed to persist corner progression", exc_info=True)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_corner_lap_slice(best_lap_df, corner_perf: dict):
    """Extract the portion of the best lap DataFrame for a corner."""
    if best_lap_df is None:
        return None
    try:
        import pandas as pd
        if not isinstance(best_lap_df, pd.DataFrame):
            return None

        s_start = corner_perf.get("s_start", 0)
        s_end = corner_perf.get("s_end", 0)

        dist_col = None
        for col in ("Distance (m)", "distance_m", "Distance"):
            if col in best_lap_df.columns:
                dist_col = col
                break

        if dist_col is None:
            return best_lap_df  # Return full DataFrame, let analyzers handle

        mask = (best_lap_df[dist_col] >= s_start) & (best_lap_df[dist_col] <= s_end)
        segment = best_lap_df.loc[mask].copy()
        return segment if len(segment) > 5 else None
    except Exception:
        return None


def _estimate_friction(friction_model, corner_perf: dict) -> float:
    """Estimate friction max from model or defaults."""
    if friction_model and isinstance(friction_model, dict):
        return friction_model.get("max_lateral_g", 1.2) * 9.81
    return 10.0  # ~1g default


def _kmh_to_mps(kmh: float | None) -> float | None:
    if kmh is None:
        return None
    return kmh / 3.6
