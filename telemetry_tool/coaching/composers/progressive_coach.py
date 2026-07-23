"""Progressive coach — generates session-to-session goals, warm-up protocol, late apex reset."""
from __future__ import annotations

from coaching.models import (
    FocusArea, WarmUpProtocol, CornerTrend,
)


def generate_warm_up(focus_areas: list[FocusArea], vehicle_class: str = "car") -> WarmUpProtocol:
    """Generate a 3-phase warm-up protocol based on session focus areas."""
    if vehicle_class == "kart":
        phase_1_laps = 2
        phase_1 = "2 easy laps: explore the track surface, feel the grip level, let the tyres come up to temperature. 60% pace."
        phase_2_laps = 2
        phase_2 = "2 build laps: increase to 80% pace. Focus on hitting your brake markers and reference points."
    else:
        phase_1_laps = 3
        phase_1 = "3 easy laps: bring tyres and brakes up to temperature. 60% pace, smooth inputs. Feel the car's balance."
        phase_2_laps = 2
        phase_2 = "2 build laps: increase to 85% pace. Check brake points, confirm reference points are visible."

    if focus_areas:
        focus_corners = []
        for fa in focus_areas[:2]:
            focus_corners.extend(fa.corner_ids[:2])
        corner_list = ", ".join(f"T{c}" for c in focus_corners[:4])
        phase_3 = f"Push to 95% — focus specifically on {corner_list}. Apply today's key drill at those corners."
    else:
        phase_3 = "Push to full pace. Drive clean, consistent laps."

    return WarmUpProtocol(
        phase_1_laps=phase_1_laps,
        phase_1_instruction=phase_1,
        phase_2_laps=phase_2_laps,
        phase_2_instruction=phase_2,
        phase_3_instruction=phase_3,
    )


def generate_next_session_goals(
    focus_areas: list[FocusArea],
    trends: list[CornerTrend] | None = None,
) -> list[str]:
    """Generate 2-4 specific goals for the next session."""
    goals: list[str] = []

    for fa in focus_areas[:2]:
        if fa.progressive_steps and len(fa.progressive_steps) >= 1:
            goals.append(f"Work on {fa.category}: {fa.progressive_steps[0]}")
        else:
            goals.append(f"Focus on {fa.category} at corners {', '.join(f'T{c}' for c in fa.corner_ids[:3])}")

    if trends:
        improving = [t for t in trends if t.trend_direction == "improving"]
        if improving:
            goals.append(f"Continue the momentum — your {improving[0].trend_text.lower()}")

        regressing = [t for t in trends if t.trend_direction == "regressing"]
        if regressing:
            goals.append(f"Attention needed: {regressing[0].trend_text}")

    if not goals:
        goals.append("Drive 5 clean, consistent laps at 90% pace to build a baseline")

    return goals[:4]


def generate_late_apex_reset(
    trends: list[CornerTrend] | None = None,
) -> str | None:
    """Generate a late apex reset instruction if regression is detected.

    The 'late apex reset' is a coaching book technique: when a driver
    is regressing, go back to deliberately late apex lines to rebuild
    the correct exit-speed-first mindset.
    """
    if not trends:
        return None

    regressing = [t for t in trends if t.trend_direction == "regressing"]
    if len(regressing) >= 2:
        return (
            "Multiple corners are regressing. Time for a Late Apex Reset: "
            "for the next 3 laps, deliberately apex 2m later than your current "
            "line at every corner. This will feel slow through the middle but "
            "will rebuild your exit speed foundation. Once exit speeds recover, "
            "gradually bring the apex back to the optimal point."
        )

    return None
