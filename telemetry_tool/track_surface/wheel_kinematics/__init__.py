"""
wheel_kinematics — Vehicle velocity state and per-wheel slip estimation.

Structured as a state-estimation boundary, not pure algebra:

  geometry.py       — static car geometry from setup YAML
  kinematics.py     — rigid-body velocity transforms (CG → wheel centers)
  beta_estimator.py — filtered sideslip / lateral velocity state
  slip_angles.py    — axle-level and per-wheel slip angles
  slip_ratio.py     — wheel-speed-based kappa (None if unobserved)

All computations work in the road tangent frame when a RoadFramePose
is provided, falling back to the flat body frame otherwise.
"""
from track_surface.wheel_kinematics.dataclasses import (
    CarGeometry,
    RoadFramePose,
    WheelKinematics,
)

__all__ = ["CarGeometry", "RoadFramePose", "WheelKinematics"]
