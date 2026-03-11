"""Throttle lift detector — finds mid-corner throttle drops and classifies severity."""
from __future__ import annotations

import numpy as np
import pandas as pd

from telemetry_tool.coaching.models import ThrottleLiftEvent

# Detection thresholds
_MIN_DROP_PCT = 15.0      # Minimum throttle drop to count as a lift
_MIN_THROTTLE_BEFORE = 20.0  # Minimum throttle before lift to be meaningful


def detect_throttle_lifts(
    corner: dict,
    lap: pd.DataFrame,
    friction_max: float,
    vehicle_mass_kg: float,
) -> list[ThrottleLiftEvent]:
    """Detect mid-corner throttle lift events within a corner segment."""
    if "Throttle (%)" not in lap.columns:
        return []

    corner_id = corner["corner_id"]
    s_start = corner["s_start"]
    s_end = corner["s_end"]

    dist = lap["Distance (m)"].values
    mask = (dist >= s_start) & (dist <= s_end)

    if mask.sum() < 5:
        return []

    throttle = lap["Throttle (%)"].values[mask]
    seg_dist = dist[mask]
    seg_speed = lap["Speed (m/s)"].values[mask]

    has_lat = "Lateral acceleration (m/s2)" in lap.columns
    lat_accel = lap["Lateral acceleration (m/s2)"].values[mask] if has_lat else np.zeros(mask.sum())

    has_time = "Time (s)" in lap.columns
    time_s = lap["Time (s)"].values[mask] if has_time else np.arange(mask.sum()) * 0.04

    has_yaw = "Yaw rate (deg/s)" in lap.columns
    yaw = lap["Yaw rate (deg/s)"].values[mask] if has_yaw else None

    events: list[ThrottleLiftEvent] = []

    # Walk through throttle trace looking for drops
    i = 0
    n = len(throttle)
    while i < n - 2:
        if throttle[i] >= _MIN_THROTTLE_BEFORE:
            # Look for a drop
            j = i + 1
            while j < n and throttle[j] < throttle[i] - _MIN_DROP_PCT:
                j += 1
            if j > i + 1:
                # Found a lift: throttle[i] → min(throttle[i+1:j])
                trough_idx = i + 1 + int(np.argmin(throttle[i + 1:j]))
                drop_pct = throttle[i] - throttle[trough_idx]

                if drop_pct >= _MIN_DROP_PCT:
                    drop_duration = float(time_s[min(trough_idx, n - 1)] - time_s[i])
                    lat_at_lift = float(np.abs(lat_accel[i])) if has_lat else 0.0
                    lat_grip_pct = (lat_at_lift / max(friction_max, 0.01)) * 100

                    # Weight shift estimate: F = m * a, where a ≈ drop_pct/100 * max_accel
                    weight_shift = vehicle_mass_kg * (drop_pct / 100) * 2.0  # simplified

                    yaw_change = None
                    if yaw is not None and trough_idx + 1 < n:
                        yaw_change = float(yaw[min(trough_idx + 1, n - 1)] - yaw[i])

                    resulted_in_correction = False
                    if yaw_change is not None and abs(yaw_change) > 5.0:
                        resulted_in_correction = True

                    severity = _classify_severity(drop_pct, lat_grip_pct, drop_duration)

                    events.append(ThrottleLiftEvent(
                        corner_id=corner_id,
                        s_position=float(seg_dist[i]),
                        throttle_before_pct=float(throttle[i]),
                        throttle_after_pct=float(throttle[trough_idx]),
                        drop_pct=float(drop_pct),
                        drop_duration_s=max(drop_duration, 0.001),
                        lateral_grip_at_lift_pct=lat_grip_pct,
                        weight_shift_estimate_kg=weight_shift,
                        yaw_rate_change_dps=yaw_change,
                        resulted_in_correction=resulted_in_correction,
                        severity=severity,
                    ))
                i = j
            else:
                i += 1
        else:
            i += 1

    return events


def _classify_severity(drop_pct: float, lat_grip_pct: float, duration_s: float) -> str:
    """Classify lift severity based on drop magnitude and grip level."""
    # Dangerous: big drop at high lateral grip
    if drop_pct > 40 and lat_grip_pct > 60:
        return "dangerous"
    # Significant: moderate drop at moderate grip
    if drop_pct > 25 and lat_grip_pct > 40:
        return "significant"
    # Benign: small drop or low grip
    return "benign"
