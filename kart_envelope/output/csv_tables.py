"""
csv_tables.py
-------------
Write ``corner_table.csv`` and ``delta_map.csv`` output files.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
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


def write_corner_sensitivity_table(
    rows: list[dict[str, object]],
    path: Path,
) -> None:
    """Write all sensitivity candidates as CSV."""
    if not rows:
        logger.warning("No corner sensitivity rows to write.")
        return
    df = pd.DataFrame(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    logger.info("Wrote corner_sensitivity.csv (%d rows) to %s", len(df), path)


def write_corner_whatif_matrix(
    rows: list[dict[str, object]],
    path: Path,
) -> None:
    """
    Write aggregated corner what-if matrix:
    per (corner, brake_shift, turn_shift) combination, summarize gain and apex timing.
    """
    if not rows:
        logger.warning("No corner sensitivity rows for what-if matrix.")
        return

    df = pd.DataFrame(rows).copy()
    required = {"corner_id", "brake_shift_s", "turn_shift_m", "gain_s"}
    if not required.issubset(set(df.columns)):
        logger.warning("Missing columns for corner what-if matrix; skipping.")
        return

    for col in [
        "corner_id",
        "brake_shift_s",
        "turn_shift_m",
        "apex_shift_input_m",
        "line_curvature_scale",
        "gain_s",
        "apex_shift_m",
        "apex_point_m",
        "apex_speed_mps",
        "eval_corner_time_s",
        "lat_force_scale",
        "brake_force_scale",
    ]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "feasible" in df.columns:
        feas_raw = df["feasible"]
        feas_num = pd.to_numeric(feas_raw, errors="coerce")
        if feas_num.isna().any():
            feas_txt = feas_raw.astype(str).str.strip().str.lower()
            feas_map = feas_txt.isin({"1", "true", "yes", "y"})
            feas_num = feas_num.where(pd.notna(feas_num), feas_map.astype(float))
        df["feasible"] = feas_num.fillna(0.0).astype(float).clip(0.0, 1.0)
    else:
        df["feasible"] = 0.0

    group_cols = ["corner_id", "brake_shift_s", "turn_shift_m"]
    agg = (
        df.groupby(group_cols, as_index=False)
        .agg(
            candidates=("gain_s", "size"),
            feasible_rate=("feasible", "mean"),
            best_gain_s=("gain_s", "max"),
            mean_gain_s=("gain_s", "mean"),
        )
    )

    # Keep best feasible candidate snapshot for each pair when available,
    # fallback to overall best otherwise.
    feas = df[df["feasible"] > 0.5].copy()
    if len(feas):
        idx_feas = feas.groupby(group_cols)["gain_s"].idxmax()
        best_feas = df.loc[idx_feas, group_cols + [
            "gain_s",
            "eval_corner_time_s",
            "apex_shift_input_m",
            "line_curvature_scale",
            "apex_shift_m",
            "apex_point_m",
            "apex_speed_mps",
            "lat_force_scale",
            "brake_force_scale",
        ]].copy()
    else:
        best_feas = pd.DataFrame(columns=group_cols + [
            "gain_s",
            "eval_corner_time_s",
            "apex_shift_input_m",
            "line_curvature_scale",
            "apex_shift_m",
            "apex_point_m",
            "apex_speed_mps",
            "lat_force_scale",
            "brake_force_scale",
        ])
    idx_any = df.groupby(group_cols)["gain_s"].idxmax()
    best_any = df.loc[idx_any, group_cols + [
        "gain_s",
        "eval_corner_time_s",
        "apex_shift_input_m",
        "line_curvature_scale",
        "apex_shift_m",
        "apex_point_m",
        "apex_speed_mps",
        "lat_force_scale",
        "brake_force_scale",
    ]].copy()
    best = best_any.merge(best_feas, on=group_cols, how="left", suffixes=("_any", ""))
    for col in [
        "gain_s",
        "eval_corner_time_s",
        "apex_shift_input_m",
        "line_curvature_scale",
        "apex_shift_m",
        "apex_point_m",
        "apex_speed_mps",
        "lat_force_scale",
        "brake_force_scale",
    ]:
        if col not in best.columns and f"{col}_any" in best.columns:
            best[col] = best[f"{col}_any"]
        elif col in best.columns and f"{col}_any" in best.columns:
            best[col] = best[col].where(pd.notna(best[col]), best[f"{col}_any"])

    best = best.rename(columns={
        "gain_s": "best_candidate_gain_s",
        "eval_corner_time_s": "best_candidate_corner_time_s",
        "apex_shift_input_m": "best_apex_shift_input_m",
        "line_curvature_scale": "best_line_curvature_scale",
        "apex_shift_m": "best_apex_shift_m",
        "apex_point_m": "best_apex_point_m",
        "apex_speed_mps": "best_apex_speed_mps",
        "lat_force_scale": "best_lat_force_scale",
        "brake_force_scale": "best_brake_force_scale",
    })
    drop_cols = [c for c in best.columns if c.endswith("_any")]
    if drop_cols:
        best = best.drop(columns=drop_cols)

    out = agg.merge(best, on=group_cols, how="left")
    out["brake_timing"] = np.where(
        out["brake_shift_s"] > 1e-6,
        "later",
        np.where(out["brake_shift_s"] < -1e-6, "earlier", "same"),
    )
    out["turn_in_timing"] = np.where(
        out["turn_shift_m"] > 1e-6,
        "later",
        np.where(out["turn_shift_m"] < -1e-6, "earlier", "same"),
    )
    apex_shift = pd.to_numeric(out.get("best_apex_shift_input_m"), errors="coerce")
    if not np.any(np.isfinite(apex_shift)):
        apex_shift = pd.to_numeric(out["best_apex_shift_m"], errors="coerce")
    out["apex_timing"] = np.where(
        np.isfinite(apex_shift),
        np.where(apex_shift > 0.2, "later", np.where(apex_shift < -0.2, "earlier", "same")),
        "unknown",
    )
    out = out.sort_values(
        by=["corner_id", "best_gain_s", "feasible_rate"],
        ascending=[True, False, False],
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False)
    logger.info("Wrote corner_whatif_matrix.csv (%d rows) to %s", len(out), path)


def write_corner_recommendations(
    rows: list[dict[str, object]],
    path: Path,
) -> None:
    """Write top accepted corner recommendations."""
    if not rows:
        logger.warning("No corner recommendations to write.")
        return
    df = pd.DataFrame(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    logger.info("Wrote corner_recommendations.csv (%d rows) to %s", len(df), path)


def write_ideal_lap_profile(
    distance_m: np.ndarray,
    baseline_speed_mps: np.ndarray,
    ideal_speed_mps: np.ndarray,
    path: Path,
) -> None:
    """Write distance-aligned baseline vs ideal speed profile."""
    if len(distance_m) == 0:
        logger.warning("No ideal-lap profile data to write.")
        return
    df = pd.DataFrame({
        "distance_m": distance_m,
        "baseline_speed_mps": baseline_speed_mps,
        "ideal_speed_mps": ideal_speed_mps,
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    logger.info("Wrote ideal_lap_profile.csv (%d rows) to %s", len(df), path)


def write_sector_summary(
    rows: list[dict[str, object]],
    path: Path,
) -> None:
    """Write baseline vs ideal sector times."""
    if not rows:
        logger.warning("No sector summary rows to write.")
        return
    df = pd.DataFrame(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    logger.info("Wrote sector_summary.csv (%d rows) to %s", len(df), path)


def write_driver_diagnostics(
    rows: list[dict[str, object]],
    path: Path,
) -> None:
    """Write session-level driver diagnostics findings."""
    if not rows:
        logger.warning("No driver diagnostics rows to write.")
        return
    df = pd.DataFrame(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    logger.info("Wrote driver_diagnostics.csv (%d rows) to %s", len(df), path)
