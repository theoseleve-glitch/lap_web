"""
track_surface/wet_model.py
--------------------------
Wet-condition grip model derived from dry grip data.

Key insight: the dry racing line (high mu in dry) is where rubber accumulates.
Rubber is hydrophobic — in the wet, the rubber line becomes the slipperiest
part of the track.  Clean asphalt off-line has better texture for water
drainage and thus better wet grip.

The wet model inverts the dry grip map to identify:
- Rubber-line danger zones (high dry mu → low wet grip)
- Preferred wet-line offsets per corner
- Compression zones where water pools
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from track_surface.frenet import FrenetFrame
from track_surface.grip_2d import GripSurface
from track_surface.model import TrackSurface

logger = logging.getLogger(__name__)

# Wet grip penalty on rubber line: rubber surface retains ~60-70% of clean
# asphalt grip when wet.  Higher dry mu (more rubber) → bigger penalty.
_RUBBER_WET_PENALTY = 0.35  # 35% grip reduction on heavy rubber
_CLEAN_ASPHALT_MU = 0.85    # baseline wet mu on clean asphalt


@dataclass
class WetLineShift:
    """Recommended line shift for a single corner in wet conditions."""
    corner_id: int
    s_start: float
    s_end: float
    s_apex: float
    dry_apex_n: float       # lateral offset of dry-optimal apex [m]
    wet_apex_n: float       # lateral offset of wet-preferred apex [m]
    shift_m: float          # magnitude of shift [m]
    shift_direction: str    # "inside" | "outside" | "none"
    rubber_severity: float  # 0-1, how much rubber is on the dry line here

    def to_dict(self) -> dict:
        return {
            "corner_id": self.corner_id,
            "s_start": round(self.s_start, 1),
            "s_end": round(self.s_end, 1),
            "dry_apex_n": round(self.dry_apex_n, 2),
            "wet_apex_n": round(self.wet_apex_n, 2),
            "shift_m": round(self.shift_m, 2),
            "shift_direction": self.shift_direction,
            "rubber_severity": round(self.rubber_severity, 2),
        }


@dataclass
class CompressionWarning:
    """Warning about a compression zone that may pool water in wet."""
    corner_id: int | None
    s_center: float
    vert_curvature: float   # kappa_v at this point
    dry_speed_bonus_pct: float  # how much grip the compression adds in dry
    wet_warning: str

    def to_dict(self) -> dict:
        return {
            "corner_id": self.corner_id,
            "s_center": round(self.s_center, 1),
            "vert_curvature": round(self.vert_curvature, 5),
            "dry_speed_bonus_pct": round(self.dry_speed_bonus_pct, 1),
            "wet_warning": self.wet_warning,
        }


def invert_grip_for_wet(grip_2d: GripSurface) -> np.ndarray:
    """Invert the dry grip map to estimate wet-preferred zones.

    Returns a (M, K) array where higher values = better wet grip.
    The inversion: areas with LOW dry sample density or LOW dry mu
    are preferred in wet (clean asphalt, off-rubber-line).
    """
    # Normalize dry mu to [0, 1] range
    mu = grip_2d.mu_grid
    mu_min = np.min(mu[mu > 0.1]) if np.any(mu > 0.1) else 0.5
    mu_max = np.max(mu) if mu.size > 0 else 1.5
    mu_range = max(mu_max - mu_min, 0.1)

    # Rubber intensity: how much rubber deposit relative to baseline
    rubber_intensity = np.clip((mu - mu_min) / mu_range, 0.0, 1.0)

    # Wet grip: clean asphalt baseline minus rubber penalty
    wet_grip = _CLEAN_ASPHALT_MU - rubber_intensity * _RUBBER_WET_PENALTY

    # Also factor in sample count: heavily-driven areas have more rubber
    count_norm = np.clip(grip_2d.count_grid / max(np.max(grip_2d.count_grid), 1), 0.0, 1.0)
    wet_grip -= count_norm * 0.1  # extra penalty for very heavily-driven areas

    return np.clip(wet_grip, 0.2, 1.0)


def compute_wet_line_shifts(
    surface: TrackSurface,
    corners: list[dict],
    dry_optimal_n: np.ndarray | None = None,
) -> list[WetLineShift]:
    """Compute recommended line shifts for each corner in wet conditions.

    For each corner, finds the lateral offset that maximizes wet grip
    (i.e., avoids the rubber line) while staying within track boundaries.
    """
    if surface.grip_2d is None:
        return []

    wet_grip = invert_grip_for_wet(surface.grip_2d)
    shifts = []

    for corner in corners:
        cid = corner.get("corner_id", 0)
        s_start = corner.get("s_start", 0.0)
        s_end = corner.get("s_end", 0.0)
        s_apex = corner.get("s_apex", (s_start + s_end) / 2.0)

        # Find the s-bin closest to the apex
        s_bins = surface.grip_2d.s_bins
        n_bins = surface.grip_2d.n_bins
        apex_s_idx = int(np.argmin(np.abs(s_bins - s_apex)))

        # Wet grip profile across the width at the apex
        wet_profile = wet_grip[apex_s_idx, :]
        dry_profile = surface.grip_2d.mu_grid[apex_s_idx, :]

        # Find dry-line apex (peak dry grip)
        dry_peak_idx = int(np.argmax(dry_profile))
        dry_apex_n = float(n_bins[dry_peak_idx])

        # Find wet-preferred apex (peak wet grip)
        # Constrain to within track boundaries if available
        if surface.has_boundaries:
            w_left_at_apex = float(np.interp(s_apex, surface.frenet.s_grid, surface.width_left))
            w_right_at_apex = float(np.interp(s_apex, surface.frenet.s_grid, surface.width_right))
            valid_n = (n_bins >= -w_right_at_apex) & (n_bins <= w_left_at_apex)
            if np.any(valid_n):
                wet_constrained = np.where(valid_n, wet_profile, -1.0)
                wet_peak_idx = int(np.argmax(wet_constrained))
            else:
                wet_peak_idx = int(np.argmax(wet_profile))
        else:
            wet_peak_idx = int(np.argmax(wet_profile))

        wet_apex_n = float(n_bins[wet_peak_idx])

        # Compute shift
        shift = wet_apex_n - dry_apex_n
        if abs(shift) < 0.3:
            direction = "none"
        elif shift > 0:
            direction = "outside" if corner.get("direction", "R") == "R" else "inside"
        else:
            direction = "inside" if corner.get("direction", "R") == "R" else "outside"

        # Rubber severity at the dry apex
        rubber_sev = float(np.clip(
            (dry_profile[dry_peak_idx] - dry_profile.min()) /
            max(dry_profile.max() - dry_profile.min(), 0.01),
            0.0, 1.0,
        ))

        shifts.append(WetLineShift(
            corner_id=cid,
            s_start=s_start,
            s_end=s_end,
            s_apex=s_apex,
            dry_apex_n=dry_apex_n,
            wet_apex_n=wet_apex_n,
            shift_m=abs(shift),
            shift_direction=direction,
            rubber_severity=rubber_sev,
        ))

    return shifts


def find_compression_warnings(
    surface: TrackSurface,
    corners: list[dict] | None = None,
    kv_threshold: float = 0.003,
) -> list[CompressionWarning]:
    """Identify compression zones that may pool water in wet conditions.

    Deep compressions (high positive kappa_v) add grip in dry but can
    collect standing water in wet — especially at high speed.
    """
    if not surface.has_vert_curvature:
        return []

    kv = surface.vert_curvature_1pm
    s = surface.frenet.s_grid
    warnings = []

    # Find peaks of vertical curvature above threshold
    for i in range(1, len(kv) - 1):
        if kv[i] > kv_threshold and kv[i] >= kv[i - 1] and kv[i] >= kv[i + 1]:
            s_center = float(s[i])

            # Estimate dry speed bonus at this compression
            # At reference speed ~50 m/s: bonus = v² * kv / g
            dry_bonus_pct = float((50.0 ** 2 * kv[i] / 9.81) * 100)

            # Find which corner this is in (if any)
            cid = None
            if corners:
                for c in corners:
                    if c.get("s_start", 0) <= s_center <= c.get("s_end", 0):
                        cid = c.get("corner_id")
                        break

            warnings.append(CompressionWarning(
                corner_id=cid,
                s_center=s_center,
                vert_curvature=float(kv[i]),
                dry_speed_bonus_pct=dry_bonus_pct,
                wet_warning=f"Compression adds {dry_bonus_pct:.0f}% grip in dry — "
                            f"may pool water in wet. Brake {max(5, int(dry_bonus_pct))}m earlier.",
            ))

    return warnings
