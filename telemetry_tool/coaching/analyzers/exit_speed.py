"""Exit speed cascade analyzer — computes how exit speed loss cascades onto the following straight."""
from __future__ import annotations

import numpy as np
import pandas as pd

from coaching.models import ExitSpeedCascade


def analyze_exit_cascades(
    corners: list[dict],
    driver_lap: pd.DataFrame,
    theoretical_lap: pd.DataFrame,
    track_length: float,
) -> list[ExitSpeedCascade]:
    """Compute exit speed cascade for each corner.

    For each corner, determines how much time is lost at exit and how that
    compounds on the following straight via full numerical integration
    (L/v_actual - L/v_theoretical).
    """
    if not corners or driver_lap.empty or theoretical_lap.empty:
        return []

    dist_col = "Distance (m)"
    speed_col = "Speed (m/s)"

    driver_dist = driver_lap[dist_col].values
    driver_speed = driver_lap[speed_col].values
    theo_dist = theoretical_lap[dist_col].values
    theo_speed = theoretical_lap[speed_col].values

    # Sort corners by start distance to find next-corner gaps
    sorted_corners = sorted(corners, key=lambda c: c["s_start"])

    results: list[ExitSpeedCascade] = []
    for i, corner in enumerate(sorted_corners):
        corner_id = corner["corner_id"]
        s_end = corner["s_end"]

        # Next corner start (or track end) defines the straight length
        if i + 1 < len(sorted_corners):
            next_start = sorted_corners[i + 1]["s_start"]
        else:
            next_start = track_length
        straight_length = max(next_start - s_end, 1.0)

        # Read exit speeds at corner end
        v_exit_actual = _speed_at(driver_dist, driver_speed, s_end)
        v_exit_theo = _speed_at(theo_dist, theo_speed, s_end)

        # Read straight-end speeds
        s_straight_end = s_end + straight_length
        v_end_actual = _speed_at(driver_dist, driver_speed, s_straight_end)
        v_end_theo = _speed_at(theo_dist, theo_speed, s_straight_end)

        # Time loss in corner: trapezoidal integration of (1/v_actual - 1/v_theo)
        corner_mask_d = (driver_dist >= corner["s_start"]) & (driver_dist <= s_end)
        corner_mask_t = (theo_dist >= corner["s_start"]) & (theo_dist <= s_end)

        time_loss_corner = _time_delta_over_segment(
            driver_dist[corner_mask_d], driver_speed[corner_mask_d],
            theo_dist[corner_mask_t], theo_speed[corner_mask_t],
        )

        # Time loss on straight: full integration L/v_actual - L/v_theo
        v_exit_actual_safe = max(v_exit_actual, 0.5)
        v_exit_theo_safe = max(v_exit_theo, 0.5)
        time_loss_straight = straight_length / v_exit_actual_safe - straight_length / v_exit_theo_safe

        total_cascade = time_loss_corner + time_loss_straight
        exit_delta = v_exit_theo - v_exit_actual

        cascade_ratio = (
            time_loss_straight / max(time_loss_corner, 0.001)
            if time_loss_corner > 0 else 0.0
        )

        results.append(ExitSpeedCascade(
            corner_id=corner_id,
            actual_exit_speed_mps=v_exit_actual,
            theoretical_exit_speed_mps=v_exit_theo,
            exit_speed_delta_mps=exit_delta,
            straight_length_m=straight_length,
            straight_end_speed_actual_mps=v_end_actual,
            straight_end_speed_theoretical_mps=v_end_theo,
            time_loss_in_corner_s=max(time_loss_corner, 0.0),
            time_loss_on_straight_s=max(time_loss_straight, 0.0),
            total_cascade_time_s=max(total_cascade, 0.0),
            exit_gain_needed_kmh=exit_delta * 3.6,
            straight_gain_resulting_kmh=(v_end_theo - v_end_actual) * 3.6,
            cascade_ratio=cascade_ratio,
        ))

    return results


def _speed_at(dist: np.ndarray, speed: np.ndarray, s: float) -> float:
    """Interpolate speed at distance s."""
    if len(dist) == 0:
        return 0.0
    idx = np.searchsorted(dist, s)
    if idx >= len(dist):
        return float(speed[-1])
    if idx == 0:
        return float(speed[0])
    return float(np.interp(s, dist, speed))


def _time_delta_over_segment(
    d_actual: np.ndarray, v_actual: np.ndarray,
    d_theo: np.ndarray, v_theo: np.ndarray,
) -> float:
    """Trapezoidal integration of time difference over a segment."""
    if len(d_actual) < 2 or len(d_theo) < 2:
        return 0.0
    # Compute time for actual and theoretical
    t_actual = np.trapezoid(1.0 / np.maximum(v_actual, 0.5), d_actual)
    t_theo = np.trapezoid(1.0 / np.maximum(v_theo, 0.5), d_theo)
    return t_actual - t_theo
