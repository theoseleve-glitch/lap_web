"""
Road state estimator — separates road bank/grade from chassis roll/pitch.

On a banked surface, the car's measured LatAccel includes a gravity
component (g × sin(bank)) that has nothing to do with tire friction.
If the inverse solver receives this contaminated a_lat, it attributes
the gravity force to the road surface (inflating lambda_surface).

This module estimates the road's bank and grade at each sample, then
outputs a corrected acceleration that represents ONLY the tire-generated
centripetal force — not the gravitational assist from banking.

The separation uses three complementary signals:
  1. Steady-state: at constant speed + constant yaw, the banking angle
     can be computed from the kinematic centripetal demand vs measured
     lateral acceleration.
  2. Roll angle: the car's roll includes both chassis roll (from
     suspension compliance under lateral load) and road bank. By
     estimating the chassis roll component from the lateral acceleration
     and suspension stiffness, the residual is the road bank.
  3. Pitch for grade: similar decomposition of pitch into chassis pitch
     (from longitudinal load transfer) and road grade.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final

import numpy as np
from scipy.ndimage import uniform_filter1d

logger = logging.getLogger(__name__)

_G: Final[float] = 9.80665


@dataclass
class RoadState:
    """Estimated road geometry at one sample."""
    bank_rad: float           # road banking angle [rad] (+ = right side high)
    grade_rad: float          # road grade [rad] (+ = uphill)

    # Corrected accelerations: tire-only, banking/grade gravity removed
    a_lat_tire: float         # lateral accel from tire forces only [m/s²]
    a_long_tire: float        # longitudinal accel from tire forces only [m/s²]

    # Gravity components projected onto the road surface
    a_lat_gravity: float      # gravity lateral component from banking [m/s²]
    a_long_gravity: float     # gravity longitudinal component from grade [m/s²]

    quality: float = 0.0     # 0-1 estimation confidence
    method: str = ""          # which estimation method dominated


@dataclass
class RoadEstimatorConfig:
    """Configuration for the road state estimator."""
    # Suspension roll compliance: how much the chassis rolls per unit a_lat
    # For a GT4: ~0.5-1.0 deg per G of lateral accel
    roll_compliance_rad_per_mps2: float = 0.005  # ~0.3 deg/G

    # Pitch compliance: how much the chassis pitches per unit a_long
    pitch_compliance_rad_per_mps2: float = 0.003  # ~0.17 deg/G

    # Smoothing window for the estimated road state (samples)
    smooth_window: int = 30

    # Minimum speed for kinematic bank estimation
    min_speed_mps: float = 10.0

    # Weight between kinematic and roll-residual methods
    # 1.0 = pure kinematic, 0.0 = pure roll-residual
    kinematic_weight: float = 0.6


def estimate_road_state_single(
    *,
    speed: float,
    a_lat_measured: float,
    a_long_measured: float,
    yaw_rate: float,
    roll_measured: float,
    pitch_measured: float,
    config: RoadEstimatorConfig,
) -> RoadState:
    """Estimate road bank and grade for one sample.

    Uses two methods and blends them:

    Method A — Kinematic bank estimation:
        On a banked surface at steady cornering, the measured lateral
        acceleration (in the world-horizontal frame) includes both the
        centripetal demand and the gravity projection:
            a_lat_measured = v × r + g × sin(bank)
        So: bank = arcsin((a_lat_measured - v × r) / g)

        This is reliable at steady state but noisy during transients.

    Method B — Roll residual:
        The car's measured roll angle = chassis_roll + road_bank
        chassis_roll ≈ compliance × a_lat_tire
        road_bank = roll_measured - chassis_roll

        This requires knowing the suspension compliance, which we
        approximate from the car's known roll stiffness.

    For grade: analogous decomposition of pitch.
    """
    quality = 0.5

    # ── Method A: Kinematic bank ─────────────────────────────
    kinematic_bank = 0.0
    if abs(speed) > config.min_speed_mps:
        # Centripetal demand from yaw rate and speed
        a_centripetal = speed * yaw_rate  # v × r

        # The difference between measured a_lat and kinematic demand
        # is the gravity component from banking
        a_lat_excess = a_lat_measured - a_centripetal

        # bank = arcsin(excess / g), clamped to ±45°
        sin_bank = np.clip(a_lat_excess / _G, -0.707, 0.707)
        kinematic_bank = float(np.arcsin(sin_bank))
        quality = min(1.0, abs(speed) / 30.0)  # higher speed = more reliable
    else:
        quality = 0.2

    # ── Method B: Roll residual ──────────────────────────────
    # Estimate chassis roll from lateral acceleration + compliance
    # At this point we don't know a_lat_tire yet (circular), so use
    # the kinematic centripetal demand as the proxy for tire lateral force
    a_centripetal_proxy = speed * yaw_rate if abs(speed) > 5.0 else 0.0
    chassis_roll = config.roll_compliance_rad_per_mps2 * a_centripetal_proxy
    roll_residual_bank = roll_measured - chassis_roll

    # ── Blend ────────────────────────────────────────────────
    w_kin = config.kinematic_weight if abs(speed) > config.min_speed_mps else 0.0
    w_roll = 1.0 - w_kin
    bank_rad = float(w_kin * kinematic_bank + w_roll * roll_residual_bank)

    # ── Grade from pitch ─────────────────────────────────────
    chassis_pitch = config.pitch_compliance_rad_per_mps2 * a_long_measured
    grade_rad = float(pitch_measured - chassis_pitch)
    # Clamp to ±15° grade (anything more is probably a data artifact)
    grade_rad = float(np.clip(grade_rad, -0.26, 0.26))

    # ── Corrected accelerations ──────────────────────────────
    # Remove the gravitational components
    a_lat_gravity = _G * np.sin(bank_rad)
    a_long_gravity = -_G * np.sin(grade_rad)  # uphill grade reduces forward accel

    a_lat_tire = a_lat_measured - a_lat_gravity
    a_long_tire = a_long_measured - a_long_gravity

    method = "kinematic" if w_kin > 0.5 else "roll_residual"

    return RoadState(
        bank_rad=bank_rad,
        grade_rad=grade_rad,
        a_lat_tire=float(a_lat_tire),
        a_long_tire=float(a_long_tire),
        a_lat_gravity=float(a_lat_gravity),
        a_long_gravity=float(a_long_gravity),
        quality=float(quality),
        method=method,
    )


def estimate_road_state_batch(
    *,
    speed: np.ndarray,
    a_lat: np.ndarray,
    a_long: np.ndarray,
    yaw_rate: np.ndarray,
    roll: np.ndarray,
    pitch: np.ndarray,
    config: RoadEstimatorConfig | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Batch road state estimation with temporal smoothing.

    Returns
    -------
    bank_rad : (N,) road banking angle [rad]
    grade_rad : (N,) road grade [rad]
    a_lat_tire : (N,) tire-only lateral acceleration [m/s²]
    a_long_tire : (N,) tire-only longitudinal acceleration [m/s²]
    quality : (N,) estimation confidence [0-1]
    """
    if config is None:
        config = RoadEstimatorConfig()

    N = len(speed)
    bank = np.zeros(N)
    grade = np.zeros(N)
    a_lat_tire = np.zeros(N)
    a_long_tire = np.zeros(N)
    quality = np.zeros(N)

    for i in range(N):
        rs = estimate_road_state_single(
            speed=float(speed[i]),
            a_lat_measured=float(a_lat[i]),
            a_long_measured=float(a_long[i]),
            yaw_rate=float(yaw_rate[i]),
            roll_measured=float(roll[i]),
            pitch_measured=float(pitch[i]),
            config=config,
        )
        bank[i] = rs.bank_rad
        grade[i] = rs.grade_rad
        a_lat_tire[i] = rs.a_lat_tire
        a_long_tire[i] = rs.a_long_tire
        quality[i] = rs.quality

    # ── Distance-aware smoothing ────────────────────────────────
    # Road geometry changes with POSITION, not time. At 60 m/s the car
    # covers 60m/s × (1/60 Hz) = 1m per sample. At 20 m/s it's 0.33m.
    # Smoothing in time blurs rapid banking transitions at high speed.
    #
    # Instead: compute cumulative distance, then smooth in distance space.
    # Additionally: detect rapid bank transitions and down-weight them.

    w = config.smooth_window
    if w > 1 and N > w:
        # Distance-weighted smoothing: use speed to convert time-window to
        # a roughly constant distance-window
        # For simplicity in v1: use an adaptive window that shrinks when
        # the bank estimate is changing fast.
        bank_gradient = np.abs(np.gradient(bank))

        # Steady regions: full smoothing. Transition regions: minimal smoothing.
        # Transition threshold: bank changing > 0.01 rad/sample ≈ 0.6 deg/sample
        transition_mask = bank_gradient > 0.005
        transition_zones = uniform_filter1d(transition_mask.astype(float), w) > 0.1

        # Smooth the steady parts with full window
        bank_smooth = uniform_filter1d(bank, w)
        grade_smooth = uniform_filter1d(grade, w)

        # In transition zones: use a much shorter window (5 samples)
        bank_tight = uniform_filter1d(bank, min(5, w))
        grade_tight = uniform_filter1d(grade, min(5, w))

        # Blend: transition zones use tight smoothing, steady zones use wide
        blend = transition_zones.astype(float)
        bank = bank_smooth * (1.0 - blend) + bank_tight * blend
        grade = grade_smooth * (1.0 - blend) + grade_tight * blend

        # Recompute corrected accelerations from smoothed geometry
        a_lat_gravity = _G * np.sin(bank)
        a_long_gravity = -_G * np.sin(grade)
        a_lat_tire = a_lat - a_lat_gravity
        a_long_tire = a_long - a_long_gravity

        # Down-weight quality in transition zones
        quality[transition_zones] *= 0.3

    return bank, grade, a_lat_tire, a_long_tire, quality
