"""
track_surface/pre_session.py
----------------------------
Pre-session coach: generates a track briefing based on accumulated data
and current conditions, BEFORE the driver goes on track.

Uses the accumulated TrackSurface to produce:
- Track overview (length, corners, elevation profile)
- Condition-specific alerts (wet rubber-line, compression pooling)
- Wet line shifts per corner (from grip inversion)
- Driver-specific focus areas (from previous session line deltas)
- Reference pace estimation
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from track_surface.model import TrackSurface
from track_surface.wet_model import (
    compute_wet_line_shifts,
    find_compression_warnings,
)

logger = logging.getLogger(__name__)

# Typical wet pace penalty by condition
_WET_FACTOR = {"dry": 1.00, "damp": 1.04, "wet": 1.08, "heavy_wet": 1.15}


@dataclass
class PreSessionBriefing:
    """Complete pre-session coaching output."""

    track_name: str
    track_id: str
    total_length_m: float
    model_quality: str
    sessions_accumulated: int
    condition: str

    # Alerts
    condition_alerts: list[dict] = field(default_factory=list)

    # Wet line advice (only when condition != dry)
    wet_line_shifts: list[dict] = field(default_factory=list)

    # Compression warnings (wet-specific)
    compression_warnings: list[dict] = field(default_factory=list)

    # Driver focus (from previous sessions)
    driver_focus: list[dict] = field(default_factory=list)

    # Reference pace
    reference_pace: dict = field(default_factory=dict)

    # Corner summary
    corner_count: int = 0
    elevation_range_m: float = 0.0

    def to_dict(self) -> dict:
        return {
            "track_briefing": {
                "track_name": self.track_name,
                "track_id": self.track_id,
                "total_length_m": round(self.total_length_m, 1),
                "model_quality": self.model_quality,
                "sessions_accumulated": self.sessions_accumulated,
                "corner_count": self.corner_count,
                "elevation_range_m": round(self.elevation_range_m, 1),
            },
            "condition": self.condition,
            "condition_alerts": self.condition_alerts,
            "wet_line_shifts": self.wet_line_shifts,
            "compression_warnings": self.compression_warnings,
            "driver_focus": self.driver_focus,
            "reference_pace": self.reference_pace,
        }


def generate_pre_session_briefing(
    surface: TrackSurface,
    condition: str = "dry",
    corners: list[dict] | None = None,
    driver_history: list[dict] | None = None,
    best_dry_lap_s: float | None = None,
    track_name: str | None = None,
) -> PreSessionBriefing:
    """Generate a pre-session briefing from accumulated track data.

    Parameters
    ----------
    surface : Accumulated TrackSurface for this track.
    condition : current track condition ("dry", "damp", "wet", "heavy_wet").
    corners : corner list from corner detection (optional, enriches advice).
    driver_history : list of dicts from previous sessions with keys like
        corner_id, time_loss_s, cause, apex_error_m (optional).
    best_dry_lap_s : best known dry lap time for reference pace.
    track_name : human-readable track name.

    Returns
    -------
    PreSessionBriefing with all coaching data.
    """
    is_wet = condition in ("damp", "wet", "heavy_wet")
    corners = corners or []

    briefing = PreSessionBriefing(
        track_name=track_name or surface.track_id,
        track_id=surface.track_id,
        total_length_m=surface.frenet.total_length_m,
        model_quality=surface.quality_tier,
        sessions_accumulated=surface.n_laps,
        condition=condition,
        corner_count=len(corners),
    )

    # Elevation range
    if surface.has_elevation:
        briefing.elevation_range_m = float(
            np.max(surface.elevation_m) - np.min(surface.elevation_m)
        )

    # ── Condition alerts ──────────────────────────────────────────

    if is_wet and surface.has_grip_2d:
        # Identify corners with significant rubber deposits
        rubber_corners = _find_rubber_line_corners(surface, corners)
        if rubber_corners:
            corner_names = ", ".join(f"T{c}" for c in rubber_corners)
            briefing.condition_alerts.append({
                "type": "wet_rubber_line",
                "severity": "high",
                "corners": rubber_corners,
                "message": f"Rubber line is slippery in wet — move 1-2m off-line through {corner_names}",
            })

    if is_wet and surface.has_vert_curvature:
        comp_warnings = find_compression_warnings(surface, corners)
        briefing.compression_warnings = [w.to_dict() for w in comp_warnings]
        if comp_warnings:
            briefing.condition_alerts.append({
                "type": "compression_pooling",
                "severity": "medium",
                "count": len(comp_warnings),
                "message": f"{len(comp_warnings)} compression zone(s) may pool water — brake earlier",
            })

    # Puddle zones from drainage model (wet-specific)
    if is_wet and surface.has_elevation_3d:
        try:
            from track_surface.drainage import compute_drainage
            puddles = compute_drainage(surface.elevation_surface)
            if puddles:
                briefing.condition_alerts.append({
                    "type": "puddle_zones",
                    "severity": "high" if len(puddles) >= 3 else "medium",
                    "count": len(puddles),
                    "zones": [p.to_dict() for p in puddles[:5]],  # top 5
                    "message": f"{len(puddles)} puddle zone(s) predicted from track drainage — watch for standing water",
                })
        except Exception:
            pass  # drainage module optional

    if condition == "damp":
        briefing.condition_alerts.append({
            "type": "mixed_conditions",
            "severity": "medium",
            "message": "Damp track — grip varies lap to lap. Explore cautiously on out-lap.",
        })

    # ── Wet line shifts ───────────────────────────────────────────

    if is_wet and surface.has_grip_2d and corners:
        shifts = compute_wet_line_shifts(surface, corners)
        briefing.wet_line_shifts = [s.to_dict() for s in shifts if s.shift_m > 0.3]

    # ── Driver focus ──────────────────────────────────────────────

    if driver_history:
        # Sort by time loss, take top 3
        sorted_hist = sorted(driver_history, key=lambda d: d.get("time_loss_s", 0), reverse=True)
        for item in sorted_hist[:3]:
            cid = item.get("corner_id")
            loss = item.get("time_loss_s", 0)
            cause = item.get("cause", "unknown")
            apex_err = item.get("apex_error_m", 0)

            tip = f"T{cid}: lost {loss:.2f}s last session"
            if cause == "line" and abs(apex_err) > 0.5:
                tip += f" — apex was {abs(apex_err):.1f}m {'early' if apex_err < 0 else 'late'}"
                if is_wet:
                    tip += " (even more critical in wet)"
            elif cause == "speed":
                tip += " — mid-corner speed too low"

            briefing.driver_focus.append({
                "corner_id": cid,
                "time_loss_s": round(loss, 3),
                "cause": cause,
                "tip": tip,
            })

    # ── Reference pace ────────────────────────────────────────────

    if best_dry_lap_s and best_dry_lap_s > 0:
        factor = _WET_FACTOR.get(condition, 1.0)
        briefing.reference_pace = {
            "best_dry_lap_s": round(best_dry_lap_s, 2),
            "condition_factor": factor,
            "estimated_target_s": round(best_dry_lap_s * factor, 2),
            "note": f"Target is ~{(factor - 1) * 100:.0f}% slower than dry best" if factor > 1.0 else "Dry conditions — target your PB",
        }

    return briefing


def _find_rubber_line_corners(
    surface: TrackSurface,
    corners: list[dict],
    threshold: float = 0.15,
) -> list[int]:
    """Identify corners with significant rubber deposit variation.

    A corner has a 'rubber line problem' when the grip variation across
    the width exceeds the threshold — meaning one lateral zone has
    substantially more rubber than another.
    """
    if surface.grip_2d is None:
        return []

    rubber_corners = []
    for corner in corners:
        s_apex = corner.get("s_apex", (corner.get("s_start", 0) + corner.get("s_end", 0)) / 2)
        s_idx = int(np.argmin(np.abs(surface.grip_2d.s_bins - s_apex)))

        profile = surface.grip_2d.mu_grid[s_idx, :]
        if profile.size < 3:
            continue

        mu_range = float(np.max(profile) - np.min(profile))
        if mu_range > threshold:
            rubber_corners.append(corner.get("corner_id", 0))

    return rubber_corners
