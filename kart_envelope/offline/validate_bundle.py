"""
validate_bundle.py
------------------
Bundle_v2 structural and functional validator.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

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
)

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


def validate_bundle(bundle_dir: Path, sample_df: pd.DataFrame | None = None) -> dict[str, Any]:
    """Validate bundle structure and run a smoke inference."""
    report: dict[str, Any] = {
        "bundle_dir": str(bundle_dir),
        "exists": bundle_dir.exists(),
        "missing_files": [],
        "smoke_inference_ok": False,
        "errors": [],
    }
    if not bundle_dir.exists():
        report["errors"].append("bundle directory does not exist")
        return report

    missing = [f for f in REQUIRED_BUNDLE_FILES if not (bundle_dir / f).exists()]
    report["missing_files"] = missing
    if missing:
        report["errors"].append(f"missing required files: {missing}")
        return report

    try:
        student = joblib.load(bundle_dir / "student_regressor.joblib")
        if not isinstance(student, dict):
            raise TypeError("student_regressor.joblib must contain a dict artifact")
        pre = student.get("preprocessor")
        m_opt = student.get("model_optimal")
        m_gain = student.get("model_gain")
        if pre is None or m_opt is None or m_gain is None:
            raise ValueError("student bundle missing required objects")

        feature_schema = _read_json(bundle_dir / "feature_schema.json")
        num_cols = list(feature_schema.get("numeric_features", []))
        cat_cols = list(feature_schema.get("categorical_features", []))
        feat_cols = num_cols + cat_cols
        if not feat_cols:
            raise ValueError("empty feature schema")

        if sample_df is None or sample_df.empty:
            # Build one neutral row from schema.
            row = {c: 0.0 for c in num_cols}
            row.update({c: "" for c in cat_cols})
            sample_df = pd.DataFrame([row])
        x = sample_df.copy()
        for c in feat_cols:
            if c not in x.columns:
                x[c] = 0.0 if c in num_cols else ""
        x = x[feat_cols]
        xt = pre.transform(x)
        pred_opt = np.asarray(m_opt.predict(xt), dtype=float)
        pred_gain = np.asarray(m_gain.predict(xt), dtype=float)
        if pred_opt.size == 0 or pred_gain.size == 0:
            raise ValueError("empty prediction arrays")
        report["smoke_inference_ok"] = True
        report["smoke_optimal_sample"] = float(pred_opt[0])
        report["smoke_gain_sample"] = float(max(0.0, pred_gain[0]))
    except Exception as exc:
        report["errors"].append(f"smoke inference failed: {exc}")
        return report

    return report


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}
