"""
envelope_boundaries.py
----------------------
Robust track surface reconstruction from RTK-grade GPS + noisy IMU.

Key insights:
- Phone GPS here is 0.17m accuracy (RTK). Position is the cleanest signal.
- IMU-derived channels (yaw_rate, Z accel, grade) have outliers and must be
  clipped/filtered before use.
- Aggregation across laps must use MEDIAN (robust) not mean (sensitive).
- Smoothing must preserve features (Savitzky-Golay) not blur them
  (uniform_filter1d).
- Per-lap trajectories benefit from 2D RTS smoothing even with clean GPS.
"""
from __future__ import annotations

import numpy as np
from scipy.signal import savgol_filter


# ---------- Outlier rejection ----------

def reject_imu_outliers(values: np.ndarray, max_abs: float) -> np.ndarray:
    """Clip IMU-derived values to physically realistic bounds.

    Replaces outliers with NaN so downstream averaging can drop them.
    """
    out = values.astype(float).copy()
    mask = ~np.isfinite(out) | (np.abs(out) > max_abs)
    out[mask] = np.nan
    return out


# ---------- Savitzky-Golay smoothing ----------

def savgol_smooth(arr: np.ndarray, window: int = 11, polyorder: int = 3) -> np.ndarray:
    """Savitzky-Golay filter — fits local polynomials, preserves features.

    Handles the circular (wrap) boundary by extending on both ends.
    """
    n = len(arr)
    if n < window:
        return arr.copy()
    if window % 2 == 0:
        window += 1
    # Wrap extend for periodic smoothing
    pad = window
    extended = np.concatenate([arr[-pad:], arr, arr[:pad]])
    smoothed = savgol_filter(extended, window, polyorder)
    return smoothed[pad:pad + n]


# ---------- Per-lap 2D Kalman + RTS smoother ----------

def kalman_rts_smooth_2d(
    x_raw: np.ndarray,
    y_raw: np.ndarray,
    dt_arr: np.ndarray | None = None,
    measurement_std: float = 0.2,  # 0.17m RTK accuracy ~ 0.2m
    process_std_accel: float = 5.0,  # m/s² process noise
) -> tuple[np.ndarray, np.ndarray]:
    """2D constant-velocity Kalman filter + RTS backward smoother.

    State: [x, y, vx, vy]
    Observation: [x, y] with R = measurement_std²
    Process: random acceleration with variance process_std_accel²

    Returns (x_smooth, y_smooth) arrays.
    Uses uniform dt if dt_arr is None.
    """
    n = len(x_raw)
    if n < 5:
        return x_raw.copy(), y_raw.copy()

    if dt_arr is None:
        dt_arr = np.ones(n - 1)

    # Storage
    X_filt = np.zeros((n, 4))
    P_filt = np.zeros((n, 4, 4))
    X_pred_store = np.zeros((n, 4))
    P_pred_store = np.zeros((n, 4, 4))

    # Initial state: first position, zero velocity
    X_filt[0] = [x_raw[0], y_raw[0], 0.0, 0.0]
    P_filt[0] = np.diag([1.0, 1.0, 100.0, 100.0])
    X_pred_store[0] = X_filt[0]
    P_pred_store[0] = P_filt[0]

    R = np.eye(2) * (measurement_std ** 2)
    H = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], dtype=float)

    # Forward filter
    for i in range(1, n):
        dt = dt_arr[i - 1] if i - 1 < len(dt_arr) else dt_arr[-1]
        F = np.array([
            [1, 0, dt, 0],
            [0, 1, 0, dt],
            [0, 0, 1, 0],
            [0, 0, 0, 1],
        ], dtype=float)
        # Process noise: random accel → Q = G @ diag([a², a²]) @ G.T
        G_mat = np.array([[0.5 * dt ** 2, 0], [0, 0.5 * dt ** 2], [dt, 0], [0, dt]])
        Q = G_mat @ (np.eye(2) * process_std_accel ** 2) @ G_mat.T

        X_pred = F @ X_filt[i - 1]
        P_pred = F @ P_filt[i - 1] @ F.T + Q
        X_pred_store[i] = X_pred
        P_pred_store[i] = P_pred

        # Update with measurement
        if np.isfinite(x_raw[i]) and np.isfinite(y_raw[i]):
            z = np.array([x_raw[i], y_raw[i]])
            y_innov = z - H @ X_pred
            S = H @ P_pred @ H.T + R
            try:
                K = P_pred @ H.T @ np.linalg.inv(S)
            except np.linalg.LinAlgError:
                X_filt[i] = X_pred
                P_filt[i] = P_pred
                continue
            X_filt[i] = X_pred + K @ y_innov
            P_filt[i] = (np.eye(4) - K @ H) @ P_pred
        else:
            X_filt[i] = X_pred
            P_filt[i] = P_pred

    # RTS backward smoother
    X_smooth = X_filt.copy()
    for i in range(n - 2, -1, -1):
        dt = dt_arr[i] if i < len(dt_arr) else dt_arr[-1]
        F = np.array([
            [1, 0, dt, 0],
            [0, 1, 0, dt],
            [0, 0, 1, 0],
            [0, 0, 0, 1],
        ], dtype=float)
        P_pred_next = P_pred_store[i + 1]
        try:
            A = P_filt[i] @ F.T @ np.linalg.inv(P_pred_next)
        except np.linalg.LinAlgError:
            continue
        X_smooth[i] = X_filt[i] + A @ (X_smooth[i + 1] - F @ X_filt[i])

    return X_smooth[:, 0], X_smooth[:, 1]


