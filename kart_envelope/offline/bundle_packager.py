"""
bundle_packager.py
------------------
Orchestrates per-track/kart bundle_v2 creation from offline datasets.
"""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from kart_envelope.envelope.capability import CapabilityEnvelope
from kart_envelope.ingest.metadata import SessionMetadata, parse_metadata
from kart_envelope.offline.counterfactual_lab import generate_counterfactual_dataset
from kart_envelope.offline.dataset_builder import (
    CATEGORICAL_FEATURE_COLUMNS,
    NUMERIC_FEATURE_COLUMNS,
    TARGET_COLUMNS,
    build_training_dataset,
    feature_columns,
    load_training_dataset,
)
from kart_envelope.offline.distill_student import distill_students
from kart_envelope.offline.high_dof_surrogate import train_high_dof_surrogate
from kart_envelope.offline.policy_train import train_mpc_imitation_policy
from kart_envelope.offline.teacher_train import train_teacher_models
from kart_envelope.tiering import normalize_product_tier

logger = logging.getLogger(__name__)

try:
    import joblib  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - compatibility fallback
    import pickle

    class _JoblibCompat:
        @staticmethod
        def dump(obj: object, path: Path | str) -> None:
            with open(path, "wb") as fh:
                pickle.dump(obj, fh, protocol=pickle.HIGHEST_PROTOCOL)

        @staticmethod
        def load(path: Path | str) -> object:
            with open(path, "rb") as fh:
                return pickle.load(fh)

    joblib = _JoblibCompat()  # type: ignore[assignment]


REQUIRED_BUNDLE_FILES: tuple[str, ...] = (
    "bundle_meta.json",
    "student_regressor.joblib",
    "student_multitask.joblib",
    "gate_model.joblib",
    "policy_corner_table.parquet",
    "envelope_4d_lut.parquet",
    "sector_dp_cache.parquet",
    "uncertainty_quantiles.json",
    "calibration.json",
    "feature_schema.json",
    "mpc_imitation_policy.json",
    "high_dof_surrogate.json",
)


