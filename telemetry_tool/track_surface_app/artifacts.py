"""ArtifactWriter — serialize PipelineResult to frontend-safe JSON files.

Each artifact is a stable DTO. No numpy arrays, no internal dataclasses, no
research-layer leakage. Output lands under ``<base>/<session_id>/<run_id>/``.

Artifact kinds and their schemas are documented in
``docs/plans/2026-04-15-track-surface-analysis-app-design.md`` §10.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from track_surface_app.gating import OutputGate

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _finite(value: Any, default: float = 0.0) -> float:
    """Return value cast to float, falling back to default for NaN / non-finite."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    if f != f or f in (float("inf"), float("-inf")):   # NaN or Inf
        return default
    return f


class ArtifactWriter:
    """Writes frontend-safe DTOs for one analysis run.

    The writer never raises on unusual PipelineResult shapes; it coerces
    silently (missing fields become zero/null) so a partial-success run can
    still produce a meaningful summary + diagnostics.
    """

    def __init__(self, base_dir: Path | str, run_id: str, session_id: int):
        self._base = Path(base_dir) / str(session_id) / run_id
        self._run_id = run_id
        self._session_id = session_id

    def write_all(self, pipeline_result: Any, gate: OutputGate) -> dict[str, str]:
        """Write every artifact kind allowed by ``gate``.

        Returns a mapping ``{kind: relative_path}`` suitable for the
        ``artifacts_index`` column on ``analysis_runs``.
        """
        self._base.mkdir(parents=True, exist_ok=True)
        index: dict[str, str] = {}

        builders = {
            "summary": self._build_summary,
            "surface_field": self._build_surface_field,
            "confidence_heatmap": self._build_confidence_heatmap,
            "planner_nominal": lambda pr: self._build_planner(pr, "nominal"),
            "planner_robust": lambda pr: self._build_planner(pr, "robust"),
            "planner_exploitable": lambda pr: self._build_planner(pr, "exploitable"),
            "racing_line_deltas": self._build_racing_line_deltas,
            "diagnostics": self._build_diagnostics,
        }

        for kind, builder in builders.items():
            if not gate.is_artifact_allowed(kind):
                continue
            try:
                dto = builder(pipeline_result)
            except Exception as exc:   # artifact-local failure; log + skip
                logger.exception("Failed to build artifact %s for run %s: %s",
                                 kind, self._run_id, exc)
                continue
            rel_path = f"{self._session_id}/{self._run_id}/{kind}.json"
            full_path = self._base / f"{kind}.json"
            full_path.write_text(json.dumps(dto, ensure_ascii=False, sort_keys=True))
            index[kind] = rel_path

        return index

    # ── Individual builders ─────────────────────────────────

    def _header(self) -> dict[str, Any]:
        return {
            "run_id": self._run_id,
            "session_id": self._session_id,
            "generated_at": _now_iso(),
        }

    def _build_summary(self, pr: Any) -> dict[str, Any]:
        return {
            **self._header(),
            "n_samples_total": int(getattr(pr, "n_samples_total", 0) or 0),
            "n_samples_accepted": int(getattr(pr, "n_valid", 0) or 0),
            "n_laps": int(getattr(pr, "n_laps", 0) or 0),
            "best_lap": int(getattr(pr, "best_lap", -1) or -1),
            "best_lap_time_s": _finite(getattr(pr, "best_lap_time_s", 0.0)),
            "track_length_m": _finite(getattr(pr, "track_length_m", 0.0)),
            "lap_times_s": {str(k): _finite(v) for k, v in
                            (getattr(pr, "lap_times_s", {}) or {}).items()},
            "warnings": list(getattr(pr, "pipeline_warnings", []) or []),
            "calibration_profile_id": getattr(pr, "calibration_profile_id", None),
            "calibration_source": getattr(pr, "calibration_source", None),
        }

    def _build_surface_field(self, pr: Any) -> dict[str, Any]:
        return {
            **self._header(),
            "coverage_pct": _finite(getattr(pr, "field_coverage_pct", 0.0)),
            "mean_confidence": _finite(getattr(pr, "field_mean_confidence", 0.0)),
            "cells_observed": int(getattr(pr, "field_cells_observed", 0) or 0),
            "cells_total": int(getattr(pr, "field_cells_total", 0) or 0),
            "bucket_active_count": int(getattr(pr, "bucket_active_count", 0) or 0),
            "bucket_sparse_count": int(getattr(pr, "bucket_sparse_count", 0) or 0),
            # No full mesh in v1 — downsampled mesh is future work; we publish
            # the stats that every tier above D needs without exposing raw cells.
        }

    def _build_confidence_heatmap(self, pr: Any) -> dict[str, Any]:
        # Placeholder shape — no raw per-cell data in v1. Histogram only.
        conf = _finite(getattr(pr, "field_mean_confidence", 0.0))
        return {
            **self._header(),
            "mean_confidence": conf,
            "high_conf_cells": int(getattr(pr, "field_high_conf_cells", 0) or 0),
            "zero_conf_cells": int(getattr(pr, "field_zero_conf_cells", 0) or 0),
            "histogram_buckets": [
                {"low": 0.0, "high": 0.25, "label": "very_low"},
                {"low": 0.25, "high": 0.50, "label": "low"},
                {"low": 0.50, "high": 0.75, "label": "medium"},
                {"low": 0.75, "high": 1.0, "label": "high"},
            ],
        }

    def _build_planner(self, pr: Any, mode: str) -> dict[str, Any]:
        mean_mu_field = f"planner_{mode}_mean_mu"
        return {
            **self._header(),
            "mode": mode,
            "mu_eff_mean": _finite(getattr(pr, mean_mu_field, 0.0)),
            "trusted_point_count": int(getattr(pr, "planner_n_trusted", 0) or 0),
            "degraded_point_count": int(getattr(pr, "planner_n_degraded", 0) or 0),
            "total_point_count": (
                int(getattr(pr, "planner_n_trusted", 0) or 0)
                + int(getattr(pr, "planner_n_degraded", 0) or 0)
            ),
            "max_robust_penalty": _finite(getattr(pr, "planner_max_robust_penalty", 0.0)),
        }

    def _build_racing_line_deltas(self, pr: Any) -> dict[str, Any]:
        return {
            **self._header(),
            "center_lambda": _finite(getattr(pr, "racing_line_center_lambda", 0.0)),
            "left_lambda": _finite(getattr(pr, "racing_line_left_lambda", 0.0)),
            "right_lambda": _finite(getattr(pr, "racing_line_right_lambda", 0.0)),
        }

    def _build_diagnostics(self, pr: Any) -> dict[str, Any]:
        # Intentionally light — this artifact is always public.
        return {
            **self._header(),
            "elapsed_s": _finite(getattr(pr, "elapsed_s", 0.0)),
            "exception": getattr(pr, "exception", None),
            "gate_accept_pct": _finite(getattr(pr, "gate_accept_pct", 0.0)),
            "transition_pct": _finite(getattr(pr, "transition_pct", 0.0)),
            "fy_residual_std": _finite(getattr(pr, "fy_residual_std", 0.0)),
            "fx_residual_std": _finite(getattr(pr, "fx_residual_std", 0.0)),
            "bucket_fallback_distribution": {
                str(k): int(v) for k, v in
                (getattr(pr, "bucket_fallback_distribution", {}) or {}).items()
            },
        }
