"""
teacher_train.py
----------------
Offline teacher-model training for bundle_v2.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import (
    GradientBoostingRegressor,
    RandomForestClassifier,
    RandomForestRegressor,
)
from sklearn.metrics import accuracy_score, mean_absolute_error
from sklearn.model_selection import GroupKFold, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from kart_envelope.offline.dataset_builder import (
    CATEGORICAL_FEATURE_COLUMNS,
    DIAGNOSTIC_CODES,
    NUMERIC_FEATURE_COLUMNS,
    feature_columns,
)
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


def train_teacher_models(
    df: pd.DataFrame,
    out_dir: Path,
    *,
    random_state: int = 42,
    product_tier: str | None = None,
) -> dict[str, Any]:
    """
    Train teacher models:
    - optimal lap regressor
    - gain regressor
    - multitask regressor
    - primary diagnostic classifier
    - per-condition gain experts
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    work = df.copy()
    work = work.replace([np.inf, -np.inf], np.nan)
    work = work.dropna(subset=["optimal_lap_time_s", "gain_s"])
    if len(work) < 20:
        raise ValueError(f"Insufficient rows for teacher training: {len(work)}")

    tier = normalize_product_tier(product_tier)
    num_cols, cat_cols = feature_columns(work, product_tier=tier)
    feature_cols = num_cols + cat_cols
    if not feature_cols:
        raise ValueError("No feature columns available for teacher training.")
    x = work[feature_cols]

    # Main regressors
    y_opt = work["optimal_lap_time_s"].astype(float)
    y_gain = work["gain_s"].astype(float)

    x_train, x_test, y_opt_train, y_opt_test = train_test_split(
        x,
        y_opt,
        test_size=0.2,
        random_state=int(random_state),
    )
    _, _, y_gain_train, y_gain_test = train_test_split(
        x,
        y_gain,
        test_size=0.2,
        random_state=int(random_state),
    )

    opt_model = Pipeline([
        ("prep", _build_preprocessor(num_cols, cat_cols)),
        ("model", GradientBoostingRegressor(
            random_state=int(random_state),
            n_estimators=260,
            max_depth=4,
            learning_rate=0.04,
            min_samples_leaf=3,
        )),
    ])
    gain_model = Pipeline([
        ("prep", _build_preprocessor(num_cols, cat_cols)),
        ("model", GradientBoostingRegressor(
            random_state=int(random_state + 1),
            n_estimators=260,
            max_depth=4,
            learning_rate=0.05,
            min_samples_leaf=3,
        )),
    ])
    multi_model = Pipeline([
        ("prep", _build_preprocessor(num_cols, cat_cols)),
        ("model", RandomForestRegressor(
            random_state=int(random_state),
            n_estimators=220,
            min_samples_leaf=2,
            n_jobs=-1,
        )),
    ])

    opt_model.fit(x_train, y_opt_train)
    gain_model.fit(x_train, y_gain_train)
    multi_model.fit(x_train, np.column_stack([y_opt_train.to_numpy(), y_gain_train.to_numpy()]))

    pred_opt = opt_model.predict(x_test)
    pred_gain = np.maximum(gain_model.predict(x_test), 0.0)
    pred_multi = multi_model.predict(x_test)
    metrics: dict[str, Any] = {
        "rows": int(len(work)),
        "product_tier": tier,
        "feature_count": int(len(feature_cols)),
        "optimal_mae_s": float(mean_absolute_error(y_opt_test, pred_opt)),
        "gain_mae_s": float(mean_absolute_error(y_gain_test, pred_gain)),
        "multi_optimal_mae_s": float(mean_absolute_error(y_opt_test, pred_multi[:, 0])),
        "multi_gain_mae_s": float(mean_absolute_error(y_gain_test, np.maximum(pred_multi[:, 1], 0.0))),
        "feature_columns": feature_cols,
        "numeric_columns": num_cols,
        "categorical_columns": cat_cols,
    }
    cv_summary = _teacher_cross_validation(work, feature_cols, num_cols, cat_cols, random_state)
    if cv_summary:
        metrics["cross_validation"] = cv_summary

    # Diagnostic classifier (session-level proxy).
    diag_scores = _diag_score_table(work)
    diag_class_model = None
    diag_acc = None
    if "diag_primary_code" in work.columns:
        y_diag = work["diag_primary_code"].fillna("clean").astype(str)
        xdt, xdv, ydt, ydv = train_test_split(
            x,
            y_diag,
            test_size=0.2,
            random_state=int(random_state),
            stratify=y_diag if y_diag.nunique() > 1 else None,
        )
        diag_class_model = Pipeline([
            ("prep", _build_preprocessor(num_cols, cat_cols)),
            ("model", RandomForestClassifier(
                random_state=int(random_state),
                n_estimators=180,
                min_samples_leaf=2,
                n_jobs=-1,
            )),
        ])
        diag_class_model.fit(xdt, ydt)
        diag_pred = diag_class_model.predict(xdv)
        diag_acc = float(accuracy_score(ydv, diag_pred))
        metrics["diag_accuracy"] = diag_acc

    # Condition experts for gain.
    cond_models: dict[str, Pipeline] = {}
    if "condition_label" in work.columns:
        for cond, g in work.groupby("condition_label"):
            cond_name = str(cond).strip().lower()
            if not cond_name or len(g) < 20:
                continue
            cx = g[feature_cols]
            cy = g["gain_s"].astype(float)
            model = Pipeline([
                ("prep", _build_preprocessor(num_cols, cat_cols)),
                ("model", GradientBoostingRegressor(
                    random_state=int(random_state),
                    n_estimators=200,
                    max_depth=3,
                    learning_rate=0.05,
                    min_samples_leaf=2,
                )),
            ])
            model.fit(cx, cy)
            cond_models[cond_name] = model
    metrics["condition_experts"] = sorted(cond_models.keys())

    # Persist
    joblib.dump(opt_model, out_dir / "teacher_optimal.joblib")
    joblib.dump(gain_model, out_dir / "teacher_gain.joblib")
    joblib.dump(multi_model, out_dir / "teacher_multi.joblib")
    if diag_class_model is not None:
        joblib.dump(diag_class_model, out_dir / "teacher_diag.joblib")
    if cond_models:
        joblib.dump(cond_models, out_dir / "teacher_condition_experts.joblib")

    metadata = {
        "product_tier": tier,
        "metrics": metrics,
        "diagnostic_score_columns": diag_scores,
    }
    with open(out_dir / "teacher_metadata.json", "w", encoding="utf-8") as fh:
        json.dump(metadata, fh, indent=2)

    logger.info(
        "Teacher models trained -> %s (rows=%d, optimal_mae=%.4f, gain_mae=%.4f)",
        out_dir,
        len(work),
        metrics["optimal_mae_s"],
        metrics["gain_mae_s"],
    )
    return metadata


