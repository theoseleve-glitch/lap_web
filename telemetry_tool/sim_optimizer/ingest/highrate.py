"""Unpack iRacing 360 Hz high-rate sub-sample arrays into flat channels.

iRacing exposes high-rate data as 6-element arrays per 60 Hz tick,
yielding an effective 360 Hz sample rate.  Column pattern:
``irsdk__{VarName}_ST__{0..5}``.

This module interleaves those sub-samples into contiguous 360 Hz arrays
suitable for suspension / vibration analysis.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, fields
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import pandas as pd
    from telemetry_tool.sim_optimizer.config import SimOptimizerConfig

logger = logging.getLogger(__name__)

_N_SUB = 6  # sub-samples per 60 Hz tick

# ── Channel mapping: (dataclass field suffix) -> irsdk var name ──────────

_DYNAMICS_MAP: dict[str, str] = {
    "lat_accel_hr": "irsdk__LatAccel",
    "long_accel_hr": "irsdk__LongAccel",
    "vert_accel_hr": "irsdk__VertAccel",
    "velocity_x_hr": "irsdk__VelocityX",
    "velocity_y_hr": "irsdk__VelocityY",
    "velocity_z_hr": "irsdk__VelocityZ",
    "yaw_rate_hr": "irsdk__YawRate",
    "roll_rate_hr": "irsdk__RollRate",
    "pitch_rate_hr": "irsdk__PitchRate",
}

_STEERING_MAP: dict[str, str] = {
    "steering_torque_hr": "irsdk__SteeringWheelTorque",
}

_WHEELS = ("LF", "RF", "LR", "RR")

_SHOCK_MAP: dict[str, str] = {}
for _wh in _WHEELS:
    _wl = _wh.lower()
    _SHOCK_MAP[f"shock_defl_{_wl}_hr"] = f"irsdk__{_wh}shockDefl"
    _SHOCK_MAP[f"shock_vel_{_wl}_hr"] = f"irsdk__{_wh}shockVel"


# ── Dataclass ────────────────────────────────────────────────────────────

@dataclass
class HighRateChannels:
    """360 Hz interleaved channels unpacked from iRacing _ST arrays.

    All array fields are ``None`` when the corresponding _ST columns are
    absent.  ``n_samples_hr`` is ``n_rows * 6`` when data is present,
    otherwise ``0``.
    """

    n_samples_hr: int = 0

    # Time axis
    time_hr: np.ndarray | None = None

    # Dynamics at 360 Hz
    lat_accel_hr: np.ndarray | None = None
    long_accel_hr: np.ndarray | None = None
    vert_accel_hr: np.ndarray | None = None
    velocity_x_hr: np.ndarray | None = None
    velocity_y_hr: np.ndarray | None = None
    velocity_z_hr: np.ndarray | None = None
    yaw_rate_hr: np.ndarray | None = None
    roll_rate_hr: np.ndarray | None = None
    pitch_rate_hr: np.ndarray | None = None

    # Steering
    steering_torque_hr: np.ndarray | None = None

    # Per-wheel shock deflection
    shock_defl_lf_hr: np.ndarray | None = None
    shock_defl_rf_hr: np.ndarray | None = None
    shock_defl_lr_hr: np.ndarray | None = None
    shock_defl_rr_hr: np.ndarray | None = None

    # Per-wheel shock velocity
    shock_vel_lf_hr: np.ndarray | None = None
    shock_vel_rf_hr: np.ndarray | None = None
    shock_vel_lr_hr: np.ndarray | None = None
    shock_vel_rr_hr: np.ndarray | None = None

    def available_channels(self) -> list[str]:
        """Return names of fields that are not ``None``."""
        return [
            f.name
            for f in fields(self)
            if f.name not in ("n_samples_hr",) and getattr(self, f.name) is not None
        ]


# ── Helpers ──────────────────────────────────────────────────────────────

def _interleave_st(
    df: "pd.DataFrame",
    prefix: str,
    n_sub: int = _N_SUB,
) -> np.ndarray | None:
    """Interleave ``{prefix}_ST__{0..n_sub-1}`` into a flat 360 Hz array.

    Returns ``None`` if any of the expected sub-columns is missing.
    The output order is:
        row0_sub0, row0_sub1, ..., row0_sub(n_sub-1), row1_sub0, ...
    giving length ``n_rows * n_sub``.
    """
    cols = [f"{prefix}_ST__{i}" for i in range(n_sub)]
    for c in cols:
        if c not in df.columns:
            return None

    # Stack columns → (n_rows, n_sub), then ravel in C order
    sub_arrays = [df[c].to_numpy(dtype=np.float64, na_value=np.nan) for c in cols]
    stacked = np.column_stack(sub_arrays)  # shape (n_rows, n_sub)
    return stacked.ravel()


def _build_time_hr(
    df: "pd.DataFrame",
    n_sub: int = _N_SUB,
) -> np.ndarray | None:
    """Build a 360 Hz time axis from ``irsdk__SessionTime``.

    For each 60 Hz tick, creates *n_sub* evenly spaced sub-times within
    the tick interval (dt_sub = 1/360).
    """
    col = "irsdk__SessionTime"
    if col not in df.columns:
        return None

    time_60 = df[col].to_numpy(dtype=np.float64, na_value=np.nan)
    n_rows = len(time_60)
    dt_sub = 1.0 / 360.0

    # For each tick, generate n_sub evenly spaced sub-times
    offsets = np.arange(n_sub) * dt_sub  # (n_sub,)
    # Broadcast: (n_rows, 1) + (1, n_sub) → (n_rows, n_sub)
    time_hr = time_60[:, np.newaxis] + offsets[np.newaxis, :]
    return time_hr.ravel()


# ── Main entry point ─────────────────────────────────────────────────────

def unpack_highrate(
    df: "pd.DataFrame",
    *,
    config: "SimOptimizerConfig",
) -> HighRateChannels:
    """Unpack iRacing _ST sub-sample columns into 360 Hz arrays.

    If no ``_ST`` columns are found at all, returns a
    ``HighRateChannels`` with ``n_samples_hr=0`` and all fields ``None``.
    """
    all_maps = {**_DYNAMICS_MAP, **_STEERING_MAP, **_SHOCK_MAP}

    # Quick check: are there ANY _ST columns?
    has_any_st = any(
        f"{prefix}_ST__0" in df.columns for prefix in all_maps.values()
    )
    if not has_any_st:
        logger.info("No _ST columns found — returning empty HighRateChannels")
        return HighRateChannels(n_samples_hr=0)

    n_rows = len(df)
    n_hr = n_rows * _N_SUB

    result = HighRateChannels(n_samples_hr=n_hr)

    # Time axis
    result.time_hr = _build_time_hr(df)

    # Unpack all channel groups
    count = 0
    for field_name, prefix in all_maps.items():
        arr = _interleave_st(df, prefix)
        setattr(result, field_name, arr)
        if arr is not None:
            count += 1

    logger.info(
        "Unpacked %d / %d high-rate channels from %d rows → %d samples at 360 Hz",
        count,
        len(all_maps),
        n_rows,
        n_hr,
    )
    return result
