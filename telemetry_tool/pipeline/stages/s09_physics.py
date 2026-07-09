"""
Stage 09 — Physics Pipeline
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Steps 09a-09i: reference line, track boundaries, line deviations,
joker detection, deltas, curvature, friction, vehicle model,
data quality, progressive physics, traffic, clustering, grip map.
"""
from __future__ import annotations

import inspect
import logging
from typing import Any, Optional

import pandas as pd

from pipeline.helpers import _COL_DIST, lazy_import  # noqa: F401

logger = logging.getLogger(__name__)


# ── 09a: Reference line ─────────────────────────────────────────────

def run_reference_line(
    resampled_laps: dict[int, pd.DataFrame],
    *,
    exclude_laps: Optional[set[int]] = None,
) -> pd.DataFrame:
    """Step 09a: Compute reference line. Returns DataFrame."""
    ref_mod = lazy_import("reference_line")
    if ref_mod is None:
        raise ImportError("reference_line module unavailable")
    sig = inspect.signature(ref_mod.compute_reference_line)
    if "exclude_laps" in sig.parameters:
        return ref_mod.compute_reference_line(
            resampled_laps, exclude_laps=exclude_laps or None,
        )
    return ref_mod.compute_reference_line(resampled_laps)


# ── 09a2: Track boundaries ──────────────────────────────────────────

def run_track_boundaries(
    resampled_laps: dict[int, pd.DataFrame],
    reference_line: Optional[pd.DataFrame],
) -> Any:
    """Step 09a2: Estimate track boundaries. Returns result or None."""
    ref_mod = lazy_import("reference_line")
    if ref_mod is None or not hasattr(ref_mod, "estimate_track_boundaries"):
        return None
    if reference_line is None or not resampled_laps:
        return None
    return ref_mod.estimate_track_boundaries(resampled_laps, reference_line)


# ── 08h (deferred): Line deviation detection ────────────────────────

def run_line_deviation_detection(
    resampled_laps: dict[int, pd.DataFrame],
    reference_line: Optional[pd.DataFrame],
    already_excluded: set[int],
) -> tuple[set[int], Optional[dict[str, Any]]]:
    """Step 08h (deferred): Line deviation detection.
    Returns (deviated_set, analysis_dict)."""
    trim_mod = lazy_import("session_trimming")
    if trim_mod is None or not hasattr(trim_mod, "identify_line_deviations"):
        return set(), None
    if not resampled_laps or reference_line is None:
        return set(), None
    result = trim_mod.identify_line_deviations(
        resampled_laps, reference_line, excluded_laps=already_excluded,
    )
    if result is None:
        return set(), None
    return result.get("deviated_laps", set()), result


# ── 08j: Joker lap detection ────────────────────────────────────────

def run_joker_detection(
    session_meta: dict[str, Any],
    track_id: str,
    lap_metrics: list[dict[str, Any]],
    lap_times: list[float],
    *,
    invalid_lap_set: frozenset[int] = frozenset(),
    incomplete_lap_set: frozenset[int] = frozenset(),
    anomalous_lap_set: frozenset[int] = frozenset(),
    deviated_lap_set: frozenset[int] = frozenset(),
    joker_callback: Any = None,
) -> tuple[set[int], Optional[dict[str, Any]], set[int]]:
    """Step 08j: Joker lap detection.
    Returns (joker_lap_set, joker_result_dict, laps_added_to_invalid)."""
    joker_lap_set: set[int] = set()
    laps_added_to_invalid: set[int] = set()

    if not session_meta.get("enable_joker", False):
        return joker_lap_set, None, laps_added_to_invalid

    # Optional: look up expected deltas from DB.
    expected_dist: Optional[float] = None
    expected_time: Optional[float] = None
    try:
        from web.db import get_db_connection
        conn = get_db_connection()
        row = conn.execute(
            "SELECT joker_distance_delta_m, joker_time_delta_s "
            "FROM tracks WHERE track_id = :tid",
            {"tid": track_id},
        ).fetchone()
        if row:
            expected_dist = row["joker_distance_delta_m"]
            expected_time = row["joker_time_delta_s"]
    except Exception:
        pass  # CLI mode or DB not available.

    try:
        from kart_envelope.processing.joker_detection import detect_joker_lap
    except ImportError:
        logger.warning("joker_detection unavailable — skipping")
        return joker_lap_set, None, laps_added_to_invalid

    already_excluded = (
        set(invalid_lap_set) | set(incomplete_lap_set)
        | set(anomalous_lap_set) | set(deviated_lap_set)
    )
    result = detect_joker_lap(
        lap_metrics, lap_times,
        expected_distance_delta_m=expected_dist,
        expected_time_delta_s=expected_time,
        excluded_laps=already_excluded,
    )
    if result is None or result.candidate_lap is None:
        return joker_lap_set, None, laps_added_to_invalid

    result_dict: dict[str, Any] = {
        "candidate_lap": result.candidate_lap,
        "confidence": result.confidence,
        "all_distances": result.all_distances,
        "median_distance": result.median_distance,
        "delta_from_median": result.delta_from_median,
        "all_times": result.all_times,
        "median_time": result.median_time,
        "time_delta_from_median": result.time_delta_from_median,
        "reason": result.reason,
    }

    confirmed_lap = None
    if joker_callback is not None:
        confirmed_lap = joker_callback(result)
    elif result.confidence >= 0.7:
        confirmed_lap = result.candidate_lap
        logger.info("Auto-accepted joker lap %d (confidence %.2f).",
                     confirmed_lap, result.confidence)

    if confirmed_lap is not None:
        joker_lap_set.add(confirmed_lap)
        logger.info("Joker lap confirmed: lap %d.", confirmed_lap)
    else:
        laps_added_to_invalid.add(result.candidate_lap)
        logger.info("Joker lap rejected: lap %d added to invalid set.",
                     result.candidate_lap)

    return joker_lap_set, result_dict, laps_added_to_invalid


