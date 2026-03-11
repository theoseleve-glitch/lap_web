"""Confidence framer — rewrites weaknesses as strengths-in-progress."""
from __future__ import annotations

from telemetry_tool.coaching.templates.confidence_frames import CONFIDENCE_FRAMES


def reframe_strengths(
    strengths_raw: list[str],
    weaknesses_raw: list[str],
    root_causes: list[str],
    corner_names: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Reframe raw strengths/weaknesses using confidence psychology.

    Returns:
        (enhanced_strengths, reframed_weaknesses)
    """
    enhanced_strengths = list(strengths_raw)
    reframed_weaknesses: list[str] = []

    corner_name = corner_names[0] if corner_names else "the target corner"

    for i, weakness in enumerate(weaknesses_raw):
        root = root_causes[i] if i < len(root_causes) else "technique"
        frame = CONFIDENCE_FRAMES.get(root, CONFIDENCE_FRAMES.get("technique", {}))

        if frame:
            reframed = frame.get("reframe", weakness)
            try:
                reframed = reframed.format(corner_name=corner_name)
            except (KeyError, IndexError):
                pass
            reframed_weaknesses.append(reframed)

            encouragement = frame.get("encouragement", "")
            if encouragement and i == 0:
                enhanced_strengths.append(encouragement)
        else:
            reframed_weaknesses.append(weakness)

    return enhanced_strengths, reframed_weaknesses
