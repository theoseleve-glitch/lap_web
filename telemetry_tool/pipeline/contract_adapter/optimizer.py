"""Build an OptimizerContract from the real-life pipeline summary.

Real-life is always TRAJECTORY_ONLY depth. FULL_FIDELITY is sim territory
(W4a/W4b). The contract validator rejects reconstructed_inputs for this
depth -- we never populate it here.
"""
from __future__ import annotations

import logging
from typing import Any

from telemetry_tool.web.schemas.contracts import OptimizerContract
from telemetry_tool.web.schemas.contracts.optimizer import (
    CornerDelta,
    OptimizerDepth,
    TrajectoryDelta,
)

logger = logging.getLogger(__name__)


def _clamp01(x: Any) -> float:
    if not isinstance(x, (int, float)):
        return 0.5
    return max(0.0, min(1.0, float(x)))


def _build_corner_deltas(summary: dict[str, Any]) -> list[CornerDelta]:
    rows = summary.get("corner_coaching") or []
    out: list[CornerDelta] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        try:
            out.append(CornerDelta(
                corner_id=str(r.get("corner_id")),
                time_loss_s=float(r.get("time_loss_s") or 0.0),
                root_cause=str(r.get("root_cause") or "unknown"),
                coaching_text=str(r.get("summary") or r.get("coaching_text") or ""),
                phase=(r.get("phase") or None),
            ))
        except Exception:
            logger.warning("skipping malformed corner_coaching row: %r", r)
    return out


def _build_trajectory_delta(summary: dict[str, Any]) -> TrajectoryDelta | None:
    df = summary.get("delta_map")
    if df is None:
        return None
    try:
        distance = df["distance_m"].tolist()
        speed = df["speed_delta_mps"].tolist()
    except Exception:
        logger.warning("delta_map missing expected columns")
        return None
    if not distance or len(distance) != len(speed):
        return None
    return TrajectoryDelta(
        distance_m=[float(x) for x in distance],
        speed_delta_ms=[float(x) for x in speed],
    )


def _build_validation(summary: dict[str, Any], attributed_loss_s: float) -> dict[str, Any]:
    theo = summary.get("theoretical_metrics") or {}
    best = theo.get("best_s")
    driver_best = None
    lap_times = [
        t for t in (summary.get("lap_times") or [])
        if isinstance(t, (int, float)) and t > 0
    ]
    if lap_times:
        driver_best = min(lap_times)
    gap = (driver_best - best) if (best and driver_best) else None
    return {
        "method_notes": summary.get("sim_method"),
        "driver_best_s": driver_best,
        "gap_to_theoretical_s": gap,
        "attributed_loss_s": attributed_loss_s,
        "unattributed_loss_s": (
            (gap - attributed_loss_s)
            if (gap is not None and attributed_loss_s is not None) else None
        ),
    }


def _build_vehicle_model(summary: dict[str, Any]) -> dict[str, Any]:
    vp = summary.get("vehicle_params")
    if vp is None:
        return {"note": "unidentified - trajectory-only mode"}
    if hasattr(vp, "to_dict"):
        try:
            return vp.to_dict()
        except Exception:
            return {"note": repr(vp)}
    if isinstance(vp, dict):
        return vp
    return {"note": repr(vp)}


def build_optimizer_contract(summary: dict[str, Any]) -> OptimizerContract:
    corner_deltas = _build_corner_deltas(summary)
    total_loss = sum(cd.time_loss_s for cd in corner_deltas)
    theo = summary.get("theoretical_metrics") or {}
    return OptimizerContract(
        depth=OptimizerDepth.TRAJECTORY_ONLY,
        method=str(summary.get("sim_method") or "trajectory"),
        theoretical_lap_time_s=float(theo.get("best_s") or 0.0),
        confidence=_clamp01(summary.get("theoretical_confidence", 0.5)),
        corner_deltas=corner_deltas,
        total_time_loss_s=total_loss,
        trajectory_delta=_build_trajectory_delta(summary),
        reconstructed_inputs=None,
        vehicle_model=_build_vehicle_model(summary),
        validation=_build_validation(summary, total_loss),
    )