# ── 09: Deltas vs best lap ──────────────────────────────────────────

def run_deltas(
    resampled_laps: dict[int, pd.DataFrame],
    best_lap_df: Optional[pd.DataFrame],
    best_lap_key: Optional[int],
    excluded_laps: set[int],
    valid_times: list[tuple[int, float]],
) -> tuple[list[dict[str, Any]], list[list[float]]]:
    """Step 09: Compute deltas vs best lap. Returns (delta_segments, segment_losses)."""
    delta_mod = lazy_import("deltas")
    if delta_mod is None:
        raise ImportError("deltas module unavailable")
    if best_lap_df is None or len(valid_times) < 2:
        return [], []

    ref = best_lap_df
    all_segs: list[dict[str, Any]] = []
    all_losses: list[list[float]] = []

    for ln in sorted(resampled_laps.keys()):
        if ln in excluded_laps:
            continue
        cmp = resampled_laps[ln]
        if ln == best_lap_key:
            try:
                curve = delta_mod.compute_delta_curve(ref, ref)
                segs = delta_mod.segment_time_loss(curve)
                all_losses.append([s.get("time_loss_ms", 0.0) for s in segs])
            except Exception:
                all_losses.append([0.0] * 20)
            continue
        try:
            causes = delta_mod.classify_time_loss_cause(ref, cmp)
            all_segs.extend(causes)
            all_losses.append([s.get("time_loss_ms", 0.0) for s in causes])
        except Exception as exc:
            logger.debug("Delta for lap %d failed: %s", ln, exc)
            all_losses.append([0.0] * 20)

    return all_segs, all_losses


# ── 09b: Curvature profile ──────────────────────────────────────────

