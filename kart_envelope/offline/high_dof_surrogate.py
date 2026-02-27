"""
high_dof_surrogate.py
---------------------
Offline trainer for high-DOF distilled correction artifact.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def train_high_dof_surrogate(
    dataset_path: Path,
    *,
    output_dir: Path,
    min_rows: int = 50,
) -> dict[str, Any]:
    """
    Train a lightweight correction surrogate from offline data.

    The artifact is a compact linear model used online as a bounded
    multiplicative correction channel.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    df = _read_table(dataset_path)
    if df is None or df.empty:
        payload = _empty_payload("dataset_missing_or_empty")
        _write(output_dir / "high_dof_surrogate.json", payload)
        return payload

    required = [
        "speed_coverage",
        "accel_coverage",
        "yaw_coverage",
        "mu_session",
        "condition_label",
        "predicted_gain_s",
    ]
    for col in required:
        if col not in df.columns:
            if col == "condition_label":
                df[col] = ""
            else:
                df[col] = np.nan

    work = df[required].copy()
    for col in ("speed_coverage", "accel_coverage", "yaw_coverage", "mu_session", "predicted_gain_s"):
        work[col] = pd.to_numeric(work[col], errors="coerce")
    work["condition_label"] = work["condition_label"].astype(str).fillna("")
    work = work.replace([np.inf, -np.inf], np.nan).dropna()
    if len(work) < int(max(min_rows, 1)):
        payload = _empty_payload("insufficient_rows", rows=int(len(work)))
        _write(output_dir / "high_dof_surrogate.json", payload)
        return payload

    X = np.column_stack([
        np.asarray(work["speed_coverage"], dtype=float),
        np.asarray(work["accel_coverage"], dtype=float),
        np.asarray(work["yaw_coverage"], dtype=float),
        np.asarray(work["mu_session"], dtype=float),
        _condition_code(work["condition_label"]),
        np.ones(len(work), dtype=float),
    ])
    y = np.asarray(work["predicted_gain_s"], dtype=float)

    # Ridge-regularized least squares (closed form).
    lam = 1e-2
    xtx = X.T @ X
    w = np.linalg.solve(xtx + lam * np.eye(xtx.shape[0]), X.T @ y)
    pred = X @ w
    resid = y - pred
    sigma = float(np.nanstd(resid))
    mae = float(np.nanmean(np.abs(resid)))
    cov = float(np.clip(len(work) / max(len(df), 1), 0.0, 1.0))
    conf = float(np.clip(0.55 * cov + 0.45 * np.clip(1.0 - mae / 0.40, 0.0, 1.0), 0.0, 1.0))

    payload = {
        "available": True,
        "rows": int(len(work)),
        "coverage": round(cov, 4),
        "confidence": round(conf, 4),
        "weights": [round(float(v), 8) for v in w.tolist()],
        "residual_sigma_s": round(float(max(0.02, sigma)), 6),
        "mae_s": round(mae, 6),
        "features": [
            "speed_coverage",
            "accel_coverage",
            "yaw_coverage",
            "mu_session",
            "condition_code",
            "bias",
        ],
        "notes": "offline_high_dof_linear_surrogate",
    }
    _write(output_dir / "high_dof_surrogate.json", payload)
    return payload


def _condition_code(s: pd.Series) -> np.ndarray:
    vals = []
    for raw in s.astype(str):
        c = raw.strip().lower()
        if "wet" in c:
            vals.append(-1.0)
        elif "damp" in c or "greasy" in c:
            vals.append(-0.5)
        elif "green" in c:
            vals.append(-0.2)
        else:
            vals.append(0.2)
    return np.asarray(vals, dtype=float)


def _empty_payload(reason: str, rows: int = 0) -> dict[str, Any]:
    return {
        "available": False,
        "rows": int(rows),
        "coverage": 0.0,
        "confidence": 0.0,
        "weights": [],
        "residual_sigma_s": None,
        "mae_s": None,
        "features": [],
        "notes": reason,
    }


def _read_table(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    try:
        if path.suffix.lower() in {".parquet", ".pq"}:
            return pd.read_parquet(path)
        return pd.read_csv(path)
    except Exception:
        return None


def _write(path: Path, payload: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)

