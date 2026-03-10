"""GPS-only basic coaching engine.

Generates per-section coaching advice using only GPS-derived data
(speed, position, distance). Produces coaching for EVERY section --
both straights and corners.

Advanced fields (handling_summary, throttle_advice, steering_advice,
gear_advice) are always None in basic mode.

Usage::

    from coaching_basic import generate_basic_coaching
    coaching = generate_basic_coaching(
        sections=sections,
        events=mrp_events,
        handling=handling_events,
        lap_df=df,
        theoretical=theoretical_dict,
        friction=mu,
    )
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from track_decomposition import TrackSection
from mrp_detector import CornerEvents
from handling_detector import HandlingEvent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_COL_DIST = "Distance (m)"
_COL_SPEED = "Speed (m/s)"
_DEFAULT_G = 9.81
_DEFAULT_MU = 1.2  # typical tyre friction coefficient


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SectionCoaching:
    """Coaching output for a single track section."""
    section: TrackSection
    events: Optional[CornerEvents]
    handling: list[HandlingEvent]
    time_loss_total_s: float
    time_loss_braking_s: float
    time_loss_apex_s: float
    time_loss_exit_s: float
    primary_focus: str
    coaching_hints: list[str]
    corner_focus_note: str
    optimal_brake_point_m: Optional[float]
    optimal_entry_speed_mps: Optional[float]
    optimal_apex_speed_mps: Optional[float]
    optimal_exit_speed_mps: Optional[float]
    optimal_line_points: Optional[list[tuple[float, float]]]
    handling_summary: Optional[str]      # None for basic
    throttle_advice: Optional[str]       # None for basic
    steering_advice: Optional[str]       # None for basic
    gear_advice: Optional[str]           # None for basic


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_section_speeds(
    df: pd.DataFrame,
    s_start: float,
    s_end: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Extract distance and speed arrays within section bounds."""
    distances = df[_COL_DIST].to_numpy(dtype=float)
    speeds = df[_COL_SPEED].to_numpy(dtype=float)
    mask = (distances >= s_start) & (distances <= s_end)
    return distances[mask], speeds[mask]


def _estimate_radius_from_section(section: TrackSection) -> float:
    """Rough radius estimate from section length and type."""
    length = section.s_end - section.s_start
    # Assume the corner subtends ~90 degrees by default
    # arc_length = radius * angle -> radius = length / angle
    # For a medium corner: ~90deg = pi/2
    return max(length / (math.pi / 2), 10.0)


