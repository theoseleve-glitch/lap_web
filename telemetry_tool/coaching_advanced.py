"""Advanced coaching engine with rich data channels.

Extends the basic GPS-only coaching engine with analysis of steering,
brake, throttle, RPM, and gear data.  Falls back gracefully when only
a subset of channels is available.

Usage::

    from coaching_advanced import get_coaching_tier, generate_advanced_coaching
    tier = get_coaching_tier(set(df.columns))
    if tier == "advanced":
        coaching = generate_advanced_coaching(sections, events, handling, df)
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

from coaching_basic import SectionCoaching, generate_basic_coaching
from track_decomposition import TrackSection
from mrp_detector import CornerEvents
from handling_detector import HandlingEvent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Channel tier detection
# ---------------------------------------------------------------------------

BASIC_CHANNELS = {"Speed (m/s)", "Latitude", "Longitude"}
ADVANCED_CHANNELS = {"Steering", "Brake", "Throttle", "RPM", "Gear"}

_COL_DIST = "Distance (m)"


def get_coaching_tier(available_columns: set[str]) -> str:
    """Return 'advanced' if 3+ advanced channels present, else 'basic'."""
    if len(ADVANCED_CHANNELS & available_columns) >= 3:
        return "advanced"
    return "basic"


# ---------------------------------------------------------------------------
# Helper analysers
# ---------------------------------------------------------------------------

def _build_handling_summary(events: list[HandlingEvent]) -> str:
    """Summarise handling events into readable text.

    Example: "Mild understeer at exit (early_throttle).
    Moderate oversteer at entry (trail_brake_too_deep)."
    """
    parts: list[str] = []
    for ev in events:
        cause_label = ev.cause.replace("_", " ") if ev.cause != "unknown" else "unidentified cause"
        parts.append(
            f"{ev.severity.capitalize()} {ev.event_type} at {ev.corner_phase} "
            f"({cause_label})"
        )
    return ". ".join(parts) + "." if parts else ""


def _analyze_throttle(
    section_df: pd.DataFrame,
    section_events: Optional[CornerEvents],
) -> str:
    """Analyse throttle application relative to corner events."""
    throttle = section_df["Throttle"].to_numpy(dtype=float)
    dist = section_df[_COL_DIST].to_numpy(dtype=float)

    # Find throttle application point (first point above 10% threshold)
    threshold = 10.0
    above = np.where(throttle > threshold)[0]

    if len(above) == 0:
        return "No significant throttle application detected in this corner."

    app_idx = above[0]
    app_dist = float(dist[app_idx])

    # Progression rate: how quickly throttle ramps from 10% to 80%
    high_threshold = 80.0
    high_above = np.where(throttle > high_threshold)[0]
    progression_note = ""
    if len(high_above) > 0:
        ramp_dist = float(dist[high_above[0]]) - app_dist
        if ramp_dist > 0:
            if ramp_dist < 10.0:
                progression_note = " Aggressive throttle ramp -- consider smoother application."
            elif ramp_dist > 40.0:
                progression_note = " Very gradual throttle -- could be more progressive."
            else:
                progression_note = " Good throttle progression rate."

    # Compare to MRP/throttle application from events
    ref_note = ""
    if section_events is not None and section_events.throttle_application_m is not None:
        delta = app_dist - section_events.mrp_m
        if delta < -5.0:
            ref_note = f" Throttle applied {abs(delta):.0f}m before MRP -- risk of understeer."
        elif delta > 15.0:
            ref_note = f" Throttle applied {delta:.0f}m after MRP -- potential for earlier application."
        else:
            ref_note = " Throttle application timing is well-placed relative to MRP."

    return (
        f"Throttle applied at {app_dist:.0f}m."
        f"{ref_note}{progression_note}"
    )


def _analyze_steering(section_df: pd.DataFrame) -> str:
    """Analyse steering smoothness and correction count."""
    steering = section_df["Steering"].to_numpy(dtype=float)

    if len(steering) < 5:
        return "Insufficient steering data for analysis."

    # Count direction changes (corrections) using sign changes of derivative
    d_steer = np.diff(steering)
    sign_changes = np.sum(np.abs(np.diff(np.sign(d_steer))) > 0)
    # Normalise: a perfectly smooth trace has ~0-2 changes; noisy has many
    # Each sign change in the derivative is a mid-corner correction
    correction_count = max(int(sign_changes) - 2, 0)  # subtract baseline

    # Turn-in rate: max steering rate in first 30% of section
    first_third = max(len(d_steer) // 3, 1)
    turn_in_rate = float(np.max(np.abs(d_steer[:first_third])))

    parts: list[str] = []
    if correction_count <= 2:
        parts.append("Smooth steering through this corner.")
    elif correction_count <= 5:
        parts.append(f"{correction_count} steering corrections detected -- minor adjustments.")
    else:
        parts.append(f"{correction_count} steering corrections detected -- aim for smoother inputs.")

    if turn_in_rate > 15.0:
        parts.append("Aggressive turn-in rate -- may benefit from smoother initial input.")
    elif turn_in_rate < 2.0:
        parts.append("Very gentle turn-in -- consider a more decisive initial input.")

    return " ".join(parts)


def _analyze_gear(section_df: pd.DataFrame) -> str:
    """Analyse gear selection relative to RPM range."""
    rpm = section_df["RPM"].to_numpy(dtype=float)
    gear = section_df["Gear"].to_numpy(dtype=float)
    speed = section_df["Speed (m/s)"].to_numpy(dtype=float)

    if len(rpm) == 0:
        return "No RPM/gear data available."

    # Find apex region (minimum speed point)
    apex_idx = int(np.argmin(speed))
    apex_rpm = float(rpm[apex_idx])
    apex_gear = int(gear[apex_idx])
    apex_rpm_k = apex_rpm / 1000.0

    parts: list[str] = []
    parts.append(f"Gear {apex_gear} at apex, RPM at {apex_rpm_k:.1f}k.")

    # Simple heuristic: if RPM < 4000 at apex, might benefit from downshift
    if apex_rpm < 4000.0:
        parts.append("Consider downshifting for better exit drive -- RPM is low at apex.")
    elif apex_rpm > 8000.0:
        parts.append("RPM very high at apex -- ensure engine is not over-revving.")
    else:
        parts.append("Good RPM range at apex for power delivery.")

    # Check for gear changes within the corner
    gear_changes = int(np.sum(np.abs(np.diff(gear)) > 0))
    if gear_changes > 2:
        parts.append(f"{gear_changes} gear changes in corner -- consider completing shifts before entry.")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_advanced_coaching(
    sections: list[TrackSection],
    events: dict[int, CornerEvents],
    handling: dict[int, list[HandlingEvent]],
    lap_df: pd.DataFrame,
    theoretical: dict | None = None,
    friction: float | None = None,
) -> list[SectionCoaching]:
    """Generate coaching enriched with advanced channel analysis.

    First calls ``generate_basic_coaching()`` for the base result, then
    enriches each section with handling, throttle, steering, and gear
    analysis when the relevant columns are present in *lap_df*.

    Parameters
    ----------
    sections : list[TrackSection]
        Track sections from decomposition.
    events : dict[int, CornerEvents]
        MRP events keyed by section_id.
    handling : dict[int, list[HandlingEvent]]
        Handling events keyed by section_id.
    lap_df : pd.DataFrame
        Lap data -- may include Throttle, Steering, RPM, Gear columns.
    theoretical : dict, optional
        Theoretical optimal data.
    friction : float, optional
        Tyre friction coefficient.

    Returns
    -------
    list[SectionCoaching]
        One enriched coaching item per section.
    """
    if not sections:
        return []

    # 1. Start with basic coaching
    basic_results = generate_basic_coaching(
        sections, events, handling, lap_df, theoretical, friction,
    )

    cols = set(lap_df.columns) if not lap_df.empty else set()
    results: list[SectionCoaching] = []

    for sc in basic_results:
        section = sc.section
        section_events = events.get(section.section_id)
        section_handling = handling.get(section.section_id, [])

        # Extract section data slice
        if _COL_DIST in lap_df.columns and len(lap_df) > 0:
            mask = (
                (lap_df[_COL_DIST] >= section.s_start)
                & (lap_df[_COL_DIST] <= section.s_end)
            )
            section_df = lap_df[mask]
        else:
            section_df = pd.DataFrame()

        is_corner = section.section_type == "corner"
        has_data = len(section_df) > 0

        # Handling summary (applicable to corners with handling events)
        handling_summary = None
        if section_handling:
            handling_summary = _build_handling_summary(section_handling)

        # Throttle advice (corners only)
        throttle_advice = None
        if "Throttle" in cols and is_corner and has_data:
            try:
                throttle_advice = _analyze_throttle(section_df, section_events)
            except Exception:
                logger.exception("Throttle analysis failed for section %d", section.section_id)

        # Steering advice (corners only)
        steering_advice = None
        if "Steering" in cols and is_corner and has_data:
            try:
                steering_advice = _analyze_steering(section_df)
            except Exception:
                logger.exception("Steering analysis failed for section %d", section.section_id)

        # Gear advice (corners only, needs both RPM and Gear)
        gear_advice = None
        if "RPM" in cols and "Gear" in cols and is_corner and has_data:
            try:
                gear_advice = _analyze_gear(section_df)
            except Exception:
                logger.exception("Gear analysis failed for section %d", section.section_id)

        # Build extra hints from advanced analysis
        extra_hints: list[str] = []
        if handling_summary:
            extra_hints.append(handling_summary)
        if throttle_advice:
            extra_hints.append(throttle_advice)
        if steering_advice:
            extra_hints.append(steering_advice)
        if gear_advice:
            extra_hints.append(gear_advice)

        # Create enriched SectionCoaching
        enriched = SectionCoaching(
            section=sc.section,
            events=sc.events,
            handling=sc.handling,
            time_loss_total_s=sc.time_loss_total_s,
            time_loss_braking_s=sc.time_loss_braking_s,
            time_loss_apex_s=sc.time_loss_apex_s,
            time_loss_exit_s=sc.time_loss_exit_s,
            primary_focus=sc.primary_focus,
            coaching_hints=sc.coaching_hints + extra_hints,
            corner_focus_note=sc.corner_focus_note,
            optimal_brake_point_m=sc.optimal_brake_point_m,
            optimal_entry_speed_mps=sc.optimal_entry_speed_mps,
            optimal_apex_speed_mps=sc.optimal_apex_speed_mps,
            optimal_exit_speed_mps=sc.optimal_exit_speed_mps,
            optimal_line_points=sc.optimal_line_points,
            handling_summary=handling_summary,
            throttle_advice=throttle_advice,
            steering_advice=steering_advice,
            gear_advice=gear_advice,
        )
        results.append(enriched)

    return results
