"""
json_summary.py
---------------
Build and write the ``session_summary.json`` output.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kart_envelope.coaching.cause_ranking import TimeLossCause
from kart_envelope.coaching.corner_coaching import CornerPerformance
from kart_envelope.inference.session_scalars import SessionScalars
from kart_envelope.ingest.metadata import SessionMetadata
from kart_envelope.solver.min_time import TheoreticalResult
from kart_envelope.solver.record_cal import RecordCalibration

logger = logging.getLogger(__name__)


def build_session_summary(
    metadata: SessionMetadata,
    scalars: SessionScalars,
    theoretical: TheoreticalResult,
    corner_perfs: list[CornerPerformance],
    causes: list[TimeLossCause],
    lap_times: dict[int, float],
    best_lap_num: int,
    record_cal: RecordCalibration | None = None,
    coaching_text: str = "",
) -> dict[str, Any]:
    """Build the session_summary.json structure."""
    best_time = lap_times.get(best_lap_num, 0.0)
    all_times = list(lap_times.values())

    import numpy as np
    median_time = float(np.median(all_times)) if all_times else 0.0
    std_time = float(np.std(all_times)) if len(all_times) > 1 else 0.0

    summary: dict[str, Any] = {
        "version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "session": {
            "file": metadata.session_file,
            "kart_id": metadata.kart_id,
            "kart_class": metadata.kart_class,
            "track_name": metadata.track_name or "",
            "condition_label": metadata.condition_label or scalars.condition_label,
            "driver_weight_kg": metadata.driver_weight_kg,
        },
        "lap_statistics": {
            "n_laps": len(lap_times),
            "best_lap_number": best_lap_num,
            "best_lap_time_s": round(best_time, 4),
            "median_lap_time_s": round(median_time, 4),
            "std_lap_time_s": round(std_time, 4),
            "all_lap_times_s": {str(k): round(v, 4) for k, v in sorted(lap_times.items())},
        },
        "theoretical": theoretical.to_dict(),
        "session_scalars": {
            "mu_session": round(scalars.mu_session, 4),
            "p_session": round(scalars.p_session, 4),
            "b_session": round(scalars.b_session, 4),
            "confidence": round(scalars.confidence, 4),
            "condition_label": scalars.condition_label,
        },
        "top_corners": [c.to_dict() for c in causes[:10]],
        "corner_details": [cp.to_dict() for cp in corner_perfs[:20]],
        "coaching_text": coaching_text,
    }

    if record_cal is not None:
        summary["record_calibration"] = record_cal.to_dict()

    return summary


def write_session_summary(summary: dict[str, Any], path: Path) -> None:
    """Write formatted JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, default=str)
    logger.info("Wrote session_summary.json to %s", path)