def _compute_corner_coaching(
    section: TrackSection,
    corner_events: Optional[CornerEvents],
    handling_events: list[HandlingEvent],
    df: pd.DataFrame,
    theoretical: Optional[dict],
    friction: float,
) -> SectionCoaching:
    """Generate coaching for a corner section."""
    s_start = section.s_start
    s_end = section.s_end
    section_length = s_end - s_start
    geometric_apex = section.geometric_apex if section.geometric_apex is not None else (s_start + s_end) / 2.0

    d_seg, v_seg = _extract_section_speeds(df, s_start, s_end)

    if len(d_seg) == 0:
        return _empty_coaching(section, corner_events, handling_events)

    # Actual speeds
    actual_entry_speed = float(v_seg[0])
    actual_exit_speed = float(v_seg[-1])

    # Apex speed: speed at geometric apex (or MRP if events available)
    apex_dist = geometric_apex
    if corner_events is not None:
        apex_dist = corner_events.mrp_m
    actual_apex_speed = float(np.interp(apex_dist, d_seg, v_seg))

    # Optimal speeds from theoretical or friction estimate
    opt_entry = None
    opt_apex = None
    opt_exit = None
    opt_brake = None

    corner_id = section.section_id
    theo_corner = None
    if theoretical and "corners" in theoretical:
        theo_corner = theoretical["corners"].get(corner_id)

    if theo_corner:
        opt_entry = theo_corner.get("optimal_entry_speed_mps")
        opt_apex = theo_corner.get("optimal_apex_speed_mps")
        opt_exit = theo_corner.get("optimal_exit_speed_mps")
        opt_brake = theo_corner.get("optimal_brake_point_m")
    else:
        # Estimate from friction circle: v_apex = sqrt(mu * g * radius)
        radius = _estimate_radius_from_section(section)
        opt_apex = math.sqrt(friction * _DEFAULT_G * radius)
        # Entry/exit estimated as ~1.3x apex speed
        opt_entry = opt_apex * 1.3
        opt_exit = opt_apex * 1.3

    # Time loss calculations
    avg_speed = float(np.mean(v_seg))
    avg_speed = max(avg_speed, 1.0)
    corner_time = section_length / avg_speed

    # Braking time loss
    time_loss_braking = 0.0
    if opt_brake is not None and corner_events is not None and corner_events.brake_point_m is not None:
        brake_delta = abs(corner_events.brake_point_m - opt_brake)
        time_loss_braking = brake_delta / max(actual_entry_speed, 1.0)
    elif opt_entry is not None and actual_entry_speed < opt_entry:
        speed_delta = opt_entry - actual_entry_speed
        entry_fraction = 0.3  # first 30% of corner
        time_loss_braking = (speed_delta / max(opt_entry, 1.0)) * corner_time * entry_fraction

    # Apex time loss
    time_loss_apex = 0.0
    if opt_apex is not None and actual_apex_speed < opt_apex:
        speed_delta = opt_apex - actual_apex_speed
        mid_fraction = 0.4  # middle 40% of corner
        time_loss_apex = (speed_delta / max(opt_apex, 1.0)) * corner_time * mid_fraction

    # Exit time loss
    time_loss_exit = 0.0
    if opt_exit is not None and actual_exit_speed < opt_exit:
        speed_delta = opt_exit - actual_exit_speed
        exit_fraction = 0.3  # last 30% of corner
        time_loss_exit = (speed_delta / max(opt_exit, 1.0)) * corner_time * exit_fraction

    time_loss_total = time_loss_braking + time_loss_apex + time_loss_exit

    # Generate coaching hints ordered by time impact
    hints_with_impact: list[tuple[float, str]] = []

    if time_loss_braking > 0.001:
        if opt_brake is not None and corner_events is not None and corner_events.brake_point_m is not None:
            hints_with_impact.append((
                time_loss_braking,
                f"Brake {abs(corner_events.brake_point_m - opt_brake):.0f}m "
                f"{'early' if corner_events.brake_point_m < opt_brake else 'late'} "
                f"-- lost {time_loss_braking:.2f}s"
            ))
        else:
            entry_kmh = actual_entry_speed * 3.6
            opt_entry_kmh = (opt_entry or 0) * 3.6
            hints_with_impact.append((
                time_loss_braking,
                f"Entry speed {entry_kmh:.0f} km/h vs {opt_entry_kmh:.0f} km/h potential "
                f"-- lost {time_loss_braking:.2f}s"
            ))

    if time_loss_apex > 0.001:
        apex_kmh = actual_apex_speed * 3.6
        opt_apex_kmh = (opt_apex or 0) * 3.6
        hints_with_impact.append((
            time_loss_apex,
            f"Apex speed {apex_kmh:.0f} km/h vs {opt_apex_kmh:.0f} km/h potential "
            f"-- lost {time_loss_apex:.2f}s"
        ))

    if time_loss_exit > 0.001:
        exit_kmh = actual_exit_speed * 3.6
        opt_exit_kmh = (opt_exit or 0) * 3.6
        hints_with_impact.append((
            time_loss_exit,
            f"Exit speed {exit_kmh:.0f} km/h vs {opt_exit_kmh:.0f} km/h potential "
            f"-- lost {time_loss_exit:.2f}s"
        ))

    # If no measurable time loss, add a generic positive hint
    if not hints_with_impact:
        hints_with_impact.append((0.0, "Corner executed well -- maintain current technique."))

    # Sort by impact descending
    hints_with_impact.sort(key=lambda x: x[0], reverse=True)
    coaching_hints = [h[1] for h in hints_with_impact]

    primary_focus = coaching_hints[0] if coaching_hints else ""

    # Corner focus note from exit importance
    corner_focus_note = ""
    if section.exit_importance > 0.5:
        corner_focus_note = (
            f"Exit critical -- long straight follows. "
            f"Prioritize exit speed over entry speed."
        )

    return SectionCoaching(
        section=section,
        events=corner_events,
        handling=handling_events,
        time_loss_total_s=time_loss_total,
        time_loss_braking_s=time_loss_braking,
        time_loss_apex_s=time_loss_apex,
        time_loss_exit_s=time_loss_exit,
        primary_focus=primary_focus,
        coaching_hints=coaching_hints,
        corner_focus_note=corner_focus_note,
        optimal_brake_point_m=opt_brake,
        optimal_entry_speed_mps=opt_entry,
        optimal_apex_speed_mps=opt_apex,
        optimal_exit_speed_mps=opt_exit,
        optimal_line_points=None,
        handling_summary=None,
        throttle_advice=None,
        steering_advice=None,
        gear_advice=None,
    )