def run_curvature(reference_line: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Step 09b: Curvature profile from reference line. Returns DataFrame."""
    ref_mod = lazy_import("reference_line")
    if ref_mod is None:
        raise ImportError("reference_line module unavailable")
    if reference_line is None:
        raise ValueError("No reference line for curvature computation")
    return ref_mod.compute_curvature_profile(reference_line)


# ── 09c: Friction model ─────────────────────────────────────────────

def run_friction_model(resampled_laps: dict[int, pd.DataFrame]) -> Any:
    """Step 09c: Build friction model. Returns friction_circle."""
    fric_mod = lazy_import("friction_model")
    if fric_mod is None:
        raise ImportError("friction_model module unavailable")
    return fric_mod.build_friction_model(resampled_laps)


# ── 09d + 09d2: Vehicle model + kart traction fix ───────────────────

def run_vehicle_model(
    friction_circle: Any,
    lap_metrics: list[dict[str, Any]],
    *,
    vehicle_overrides: Optional[dict[str, Any]] = None,
) -> Any:
    """Step 09d + 09d2: Vehicle classification + kart traction fix.
    Returns ``(vehicle_params, friction_circle)`` — the friction model is the
    kart-floored copy when applicable (``apply_kart_traction_floor`` returns a new
    object; the orchestrator adopts it as ``corrected_friction``)."""
    veh_mod = lazy_import("vehicle_model")
    if veh_mod is None:
        raise ImportError("vehicle_model module unavailable")
    if friction_circle is None:
        raise ValueError("No friction model for vehicle classification")

    vehicle_params = veh_mod.classify_vehicle(friction_circle, lap_metrics)

    # Apply user overrides.
    if vehicle_params is not None and vehicle_overrides:
        vo = vehicle_overrides
        if vo.get("mass_kg") is not None:
            vehicle_params.estimated_mass_kg = float(vo["mass_kg"])
            vehicle_params.classification_reasons.append("mass overridden by user")
            logger.info("Vehicle mass overridden: %.1f kg", vo["mass_kg"])
        if vo.get("power_kw") is not None:
            logger.info("Vehicle power override noted: %.1f kW", vo["power_kw"])
        if vo.get("drag_model") is not None:
            logger.info("Drag model override: %s", vo["drag_model"])

    # 09d2: Kart traction floor correction.
    if vehicle_params is not None and hasattr(vehicle_params, "vehicle_class"):
        vc = vehicle_params.vehicle_class
        is_kart = (hasattr(vc, "value") and vc.value == "kart") or str(vc) == "kart"
        if is_kart:
            fric_mod = lazy_import("friction_model")
            if fric_mod is not None and hasattr(fric_mod, "apply_kart_traction_floor"):
                logger.info("Applying kart traction floor correction.")
                # apply_kart_traction_floor returns a NEW floored FrictionCircle;
                # capture it so the floor actually reaches the simulator (the
                # return was previously dropped, so the floor was a no-op).
                friction_circle = fric_mod.apply_kart_traction_floor(
                    friction_circle, floor_g=0.35,
                )

    return vehicle_params, friction_circle


# ── 09e: Data quality assessment ─────────────────────────────────────

def run_data_quality(
    resampled_laps: dict[int, pd.DataFrame],
    lap_times: list[float],
    *,
    fusion_confidence: float = -1.0,
) -> Any:
    """Step 09e: Data quality assessment. Returns data_quality_report."""
    dq_mod = lazy_import("data_quality")
    if dq_mod is None:
        raise ImportError("data_quality module unavailable")
    return dq_mod.score_data_quality(
        resampled_laps, lap_times, fusion_confidence=fusion_confidence,
    )


# ── 09f: Progressive physics ────────────────────────────────────────

def run_progressive_physics(
    resampled_laps: dict[int, pd.DataFrame],
    corners: list[dict[str, Any]],
    data_tier: int,
) -> dict[str, Any]:
    """Step 09f: Progressive physics (tier 2+). Returns dict of results."""
    results: dict[str, Any] = {}
    if not resampled_laps:
        return results

    if data_tier >= 2:
        try:
            cp_mod = lazy_import("telemetry_tool.physics.controls_physics")
            if cp_mod is not None:
                per_lap: dict[int, list[dict]] = {}
                for ln in sorted(resampled_laps.keys()):
                    per_lap[ln] = cp_mod.analyze_corners_with_controls(
                        resampled_laps[ln], corners,
                    )
                results["controls_analysis"] = per_lap
                logger.info("Tier 2 controls physics: %d laps.", len(per_lap))
        except Exception as exc:
            logger.warning("Controls physics failed: %s", exc)

    if data_tier >= 3:
        _run_tier3_physics(resampled_laps, corners, results)

    return results


def _run_tier3_physics(
    resampled_laps: dict[int, pd.DataFrame],
    corners: list[dict[str, Any]],
    results: dict[str, Any],
) -> None:
    """Tier 3 sub-steps: tire thermal, slip model, fuel model."""
    # Tire thermal.
    try:
        tt_mod = lazy_import("telemetry_tool.physics.tire_thermal")
        if tt_mod is not None:
            results["tire_thermal"] = tt_mod.analyze_tire_session(
                resampled_laps, corners,
            )
            logger.info("Tier 3 tire thermal analysis complete.")
    except Exception as exc:
        logger.warning("Tire thermal analysis failed: %s", exc)

    # Slip model.
    try:
        sl_mod = lazy_import("telemetry_tool.physics.slip_model")
        if sl_mod is not None:
            results["slip_analysis"] = sl_mod.analyze_slip_session(
                resampled_laps, corners,
            )
            logger.info("Tier 3 slip analysis complete.")
    except Exception as exc:
        logger.warning("Slip analysis failed: %s", exc)

    # Fuel model.
    try:
        fu_mod = lazy_import("telemetry_tool.physics.fuel_model")
        if fu_mod is None:
            return
        fuel_levels: list[float] = []
        for ln in sorted(resampled_laps.keys()):
            ldf = resampled_laps[ln]
            for fc in ("fuel_kg", "fuel_remaining_kg", "FuelLevel"):
                if fc in ldf.columns and ldf[fc].notna().any():
                    fuel_levels.append(float(ldf[fc].iloc[-1]))
                    break
        if len(fuel_levels) >= 2:
            results["fuel_analysis"] = fu_mod.analyze_fuel_session(
                list(range(len(fuel_levels))), fuel_levels,
            )
            logger.info("Tier 3 fuel analysis complete.")
    except Exception as exc:
        logger.warning("Fuel analysis failed: %s", exc)


# ── 09g: Traffic detection + lap inclusion ───────────────────────────

def run_traffic_and_inclusion(
    resampled_laps: dict[int, pd.DataFrame],
    lap_times: list[float],
    corners: list[dict[str, Any]],
    *,
    distance_quality: Any = None,
) -> tuple[Any, Any]:
    """Step 09g: Traffic detection + lap inclusion policy.
    Returns (traffic_result, inclusion_policy)."""
    td_mod = lazy_import("traffic_detection")
    li_mod = lazy_import("lap_inclusion")
    traffic_result = None
    inclusion_policy = None

    if td_mod is not None and resampled_laps:
        traffic_result = td_mod.run_traffic_detection(resampled_laps, corners)

    if li_mod is not None:
        if traffic_result is not None:
            inclusion_policy = li_mod.build_inclusion_policy(
                resampled_laps, lap_times, traffic_result,
                distance_quality=distance_quality,
            )
        elif td_mod is not None:
            try:
                empty_traffic = td_mod.TrafficResult(
                    [], [], {k: 0.0 for k in resampled_laps}, 0,
                )
                inclusion_policy = li_mod.build_inclusion_policy(
                    resampled_laps, lap_times, empty_traffic,
                    distance_quality=distance_quality,
                )
            except Exception as exc:
                logger.debug("Empty TrafficResult fallback failed: %s", exc)

    return traffic_result, inclusion_policy


# ── 09h: Condition clustering ────────────────────────────────────────

def run_condition_clustering(
    resampled_laps: dict[int, pd.DataFrame],
    lap_times: list[float],
    *,
    traffic_result: Any = None,
    inclusion_policy: Any = None,
) -> Any:
    """Step 09h: Condition clustering. Returns clustering_result or None."""
    cc_mod = lazy_import("condition_clustering")
    if cc_mod is None or not resampled_laps:
        return None

    traffic_scores: dict[int, float] = {}
    if traffic_result is not None:
        traffic_scores = traffic_result.per_lap_score

    learning_laps = None
    if inclusion_policy is not None:
        learning_laps = inclusion_policy.learning_laps

    return cc_mod.cluster_laps(
        resampled_laps, lap_times, traffic_scores,
        learning_laps=learning_laps,
    )


# ── 09i: Grip map + friction envelope ───────────────────────────────

def run_grip_map(
    resampled_laps: dict[int, pd.DataFrame],
    *,
    curvature_profile: Any = None,
    inclusion_policy: Any = None,
    clustering_result: Any = None,
) -> tuple[Any, Any]:
    """Step 09i: Grip map + friction envelope.
    Returns (grip_map, friction_envelope)."""
    gm_mod = lazy_import("grip_map")
    fe_mod = lazy_import("friction_envelope")
    grip_map = None
    friction_envelope = None

    learning_laps = None
    if inclusion_policy is not None:
        learning_laps = inclusion_policy.learning_laps

    if gm_mod is not None and resampled_laps:
        try:
            grip_map = gm_mod.compute_grip_map(
                resampled_laps,
                curvature_profile=curvature_profile,
                learning_laps=learning_laps,
            )
        except Exception as exc:
            logger.warning("Grip map computation failed: %s", exc)

    if fe_mod is not None and resampled_laps:
        try:
            friction_envelope = fe_mod.compute_friction_envelope(
                resampled_laps, learning_laps=learning_laps,
            )
        except Exception as exc:
            logger.warning("Friction envelope computation failed: %s", exc)

    return grip_map, friction_envelope