def train_and_package_bundles(
    metadata_path: Path,
    *,
    outputs_dir: Path,
    models_dir: Path,
    bundle_root: Path,
    dataset_path: Path,
    counterfactual_path: Path,
    report_path: Path,
    min_rows_per_bundle: int = 40,
    counterfactual_samples_per_row: int = 6,
    counterfactual_noise_scale: float = 0.08,
    random_state: int = 42,
    publish_global_fallback: bool = True,
    product_tier: str = "b2c",
    distill_teacher_dir: Path | None = None,
    tier_bundle_subdir: bool = True,
    export_teacher_dir: Path | None = None,
) -> dict[str, Any]:
    """Build offline dataset, train models, and package bundle_v2 artifacts."""
    tier = normalize_product_tier(product_tier)
    meta_rows = parse_metadata(metadata_path)
    meta_by_session = {Path(m.session_file).stem: m for m in meta_rows}

    # 1) Dataset + synthetic expansion.
    base_df = build_training_dataset(
        metadata_path=metadata_path,
        outputs_dir=outputs_dir,
        output_path=dataset_path,
        min_rows=1,
    )
    cf_df = generate_counterfactual_dataset(
        base_df,
        output_path=counterfactual_path,
        samples_per_row=counterfactual_samples_per_row,
        noise_scale=counterfactual_noise_scale,
        random_state=random_state,
    )
    train_df = pd.concat([base_df.assign(synthetic=0), cf_df], ignore_index=True)
    train_df = train_df.reset_index(drop=True)
    if "product_tier" not in train_df.columns:
        train_df["product_tier"] = tier
    else:
        train_df["product_tier"] = train_df["product_tier"].fillna("").astype(str)
        train_df.loc[train_df["product_tier"] == "", "product_tier"] = tier

    # 2) Per track-kart packaging.
    report: dict[str, Any] = {
        "product_tier": tier,
        "rows_base": int(len(base_df)),
        "rows_counterfactual": int(len(cf_df)),
        "rows_total": int(len(train_df)),
        "bundles": {},
    }
    for (track_name, kart_id), g in train_df.groupby(["track_name", "kart_id"], dropna=False):
        track = _safe_key(track_name)
        kart = _safe_key(kart_id)
        if not track or not kart:
            continue
        if len(g) < int(max(1, min_rows_per_bundle)):
            logger.info("Skipping bundle %s/%s: %d rows (< %d).", track, kart, len(g), min_rows_per_bundle)
            continue

        if tier_bundle_subdir:
            bundle_dir = bundle_root / tier / track / kart / "bundle_v2"
        else:
            bundle_dir = bundle_root / track / kart / "bundle_v2"
        tmp_dir = bundle_dir / "_tmp_train"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        bundle_dir.mkdir(parents=True, exist_ok=True)

        teacher_train_dir = tmp_dir / "teacher"
        if distill_teacher_dir is None:
            teacher_meta = train_teacher_models(
                g,
                out_dir=teacher_train_dir,
                random_state=random_state,
                product_tier=tier,
            )
        else:
            teacher_meta = _read_json_file(distill_teacher_dir / "teacher_metadata.json")
            teacher_meta.setdefault("metrics", {})
            teacher_meta["distill_only_teacher_dir"] = str(distill_teacher_dir)
        student_meta = distill_students(
            g,
            teacher_dir=teacher_train_dir,
            out_dir=tmp_dir / "student",
            random_state=random_state,
            product_tier=tier,
            teacher_override_dir=distill_teacher_dir,
        )

        _write_student_artifacts(tmp_dir / "student", bundle_dir, g)
        _write_policy_table(bundle_dir, outputs_dir, meta_by_session, track, kart)
        _write_envelope_lut(bundle_dir, models_dir, track, kart)
        _write_sector_cache(bundle_dir, outputs_dir, meta_by_session, track, kart)
        _write_uncertainty(bundle_dir, student_meta)
        _write_calibration(bundle_dir, g)
        _write_feature_schema(bundle_dir, g, product_tier=tier)
        g_tmp = tmp_dir / "group_rows.csv"
        g.to_csv(g_tmp, index=False)
        mpc_meta = train_mpc_imitation_policy(
            g_tmp,
            output_dir=bundle_dir,
            min_rows=max(20, min_rows_per_bundle // 2),
        )
        high_dof_meta = train_high_dof_surrogate(
            g_tmp,
            output_dir=bundle_dir,
            min_rows=max(30, min_rows_per_bundle),
        )

        policy_rows = _count_table_rows(bundle_dir / "policy_corner_table.parquet")
        calibration_report = _read_json_file(bundle_dir / "calibration.json")
        validation_report = _build_bundle_validation_report(teacher_meta)
        bundle_meta = {
            "track_name": track,
            "kart_id": kart,
            "product_tier": tier,
            "rows": int(len(g)),
            "synthetic_ratio": float(np.mean(pd.to_numeric(g.get("synthetic", 0), errors="coerce").fillna(0))),
            "teacher_metrics": teacher_meta.get("metrics", {}),
            "student_metrics": student_meta,
            "required_files": list(REQUIRED_BUNDLE_FILES),
            "bundle_version": 2,
            "physics_stack_version": "cycle_b_v1",
            "policy_model": {
                "name": "advanced_bundle_policy",
                "artifact": "policy_corner_table.parquet",
                "rows": int(policy_rows),
            },
            "mpc_imitation_model": mpc_meta,
            "high_dof_surrogate": high_dof_meta,
            "calibration_report": calibration_report,
            "validation_report": validation_report,
        }
        with open(bundle_dir / "bundle_meta.json", "w", encoding="utf-8") as fh:
            json.dump(bundle_meta, fh, indent=2)

        _cleanup_tmp(tmp_dir)
        report["bundles"][f"{tier}/{track}/{kart}"] = bundle_meta

    # 3) Optional global fallback bundle.
    if publish_global_fallback and len(train_df) >= int(max(20, min_rows_per_bundle)):
        global_track = "_global"
        global_kart = "_global"
        if tier_bundle_subdir:
            bundle_dir = bundle_root / tier / global_track / global_kart / "bundle_v2"
        else:
            bundle_dir = bundle_root / global_track / global_kart / "bundle_v2"
        tmp_dir = bundle_dir / "_tmp_train"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        bundle_dir.mkdir(parents=True, exist_ok=True)
        teacher_train_dir = tmp_dir / "teacher"
        if distill_teacher_dir is None:
            teacher_meta = train_teacher_models(
                train_df,
                out_dir=teacher_train_dir,
                random_state=random_state,
                product_tier=tier,
            )
            if export_teacher_dir is not None:
                export_teacher_dir.mkdir(parents=True, exist_ok=True)
                for name in (
                    "teacher_optimal.joblib",
                    "teacher_gain.joblib",
                    "teacher_multi.joblib",
                    "teacher_diag.joblib",
                    "teacher_condition_experts.joblib",
                    "teacher_metadata.json",
                ):
                    src = teacher_train_dir / name
                    if src.exists():
                        shutil.copy2(src, export_teacher_dir / name)
        else:
            teacher_meta = _read_json_file(distill_teacher_dir / "teacher_metadata.json")
            teacher_meta.setdefault("metrics", {})
            teacher_meta["distill_only_teacher_dir"] = str(distill_teacher_dir)
        student_meta = distill_students(
            train_df,
            teacher_dir=teacher_train_dir,
            out_dir=tmp_dir / "student",
            random_state=random_state,
            product_tier=tier,
            teacher_override_dir=distill_teacher_dir,
        )
        _write_student_artifacts(tmp_dir / "student", bundle_dir, train_df)
        _write_policy_table(bundle_dir, outputs_dir, meta_by_session, None, None)
        _write_envelope_lut(bundle_dir, models_dir, None, None)
        _write_sector_cache(bundle_dir, outputs_dir, meta_by_session, None, None)
        _write_uncertainty(bundle_dir, student_meta)
        _write_calibration(bundle_dir, train_df)
        _write_feature_schema(bundle_dir, train_df, product_tier=tier)
        g_tmp = tmp_dir / "group_rows.csv"
        train_df.to_csv(g_tmp, index=False)
        mpc_meta = train_mpc_imitation_policy(
            g_tmp,
            output_dir=bundle_dir,
            min_rows=max(20, min_rows_per_bundle // 2),
        )
        high_dof_meta = train_high_dof_surrogate(
            g_tmp,
            output_dir=bundle_dir,
            min_rows=max(30, min_rows_per_bundle),
        )
        policy_rows = _count_table_rows(bundle_dir / "policy_corner_table.parquet")
        calibration_report = _read_json_file(bundle_dir / "calibration.json")
        validation_report = _build_bundle_validation_report(teacher_meta)
        with open(bundle_dir / "bundle_meta.json", "w", encoding="utf-8") as fh:
            json.dump({
                "track_name": global_track,
                "kart_id": global_kart,
                "product_tier": tier,
                "rows": int(len(train_df)),
                "teacher_metrics": teacher_meta.get("metrics", {}),
                "student_metrics": student_meta,
                "required_files": list(REQUIRED_BUNDLE_FILES),
                "bundle_version": 2,
                "physics_stack_version": "cycle_b_v1",
                "policy_model": {
                    "name": "advanced_bundle_policy",
                    "artifact": "policy_corner_table.parquet",
                    "rows": int(policy_rows),
                },
                "mpc_imitation_model": mpc_meta,
                "high_dof_surrogate": high_dof_meta,
                "calibration_report": calibration_report,
                "validation_report": validation_report,
            }, fh, indent=2)
        _cleanup_tmp(tmp_dir)
        report["bundles"][f"{tier}/{global_track}/{global_kart}"] = {
            "rows": int(len(train_df)),
            "bundle_version": 2,
        }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    logger.info("Bundle packaging complete -> %s", report_path)
    return report


def train_and_package_three_tier_bundles(
    metadata_path: Path,
    *,
    outputs_dir: Path,
    models_dir: Path,
    bundle_root: Path,
    dataset_path: Path,
    counterfactual_path: Path,
    report_path: Path,
    min_rows_per_bundle: int = 40,
    counterfactual_samples_per_row: int = 6,
    counterfactual_noise_scale: float = 0.08,
    random_state: int = 42,
    publish_global_fallback: bool = True,
    premium_teacher_dir: Path | None = None,
) -> dict[str, Any]:
    """
    Build premium + basic + b2c bundles in one wave.

    Premium is trained first and exported as teacher for cross-tier distillation.
    """
    teacher_dir = premium_teacher_dir or (models_dir / "offline" / "premium_teacher")
    report_premium = train_and_package_bundles(
        metadata_path=metadata_path,
        outputs_dir=outputs_dir,
        models_dir=models_dir,
        bundle_root=bundle_root,
        dataset_path=dataset_path,
        counterfactual_path=counterfactual_path,
        report_path=report_path.with_name(f"{report_path.stem}_b2b_premium{report_path.suffix}"),
        min_rows_per_bundle=min_rows_per_bundle,
        counterfactual_samples_per_row=counterfactual_samples_per_row,
        counterfactual_noise_scale=counterfactual_noise_scale,
        random_state=random_state,
        publish_global_fallback=publish_global_fallback,
        product_tier="b2b_premium",
        tier_bundle_subdir=True,
        export_teacher_dir=teacher_dir,
    )
    report_basic = train_and_package_bundles(
        metadata_path=metadata_path,
        outputs_dir=outputs_dir,
        models_dir=models_dir,
        bundle_root=bundle_root,
        dataset_path=dataset_path.with_name(f"{dataset_path.stem}_b2b_basic{dataset_path.suffix}"),
        counterfactual_path=counterfactual_path.with_name(f"{counterfactual_path.stem}_b2b_basic{counterfactual_path.suffix}"),
        report_path=report_path.with_name(f"{report_path.stem}_b2b_basic{report_path.suffix}"),
        min_rows_per_bundle=min_rows_per_bundle,
        counterfactual_samples_per_row=counterfactual_samples_per_row,
        counterfactual_noise_scale=counterfactual_noise_scale,
        random_state=random_state,
        publish_global_fallback=publish_global_fallback,
        product_tier="b2b_basic",
        distill_teacher_dir=teacher_dir,
        tier_bundle_subdir=True,
    )
    report_b2c = train_and_package_bundles(
        metadata_path=metadata_path,
        outputs_dir=outputs_dir,
        models_dir=models_dir,
        bundle_root=bundle_root,
        dataset_path=dataset_path.with_name(f"{dataset_path.stem}_b2c{dataset_path.suffix}"),
        counterfactual_path=counterfactual_path.with_name(f"{counterfactual_path.stem}_b2c{counterfactual_path.suffix}"),
        report_path=report_path.with_name(f"{report_path.stem}_b2c{report_path.suffix}"),
        min_rows_per_bundle=min_rows_per_bundle,
        counterfactual_samples_per_row=counterfactual_samples_per_row,
        counterfactual_noise_scale=counterfactual_noise_scale,
        random_state=random_state,
        publish_global_fallback=publish_global_fallback,
        product_tier="b2c",
        distill_teacher_dir=teacher_dir,
        tier_bundle_subdir=True,
    )
    final = {
        "mode": "three_tier_distillation",
        "teacher_dir": str(teacher_dir),
        "reports": {
            "b2b_premium": report_premium,
            "b2b_basic": report_basic,
            "b2c": report_b2c,
        },
    }
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(final, fh, indent=2)
    return final


def _write_student_artifacts(student_dir: Path, bundle_dir: Path, group_df: pd.DataFrame) -> None:
    pre = joblib.load(student_dir / "student_preprocessor.joblib")
    model_opt = joblib.load(student_dir / "student_optimal.joblib")
    model_gain = joblib.load(student_dir / "student_gain.joblib")
    diag_model = joblib.load(student_dir / "student_diag.joblib") if (student_dir / "student_diag.joblib").exists() else None
    gate = joblib.load(student_dir / "gate_model.joblib") if (student_dir / "gate_model.joblib").exists() else None

    student_bundle = {
        "preprocessor": pre,
        "model_optimal": model_opt,
        "model_gain": model_gain,
        "model_diag": diag_model,
    }
    joblib.dump(student_bundle, bundle_dir / "student_regressor.joblib")
    joblib.dump(
        {
            "preprocessor": pre,
            "model_optimal": model_opt,
            "model_gain": model_gain,
            "mode": "multitask_proxy",
        },
        bundle_dir / "student_multitask.joblib",
    )
    if gate is None:
        mode = (
            group_df["condition_label"].astype(str).mode().iloc[0]
            if "condition_label" in group_df.columns and not group_df.empty
            else "dry"
        )
        gate = {"default_condition": str(mode)}
    joblib.dump(gate, bundle_dir / "gate_model.joblib")


def _write_policy_table(
    bundle_dir: Path,
    outputs_dir: Path,
    meta_by_session: dict[str, SessionMetadata],
    track: str | None,
    kart: str | None,
) -> None:
    rows: list[pd.DataFrame] = []
    for session_id, meta in meta_by_session.items():
        if track and _safe_key(meta.track_name) != track:
            continue
        if kart and _safe_key(meta.kart_id) != kart:
            continue
        path = outputs_dir / session_id / "corner_sensitivity.csv"
        if not path.exists():
            continue
        try:
            df = pd.read_csv(path)
        except Exception:
            continue
        if df.empty:
            continue
        for col in ("corner_id", "brake_shift_s", "turn_shift_m", "lat_force_scale", "brake_force_scale", "gain_s"):
            if col not in df.columns:
                continue
        f = df.copy()
        if "feasible" in f.columns:
            f = f[f["feasible"].astype(str).str.lower().isin({"true", "1"})]
        if "gain_s" in f.columns:
            f = f[pd.to_numeric(f["gain_s"], errors="coerce") > 0]
        if f.empty:
            continue
        f["session_id"] = session_id
        f["condition_label"] = meta.condition_label or ""
        rows.append(f)

    if not rows:
        out = pd.DataFrame([{
            "corner_id": 0,
            "brake_shift_s": 0.0,
            "turn_shift_m": 0.0,
            "lat_force_scale": 1.0,
            "brake_force_scale": 1.0,
            "mean_gain_s": 0.0,
            "n_samples": 1,
            "condition_label": "",
        }])
    else:
        all_df = pd.concat(rows, ignore_index=True)
        grp = all_df.groupby(["corner_id", "condition_label"], dropna=False).agg({
            "brake_shift_s": "median",
            "turn_shift_m": "median",
            "lat_force_scale": "median",
            "brake_force_scale": "median",
            "gain_s": "mean",
        }).reset_index()
        grp = grp.rename(columns={"gain_s": "mean_gain_s"})
        counts = all_df.groupby(["corner_id", "condition_label"]).size().rename("n_samples").reset_index()
        out = grp.merge(counts, on=["corner_id", "condition_label"], how="left")

    _write_table(out, bundle_dir / "policy_corner_table.parquet")


def _write_envelope_lut(bundle_dir: Path, models_dir: Path, track: str | None, kart: str | None) -> None:
    if track and kart:
        env_path = models_dir / track / kart / "envelope.json"
    else:
        env_path = None
    rows: list[dict[str, Any]] = []
    if env_path is not None and env_path.exists():
        try:
            env = CapabilityEnvelope.load(env_path)
        except Exception:
            env = None
        if env is not None:
            cond_scale = {
                "dry": 1.00,
                "green": 0.95,
                "damp": 0.90,
                "wet": 0.82,
                "greasy": 0.88,
            }
            for cond, scale in cond_scale.items():
                for i, v in enumerate(np.asarray(env.v_grid, dtype=float)):
                    rows.append({
                        "condition_label": cond,
                        "v_mps": float(v),
                        "ay_max_mps2": float(env.ay_max[i] * scale),
                        "ax_drive_max_mps2": float(env.ax_drive_max[i] * scale),
                        "ax_brake_max_mps2": float(env.ax_brake_max[i] * scale),
                    })
    if not rows:
        v_grid = np.linspace(1.0, 40.0, 30)
        for cond, scale in {"dry": 1.0, "wet": 0.82}.items():
            for v in v_grid:
                rows.append({
                    "condition_label": cond,
                    "v_mps": float(v),
                    "ay_max_mps2": float(9.0 * scale),
                    "ax_drive_max_mps2": float(2.0 * scale),
                    "ax_brake_max_mps2": float(3.0 * scale),
                })
    out = pd.DataFrame(rows)
    _write_table(out, bundle_dir / "envelope_4d_lut.parquet")


def _write_sector_cache(
    bundle_dir: Path,
    outputs_dir: Path,
    meta_by_session: dict[str, SessionMetadata],
    track: str | None,
    kart: str | None,
) -> None:
    rows: list[pd.DataFrame] = []
    for session_id, meta in meta_by_session.items():
        if track and _safe_key(meta.track_name) != track:
            continue
        if kart and _safe_key(meta.kart_id) != kart:
            continue
        path = outputs_dir / session_id / "sector_summary.csv"
        if not path.exists():
            continue
        try:
            df = pd.read_csv(path)
        except Exception:
            continue
        if df.empty or "sector" not in df.columns:
            continue
        df = df.copy()
        df["session_id"] = session_id
        df["condition_label"] = meta.condition_label or ""
        rows.append(df)

    if not rows:
        out = pd.DataFrame([{
            "sector": "S1",
            "baseline_time_s": 0.0,
            "ideal_time_s": 0.0,
            "gain_s": 0.0,
            "condition_label": "",
            "n_samples": 1,
        }])
    else:
        all_df = pd.concat(rows, ignore_index=True)
        grp = all_df.groupby(["sector", "condition_label"], dropna=False).agg({
            "baseline_time_s": "mean",
            "ideal_time_s": "mean",
            "gain_s": "mean",
        }).reset_index()
        counts = all_df.groupby(["sector", "condition_label"]).size().rename("n_samples").reset_index()
        out = grp.merge(counts, on=["sector", "condition_label"], how="left")
    _write_table(out, bundle_dir / "sector_dp_cache.parquet")


def _write_uncertainty(bundle_dir: Path, student_meta: dict[str, Any]) -> None:
    q10 = float(student_meta.get("residual_q10_s", -0.25))
    q90 = float(student_meta.get("residual_q90_s", 0.25))
    sigma = float(student_meta.get("residual_sigma_s", 0.12))
    payload = {
        "residual_q10_s": q10,
        "residual_q90_s": q90,
        "residual_sigma_s": sigma,
        "confidence_bands": {
            "p50": [0.0, 0.0],
            "p80": [q10, q90],
            "p90": [q10 * 1.2, q90 * 1.2],
        },
    }
    with open(bundle_dir / "uncertainty_quantiles.json", "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)


def _write_calibration(bundle_dir: Path, group_df: pd.DataFrame) -> None:
    g = group_df.copy()
    for col in ("quality_score", "gain_s", "actual_lap_time_s"):
        if col not in g.columns:
            g[col] = np.nan
        g[col] = pd.to_numeric(g[col], errors="coerce")
    g = g.dropna(subset=["quality_score", "gain_s", "actual_lap_time_s"])
    if len(g) < 8:
        payload = {
            "method": "default",
            "intercept": 0.90,
            "slope_quality": 0.10,
            "min": 0.60,
            "max": 1.00,
        }
    else:
        y = np.clip(g["gain_s"].to_numpy(dtype=float) / np.maximum(g["actual_lap_time_s"].to_numpy(dtype=float), 1e-6), 0.0, 0.30)
        x = np.clip(g["quality_score"].to_numpy(dtype=float), 0.0, 1.0)
        if np.nanstd(x) < 1e-6:
            payload = {
                "method": "default_constant_quality",
                "intercept": 0.90,
                "slope_quality": 0.0,
                "min": 0.60,
                "max": 1.00,
            }
        else:
            try:
                a, b = np.polyfit(x, y, deg=1)
            except Exception:
                a, b = 0.0, float(np.nanmean(y))
            # Map gain% tendency to shrink factor range.
            intercept = float(np.clip(0.85 + 0.10 * b, 0.60, 1.00))
            slope_q = float(np.clip(0.25 * a, -0.20, 0.20))
            payload = {
                "method": "linear_quality",
                "intercept": intercept,
                "slope_quality": slope_q,
                "min": 0.60,
                "max": 1.00,
            }
    with open(bundle_dir / "calibration.json", "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)


def _write_feature_schema(bundle_dir: Path, group_df: pd.DataFrame, *, product_tier: str) -> None:
    features_num = [c for c in NUMERIC_FEATURE_COLUMNS if c in group_df.columns]
    features_cat = [c for c in CATEGORICAL_FEATURE_COLUMNS if c in group_df.columns]
    tier_schema: dict[str, dict[str, list[str]]] = {}
    for tier_key in ("b2c", "b2b_basic", "b2b_premium"):
        num_t, cat_t = feature_columns(group_df, product_tier=tier_key)
        tier_schema[tier_key] = {
            "numeric_features": num_t,
            "categorical_features": cat_t,
        }
    payload = {
        "numeric_features": features_num,
        "categorical_features": features_cat,
        "targets": [c for c in TARGET_COLUMNS if c in group_df.columns],
        "version": 3,
        "product_tier": normalize_product_tier(product_tier),
        "tier_feature_schema": tier_schema,
    }
    with open(bundle_dir / "feature_schema.json", "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)


def _write_table(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        df.to_parquet(path, index=False)
    except Exception:
        df.to_csv(path.with_suffix(".csv"), index=False)


def _safe_key(value: object) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    out = []
    for ch in s.lower():
        if ch.isalnum() or ch in {"-", "_"}:
            out.append(ch)
        else:
            out.append("_")
    return "".join(out).strip("_")


def _cleanup_tmp(tmp_dir: Path) -> None:
    try:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception:
        pass


def _count_table_rows(path: Path) -> int:
    if not path.exists():
        csv_fallback = path.with_suffix(".csv")
        if not csv_fallback.exists():
            return 0
        try:
            return int(len(pd.read_csv(csv_fallback)))
        except Exception:
            return 0
    try:
        return int(len(pd.read_parquet(path)))
    except Exception:
        csv_fallback = path.with_suffix(".csv")
        if csv_fallback.exists():
            try:
                return int(len(pd.read_csv(csv_fallback)))
            except Exception:
                return 0
    return 0


def _read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _build_bundle_validation_report(teacher_meta: dict[str, Any]) -> dict[str, Any]:
    metrics = teacher_meta.get("metrics", {}) if isinstance(teacher_meta, dict) else {}
    cv = metrics.get("cross_validation", {}) if isinstance(metrics, dict) else {}
    opt_mae = float(metrics.get("optimal_mae_s", 9.9) or 9.9)
    cv_opt_mae = float(cv.get("optimal_mae_mean_s", opt_mae) or opt_mae) if isinstance(cv, dict) else opt_mae
    return {
        "status": "ok",
        "mode": "offline_teacher_proxy",
        "optimal_mae_s": round(opt_mae, 4),
        "cv_optimal_mae_s": round(cv_opt_mae, 4),
        "passes_gate": bool(cv_opt_mae <= max(opt_mae * 1.5, 2.0)),
    }
