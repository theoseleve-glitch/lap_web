"""
track_surface/dense_grip.py
---------------------------
Build a DENSE grip field (s,n) for the optimizer — every cell finite, full
track width — from a sparse measured GripSurface.

The car only drives the racing line, so grip is MEASURED only on/near it. To
let the optimizer use the full width (out-in-out), undriven tarmac is filled:
  driven cell  : the measured limit (absolute mu)
  undriven cell: the row's measured LEVEL laterally extended, * condition_factor
both modulated by an optional meteo spatial(s,n) factor (drainage/sun/wind),
and blended by per-cell confidence so the driven->undriven edge is continuous.
'condition_factor' is 1.0 for the measured condition; Part C will set it from
the classifier mu_scale ratio when projecting a different condition.
"""
from __future__ import annotations

from typing import Final

import numpy as np

from track_surface.grip_2d import GripSurface, _MIN_LIMIT_SAMPLES

_MU_FLOOR: Final[float] = 0.1
_MU_CEIL: Final[float] = 2.5
_GLOBAL_FALLBACK_MU: Final[float] = 1.0   # nothing measured anywhere


def build_dense_grip_grid(
    grip_2d: GripSurface,
    *,
    spatial: np.ndarray | None = None,
    condition_factor: float = 1.0,
) -> np.ndarray:
    """Dense absolute-mu grid (M,K), no NaN. See module docstring."""
    measured = grip_2d.mu_limit_grid
    if measured is None:
        measured = grip_2d.mu_grid          # old sidecar: mean is the measured source
    measured = np.asarray(measured, dtype=float)
    count = np.asarray(grip_2d.count_grid)
    M, K = measured.shape

    has_meas = (count > 0) & np.isfinite(measured)

    # Per-row surface-grip LEVEL = a robust high percentile of the row's measured
    # cells (the demonstrated surface limit at that arclength). NOTE: where the
    # driven line is SUB-limit (e.g. trail-braking, using grip longitudinally), an
    # on-line cell can read lower than this level — that cell is UNDER-driven, not
    # less grippy, so filling undriven width at the row limit is physically honest,
    # not a fabricated grip. Falls back to the global level for rows with no data.
    global_level = float(np.nanpercentile(measured[has_meas], 90)) if has_meas.any() else _GLOBAL_FALLBACK_MU
    row_level = np.full(M, global_level)
    for i in range(M):
        if has_meas[i].any():
            row_level[i] = float(np.nanpercentile(measured[i, has_meas[i]], 90))

    undriven_level = (row_level * condition_factor)[:, None]        # (M,1) broadcast
    # Surface-LIMIT model (not driving-style model): the optimizer needs the grip
    # the surface CAN deliver, not what the driver happened to use. A measured cell
    # overrides the row level only when it demonstrates MORE grip (a real rubbered-in
    # / high-grip patch); a LOWER reading means the car was under the limit there
    # (straight, lift, trail-brake) — under-driven, not less grippy — so it keeps the
    # row level. Without this, sub-limit on-line cells become phantom low-grip
    # "potholes" and the line weaves to dodge them instead of running a clean racing
    # line. Genuine low-grip patches (wet/gravel) are the wet builder's job, not the
    # dry surface-limit field's.
    meas_filled = np.where(has_meas, np.maximum(measured, undriven_level), undriven_level)
    w = np.clip(count / float(_MIN_LIMIT_SAMPLES), 0.0, 1.0)
    # base: measured where driven, undriven_level where not, confidence-blended.
    # NOTE: condition_factor reaches partially-driven cells (0<count<floor) through
    # this blend by design — low-confidence on-line cells trust the projected
    # condition more. Moot at condition_factor=1.0 (Part A).
    base = w * meas_filled + (1.0 - w) * undriven_level

    if spatial is None:
        factor = 1.0
    else:
        factor = np.asarray(spatial, dtype=float)
        if factor.shape != base.shape:
            raise ValueError(
                f"spatial shape {factor.shape} != grip grid {base.shape}; "
                "resample it to the grip lattice first (spatial_to_grid.resample_spatial_to_grid)"
            )
    out = base * factor
    out = np.clip(out, _MU_FLOOR, _MU_CEIL)
    if not np.all(np.isfinite(out)):
        raise ValueError("build_dense_grip_grid produced non-finite cells")
    return out
