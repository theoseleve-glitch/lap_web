"""Combined-slip zone splitting for trail braking reconstruction."""
from __future__ import annotations

import numpy as np


def available_longitudinal(
    ay_required: float,
    ay_max: float,
    ax_max: float,
    p: float,
) -> float:
    """Maximum |ax| available given lateral acceleration usage.

    From p-norm: (|ax|/ax_max)^p + (|ay|/ay_max)^p = 1
    Solve: |ax| = ax_max * (1 - (|ay|/ay_max)^p)^(1/p)

    Returns 0 if ay_required >= ay_max.
    Returns ax_max if ay_required == 0.
    """
    if ay_max <= 0.0 or ax_max <= 0.0:
        return 0.0
    ratio = abs(ay_required) / ay_max
    if ratio >= 1.0:
        return 0.0
    if ratio <= 0.0:
        return ax_max
    return ax_max * (1.0 - ratio ** p) ** (1.0 / p)


def split_braking_cornering(
    a_long_required: float,
    curvature: float,
    speed_mps: float,
    ay_max: float,
    ax_brake_max: float,
    p: float,
) -> tuple[float, float]:
    """Split required deceleration and cornering under combined limit.

    Returns (a_long_actual, a_lat_actual) that satisfy the p-norm constraint.

    a_lat_needed = speed^2 * curvature
    If the combined demand fits within the limit, return as-is.
    If not, prioritize lateral (must make the corner) and reduce longitudinal.
    """
    a_lat_needed = speed_mps ** 2 * abs(curvature)
    a_long_mag = abs(a_long_required)

    # Clamp lateral to maximum available
    a_lat_actual = min(a_lat_needed, ay_max)

    # Check if combined demand fits within the p-norm envelope
    if ay_max > 0.0 and ax_brake_max > 0.0:
        lat_usage = (a_lat_actual / ay_max) ** p
        long_usage = (a_long_mag / ax_brake_max) ** p
        if lat_usage + long_usage <= 1.0:
            # Within limit — return as-is (braking is negative)
            return (-a_long_mag, a_lat_actual)

    # Exceeds limit — prioritize lateral, reduce longitudinal
    ax_avail = available_longitudinal(a_lat_actual, ay_max, ax_brake_max, p)
    a_long_actual = min(a_long_mag, ax_avail)
    return (-a_long_actual, a_lat_actual)


def split_traction_cornering(
    a_long_required: float,
    curvature: float,
    speed_mps: float,
    ay_max: float,
    ax_drive_max: float,
    p: float,
) -> tuple[float, float]:
    """Same as split_braking_cornering but for traction (positive ax)."""
    a_lat_needed = speed_mps ** 2 * abs(curvature)
    a_long_mag = abs(a_long_required)

    # Clamp lateral to maximum available
    a_lat_actual = min(a_lat_needed, ay_max)

    # Check if combined demand fits within the p-norm envelope
    if ay_max > 0.0 and ax_drive_max > 0.0:
        lat_usage = (a_lat_actual / ay_max) ** p
        long_usage = (a_long_mag / ax_drive_max) ** p
        if lat_usage + long_usage <= 1.0:
            return (a_long_mag, a_lat_actual)

    # Exceeds limit — prioritize lateral, reduce longitudinal
    ax_avail = available_longitudinal(a_lat_actual, ay_max, ax_drive_max, p)
    a_long_actual = min(a_long_mag, ax_avail)
    return (a_long_actual, a_lat_actual)
