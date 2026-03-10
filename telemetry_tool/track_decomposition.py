"""Track decomposition engine.

Segments a track into typed sections (straights, corners, transitions)
using GPS-derived curvature, speed profiles, and the corner classifier.

Replaces ad-hoc corner detection with a full track decomposition that
assigns every metre of track to a named section.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from corner_classifier import classify_corner
from corner_focus import score_exit_importance

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_COL_LAT = "Latitude"
_COL_LON = "Longitude"
_COL_SPEED = "Speed (m/s)"
_COL_DIST = "Distance (m)"

_DEFAULT_CURV_THRESHOLD: float = 0.008   # 1/m — radius < 125 m is corner
_DEFAULT_SMOOTH_HALF_WINDOW: int = 15
_MIN_STRAIGHT_LENGTH_M: float = 50.0
_DEFAULT_MERGE_GAP_M: float = 30.0
_MIN_CORNER_LENGTH_M: float = 15.0


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class TrackSection:
    """A contiguous section of track."""
    section_id: int
    section_type: str                        # "straight" | "corner" | "transition"
    corner_type: Optional[str]               # from corner_classifier
    s_start: float                           # distance (m)
    s_end: float
    direction: Optional[str]                 # "L" | "R" | None for straights
    geometric_apex: Optional[float]          # distance at max curvature
    exit_importance: float                   # 0.0–1.0
    sub_corners: Optional[list[dict]] = None  # for compound/chicane

    def to_dict(self) -> dict:
        return {
            "section_id": self.section_id,
            "section_type": self.section_type,
            "corner_type": self.corner_type,
            "s_start": self.s_start,
            "s_end": self.s_end,
            "direction": self.direction,
            "geometric_apex": self.geometric_apex,
            "exit_importance": self.exit_importance,
            "sub_corners": self.sub_corners,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _gaussian_smooth(signal: np.ndarray, half_window: int) -> np.ndarray:
    """Gaussian-weighted symmetric rolling average."""
    if half_window <= 0 or len(signal) < 3:
        return signal.copy()

    k = 2 * half_window + 1
    x = np.arange(k) - half_window
    w = np.exp(-0.5 * (x / max(half_window / 2.0, 0.5)) ** 2)
    w /= w.sum()

    pad = np.pad(signal, half_window, mode="reflect")
    out = np.convolve(pad, w, mode="valid")
    return out[: len(signal)]


def _compute_curvature(
    lats: np.ndarray,
    lons: np.ndarray,
    distances: np.ndarray,
) -> np.ndarray:
    """Compute signed curvature from GPS coordinates.

    Converts lat/lon to local XY (flat-earth approximation), then uses the
    Frenet–Serret formula:  kappa = (x'y'' - y'x'') / (x'^2 + y'^2)^(3/2)
    """
    # Convert to metres (flat-earth)
    lat_ref = lats[0]
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * np.cos(np.radians(lat_ref))

    x = (lons - lons[0]) * m_per_deg_lon
    y = (lats - lats[0]) * m_per_deg_lat

    ds = np.diff(distances)
    ds = np.where(ds > 0, ds, 1e-9)

    dx = np.diff(x)
    dy = np.diff(y)
    xd = dx / ds
    yd = dy / ds

    # Second derivatives
    xd_mid = 0.5 * (xd[:-1] + xd[1:])
    yd_mid = 0.5 * (yd[:-1] + yd[1:])
    ds_mid = 0.5 * (ds[:-1] + ds[1:])
    ds_mid = np.where(ds_mid > 0, ds_mid, 1e-9)

    xdd = np.diff(xd) / ds_mid
    ydd = np.diff(yd) / ds_mid

    denom = (xd_mid ** 2 + yd_mid ** 2) ** 1.5
    with np.errstate(divide="ignore", invalid="ignore"):
        kappa = np.where(denom > 0, (xd_mid * ydd - yd_mid * xdd) / denom, 0.0)

    # Pad to original length
    kappa_full = np.zeros(len(lats))
    kappa_full[1:-1] = kappa
    if len(kappa) > 0:
        kappa_full[0] = kappa[0]
        kappa_full[-1] = kappa[-1]

    return kappa_full


def _compute_heading(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Heading in radians at each point (atan2-based)."""
    dx = np.diff(x)
    dy = np.diff(y)
    headings = np.arctan2(dy, dx)
    # Pad last element
    return np.concatenate([headings, [headings[-1]]])


