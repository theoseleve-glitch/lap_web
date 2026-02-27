"""
policy_train.py
---------------
Offline MPC-imitation policy trainer (lightweight artifact builder).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def train_mpc_imitation_policy(
    dataset_path: Path,
    *,
    output_dir: Path,
    min_rows: int = 30,
) -> dict[str, Any]:
    """
    Build a lightweight policy artifact for online confidence-gated usage.

    This trainer intentionally keeps dependencies minimal. It derives a robust
    corner-action table from historical rows and emits summary confidence.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    df = _read_table(dataset_path)
    if df is None or df.empty:
        payload = _empty_payload(reason="dataset_missing_or_empty")
        _write_payload(output_dir / "mpc_imitation_policy.json", payload)
        return payload

    use_cols = [
        "corner_id",
        "condition_label",
        "brake_shift_s",
        "turn_shift_m",
        "lat_force_scale",
        "brake_force_scale",
        "gain_s",
    ]
    for col in use_cols:
        if col not in df.columns:
            df[col] = 0.0 if col != "condition_label" else ""

    work = df[use_cols].copy()
    for c in ("corner_id",):
        work[c] = pd.to_numeric(work[c], errors="coerce")
    for c in ("brake_shift_s", "turn_shift_m", "lat_force_scale", "brake_force_scale", "gain_s"):
        work[c] = pd.to_numeric(work[c], errors="coerce")
    work["condition_label"] = work["condition_label"].astype(str).fillna("")
    work = work.replace([np.inf, -np.inf], np.nan).dropna(subset=["corner_id"])

    if len(work) < int(max(min_rows, 1)):
        payload = _empty_payload(reason="insufficient_rows", rows=int(len(work)))
        _write_payload(output_dir / "mpc_imitation_policy.json", payload)
        return payload

    if "gain_s" in work.columns:
        work = work[work["gain_s"].fillna(0.0) > 0.0]
    if work.empty:
        payload = _empty_payload(reason="no_positive_gain_rows", rows=0)
        _write_payload(output_dir / "mpc_imitation_policy.json", payload)
        return payload

    grouped = work.groupby(["corner_id", "condition_label"], dropna=False).agg({
        "brake_shift_s": "median",
        "turn_shift_m": "median",
        "lat_force_scale": "median",
        "brake_force_scale": "median",
        "gain_s": "mean",
    }).reset_index()
    grouped = grouped.rename(columns={"gain_s": "expected_gain_s"})
    counts = work.groupby(["corner_id", "condition_label"]).size().rename("n_samples").reset_index()
    table = grouped.merge(counts, on=["corner_id", "condition_label"], how="left")
    table["corner_id"] = table["corner_id"].astype(int)
    table = table.sort_values(["corner_id", "condition_label"]).reset_index(drop=True)
    table.to_csv(output_dir / "mpc_imitation_policy.csv", index=False)

    coverage = float(np.clip(len(table) / max(len(work), 1), 0.0, 1.0))
    gain_med = float(np.nanmedian(pd.to_numeric(table["expected_gain_s"], errors="coerce").fillna(0.0)))
    conf = float(np.clip(0.50 * coverage + 0.50 * np.clip(gain_med / 0.30, 0.0, 1.0), 0.0, 1.0))
    payload = {
        "available": True,
        "rows": int(len(table)),
        "source_rows": int(len(work)),
        "coverage": round(coverage, 4),
        "confidence": round(conf, 4),
        "artifact_csv": "mpc_imitation_policy.csv",
        "notes": "offline_mpc_imitation_proxy",
    }
    _write_payload(output_dir / "mpc_imitation_policy.json", payload)
    return payload


def _read_table(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    try:
        if path.suffix.lower() in {".parquet", ".pq"}:
            return pd.read_parquet(path)
        return pd.read_csv(path)
    except Exception:
        return None


def _empty_payload(reason: str, rows: int = 0) -> dict[str, Any]:
    return {
        "available": False,
        "rows": int(rows),
        "source_rows": int(rows),
        "coverage": 0.0,
        "confidence": 0.0,
        "artifact_csv": "",
        "notes": reason,
    }


def _write_payload(path: Path, payload: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)

