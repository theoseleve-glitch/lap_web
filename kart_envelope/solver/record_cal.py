"""
record_cal.py
-------------
Track-record calibration: find bounded multipliers (α_lat, α_drive,
α_brake) that align the simulated best-case lap time with a provided
track record.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from kart_envelope.config import KartEnvelopeConfig, default_config
from kart_envelope.envelope.capability import CapabilityEnvelope
from kart_envelope.solver.min_time import TheoreticalResult, compute_theoretical_lap
from kart_envelope.track.geometry import TrackGeometry

logger = logging.getLogger(__name__)


class CalibrationError(ValueError):
    """Raised when calibration fails."""


@dataclass
class RecordCalibration:
    """Result of record-based calibration."""

    alpha_lat: float = 1.0
    alpha_drive: float = 1.0
    alpha_brake: float = 1.0
    record_time_s: float = 0.0
    data_theoretical_time_s: float = 0.0
    calibrated_time_s: float = 0.0
    residual_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "alpha_lat": round(self.alpha_lat, 4),
            "alpha_drive": round(self.alpha_drive, 4),
            "alpha_brake": round(self.alpha_brake, 4),
            "record_time_s": round(self.record_time_s, 4),
            "data_theoretical_time_s": round(self.data_theoretical_time_s, 4),
            "calibrated_time_s": round(self.calibrated_time_s, 4),
            "residual_s": round(self.residual_s, 4),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RecordCalibration:
        return cls(**{k: v for k, v in d.items()
                       if k in cls.__dataclass_fields__})

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2)

    @classmethod
    def load(cls, path: Path) -> RecordCalibration:
        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))


def calibrate_to_record(
    geometry: TrackGeometry,
    envelope: CapabilityEnvelope,
    record_time_s: float,
    config: KartEnvelopeConfig | None = None,
    data_theoretical_time_s: float | None = None,
) -> RecordCalibration:
    """Find bounded α multipliers to match a track record.

    Uses Nelder-Mead simplex to minimise:

        f(α) = |T_sim(env.scaled(α_lat, α_drive, α_brake)) - record_time|²
             + λ · |α - 1|²

    Parameters
    ----------
    geometry : TrackGeometry
    envelope : CapabilityEnvelope
    record_time_s : float
        Target track-record time.
    config : KartEnvelopeConfig | None
    data_theoretical_time_s : float | None
        Pre-computed data-only theoretical time for reference.

    Returns
    -------
    RecordCalibration
    """
    if config is None:
        config = default_config()

    if record_time_s <= 0:
        raise CalibrationError(f"Invalid record time: {record_time_s}")

    lo = config.cal_alpha_lo
    hi = config.cal_alpha_hi
    lam = config.cal_regularisation

    # Use a coarser config for calibration solves (fewer wrap iterations)
    from dataclasses import replace
    cal_config = replace(config, solver_wrap_iterations=3, solver_wrap_tol_mps=0.1)

    def _objective(alpha: np.ndarray) -> float:
        a_lat, a_drive, a_brake = np.clip(alpha, lo, hi)
        env_cal = envelope.scaled(mu=a_lat, p_drive=a_drive, b_brake=a_brake)
        try:
            result = compute_theoretical_lap(geometry, env_cal, config=cal_config)
            t = result.lap_time_s
        except Exception:
            return 1e6
        data_fit = (t - record_time_s) ** 2
        reg = lam * ((a_lat - 1.0) ** 2 + (a_drive - 1.0) ** 2 + (a_brake - 1.0) ** 2)
        return data_fit + reg

    # Nelder-Mead via scipy
    try:
        from scipy.optimize import minimize as sp_minimize
        x0 = np.array([1.0, 1.0, 1.0])
        res = sp_minimize(_objective, x0, method="Nelder-Mead",
                           options={"maxiter": 40, "xatol": 0.01, "fatol": 0.1})
        best = np.clip(res.x, lo, hi)
    except ImportError:
        logger.warning("scipy not available; using grid search for calibration.")
        best = _grid_search(_objective, lo, hi)

    # Compute calibrated lap time at the solution
    env_cal = envelope.scaled(mu=best[0], p_drive=best[1], b_brake=best[2])
    try:
        cal_result = compute_theoretical_lap(geometry, env_cal, config=config)
        cal_time = cal_result.lap_time_s
    except Exception:
        cal_time = 0.0

    cal = RecordCalibration(
        alpha_lat=float(best[0]),
        alpha_drive=float(best[1]),
        alpha_brake=float(best[2]),
        record_time_s=record_time_s,
        data_theoretical_time_s=data_theoretical_time_s or 0.0,
        calibrated_time_s=cal_time,
        residual_s=abs(cal_time - record_time_s),
    )

    logger.info(
        "Record calibration: α_lat=%.3f, α_drive=%.3f, α_brake=%.3f, "
        "T_cal=%.3f s (record=%.3f s, residual=%.3f s).",
        cal.alpha_lat, cal.alpha_drive, cal.alpha_brake,
        cal.calibrated_time_s, record_time_s, cal.residual_s,
    )
    return cal


def _grid_search(
    objective, lo: float, hi: float, n_steps: int = 5,
) -> np.ndarray:
    """Fallback grid search over 3-D alpha space."""
    grid = np.linspace(lo, hi, n_steps)
    best_cost = float("inf")
    best_alpha = np.array([1.0, 1.0, 1.0])
    for a_lat in grid:
        for a_drive in grid:
            for a_brake in grid:
                alpha = np.array([a_lat, a_drive, a_brake])
                cost = objective(alpha)
                if cost < best_cost:
                    best_cost = cost
                    best_alpha = alpha.copy()
    return best_alpha