def _segment_by_curvature(
    distances: np.ndarray,
    curvatures: np.ndarray,
    speeds: np.ndarray,
    threshold: float = _DEFAULT_CURV_THRESHOLD,
) -> list[dict]:
    """Classify each point as corner or straight, then group into raw segments.

    A straight must be sustained for at least _MIN_STRAIGHT_LENGTH_M.
    """
    n = len(distances)
    abs_curv = np.abs(curvatures)

    # Label each point
    is_corner = abs_curv >= threshold

    # Build raw runs
    segments: list[dict] = []
    i = 0
    while i < n:
        stype = "corner" if is_corner[i] else "straight"
        j = i + 1
        while j < n and is_corner[j] == is_corner[i]:
            j += 1
        seg_len = distances[min(j, n - 1)] - distances[i]

        # Short straights embedded between corners get absorbed as corners
        if stype == "straight" and seg_len < _MIN_STRAIGHT_LENGTH_M:
            stype = "corner"

        segments.append({
            "type": stype,
            "idx_start": i,
            "idx_end": min(j - 1, n - 1),
            "s_start": float(distances[i]),
            "s_end": float(distances[min(j - 1, n - 1)]),
        })
        i = j

    # Merge adjacent segments of same type
    merged: list[dict] = []
    for seg in segments:
        if merged and merged[-1]["type"] == seg["type"]:
            merged[-1]["idx_end"] = seg["idx_end"]
            merged[-1]["s_end"] = seg["s_end"]
        else:
            merged.append(dict(seg))

    # Filter out very short corners
    result: list[dict] = []
    for seg in merged:
        seg_len = seg["s_end"] - seg["s_start"]
        if seg["type"] == "corner" and seg_len < _MIN_CORNER_LENGTH_M:
            seg["type"] = "straight"
        result.append(seg)

    # Re-merge after reclassification
    final: list[dict] = []
    for seg in result:
        if final and final[-1]["type"] == seg["type"]:
            final[-1]["idx_end"] = seg["idx_end"]
            final[-1]["s_end"] = seg["s_end"]
        else:
            final.append(dict(seg))

    return final


def _merge_close_corners(
    segments: list[dict],
    merge_gap_m: float = _DEFAULT_MERGE_GAP_M,
) -> list[dict]:
    """Merge corners separated by < merge_gap_m of straight into compound/chicane."""
    if len(segments) < 3:
        return segments

    merged: list[dict] = []
    i = 0
    while i < len(segments):
        seg = dict(segments[i])
        if seg["type"] == "corner":
            # Look ahead: corner - short_straight - corner → merge
            while (i + 2 < len(segments)
                   and segments[i + 1]["type"] == "straight"
                   and segments[i + 2]["type"] == "corner"
                   and (segments[i + 1]["s_end"] - segments[i + 1]["s_start"]) < merge_gap_m):
                seg["idx_end"] = segments[i + 2]["idx_end"]
                seg["s_end"] = segments[i + 2]["s_end"]
                seg["merged"] = True
                i += 2
        merged.append(seg)
        i += 1

    return merged


