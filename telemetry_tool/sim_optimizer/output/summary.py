"""Session-level summary JSON generation."""
from __future__ import annotations

from typing import Any


def build_session_summary(
    theoretical_result,
    input_trace,
    corners: list,
    vehicle_model,
    validation: dict[str, Any],
    *,
    session_id: str = "",
) -> dict[str, Any]:
    """Build complete session summary dict.

    Keys: session_id, theoretical_lap_time_s, method, vehicle_model (sub-dict),
    validation (sub-dict), n_corners, top_corners (top 5 by time loss),
    total_time_loss_s
    """
    # Sort corners by time_loss_s descending, take top 5
    sorted_corners = sorted(
        corners,
        key=lambda c: getattr(c, "time_loss_s", 0.0) if not isinstance(c, dict) else c.get("time_loss_s", 0.0),
        reverse=True,
    )
    top_5 = sorted_corners[:5]

    top_corners_dicts: list[dict[str, Any]] = []
    for c in top_5:
        if isinstance(c, dict):
            top_corners_dicts.append(c)
        elif hasattr(c, "to_dict"):
            top_corners_dicts.append(c.to_dict())
        else:
            top_corners_dicts.append({
                "corner_id": getattr(c, "corner_id", None),
                "time_loss_s": getattr(c, "time_loss_s", 0.0),
                "root_cause": getattr(c, "root_cause", ""),
                "coaching_text": getattr(c, "coaching_text", ""),
            })

    total_time_loss = sum(
        (getattr(c, "time_loss_s", 0.0) if not isinstance(c, dict) else c.get("time_loss_s", 0.0))
        for c in corners
    )

    vehicle_dict: dict[str, Any] = {}
    if vehicle_model is not None:
        if hasattr(vehicle_model, "to_dict"):
            vehicle_dict = vehicle_model.to_dict()
        elif isinstance(vehicle_model, dict):
            vehicle_dict = vehicle_model

    return {
        "session_id": session_id,
        "theoretical_lap_time_s": round(float(theoretical_result.lap_time_s), 3),
        "method": str(theoretical_result.method),
        "vehicle_model": vehicle_dict,
        "validation": validation,
        "n_corners": len(corners),
        "top_corners": top_corners_dicts,
        "total_time_loss_s": round(float(total_time_loss), 3),
    }
