"""Core data structures for wheel kinematics estimation."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class CarGeometry:
    """Static vehicle geometry — ideally parsed from iRacing setup YAML.

    All distances in metres, angles in radians.
    """
    wheelbase_m: float
    track_front_m: float
    track_rear_m: float
    cg_to_front_m: float       # a: CG → front axle
    cg_to_rear_m: float        # b: CG → rear axle (= wheelbase - a)
    steer_ratio: float = 14.0  # steering wheel angle → road wheel angle
    max_steer_rad: float = 0.5 # max road-wheel steer angle (from SteeringWheelAngleMax / ratio)

    # Per-wheel camber (static, from setup)
    camber_fl_rad: float = 0.0
    camber_fr_rad: float = 0.0
    camber_rl_rad: float = 0.0
    camber_rr_rad: float = 0.0

    # Ackermann geometry flag
    has_ackermann_data: bool = False  # True only if we know the actual L/R steer split

    @classmethod
    def from_setup_yaml(cls, setup: dict, wheelbase: float = 2.67) -> CarGeometry:
        """Parse geometry from iRacing CarSetup YAML dict."""
        chassis = setup.get("Chassis", {})
        lf = chassis.get("LeftFront", {})
        rf = chassis.get("RightFront", {})
        lr = chassis.get("LeftRear", {})
        rr = chassis.get("RightRear", {})
        dials = chassis.get("InCarDials", {})

        # Corner weights → weight distribution
        w_lf = _parse_value(lf.get("CornerWeight", "0"), "N")
        w_rf = _parse_value(rf.get("CornerWeight", "0"), "N")
        w_lr = _parse_value(lr.get("CornerWeight", "0"), "N")
        w_rr = _parse_value(rr.get("CornerWeight", "0"), "N")
        total = w_lf + w_rf + w_lr + w_rr

        if total > 100:
            nose_frac = (w_lf + w_rf) / total
        else:
            nose_str = dials.get("NoseWeight", "0.46")
            nose_frac = _parse_value(nose_str, "%") / 100.0 if "%" in str(nose_str) else float(nose_str)

        cg_to_front = wheelbase * (1.0 - nose_frac)
        cg_to_rear = wheelbase * nose_frac

        # Camber
        camber_fl = np.radians(_parse_value(lf.get("Camber", "0"), "deg"))
        camber_fr = np.radians(_parse_value(rf.get("Camber", "0"), "deg"))
        camber_rl = np.radians(_parse_value(lr.get("Camber", "0"), "deg"))
        camber_rr = np.radians(_parse_value(rr.get("Camber", "0"), "deg"))

        # Track widths (not in setup YAML — use defaults, could be enriched)
        return cls(
            wheelbase_m=wheelbase,
            track_front_m=1.666,  # McLaren 570S GT4 default
            track_rear_m=1.627,
            cg_to_front_m=cg_to_front,
            cg_to_rear_m=cg_to_rear,
            camber_fl_rad=camber_fl,
            camber_fr_rad=camber_fr,
            camber_rl_rad=camber_rl,
            camber_rr_rad=camber_rr,
        )


@dataclass
class RoadFramePose:
    """Local road tangent frame at a point on the track surface.

    The tangent frame is defined by three orthonormal vectors:
    - tangent: along the road direction (heading)
    - normal: perpendicular to the road surface (up from the asphalt)
    - lateral: tangent × normal (across the road)

    On a flat track this equals the world frame. On banked/graded
    surfaces it differs and matters for slip angle computation.
    """
    tangent: np.ndarray    # (3,) unit vector along road heading
    normal: np.ndarray     # (3,) unit vector perpendicular to road surface
    lateral: np.ndarray    # (3,) = cross(tangent, normal), across road

    bank_rad: float = 0.0   # road bank angle
    grade_rad: float = 0.0  # road grade (slope) angle

    @classmethod
    def flat(cls) -> RoadFramePose:
        """Default flat road frame (identity)."""
        return cls(
            tangent=np.array([1.0, 0.0, 0.0]),
            normal=np.array([0.0, 0.0, 1.0]),
            lateral=np.array([0.0, 1.0, 0.0]),
        )

    @classmethod
    def from_bank_grade(cls, bank_rad: float, grade_rad: float, heading_rad: float) -> RoadFramePose:
        """Build road frame from bank angle, grade, and heading."""
        ch, sh = np.cos(heading_rad), np.sin(heading_rad)
        cb, sb = np.cos(bank_rad), np.sin(bank_rad)
        cg, sg = np.cos(grade_rad), np.sin(grade_rad)

        # Tangent: heading direction, tilted by grade
        tangent = np.array([ch * cg, sh * cg, sg])
        # Normal: perpendicular to surface, tilted by bank
        normal = np.array([-ch * sg * cb + sh * sb,
                           -sh * sg * cb - ch * sb,
                           cg * cb])
        normal /= max(np.linalg.norm(normal), 1e-9)
        lateral = np.cross(tangent, normal)
        lateral /= max(np.linalg.norm(lateral), 1e-9)

        return cls(tangent=tangent, normal=normal, lateral=lateral,
                   bank_rad=bank_rad, grade_rad=grade_rad)


@dataclass
class WheelKinematics:
    """Per-sample vehicle velocity state and slip estimates.

    None values indicate the quantity is unobservable from available data.
    Quality scores (0→1) indicate estimation confidence.
    """
    # ── CG velocity state ────────────────────────────────────
    vx_cg: float              # longitudinal velocity in road tangent frame [m/s]
    vy_cg: float              # lateral velocity in road tangent frame [m/s]
    beta_cg: float            # sideslip angle at CG [rad]

    # ── Axle-level slip angles (always available) ────────────
    alpha_f_axle: float       # front axle average slip angle [rad]
    alpha_r_axle: float       # rear axle average slip angle [rad]

    # ── Per-wheel slip angles (None if geometry insufficient) ─
    alpha_fl: float | None = None
    alpha_fr: float | None = None
    alpha_rl: float | None = None
    alpha_rr: float | None = None

    # ── Per-wheel slip ratio (None if wheel speed unavailable) ─
    kappa_fl: float | None = None
    kappa_fr: float | None = None
    kappa_rl: float | None = None
    kappa_rr: float | None = None

    # ── Quality / confidence ─────────────────────────────────
    quality_beta: float = 0.0   # 0→1 confidence in sideslip estimate
    quality_alpha: float = 0.0  # 0→1 confidence in slip angle estimates
    quality_kappa: float = 0.0  # 0→1 confidence in slip ratio estimates

    # ── Observability flags ──────────────────────────────────
    flags: dict = field(default_factory=dict)
    # Expected flags:
    #   vx_sufficient: bool     — speed above minimum for estimation
    #   beta_filtered: bool     — sideslip from filtered estimator (vs raw)
    #   per_wheel_alpha: bool   — per-wheel slip angles available
    #   kappa_observed: bool    — wheel speeds available for slip ratio
    #   assumed_ackermann: bool — per-wheel steer split assumed, not measured
    #   road_frame_used: bool   — nonplanar road frame applied
    #   low_speed_guard: bool   — near-zero speed protection active
    #   abs_active: bool        — ABS chopping detected (kappa unreliable)
    #   curb_strike: bool       — shock spike detected (all estimates noisy)


def _parse_value(s: str, unit: str = "") -> float:
    """Parse a value string like '140 N/mm' or '43.5%' into a float."""
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip()
    # Remove unit suffix
    for suffix in [unit, "N/mm", "N", "mm", "kPa", "deg", "%", "L", "clicks"]:
        s = s.replace(suffix, "").strip()
    # Handle comma-separated values (take first)
    if "," in s:
        s = s.split(",")[0].strip()
    try:
        return float(s)
    except ValueError:
        return 0.0