def _classify_segments(
    segments: list[dict],
    curvatures: np.ndarray,
    speeds: np.ndarray,
    distances: np.ndarray,
    lats: np.ndarray,
    lons: np.ndarray,
) -> list[TrackSection]:
    """Classify each segment and build TrackSection objects."""
    # Pre-compute local XY for heading
    lat_ref = lats[0]
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * np.cos(np.radians(lat_ref))
    x = (lons - lons[0]) * m_per_deg_lon
    y = (lats - lats[0]) * m_per_deg_lat
    headings = _compute_heading(x, y)

    # Compute straight speed reference (median of straight segment speeds)
    straight_speeds = []
    for seg in segments:
        if seg["type"] == "straight":
            i0, i1 = seg["idx_start"], seg["idx_end"] + 1
            straight_speeds.extend(speeds[i0:i1].tolist())
    straight_speed = float(np.median(straight_speeds)) if straight_speeds else float(np.max(speeds))

    sections: list[TrackSection] = []
    for idx, seg in enumerate(segments):
        i0 = seg["idx_start"]
        i1 = seg["idx_end"] + 1  # exclusive

        seg_dists = distances[i0:i1]
        seg_curvs = curvatures[i0:i1]
        seg_speeds = speeds[i0:i1]

        s_start = seg["s_start"]
        s_end = seg["s_end"]

        if seg["type"] == "corner":
            # Direction from total heading change
            heading_change = float(np.sum(np.diff(headings[i0:i1])))
            # Wrap heading changes to [-pi, pi]
            dh = np.diff(headings[i0:i1])
            dh = (dh + np.pi) % (2 * np.pi) - np.pi
            total_heading = float(np.sum(dh))

            direction = "R" if total_heading < 0 else "L"

            # Geometric apex: point of max absolute curvature
            if len(seg_curvs) > 0:
                apex_idx = int(np.argmax(np.abs(seg_curvs)))
                geometric_apex = float(seg_dists[apex_idx])
            else:
                geometric_apex = None

            # Count curvature peaks for classification
            abs_c = np.abs(seg_curvs)
            peak_threshold = np.max(abs_c) * 0.5 if len(abs_c) > 0 else 0
            n_peaks = 1
            if len(abs_c) > 4:
                above = abs_c > peak_threshold
                # Count transitions from below to above
                transitions = np.diff(above.astype(int))
                n_peaks = max(1, int(np.sum(transitions == 1)))

            # Direction changes within segment
            signs = np.sign(seg_curvs)
            sign_changes = int(np.sum(np.abs(np.diff(signs[signs != 0])) > 0))
            direction_changes = sign_changes

            # Total heading change in degrees
            total_heading_deg = float(np.abs(np.degrees(total_heading)))

            # Classify via corner_classifier
            classification = classify_corner(
                seg_dists,
                seg_curvs,
                seg_speeds,
                direction_changes=direction_changes,
                n_peaks=n_peaks,
                total_heading_change=total_heading_deg,
                straight_speed_mps=straight_speed,
            )
            corner_type = classification.corner_type

            # Sub-corners for merged segments
            sub_corners = None
            if seg.get("merged"):
                sub_corners = [{"s_start": s_start, "s_end": s_end}]

        else:
            # Straight
            direction = None
            geometric_apex = None
            corner_type = None
            sub_corners = None

        # Exit importance: distance to next corner
        next_straight_length = 0.0
        if seg["type"] == "corner":
            # Find following straight length
            for j in range(idx + 1, len(segments)):
                if segments[j]["type"] == "straight":
                    next_straight_length = segments[j]["s_end"] - segments[j]["s_start"]
                    break
            exit_imp = score_exit_importance(next_straight_length)
        else:
            # For straights: importance based on own length (how much exit speed matters)
            own_length = s_end - s_start
            exit_imp = score_exit_importance(own_length)

        sections.append(TrackSection(
            section_id=0,  # assigned later
            section_type=seg["type"],
            corner_type=corner_type,
            s_start=s_start,
            s_end=s_end,
            direction=direction,
            geometric_apex=geometric_apex,
            exit_importance=exit_imp,
            sub_corners=sub_corners,
        ))

    # Assign sequential IDs
    for i, sec in enumerate(sections):
        sec.section_id = i + 1

    return sections


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def decompose_track(
    df: pd.DataFrame,
    *,
    curvature_threshold: float = _DEFAULT_CURV_THRESHOLD,
    smooth_half_window: int = _DEFAULT_SMOOTH_HALF_WINDOW,
    merge_gap_m: float = _DEFAULT_MERGE_GAP_M,
) -> list[TrackSection]:
    """Decompose a track into typed sections from telemetry data.

    Parameters
    ----------
    df : DataFrame with columns: Latitude, Longitude, Speed (m/s), Distance (m).
    curvature_threshold : curvature above which a section is considered a corner.
    smooth_half_window : half-window for Gaussian smoothing of curvature.
    merge_gap_m : corners closer than this are merged.

    Returns
    -------
    List of TrackSection covering the full track.
    """
    required = [_COL_LAT, _COL_LON, _COL_SPEED, _COL_DIST]
    for col in required:
        if col not in df.columns:
            logger.warning("Missing column %s — returning empty", col)
            return []

    if len(df) < 5:
        return []

    lats = df[_COL_LAT].to_numpy(dtype=float)
    lons = df[_COL_LON].to_numpy(dtype=float)
    speeds = df[_COL_SPEED].to_numpy(dtype=float)
    distances = df[_COL_DIST].to_numpy(dtype=float)

    # 1. Compute curvature
    raw_curvature = _compute_curvature(lats, lons, distances)

    # 2. Smooth
    curvature = _gaussian_smooth(raw_curvature, smooth_half_window)

    # Replace any NaNs with 0
    curvature = np.nan_to_num(curvature, nan=0.0)

    # 3. Segment by curvature
    segments = _segment_by_curvature(distances, curvature, speeds, curvature_threshold)

    # 4. Merge close corners
    segments = _merge_close_corners(segments, merge_gap_m)

    # 5. Classify segments
    sections = _classify_segments(segments, curvature, speeds, distances, lats, lons)

    return sections