def _compute_straight_coaching(
    section: TrackSection,
    handling_events: list[HandlingEvent],
    df: pd.DataFrame,
    theoretical: Optional[dict],
) -> SectionCoaching:
    """Generate coaching for a straight section."""
    d_seg, v_seg = _extract_section_speeds(df, section.s_start, section.s_end)

    if len(d_seg) == 0:
        return _empty_coaching(section, None, handling_events)

    actual_top_speed = float(np.max(v_seg))
    actual_top_kmh = actual_top_speed * 3.6
    section_length = section.s_end - section.s_start
    avg_speed = float(np.mean(v_seg))
    avg_speed = max(avg_speed, 1.0)

    # Optimal top speed from theoretical
    opt_top_speed = None
    section_id = section.section_id
    if theoretical and "straights" in theoretical:
        theo_straight = theoretical["straights"].get(section_id)
        if theo_straight:
            opt_top_speed = theo_straight.get("optimal_top_speed_mps")

    # Time loss from insufficient top speed
    time_loss = 0.0
    coaching_hints = []

    if opt_top_speed is not None and actual_top_speed < opt_top_speed:
        opt_kmh = opt_top_speed * 3.6
        speed_delta = opt_top_speed - actual_top_speed
        time_loss = (speed_delta / max(opt_top_speed, 1.0)) * (section_length / avg_speed)
        coaching_hints.append(
            f"Reached {actual_top_kmh:.0f} km/h vs {opt_kmh:.0f} km/h potential "
            f"-- lost {time_loss:.1f}s"
        )
    else:
        coaching_hints.append(
            f"Top speed {actual_top_kmh:.0f} km/h on this straight -- good acceleration."
        )

    primary_focus = coaching_hints[0] if coaching_hints else ""

    return SectionCoaching(
        section=section,
        events=None,
        handling=handling_events,
        time_loss_total_s=time_loss,
        time_loss_braking_s=0.0,
        time_loss_apex_s=0.0,
        time_loss_exit_s=0.0,
        primary_focus=primary_focus,
        coaching_hints=coaching_hints,
        corner_focus_note="",
        optimal_brake_point_m=None,
        optimal_entry_speed_mps=None,
        optimal_apex_speed_mps=None,
        optimal_exit_speed_mps=None,
        optimal_line_points=None,
        handling_summary=None,
        throttle_advice=None,
        steering_advice=None,
        gear_advice=None,
    )


def _empty_coaching(
    section: TrackSection,
    events: Optional[CornerEvents],
    handling: list[HandlingEvent],
) -> SectionCoaching:
    """Return a zero-loss coaching result when no data is available."""
    return SectionCoaching(
        section=section,
        events=events,
        handling=handling,
        time_loss_total_s=0.0,
        time_loss_braking_s=0.0,
        time_loss_apex_s=0.0,
        time_loss_exit_s=0.0,
        primary_focus="No data available for this section.",
        coaching_hints=["No data available for this section."],
        corner_focus_note="",
        optimal_brake_point_m=None,
        optimal_entry_speed_mps=None,
        optimal_apex_speed_mps=None,
        optimal_exit_speed_mps=None,
        optimal_line_points=None,
        handling_summary=None,
        throttle_advice=None,
        steering_advice=None,
        gear_advice=None,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_basic_coaching(
    sections: list[TrackSection],
    events: dict[int, CornerEvents],
    handling: dict[int, list[HandlingEvent]],
    lap_df: pd.DataFrame,
    theoretical: Optional[dict] = None,
    friction: Optional[float] = None,
) -> list[SectionCoaching]:
    """Generate GPS-only coaching for every section of the track.

    Parameters
    ----------
    sections : list[TrackSection]
        Track sections from decomposition (corners + straights).
    events : dict[int, CornerEvents]
        MRP events keyed by section_id.
    handling : dict[int, list[HandlingEvent]]
        Handling events keyed by section_id.
    lap_df : pd.DataFrame
        Lap data with at least ``Distance (m)`` and ``Speed (m/s)`` columns.
    theoretical : dict, optional
        Theoretical optimal data with keys ``corners`` and ``straights``,
        each mapping section_id to optimal speeds / brake points.
    friction : float, optional
        Tyre friction coefficient for physics estimates. Defaults to 1.2.

    Returns
    -------
    list[SectionCoaching]
        One coaching item per section, ordered same as input.
    """
    if not sections:
        return []

    mu = friction if friction is not None else _DEFAULT_MU
    result: list[SectionCoaching] = []

    for sec in sections:
        sec_handling = handling.get(sec.section_id, [])

        try:
            if sec.section_type == "corner":
                corner_events = events.get(sec.section_id)
                coaching = _compute_corner_coaching(
                    section=sec,
                    corner_events=corner_events,
                    handling_events=sec_handling,
                    df=lap_df,
                    theoretical=theoretical,
                    friction=mu,
                )
            else:
                coaching = _compute_straight_coaching(
                    section=sec,
                    handling_events=sec_handling,
                    df=lap_df,
                    theoretical=theoretical,
                )
        except Exception:
            logger.exception("Coaching failed for section %d", sec.section_id)
            coaching = _empty_coaching(sec, events.get(sec.section_id), sec_handling)

        result.append(coaching)

    return result