# ---------- Centerline (robust median) ----------

def robust_median_centerline(
    all_laps_xy: list[tuple[np.ndarray, np.ndarray, np.ndarray]],
    n_bins: int,
    track_length: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Median-of-laps centerline — robust to outlier laps.

    For each s-bin, collects positions from all laps and takes the median.
    A single bad lap (GPS glitch) won't pull the centerline off.
    """
    s_grid = np.linspace(0, track_length, n_bins)
    x_samples = [[] for _ in range(n_bins)]
    y_samples = [[] for _ in range(n_bins)]

    for x, y, dist in all_laps_xy:
        if len(dist) < 5:
            continue
        lap_len = float(dist[-1] - dist[0])
        if abs(lap_len - track_length) > track_length * 0.10:
            continue
        dist_norm = dist - dist[0]
        x_i = np.interp(s_grid, dist_norm, x)
        y_i = np.interp(s_grid, dist_norm, y)
        for i in range(n_bins):
            if np.isfinite(x_i[i]) and np.isfinite(y_i[i]):
                x_samples[i].append(float(x_i[i]))
                y_samples[i].append(float(y_i[i]))

    center_x = np.zeros(n_bins)
    center_y = np.zeros(n_bins)
    for i in range(n_bins):
        if x_samples[i]:
            center_x[i] = float(np.median(x_samples[i]))
            center_y[i] = float(np.median(y_samples[i]))

    # Savitzky-Golay preserves corner features
    center_x = savgol_smooth(center_x, window=11, polyorder=3)
    center_y = savgol_smooth(center_y, window=11, polyorder=3)
    return center_x, center_y, s_grid


def signed_perp_offset(
    x_lap: np.ndarray,
    y_lap: np.ndarray,
    dist_lap: np.ndarray,
    center_x: np.ndarray,
    center_y: np.ndarray,
    s_grid: np.ndarray,
) -> np.ndarray:
    """Signed perpendicular offset per s-bin.

    Positive = left of travel direction.
    """
    dist_norm = dist_lap - dist_lap[0]
    x_at_s = np.interp(s_grid, dist_norm, x_lap)
    y_at_s = np.interp(s_grid, dist_norm, y_lap)

    dx_c = np.gradient(center_x)
    dy_c = np.gradient(center_y)
    mag = np.sqrt(dx_c ** 2 + dy_c ** 2)
    mag[mag < 1e-9] = 1e-9
    nx = -dy_c / mag
    ny = dx_c / mag

    dx = x_at_s - center_x
    dy = y_at_s - center_y
    return dx * nx + dy * ny


# ---------- Percentile envelope ----------

def percentile_envelope(
    all_laps_xy: list[tuple[np.ndarray, np.ndarray, np.ndarray]],
    center_x: np.ndarray,
    center_y: np.ndarray,
    s_grid: np.ndarray,
    track_length: float,
    p_low: float = 5.0,
    p_high: float = 95.0,
    buffer_m: float = 0.8,
) -> tuple[np.ndarray, np.ndarray]:
    """Percentile-based envelope (robust to outliers).

    Returns (left_edge, right_edge) arrays, both as SIGNED values:
    left_edge > 0 (positive side), right_edge < 0 (negative side).
    """
    n_bins = len(s_grid)
    all_offsets = [[] for _ in range(n_bins)]

    for x, y, dist in all_laps_xy:
        if len(dist) < 5:
            continue
        lap_len = float(dist[-1] - dist[0])
        if abs(lap_len - track_length) > track_length * 0.10:
            continue
        offsets = signed_perp_offset(x, y, dist, center_x, center_y, s_grid)
        for i, off in enumerate(offsets):
            if np.isfinite(off):
                all_offsets[i].append(float(off))

    left_edge = np.full(n_bins, 4.0)
    right_edge = np.full(n_bins, -4.0)
    for i, offs in enumerate(all_offsets):
        if len(offs) >= 3:
            left_edge[i] = float(np.percentile(offs, p_high)) + buffer_m
            right_edge[i] = float(np.percentile(offs, p_low)) - buffer_m

    left_edge = savgol_smooth(left_edge, window=11, polyorder=2)
    right_edge = savgol_smooth(right_edge, window=11, polyorder=2)
    return left_edge, right_edge


def apply_min_width(
    left_edge: np.ndarray,
    right_edge: np.ndarray,
    min_total_width: float = 7.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Enforce a minimum total width via symmetric expansion around midpoint."""
    out_left = left_edge.copy()
    out_right = right_edge.copy()
    for i in range(len(out_left)):
        total = out_left[i] - out_right[i]
        if total < min_total_width:
            mid = (out_left[i] + out_right[i]) / 2
            out_left[i] = mid + min_total_width / 2
            out_right[i] = mid - min_total_width / 2
    return out_left, out_right


# ---------- Top-level orchestrator ----------

def refine_centerline_iteratively(
    all_laps_xy: list[tuple[np.ndarray, np.ndarray, np.ndarray]],
    n_bins: int,
    track_length: float,
    n_iterations: int = 2,
    buffer_m: float = 0.8,
    min_total_width: float = 7.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Robust centerline + boundary extraction.

    Uses median aggregation, percentile envelope, Savitzky-Golay smoothing.
    """
    # Pass 1: robust median centerline
    center_x, center_y, s_grid = robust_median_centerline(
        all_laps_xy, n_bins, track_length,
    )

    for iteration in range(n_iterations):
        left_edge, right_edge = percentile_envelope(
            all_laps_xy, center_x, center_y, s_grid, track_length,
            buffer_m=buffer_m,
        )
        left_edge, right_edge = apply_min_width(
            left_edge, right_edge, min_total_width,
        )

        # Shift centerline toward envelope midpoint along normal
        midpoint_offset = (left_edge + right_edge) / 2
        dx_c = np.gradient(center_x)
        dy_c = np.gradient(center_y)
        mag = np.sqrt(dx_c ** 2 + dy_c ** 2)
        mag[mag < 1e-9] = 1e-9
        nx = -dy_c / mag
        ny = dx_c / mag
        center_x = center_x + nx * midpoint_offset
        center_y = center_y + ny * midpoint_offset
        center_x = savgol_smooth(center_x, window=11, polyorder=3)
        center_y = savgol_smooth(center_y, window=11, polyorder=3)

    # Final envelope
    left_edge, right_edge = percentile_envelope(
        all_laps_xy, center_x, center_y, s_grid, track_length,
        buffer_m=buffer_m,
    )
    left_edge, right_edge = apply_min_width(left_edge, right_edge, min_total_width)

    width_left = np.clip(left_edge, 0.5, 8.0)
    width_right = np.clip(-right_edge, 0.5, 8.0)
    # Extra smoothing pass on widths
    width_left = savgol_smooth(width_left, window=15, polyorder=2)
    width_right = savgol_smooth(width_right, window=15, polyorder=2)
    return center_x, center_y, s_grid, width_left, width_right


def compute_curvature(
    center_x: np.ndarray,
    center_y: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute signed curvature + unwrapped heading from centerline.

    Uses Savitzky-Golay smoothing (preserves corner features) instead of
    box blur (which rounds off corners).
    """
    dx = np.gradient(center_x)
    dy = np.gradient(center_y)
    heading = np.arctan2(dy, dx)
    heading_unwrapped = np.unwrap(heading)

    ds = np.sqrt(np.diff(center_x) ** 2 + np.diff(center_y) ** 2)
    ds = np.append(ds, ds[-1])
    dheading = np.gradient(heading_unwrapped)
    curvature = dheading / np.maximum(ds, 0.01)
    # Savitzky-Golay preserves corner curvature peaks
    curvature = savgol_smooth(curvature, window=11, polyorder=3)
    curvature = np.clip(curvature, -0.35, 0.35)
    return curvature, heading_unwrapped
