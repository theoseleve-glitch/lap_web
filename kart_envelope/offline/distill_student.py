"""
distill_student.py
------------------
Distill teacher models into compact student models for fast online inference.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor, RandomForestClassifier
from sklearn.metrics import accuracy_score, mean_absolute_error
from sklearn.model_selection import train_test_split

from kart_envelope.offline.dataset_builder import (
    CATEGORICAL_FEATURE_COLUMNS,
    NUMERIC_FEATURE_COLUMNS,
    feature_columns,
)
from kart_envelope.offline.teacher_train import _build_preprocessor
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


def distill_students(
    df: pd.DataFrame,
    teacher_dir: Path,
    out_dir: Path,
    *,
    random_state: int = 42,
    max_depth: int = 4,
    n_estimators: int = 120,
    product_tier: str | None = None,
    teacher_override_dir: Path | None = None,
) -> dict[str, Any]:
    """
    Distill teacher predictions into lightweight student models.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    work = df.copy().replace([np.inf, -np.inf], np.nan)
    work = work.dropna(subset=["optimal_lap_time_s", "gain_s"])
    if len(work) < 20:
        raise ValueError(f"Insufficient rows for student distillation: {len(work)}")

    tier = normalize_product_tier(product_tier)
    num_cols, cat_cols = feature_columns(work, product_tier=tier)
    feature_cols = num_cols + cat_cols
    x = work[feature_cols]

    teacher_src = teacher_override_dir or teacher_dir
    teacher_opt = joblib.load(teacher_src / "teacher_optimal.joblib")
    teacher_gain = joblib.load(teacher_src / "teacher_gain.joblib")
    teacher_multi = joblib.load(teacher_src / "teacher_multi.joblib")
    teacher_feature_cols = _load_teacher_feature_columns(teacher_src, fallback=feature_cols)
    x_teacher = _align_teacher_features(x, teacher_feature_cols)

    # Pseudo labels from teacher blend.
    t_opt = np.asarray(teacher_opt.predict(x_teacher), dtype=float)
    t_gain = np.asarray(teacher_gain.predict(x_teacher), dtype=float)
    t_multi = np.asarray(teacher_multi.predict(x_teacher), dtype=float)
    if t_multi.ndim == 1:
        t_multi = np.column_stack([t_multi, np.maximum(0.0, work["gain_s"].to_numpy(dtype=float))])

    y_opt_pseudo = 0.55 * t_opt + 0.35 * t_multi[:, 0] + 0.10 * work["optimal_lap_time_s"].to_numpy(dtype=float)
    y_gain_pseudo = np.maximum(
        0.0,
        0.55 * t_gain + 0.35 * np.maximum(t_multi[:, 1], 0.0) + 0.10 * work["gain_s"].to_numpy(dtype=float),
    )

    x_train, x_test, y_opt_train, y_opt_test = train_test_split(
        x, y_opt_pseudo, test_size=0.2, random_state=int(random_state)
    )
    _, _, y_gain_train, y_gain_test = train_test_split(
        x, y_gain_pseudo, test_size=0.2, random_state=int(random_state)
    )

    pre = _build_preprocessor(num_cols, cat_cols)
    x_train_t = pre.fit_transform(x_train)
    x_test_t = pre.transform(x_test)
    x_all_t = pre.transform(x)

    student_opt = GradientBoostingRegressor(
        random_state=int(random_state),
        n_estimators=int(max(40, n_estimators)),
        max_depth=int(max(2, max_depth)),
        learning_rate=0.05,
        min_samples_leaf=3,
    )
    student_gain = GradientBoostingRegressor(
        random_state=int(random_state + 1),
        n_estimators=int(max(40, n_estimators)),
        max_depth=int(max(2, max_depth)),
        learning_rate=0.06,
        min_samples_leaf=3,
    )
    student_opt.fit(x_train_t, y_opt_train)
    student_gain.fit(x_train_t, y_gain_train)

    pred_opt = np.asarray(student_opt.predict(x_test_t), dtype=float)
    pred_gain = np.maximum(np.asarray(student_gain.predict(x_test_t), dtype=float), 0.0)

    # Optional gate model: predict condition label.
    gate_model = None
    gate_acc = None
    if "condition_label" in work.columns:
        y_gate = work["condition_label"].fillna("").astype(str)
        if y_gate.nunique() > 1:
            g_xt, g_xv, g_yt, g_yv = train_test_split(
                x_all_t,
                y_gate,
                test_size=0.2,
                random_state=int(random_state),
                stratify=y_gate,
            )
            gate_model = RandomForestClassifier(
                random_state=int(random_state),
                n_estimators=140,
                min_samples_leaf=2,
                n_jobs=-1,
            )
            gate_model.fit(g_xt, g_yt)
            gate_pred = gate_model.predict(g_xv)
            gate_acc = float(accuracy_score(g_yv, gate_pred))

    # Optional distilled diagnostics.
    diag_model = None
    diag_acc = None
    teacher_diag_path = teacher_src / "teacher_diag.joblib"
    if teacher_diag_path.exists():
        teacher_diag = joblib.load(teacher_diag_path)
        y_diag_pseudo = np.asarray(teacher_diag.predict(x_teacher), dtype=str)
        if len(np.unique(y_diag_pseudo)) > 1:
            dx_t, dx_v, dy_t, dy_v = train_test_split(
                x_all_t, y_diag_pseudo, test_size=0.2, random_state=int(random_state), stratify=y_diag_pseudo
            )
            diag_model = RandomForestClassifier(
                random_state=int(random_state + 3),
                n_estimators=120,
                min_samples_leaf=2,
                n_jobs=-1,
            )
            diag_model.fit(dx_t, dy_t)
            diag_pred = diag_model.predict(dx_v)
            diag_acc = float(accuracy_score(dy_v, diag_pred))

    # Residual-based uncertainty cache (global).
    full_pred_opt = np.asarray(student_opt.predict(x_all_t), dtype=float)
    residual = work["optimal_lap_time_s"].to_numpy(dtype=float) - full_pred_opt
    q_lo, q_hi = np.quantile(residual, [0.10, 0.90])
    sigma = float(np.std(residual))

    joblib.dump(pre, out_dir / "student_preprocessor.joblib")
    joblib.dump(student_opt, out_dir / "student_optimal.joblib")
    joblib.dump(student_gain, out_dir / "student_gain.joblib")
    if gate_model is not None:
        joblib.dump(gate_model, out_dir / "gate_model.joblib")
    if diag_model is not None:
        joblib.dump(diag_model, out_dir / "student_diag.joblib")

    metrics: dict[str, Any] = {
        "rows": int(len(work)),
        "product_tier": tier,
        "teacher_source": str(teacher_src),
        "student_optimal_mae_s": float(mean_absolute_error(y_opt_test, pred_opt)),
        "student_gain_mae_s": float(mean_absolute_error(y_gain_test, pred_gain)),
        "gate_accuracy": gate_acc,
        "diag_accuracy": diag_acc,
        "residual_q10_s": float(q_lo),
        "residual_q90_s": float(q_hi),
        "residual_sigma_s": sigma,
        "feature_columns": feature_cols,
        "numeric_columns": num_cols,
        "categorical_columns": cat_cols,
        "teacher_feature_columns": teacher_feature_cols,
    }
    with open(out_dir / "student_metadata.json", "w", encoding="utf-8") as fh:
        json.dump(metrics, fh, indent=2)

    logger.info(
        "Student distillation complete -> %s (opt_mae=%.4f, gain_mae=%.4f)",
        out_dir,
        metrics["student_optimal_mae_s"],
        metrics["student_gain_mae_s"],
    )
    return metrics


def _load_teacher_feature_columns(teacher_dir: Path, *, fallback: list[str]) -> list[str]:
    meta_path = teacher_dir / "teacher_metadata.json"
    if not meta_path.exists():
        return list(fallback)
    try:
        with open(meta_path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except Exception:
        return list(fallback)
    if not isinstance(raw, dict):
        return list(fallback)
    metrics = raw.get("metrics", {})
    if not isinstance(metrics, dict):
        return list(fallback)
    cols = metrics.get("feature_columns")
    if not isinstance(cols, list) or not cols:
        return list(fallback)
    return [str(c) for c in cols if str(c).strip()]


def _align_teacher_features(x: pd.DataFrame, teacher_cols: list[str]) -> pd.DataFrame:
    xt = x.copy()
    numeric = set(NUMERIC_FEATURE_COLUMNS)
    for col in teacher_cols:
        if col in xt.columns:
            continue
        xt[col] = 0.0 if col in numeric else ""
    return xt[teacher_cols]
