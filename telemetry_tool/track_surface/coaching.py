"""
track_surface/coaching.py
-------------------------
Generate spatial coaching messages from line delta analysis.

Translates CornerLineLoss data into human-readable, actionable coaching
text that references physical positions on the track.
"""
from __future__ import annotations

from track_surface.line_delta import CornerLineLoss
from track_surface.model import TrackSurface


def _format_direction(error_m: float) -> str:
    """Convert apex error to 'earlier'/'later' instruction."""
    if error_m > 0:
        return f"{abs(error_m):.1f}m later"
    return f"{abs(error_m):.1f}m earlier"


def generate_spatial_coaching(
    corner_losses: list[CornerLineLoss],
    surface: TrackSurface,
    min_loss_s: float = 0.05,
) -> list[dict]:
    """Generate human-readable spatial coaching per corner.

    Parameters
    ----------
    corner_losses : from decompose_corner_losses().
    surface : TrackSurface for boundary data.
    min_loss_s : ignore corners with less than this total loss.

    Returns
    -------
    List of coaching dicts with corner_id, total_loss, components, and text.
    """
    results = []

    for cl in corner_losses:
        if cl.total_loss_s < min_loss_s:
            continue

        tips = []

        # Apex position
        if abs(cl.apex_error_m) > 0.5:
            tips.append(f"Move apex {_format_direction(cl.apex_error_m)}")

        # Exit width usage
        if surface.has_boundaries and abs(cl.exit_error_m) > 1.0:
            tips.append(f"Use more track width on exit ({abs(cl.exit_error_m):.1f}m unused)")

        # Dominant loss type
        if cl.line_loss_s > cl.speed_loss_s and cl.line_loss_s > 0.05:
            tips.append(
                f"Line costs {cl.line_loss_s:.2f}s — "
                "biggest gain here is position, not speed"
            )
        elif cl.speed_loss_s > 0.1:
            speed_delta_kph = cl.speed_loss_s * 50  # rough approximation
            tips.append(f"Carry ~{speed_delta_kph:.0f} kph more mid-corner")

        # Entry line
        if abs(cl.entry_error_m) > 1.5:
            if cl.entry_error_m > 0:
                tips.append(f"Entry {cl.entry_error_m:.1f}m too wide — tighten turn-in")
            else:
                tips.append(f"Entry {abs(cl.entry_error_m):.1f}m too tight — widen approach")

        coaching_text = ". ".join(tips) + "." if tips else "On-line — minor refinement only."

        # Update the CornerLineLoss suggestion field
        cl.suggestion = coaching_text

        results.append({
            "corner_id": cl.corner_id,
            "total_loss_s": round(cl.total_loss_s, 3),
            "line_loss_s": round(cl.line_loss_s, 3),
            "speed_loss_s": round(cl.speed_loss_s, 3),
            "apex_error_m": round(cl.apex_error_m, 2),
            "coaching": coaching_text,
        })

    return results
