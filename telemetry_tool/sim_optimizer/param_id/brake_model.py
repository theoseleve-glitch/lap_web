"""Brake performance identification from telemetry."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

_G = 9.80665


@dataclass
class BrakeModel:
    """Identified braking parameters."""

    max_decel_mps2: float       # peak decel on cold brakes
    brake_bias_front: float     # 0-1 fraction on front
    fade_onset_temp_c: float    # temp above which fade starts
    fade_rate: float            # decel loss per degree C above onset

    def max_braking_decel(
        self, speed_mps: float, brake_temp_c: float = 200.0
    ) -> float:
        """Return max deceleration accounting for brake fade.

        ``max_decel - fade_rate * max(temp - onset, 0)``, clamped >= 1.0.
        """
        fade = self.fade_rate * max(brake_temp_c - self.fade_onset_temp_c, 0.0)
        return max(self.max_decel_mps2 - fade, 1.0)

    def inverse_brake_pct(
        self,
        decel_mps2: float,
        speed_mps: float,
        brake_temp_c: float = 200.0,
    ) -> float:
        """Estimate brake pedal percentage for a given deceleration.

        ``|decel| / max_braking_decel``, clipped to [0, 1].
        """
        cap = self.max_braking_decel(speed_mps, brake_temp_c)
        return float(np.clip(abs(decel_mps2) / cap, 0.0, 1.0))

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_decel_mps2": self.max_decel_mps2,
            "brake_bias_front": self.brake_bias_front,
            "fade_onset_temp_c": self.fade_onset_temp_c,
            "fade_rate": self.fade_rate,
        }


# ======================================================================
# Identification
# ======================================================================

def identify_brake_model(
    *,
    speed_mps: np.ndarray,
    long_accel: np.ndarray,
    brake: np.ndarray,
    brake_raw: np.ndarray,
    abs_active: np.ndarray,
    brake_bias: np.ndarray,
    brake_temps: np.ndarray | None = None,
    config,
) -> BrakeModel:
    """Identify braking parameters from telemetry arrays.

    Braking mask: ``brake > 0.1`` AND ``long_accel < -brake_min_decel_mps2``.

    If fewer than *config.brake_min_samples* braking points exist, returns
    default values.  Otherwise the 98th-percentile of ``|long_accel|`` in
    the braking zone is used as peak deceleration.  ABS data (if >10
    active points) contributes a 95th-percentile peak that may raise the
    estimate.

    Clamping ranges:
        - max_decel: [5.0, 20.0]
        - brake_bias_front: [0.40, 0.75]
        - fade_rate: [0.0, 0.01]
    """
    # Median brake bias (iRacing reports as percentage 0-100)
    median_bias = float(np.median(brake_bias)) / 100.0

    # Default model returned when data is insufficient
    default = BrakeModel(
        max_decel_mps2=10.0,
        brake_bias_front=float(np.clip(median_bias, 0.40, 0.75)),
        fade_onset_temp_c=config.brake_fade_temp_threshold_c,
        fade_rate=0.001,
    )

    # Braking mask
    mask = (brake > 0.1) & (long_accel < -config.brake_min_decel_mps2)

    if mask.sum() < config.brake_min_samples:
        return default

    decel_abs = np.abs(long_accel[mask])

    # 98th percentile of |long_accel| during braking
    max_decel = float(np.percentile(decel_abs, 98))

    # ABS contribution: if enough active points, use 95th percentile
    abs_mask = abs_active.astype(bool)
    if abs_mask.sum() > 10:
        abs_decel = np.abs(long_accel[abs_mask])
        abs_peak = float(np.percentile(abs_decel, 95))
        max_decel = max(max_decel, abs_peak)

    # Fade rate estimation from brake temps (simple approach)
    fade_rate = 0.001  # default
    if brake_temps is not None and len(brake_temps) == len(long_accel):
        hot_mask = mask & (brake_temps > config.brake_fade_temp_threshold_c)
        cold_mask = mask & (brake_temps <= config.brake_fade_temp_threshold_c)
        if hot_mask.sum() > 20 and cold_mask.sum() > 20:
            hot_decel = float(np.median(np.abs(long_accel[hot_mask])))
            cold_decel = float(np.median(np.abs(long_accel[cold_mask])))
            temp_diff = float(
                np.median(brake_temps[hot_mask])
                - config.brake_fade_temp_threshold_c
            )
            if temp_diff > 0 and cold_decel > hot_decel:
                fade_rate = (cold_decel - hot_decel) / temp_diff

    # Clamp all outputs
    max_decel = float(np.clip(max_decel, 5.0, 20.0))
    bias = float(np.clip(median_bias, 0.40, 0.75))
    fade_rate = float(np.clip(fade_rate, 0.0, 0.01))

    return BrakeModel(
        max_decel_mps2=max_decel,
        brake_bias_front=bias,
        fade_onset_temp_c=config.brake_fade_temp_threshold_c,
        fade_rate=fade_rate,
    )
