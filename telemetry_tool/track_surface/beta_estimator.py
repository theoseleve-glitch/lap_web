"""
Sideslip / lateral velocity estimator using a complementary filter.

Combines two independent beta estimates:

  1. Kinematic beta (from yaw rate + geometry):
       vy_kin = -b × yaw_rate  (rear-axle relation at steady state)
       beta_kin = atan2(vy_kin, vx)

     Noisy (amplifies yaw-rate noise) but UNBIASED — no drift.
     Best at high speed where the noise-to-signal ratio is low.

  2. Integrated beta (from lateral acceleration):
       d(vy)/dt = a_lat_tire - vx × yaw_rate
       vy_int += (a_lat_tire - vx × yaw_rate) × dt

     Smooth (low noise) but DRIFTS due to accelerometer bias and
     integration error. Best at high frequency (transient response).

The complementary filter blends them:
  beta = alpha(v) × beta_kin + (1 - alpha(v)) × beta_int

with alpha increasing with speed (kinematic more reliable at speed)
and a slow drift correction that pulls the integral toward the
kinematic estimate.

Road-frame aware: uses a_lat_tire (banking gravity removed) from
road_state_estimator.py, not raw a_lat.

Assumptions
-----------
1. vx ≈ Speed (longitudinal velocity dominates; cos(beta) ≈ 1)
2. The rear-axle kinematic relation holds approximately
3. a_lat_tire from road_state_estimator is the tire-generated lateral force
4. No wheel-speed-based corrections in v1

Failure modes
-------------
- Low speed (< 5 m/s): beta is unreliable → quality drops, fallback to 0
- High yaw rate + low speed: kinematic blows up → clamped + low quality
- Accelerometer bias: causes drift in integrated path → DC-corrected by kinematic
- Banking transitions: road_state errors propagate → detected via quality flags
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final

import numpy as np

logger = logging.getLogger(__name__)

_G: Final[float] = 9.80665


@dataclass
class BetaEstimatorConfig:
    """Configuration for the complementary filter."""
    # Blending: alpha = alpha_min + (alpha_max - alpha_min) × clip(vx / v_blend, 0, 1)
    alpha_min: float = 0.1    # at low speed: mostly integral
    alpha_max: float = 0.7    # at high speed: mostly kinematic
    v_blend: float = 40.0     # speed at which alpha reaches alpha_max [m/s]

    # Drift correction: how fast the integral is pulled toward kinematic
    drift_correction_rate: float = 0.5  # per second (time constant ~2s)

    # Clamps
    max_beta_rad: float = 0.25   # ±14 deg — anything more is a data error
    max_vy_mps: float = 5.0      # ±5 m/s lateral velocity

    # Low-speed guard
    min_speed_mps: float = 5.0

    # Quality scaling
    quality_speed_ref: float = 30.0  # speed at which quality = 1.0


@dataclass
class BetaEstimate:
    """Per-sample sideslip estimate with uncertainty."""
    vy: float                # lateral velocity [m/s]
    beta: float              # sideslip angle [rad]
    beta_std: float          # estimated uncertainty [rad]
    quality: float           # 0-1 confidence

    # Decomposition (for diagnostics)
    vy_kinematic: float      # from yaw rate geometry
    vy_integrated: float     # from accel integration
    alpha_blend: float       # blending weight used (0=integral, 1=kinematic)

    flags: dict


def estimate_beta_batch(
    *,
    speed: np.ndarray,            # (N,) longitudinal speed [m/s]
    yaw_rate: np.ndarray,         # (N,) [rad/s]
    a_lat_tire: np.ndarray,       # (N,) tire-only lateral accel [m/s²] (from road_state)
    cg_to_rear_m: float,          # b: CG → rear axle distance [m]
    dt: float = 1.0 / 60.0,      # sample period [s]
    config: BetaEstimatorConfig | None = None,
    road_quality: np.ndarray | None = None,  # (N,) from road_state_estimator
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Batch sideslip estimation via complementary filter.

    Parameters
    ----------
    speed : longitudinal speed (always positive) [m/s]
    yaw_rate : yaw angular velocity [rad/s]
    a_lat_tire : lateral acceleration with banking gravity REMOVED [m/s²]
    cg_to_rear_m : CG to rear axle distance (b) [m]
    dt : sample period
    config : filter configuration
    road_quality : optional per-sample road-state quality (0-1)

    Returns
    -------
    vy : (N,) estimated lateral velocity [m/s]
    beta : (N,) estimated sideslip angle [rad]
    beta_std : (N,) estimated uncertainty [rad]
    quality : (N,) estimation confidence [0-1]
    """
    if config is None:
        config = BetaEstimatorConfig()

    N = len(speed)
    b = cg_to_rear_m

    vy_out = np.zeros(N)
    beta_out = np.zeros(N)
    beta_std_out = np.full(N, config.max_beta_rad)
    quality_out = np.zeros(N)

    # ── State: integrated lateral velocity ────────────────────
    vy_int = 0.0

    for i in range(N):
        vx = speed[i]

        # ── Low-speed guard ──────────────────────────────────
        if vx < config.min_speed_mps:
            vy_out[i] = 0.0
            beta_out[i] = 0.0
            beta_std_out[i] = config.max_beta_rad
            quality_out[i] = 0.0
            vy_int = 0.0  # reset integral to prevent drift accumulation
            continue

        r = yaw_rate[i]
        a_lat_t = a_lat_tire[i]

        # ── Path 1: Kinematic (from yaw rate + rear axle geometry) ──
        # At the CG: vy_kin ≈ -b × r (the lateral velocity that produces
        # the observed yaw rate via the rear tire slip angle)
        # This is the linearized bicycle model relation.
        vy_kin = -b * r

        # ── Path 2: Integrated (from lateral accel) ─────────
        # d(vy)/dt = a_lat_tire - vx × yaw_rate
        # (Newton's second law in the body frame, lateral direction)
        vy_dot = a_lat_t - vx * r
        vy_int += vy_dot * dt

        # Drift correction: pull integral toward kinematic slowly
        drift_error = vy_int - vy_kin
        vy_int -= config.drift_correction_rate * drift_error * dt

        # ── Blend ────────────────────────────────────────────
        alpha = config.alpha_min + (config.alpha_max - config.alpha_min) * min(vx / config.v_blend, 1.0)
        vy_blended = alpha * vy_kin + (1.0 - alpha) * vy_int

        # ── Clamp ────────────────────────────────────────────
        vy_blended = float(np.clip(vy_blended, -config.max_vy_mps, config.max_vy_mps))

        # ── Beta from vy ─────────────────────────────────────
        beta = np.arctan2(vy_blended, vx)
        beta = float(np.clip(beta, -config.max_beta_rad, config.max_beta_rad))

        # ── Uncertainty ──────────────────────────────────────
        # Higher speed → lower uncertainty (kinematic more reliable)
        # Higher alpha → lower uncertainty (less reliance on drifting integral)
        speed_factor = min(vx / config.quality_speed_ref, 1.0)
        # Disagreement between paths → higher uncertainty
        path_disagreement = abs(vy_kin - vy_int) / max(vx, 1.0)
        disagreement_penalty = min(path_disagreement / 0.05, 1.0)

        beta_std = config.max_beta_rad * (1.0 - speed_factor * 0.7) * (1.0 + disagreement_penalty * 0.5)
        beta_std = max(beta_std, 0.002)  # minimum uncertainty

        # Quality
        quality = speed_factor * (1.0 - disagreement_penalty * 0.5)
        if road_quality is not None:
            quality *= max(road_quality[i], 0.3)  # road state uncertainty propagates
        quality = float(np.clip(quality, 0.0, 1.0))

        vy_out[i] = vy_blended
        beta_out[i] = beta
        beta_std_out[i] = float(beta_std)
        quality_out[i] = quality

    return vy_out, beta_out, beta_std_out, quality_out