def _build_preprocessor(num_cols: list[str], cat_cols: list[str]) -> ColumnTransformer:
    try:
        ohe = OneHotEncoder(handle_unknown="ignore", sparse_output=False)
    except TypeError:
        ohe = OneHotEncoder(handle_unknown="ignore", sparse=False)
    return ColumnTransformer(
        transformers=[
            ("num", "passthrough", num_cols),
            ("cat", ohe, cat_cols),
        ],
        remainder="drop",
    )


def _diag_score_table(df: pd.DataFrame) -> list[str]:
    cols = [f"diag_{code}" for code in DIAGNOSTIC_CODES if f"diag_{code}" in df.columns]
    return cols


def _teacher_cross_validation(
    work: pd.DataFrame,
    feature_cols: list[str],
    num_cols: list[str],
    cat_cols: list[str],
    random_state: int,
) -> dict[str, Any]:
    """
    Run session-aware GroupKFold validation for teacher regressors.

    We split by session_id to avoid optimistic leakage from lap-to-lap
    similarity within the same session.
    """
    if "session_id" not in work.columns:
        return {}
    groups = work["session_id"].fillna("").astype(str).to_numpy()
    unique_groups = sorted({g for g in groups if g})
    if len(unique_groups) < 3:
        return {}

    n_splits = min(5, len(unique_groups))
    if n_splits < 3:
        return {}

    x = work[feature_cols]
    y_opt = work["optimal_lap_time_s"].astype(float).to_numpy()
    y_gain = work["gain_s"].astype(float).to_numpy()

    gkf = GroupKFold(n_splits=n_splits)
    opt_mae: list[float] = []
    gain_mae: list[float] = []

    fold = 0
    for tr_idx, te_idx in gkf.split(x, y_opt, groups):
        fold += 1
        x_tr = x.iloc[tr_idx]
        x_te = x.iloc[te_idx]
        y_opt_tr = y_opt[tr_idx]
        y_opt_te = y_opt[te_idx]
        y_gain_tr = y_gain[tr_idx]
        y_gain_te = y_gain[te_idx]

        opt_model = Pipeline([
            ("prep", _build_preprocessor(num_cols, cat_cols)),
            ("model", GradientBoostingRegressor(
                random_state=int(random_state + fold),
                n_estimators=220,
                max_depth=4,
                learning_rate=0.05,
                min_samples_leaf=3,
            )),
        ])
        gain_model = Pipeline([
            ("prep", _build_preprocessor(num_cols, cat_cols)),
            ("model", GradientBoostingRegressor(
                random_state=int(random_state + 100 + fold),
                n_estimators=220,
                max_depth=4,
                learning_rate=0.05,
                min_samples_leaf=3,
            )),
        ])

        opt_model.fit(x_tr, y_opt_tr)
        gain_model.fit(x_tr, y_gain_tr)
        pred_opt = np.asarray(opt_model.predict(x_te), dtype=float)
        pred_gain = np.maximum(np.asarray(gain_model.predict(x_te), dtype=float), 0.0)

        opt_mae.append(float(mean_absolute_error(y_opt_te, pred_opt)))
        gain_mae.append(float(mean_absolute_error(y_gain_te, pred_gain)))

    return {
        "mode": "group_kfold_session",
        "n_splits": int(n_splits),
        "groups": int(len(unique_groups)),
        "optimal_mae_mean_s": float(np.mean(opt_mae)),
        "optimal_mae_std_s": float(np.std(opt_mae)),
        "gain_mae_mean_s": float(np.mean(gain_mae)),
        "gain_mae_std_s": float(np.std(gain_mae)),
    }
