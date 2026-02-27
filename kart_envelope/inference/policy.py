"""
policy.py
---------
Cycle-A driver policy selector.

Online behavior:
- always supports deterministic virtual policy
- optionally activates advanced bundle policy when coverage/confidence gates pass
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from kart_envelope.config import KartEnvelopeConfig
from kart_envelope.control.mpc_imitation import (
    resolve_mpc_imitation_artifact,
    score_policy_confidence,
)


@dataclass
class PolicySelection:
    """Selected policy metadata for one session."""

    selected_policy: str
    confidence: float
    source: str
    reason: str
    advanced_available: bool
    advanced_rows: int
    mpc_available: bool = False
    mpc_confidence: float = 0.0
    mpc_coverage: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_policy": self.selected_policy,
            "confidence": round(float(self.confidence), 4),
            "source": self.source,
            "reason": self.reason,
            "advanced_available": bool(self.advanced_available),
            "advanced_rows": int(self.advanced_rows),
            "mpc_available": bool(self.mpc_available),
            "mpc_confidence": round(float(self.mpc_confidence), 4),
            "mpc_coverage": round(float(self.mpc_coverage), 4),
        }


def select_driver_policy(
    config: KartEnvelopeConfig,
    *,
    quality_score: float,
    bundle_dir: Path | None = None,
) -> PolicySelection:
    """Select virtual vs advanced policy for online usage."""
    virtual_on = bool(config.policy_enable_virtual_driver)
    advanced_on = bool(config.policy_enable_advanced_driver)
    mpc_on = bool(config.policy_enable_mpc_imitation)
    adv_rows = 0
    adv_ok = False
    if advanced_on and bundle_dir is not None:
        adv_rows = _count_policy_rows(bundle_dir)
        adv_ok = adv_rows >= 5
    mpc_art = resolve_mpc_imitation_artifact(bundle_dir if mpc_on else None)
    mpc_score, mpc_ok = score_policy_confidence(
        quality_score=float(np.clip(quality_score, 0.0, 1.0)),
        artifact=mpc_art,
        min_threshold=float(np.clip(config.policy_mpc_confidence_threshold, 0.0, 1.0)),
    )

    q = float(np.clip(quality_score, 0.0, 1.0))
    threshold = float(np.clip(config.policy_advanced_min_confidence, 0.0, 1.0))
    if mpc_on and mpc_art.available and mpc_ok:
        return PolicySelection(
            selected_policy="advanced_mpc_imitation",
            confidence=float(np.clip(mpc_score, 0.0, 1.0)),
            source="bundle_v2_mpc_imitation",
            reason=(
                f"mpc_imitation confidence gate passed "
                f"({mpc_score:.3f} >= {config.policy_mpc_confidence_threshold:.3f})"
            ),
            advanced_available=adv_ok,
            advanced_rows=adv_rows,
            mpc_available=True,
            mpc_confidence=float(np.clip(mpc_art.confidence, 0.0, 1.0)),
            mpc_coverage=float(np.clip(mpc_art.coverage, 0.0, 1.0)),
        )

    if advanced_on and adv_ok and q >= threshold:
        return PolicySelection(
            selected_policy="advanced_bundle_policy",
            confidence=q,
            source="bundle_v2",
            reason=f"quality_score={q:.3f} >= threshold={threshold:.3f} and policy table is available",
            advanced_available=True,
            advanced_rows=adv_rows,
            mpc_available=bool(mpc_art.available),
            mpc_confidence=float(np.clip(mpc_art.confidence, 0.0, 1.0)),
            mpc_coverage=float(np.clip(mpc_art.coverage, 0.0, 1.0)),
        )

    if virtual_on:
        reason = "advanced policy disabled or confidence/coverage gate not met"
        if advanced_on and not adv_ok:
            reason = "advanced policy file missing/too small; fallback to virtual policy"
        elif advanced_on and adv_ok and q < threshold:
            reason = f"advanced policy confidence gate failed ({q:.3f} < {threshold:.3f})"
        return PolicySelection(
            selected_policy="virtual_reference_policy",
            confidence=max(0.40, q),
            source="runtime_virtual_driver",
            reason=reason,
            advanced_available=adv_ok,
            advanced_rows=adv_rows,
            mpc_available=bool(mpc_art.available),
            mpc_confidence=float(np.clip(mpc_art.confidence, 0.0, 1.0)),
            mpc_coverage=float(np.clip(mpc_art.coverage, 0.0, 1.0)),
        )

    return PolicySelection(
        selected_policy="none",
        confidence=0.0,
        source="disabled",
        reason="all driver policy layers disabled",
        advanced_available=adv_ok,
        advanced_rows=adv_rows,
        mpc_available=bool(mpc_art.available),
        mpc_confidence=float(np.clip(mpc_art.confidence, 0.0, 1.0)),
        mpc_coverage=float(np.clip(mpc_art.coverage, 0.0, 1.0)),
    )


def build_policy_attribution(
    lap_numbers: list[int],
    selection: PolicySelection,
) -> list[dict[str, Any]]:
    """Attach policy metadata to per-lap outputs."""
    rows: list[dict[str, Any]] = []
    for lap in lap_numbers:
        rows.append({
            "lap_number": int(lap),
            "policy": selection.selected_policy,
            "policy_confidence": round(float(selection.confidence), 4),
            "policy_source": selection.source,
        })
    return rows


def _count_policy_rows(bundle_dir: Path) -> int:
    base = Path(bundle_dir)
    parquet_path = base / "policy_corner_table.parquet"
    if parquet_path.exists():
        try:
            df = pd.read_parquet(parquet_path)
            return int(len(df))
        except Exception:
            pass
    csv_path = base / "policy_corner_table.csv"
    if csv_path.exists():
        try:
            df = pd.read_csv(csv_path)
            return int(len(df))
        except Exception:
            return 0
    return 0