def estimate_beta_offline_smooth(
    *,
    speed: np.ndarray,
    yaw_rate: np.ndarray,
    a_lat_tire: np.ndarray,
    cg_to_rear_m: float,
    dt: float = 1.0 / 60.0,
    config: BetaEstimatorConfig | None = None,
    road_quality: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Offline (non-causal) beta estimation: forward + backward + blend.

    Runs the complementary filter forward AND backward, then averages.
    This is a poor-man's RTS smoother — the backward pass fills in
    information about transients that the forward pass missed, and
    the average cancels some of the drift bias.

    For offline replay (not live coaching), this gives better estimates
    than the forward-only filter.
    """
    # Forward pass
    vy_fwd, beta_fwd, std_fwd, q_fwd = estimate_beta_batch(
        speed=speed, yaw_rate=yaw_rate, a_lat_tire=a_lat_tire,
        cg_to_rear_m=cg_to_rear_m, dt=dt, config=config,
        road_quality=road_quality,
    )

    # Backward pass (reverse the arrays, negate yaw rate for time reversal)
    vy_bwd, beta_bwd, std_bwd, q_bwd = estimate_beta_batch(
        speed=speed[::-1], yaw_rate=-yaw_rate[::-1],
        a_lat_tire=-a_lat_tire[::-1],
        cg_to_rear_m=cg_to_rear_m, dt=dt, config=config,
        road_quality=road_quality[::-1] if road_quality is not None else None,
    )

    # Reverse the backward results back to forward order
    vy_bwd = -vy_bwd[::-1]
    beta_bwd = -beta_bwd[::-1]
    std_bwd = std_bwd[::-1]
    q_bwd = q_bwd[::-1]

    # Blend: weight by inverse variance (quality-weighted average)
    w_fwd = q_fwd / np.maximum(std_fwd, 0.001)
    w_bwd = q_bwd / np.maximum(std_bwd, 0.001)
    w_total = w_fwd + w_bwd
    w_total = np.maximum(w_total, 1e-9)

    vy = (vy_fwd * w_fwd + vy_bwd * w_bwd) / w_total
    beta = (beta_fwd * w_fwd + beta_bwd * w_bwd) / w_total
    beta_std = np.minimum(std_fwd, std_bwd)  # smoothed estimate is at least as good as either
    quality = np.maximum(q_fwd, q_bwd)  # take the better quality

    return vy, beta, beta_std, quality
