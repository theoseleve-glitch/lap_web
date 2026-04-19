"""Cross-check theoretical lap time against iRacing's optimal."""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

_SLOW_THRESHOLD_S = 1.0


def validate_against_iracing_optimal(
    our_lap_time_s: float,
    iracing_optimal_delta: np.ndarray | None,
) -> dict[str, Any]:
    """Compare our theoretical lap time to iRacing's sector-composite optimal.

    Returns dict with:
    - "status": "pass"|"warn"|"skip"
    - "our_lap_time_s": our time
    - "iracing_optimal_delta_median_s": median of iRacing delta (None if unavailable)
    - "message": human-readable

    Logic:
    - If iracing_optimal_delta is None or empty or all-NaN: status="skip"
    - If our theoretical is faster than iRacing optimal: status="pass" (good)
    - If our theoretical is > 1.0s slower: status="warn" (model may be too conservative)
    - Otherwise: status="pass"
    """
    result: dict[str, Any] = {
        "status": "skip",
        "our_lap_time_s": our_lap_time_s,
        "iracing_optimal_delta_median_s": None,
        "message": "",
    }

    # Guard: no reference data available
    if iracing_optimal_delta is None:
        result["message"] = "No iRacing optimal delta available; skipping validation."
        log.info(result["message"])
        return result

    arr = np.asarray(iracing_optimal_delta, dtype=float)

    if arr.size == 0:
        result["message"] = "iRacing optimal delta array is empty; skipping validation."
        log.info(result["message"])
        return result

    finite_vals = arr[np.isfinite(arr)]
    if finite_vals.size == 0:
        result["message"] = "iRacing optimal delta contains only NaN; skipping validation."
        log.info(result["message"])
        return result

    median_delta = float(np.median(finite_vals))
    result["iracing_optimal_delta_median_s"] = round(median_delta, 4)

    # Positive median_delta means our lap is slower than iRacing optimal
    if median_delta <= 0.0:
        result["status"] = "pass"
        result["message"] = (
            f"Theoretical lap ({our_lap_time_s:.3f}s) is faster than or equal to "
            f"iRacing optimal (median delta {median_delta:+.3f}s). Model looks good."
        )
    elif median_delta > _SLOW_THRESHOLD_S:
        result["status"] = "warn"
        result["message"] = (
            f"Theoretical lap ({our_lap_time_s:.3f}s) is {median_delta:.3f}s slower "
            f"than iRacing optimal. Model may be too conservative."
        )
    else:
        result["status"] = "pass"
        result["message"] = (
            f"Theoretical lap ({our_lap_time_s:.3f}s) is {median_delta:.3f}s slower "
            f"than iRacing optimal. Within acceptable tolerance."
        )

    log.info("Validation: %s — %s", result["status"], result["message"])
    return result
