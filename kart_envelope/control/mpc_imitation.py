"""
mpc_imitation.py
----------------
Lightweight runtime helpers for confidence-gated MPC-imitation policy usage.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


@dataclass
class MPCImitationArtifact:
    """Summary of an offline-trained MPC-imitation artifact."""

    available: bool
    path: str
    coverage: float
    confidence: float
    rows: int
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": bool(self.available),
            "path": self.path,
            "coverage": round(float(self.coverage), 4),
            "confidence": round(float(self.confidence), 4),
            "rows": int(self.rows),
            "notes": self.notes,
        }


def resolve_mpc_imitation_artifact(bundle_dir: Path | None) -> MPCImitationArtifact:
    """Load the optional MPC-imitation artifact metadata from a bundle directory."""
    if bundle_dir is None:
        return MPCImitationArtifact(
            available=False,
            path="",
            coverage=0.0,
            confidence=0.0,
            rows=0,
            notes="bundle_dir_missing",
        )
    meta_path = Path(bundle_dir) / "mpc_imitation_policy.json"
    if not meta_path.exists():
        return MPCImitationArtifact(
            available=False,
            path=str(meta_path),
            coverage=0.0,
            confidence=0.0,
            rows=0,
            notes="artifact_missing",
        )
    try:
        with open(meta_path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except Exception:
        return MPCImitationArtifact(
            available=False,
            path=str(meta_path),
            coverage=0.0,
            confidence=0.0,
            rows=0,
            notes="artifact_invalid_json",
        )
    if not isinstance(raw, dict):
        return MPCImitationArtifact(
            available=False,
            path=str(meta_path),
            coverage=0.0,
            confidence=0.0,
            rows=0,
            notes="artifact_invalid_payload",
        )
    coverage = _coerce_float(raw.get("coverage"), 0.0)
    confidence = _coerce_float(raw.get("confidence"), 0.0)
    rows = int(max(0, _coerce_float(raw.get("rows"), 0.0)))
    return MPCImitationArtifact(
        available=True,
        path=str(meta_path),
        coverage=float(np.clip(coverage, 0.0, 1.0)),
        confidence=float(np.clip(confidence, 0.0, 1.0)),
        rows=rows,
        notes=str(raw.get("notes") or ""),
    )


def score_policy_confidence(
    *,
    quality_score: float,
    artifact: MPCImitationArtifact,
    min_threshold: float,
) -> tuple[float, bool]:
    """
    Combine runtime quality and artifact quality into one confidence score.
    """
    q = float(np.clip(quality_score, 0.0, 1.0))
    if not artifact.available:
        return q, False
    a = float(np.clip(artifact.confidence, 0.0, 1.0))
    c = float(np.clip(artifact.coverage, 0.0, 1.0))
    blended = float(np.clip(0.50 * q + 0.30 * a + 0.20 * c, 0.0, 1.0))
    ok = bool(blended >= float(np.clip(min_threshold, 0.0, 1.0)))
    return blended, ok


def _coerce_float(value: object, default: float) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return float(default)
    if not np.isfinite(out):
        return float(default)
    return float(out)

