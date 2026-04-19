"""
Axle-level and per-wheel slip angle computation.

Stage 1: axle-level from bicycle model (always available)
Stage 2: per-wheel from rigid-body kinematics (requires track widths)

All computation optionally uses the road tangent frame when a
RoadFramePose is provided. On a banked surface, the body-frame
lateral velocity projected onto the road lateral direction gives
a more physically meaningful slip angle than the raw body-frame value.
"""
from __future__ import annotations

import numpy as np

from track_surface.wheel_kinematics.dataclasses import (
    CarGeometry,
    RoadFramePose,
    WheelKinematics,
)

# Minimum longitudinal speed for slip angle computation.
# Below this, atan2 becomes numerically unstable.
_VX_MIN: float = 3.0

# Speed below which low-speed guard activates (all alpha → 0)
_VX_GUARD: float = 1.5


def compute_slip_angles(
    *,
    vx_body: float,
    vy_body: float,
    yaw_rate: float,       # rad/s
    steer_wheel_rad: float, # steering wheel angle, radians
    geom: CarGeometry,
    road_frame: RoadFramePose | None = None,
    wheel_speeds: tuple[float, float, float, float] | None = None,
) -> WheelKinematics:
    """Compute vehicle velocity state and slip angles for one sample.

    Parameters
    ----------
    vx_body : longitudinal velocity in body frame [m/s]
    vy_body : lateral velocity in body frame [m/s]
    yaw_rate : yaw angular velocity [rad/s]
    steer_wheel_rad : steering wheel angle [rad] (will be divided by steer_ratio)
    geom : static car geometry
    road_frame : optional nonplanar road frame (flat if None)
    wheel_speeds : optional (FL, FR, RL, RR) angular velocities [rad/s]

    Returns
    -------
    WheelKinematics with all observable fields filled, None for unobservable.
    """
    flags: dict[str, bool] = {}

    # ── Road frame projection ────────────────────────────────
    if road_frame is not None and not _is_flat(road_frame):
        # Project body-frame velocity onto road tangent frame
        # On a banked surface, the body's lateral velocity has a component
        # along the road normal. We want only the road-tangential components.
        v_body_3d = np.array([vx_body, vy_body, 0.0])

        # Approximate: rotate body velocity by bank angle
        # (full 3D projection would need the body-to-world rotation too,
        # but for v1 the bank correction is the dominant term)
        cb = np.cos(road_frame.bank_rad)
        sb = np.sin(road_frame.bank_rad)
        vx_road = vx_body  # longitudinal is ~unaffected by bank
        vy_road = vy_body * cb  # lateral reduced by bank projection
        flags["road_frame_used"] = True
    else:
        vx_road = vx_body
        vy_road = vy_body
        flags["road_frame_used"] = False

    # ── Low-speed guard ──────────────────────────────────────
    if abs(vx_road) < _VX_GUARD:
        flags["low_speed_guard"] = True
        flags["vx_sufficient"] = False
        return WheelKinematics(
            vx_cg=vx_road, vy_cg=vy_road, beta_cg=0.0,
            alpha_f_axle=0.0, alpha_r_axle=0.0,
            quality_beta=0.0, quality_alpha=0.0, quality_kappa=0.0,
            flags=flags,
        )

    flags["vx_sufficient"] = True
    flags["low_speed_guard"] = False

    # ── CG sideslip ──────────────────────────────────────────
    beta = np.arctan2(vy_road, vx_road)

    # Quality: higher speed + lower beta = better estimate
    quality_beta = min(1.0, abs(vx_road) / 30.0) * (1.0 - min(abs(beta) / 0.3, 1.0) * 0.3)
    flags["beta_filtered"] = False  # v1: raw computation, not filtered

    # ── Road-wheel steer angle ───────────────────────────────
    delta = steer_wheel_rad / geom.steer_ratio
    delta = np.clip(delta, -geom.max_steer_rad, geom.max_steer_rad)

    a = geom.cg_to_front_m
    b = geom.cg_to_rear_m
    r = yaw_rate

    # ── Stage 1: Axle-level slip angles (bicycle model) ──────
    vx_safe = max(abs(vx_road), _VX_MIN) * np.sign(vx_road) if vx_road != 0 else _VX_MIN

    alpha_f = np.arctan2(vy_road + a * r, vx_safe) - delta
    alpha_r = np.arctan2(vy_road - b * r, vx_safe)

    # Clamp to physical range (> ±20° means something is very wrong)
    alpha_f = np.clip(alpha_f, -0.35, 0.35)
    alpha_r = np.clip(alpha_r, -0.35, 0.35)

    quality_alpha = min(1.0, abs(vx_road) / 20.0)

    # ── Stage 2: Per-wheel slip angles ───────────────────────
    alpha_fl = alpha_fr = alpha_rl = alpha_rr = None
    per_wheel_available = (geom.track_front_m > 0 and geom.track_rear_m > 0)
    flags["per_wheel_alpha"] = per_wheel_available

    if per_wheel_available:
        half_tf = geom.track_front_m / 2.0
        half_tr = geom.track_rear_m / 2.0

        # Wheel-center velocities from rigid-body kinematics:
        # v_wheel = v_cg + omega × r_wheel
        # For yaw only (ignore roll/pitch rates in v1):
        # v_x_wheel_i = vx - r * y_offset
        # v_y_wheel_i = vy + r * x_offset

        # Front left: x_offset = +a, y_offset = +half_tf
        vx_fl = vx_road - r * half_tf
        vy_fl = vy_road + r * a
        alpha_fl = float(np.arctan2(vy_fl, max(abs(vx_fl), _VX_MIN)) - delta)

        # Front right: x_offset = +a, y_offset = -half_tf
        vx_fr = vx_road + r * half_tf
        vy_fr = vy_road + r * a
        alpha_fr = float(np.arctan2(vy_fr, max(abs(vx_fr), _VX_MIN)) - delta)

        # Rear left: x_offset = -b, y_offset = +half_tr
        vx_rl = vx_road - r * half_tr
        vy_rl = vy_road - r * b
        alpha_rl = float(np.arctan2(vy_rl, max(abs(vx_rl), _VX_MIN)))

        # Rear right: x_offset = -b, y_offset = -half_tr
        vx_rr = vx_road + r * half_tr
        vy_rr = vy_road - r * b
        alpha_rr = float(np.arctan2(vy_rr, max(abs(vx_rr), _VX_MIN)))

        # Clamp per-wheel to physical range
        alpha_fl = float(np.clip(alpha_fl, -0.35, 0.35))
        alpha_fr = float(np.clip(alpha_fr, -0.35, 0.35))
        alpha_rl = float(np.clip(alpha_rl, -0.35, 0.35))
        alpha_rr = float(np.clip(alpha_rr, -0.35, 0.35))

        flags["assumed_ackermann"] = not geom.has_ackermann_data

    # ── Stage 3: Slip ratio ──────────────────────────────────
    kappa_fl = kappa_fr = kappa_rl = kappa_rr = None
    quality_kappa = 0.0

    if wheel_speeds is not None:
        # wheel_speeds = (omega_fl, omega_fr, omega_rl, omega_rr) in rad/s
        # Need effective rolling radius — approximate from ride height + tire spec
        # For v1: use a default 0.33m (GT4 tire ~660mm diameter)
        R_eff = 0.33

        omega_fl, omega_fr, omega_rl, omega_rr = wheel_speeds
        vx_abs = max(abs(vx_road), _VX_MIN)

        def _kappa(omega: float, vx_wheel: float) -> float | None:
            v_wheel = omega * R_eff
            if abs(vx_wheel) < _VX_MIN:
                return None
            k = (v_wheel - vx_wheel) / max(abs(vx_wheel), _VX_MIN)
            return float(np.clip(k, -1.0, 1.0))

        kappa_fl = _kappa(omega_fl, vx_fl if per_wheel_available else vx_road)
        kappa_fr = _kappa(omega_fr, vx_fr if per_wheel_available else vx_road)
        kappa_rl = _kappa(omega_rl, vx_rl if per_wheel_available else vx_road)
        kappa_rr = _kappa(omega_rr, vx_rr if per_wheel_available else vx_road)
        quality_kappa = 0.8
        flags["kappa_observed"] = True
    else:
        flags["kappa_observed"] = False

    return WheelKinematics(
        vx_cg=vx_road,
        vy_cg=vy_road,
        beta_cg=float(beta),
        alpha_f_axle=float(alpha_f),
        alpha_r_axle=float(alpha_r),
        alpha_fl=alpha_fl,
        alpha_fr=alpha_fr,
        alpha_rl=alpha_rl,
        alpha_rr=alpha_rr,
        kappa_fl=kappa_fl,
        kappa_fr=kappa_fr,
        kappa_rl=kappa_rl,
        kappa_rr=kappa_rr,
        quality_beta=float(quality_beta),
        quality_alpha=float(quality_alpha),
        quality_kappa=float(quality_kappa),
        flags=flags,
    )


def compute_slip_angles_batch(
    *,
    vx_body: np.ndarray,
    vy_body: np.ndarray,
    yaw_rate: np.ndarray,
    steer_wheel_rad: np.ndarray,
    geom: CarGeometry,
    road_frames: list[RoadFramePose] | None = None,
) -> list[WheelKinematics]:
    """Batch computation over N samples. Returns list of WheelKinematics."""
    n = len(vx_body)
    results = []
    for i in range(n):
        rf = road_frames[i] if road_frames is not None else None
        results.append(compute_slip_angles(
            vx_body=float(vx_body[i]),
            vy_body=float(vy_body[i]),
            yaw_rate=float(yaw_rate[i]),
            steer_wheel_rad=float(steer_wheel_rad[i]),
            geom=geom,
            road_frame=rf,
        ))
    return results


def _is_flat(rf: RoadFramePose) -> bool:
    """Check if a road frame is effectively flat (bank+grade < 0.5°)."""
    return abs(rf.bank_rad) < 0.009 and abs(rf.grade_rad) < 0.009
