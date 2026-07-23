"""Symptom detector — rule-based symptom detection with 3-tier channel fallback.

Tier 1: Full channels (throttle, brake, steering, accelerations)
Tier 2: GPS + accelerations (no pedal data)
Tier 3: GPS only (speed + position)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from coaching.models import Symptom, SymptomDetection


def detect_symptoms(corner: dict, lap: pd.DataFrame) -> SymptomDetection:
    """Detect coaching-book symptoms for a single corner."""
    corner_id = corner["corner_id"]
    s_start = corner["s_start"]
    s_end = corner["s_end"]
    s_apex = corner.get("s_apex", (s_start + s_end) / 2)

    dist = lap["Distance (m)"].values
    mask = (dist >= s_start) & (dist <= s_end)

    if mask.sum() < 4:
        return SymptomDetection(corner_id=corner_id, symptoms=[])

    seg_dist = dist[mask]
    seg_speed = lap["Speed (m/s)"].values[mask]

    # Determine available channels
    has_steering = "Steering angle (deg)" in lap.columns
    has_lat_pos = "Lateral position (m)" in lap.columns
    has_lat_accel = "Lateral acceleration (m/s2)" in lap.columns
    has_lon_accel = "Longitudinal acceleration (m/s2)" in lap.columns
    has_throttle = "Throttle (%)" in lap.columns
    has_brake = "Brake (%)" in lap.columns

    symptoms: list[Symptom] = []

    # --- Early apex detection ---
    # Tier 1: steering angle still increasing past geometric apex
    if has_steering:
        steer = np.abs(lap["Steering angle (deg)"].values[mask])
        apex_rel_idx = int(len(seg_dist) * (s_apex - s_start) / max(s_end - s_start, 1))
        apex_rel_idx = min(max(apex_rel_idx, 1), len(steer) - 2)
        # If steering is still increasing after the apex point → early apex
        post_apex_steer = steer[apex_rel_idx:]
        if len(post_apex_steer) > 3:
            steer_gradient = np.mean(np.diff(post_apex_steer[:len(post_apex_steer) // 2]))
            if steer_gradient > 0.5:  # increasing steering past apex
                symptoms.append(Symptom(
                    symptom_id="early_apex",
                    description="Steering angle increases past apex, indicating turn-in was too early",
                    evidence={"post_apex_steer_gradient": float(steer_gradient)},
                    confidence=min(steer_gradient / 3.0, 1.0),
                ))

    # Tier 2/3: lateral position at exit (road not used)
    if "early_apex" not in [s.symptom_id for s in symptoms] and has_lat_pos:
        lat_pos = lap["Lateral position (m)"].values[mask]
        exit_zone = lat_pos[int(len(lat_pos) * 0.8):]
        if len(exit_zone) > 0:
            avg_exit_offset = float(np.mean(np.abs(exit_zone)))
            if avg_exit_offset > 0.8:  # >0.8m inside at exit
                symptoms.append(Symptom(
                    symptom_id="early_apex",
                    description="Exit lateral position suggests not using full road width (early apex likely)",
                    evidence={"exit_offset_m": avg_exit_offset},
                    confidence=min(avg_exit_offset / 2.5, 1.0),
                ))

    # --- Understeer entry (Tier 1 only: needs steering + lateral accel) ---
    if has_steering and has_lat_accel:
        steer = np.abs(lap["Steering angle (deg)"].values[mask])
        lat_accel = np.abs(lap["Lateral acceleration (m/s2)"].values[mask])
        entry_zone = slice(0, len(seg_dist) // 4)
        entry_steer = steer[entry_zone]
        entry_lat = lat_accel[entry_zone]
        if len(entry_steer) > 2 and np.mean(entry_steer) > 15:
            # High steering but low lateral accel → understeer
            steer_to_lat_ratio = float(np.mean(entry_steer) / max(np.mean(entry_lat), 0.1))
            if steer_to_lat_ratio > 8:  # excessive steering for the lat accel produced
                symptoms.append(Symptom(
                    symptom_id="understeer_entry",
                    description="High steering angle with low lateral acceleration at entry suggests understeer",
                    evidence={"steer_lat_ratio": steer_to_lat_ratio},
                    confidence=min((steer_to_lat_ratio - 5) / 10, 1.0),
                ))

    # --- Mid-corner speed loss ---
    apex_idx = int(len(seg_speed) * (s_apex - s_start) / max(s_end - s_start, 1))
    apex_idx = min(max(apex_idx, 0), len(seg_speed) - 1)
    apex_speed = seg_speed[apex_idx]
    entry_speed = seg_speed[0]
    if entry_speed > 0 and apex_speed < entry_speed * 0.5:
        speed_loss_pct = (1 - apex_speed / entry_speed) * 100
        symptoms.append(Symptom(
            symptom_id="mid_corner_speed_loss",
            description="Significant speed reduction at apex",
            evidence={"speed_loss_pct": float(speed_loss_pct)},
            confidence=min(speed_loss_pct / 60, 1.0),
        ))

    return SymptomDetection(corner_id=corner_id, symptoms=symptoms)
