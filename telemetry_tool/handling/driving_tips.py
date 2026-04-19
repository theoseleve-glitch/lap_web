"""Generate driving-style tips for handling events.

Unlike setup recommendations (which change the kart), these tell the
driver what to do differently. This is the primary actionable for most
drivers — setup changes are only relevant at high skill levels.
"""
from __future__ import annotations


# Driving tips indexed by (event_type, zone)
_TIPS = {
    ("understeer", "entry"): [
        "Brake earlier to let the kart rotate before the apex",
        "Trail brake deeper into the corner to keep weight on the front",
        "Turn in more progressively — aggressive input overloads the front tyres",
    ],
    ("understeer", "mid"): [
        "Carry slightly less speed into the apex",
        "Maintain a light throttle through the apex to keep the kart balanced",
        "Look further ahead through the corner — eyes lead the kart",
    ],
    ("understeer", "exit"): [
        "Be patient with throttle application on exit",
        "Unwind steering gradually — snapping it straight loads the front",
        "Focus on a later apex to straighten the exit line",
    ],
    ("oversteer", "entry"): [
        "Release the brake more gradually before turn-in",
        "Reduce trail braking depth — the rear is unloading too much",
        "Turn in slightly later to keep the kart straighter under braking",
    ],
    ("oversteer", "mid"): [
        "Keep steering inputs smooth — avoid sudden corrections",
        "Maintain a constant throttle through the apex, don't lift",
        "Avoid abrupt weight transfers mid-corner",
    ],
    ("oversteer", "exit"): [
        "Apply throttle more gradually — the rear tyres are spinning up",
        "Wait until the kart is straighter before going to full throttle",
        "Unwind steering before applying power to avoid snap oversteer",
    ],
}


def generate_driving_tips(events: list[dict], max_tips: int = 3) -> list[dict]:
    """Generate driving tips from handling events.

    Returns a list of tips sorted by event impact, each with:
      - corner_number: which corner
      - tip: the driving advice
      - type: "understeer" or "oversteer"
      - zone: "entry", "mid", "exit"
    """
    if not events:
        return []

    # Sort events by impact (confidence × magnitude)
    scored = []
    for ev in events:
        conf = ev.get("confidence", ev.get("magnitude", 0))
        direction = abs(ev.get("direction", 0))
        impact = conf * direction
        scored.append((impact, ev))

    scored.sort(key=lambda x: -x[0])

    tips = []
    seen_corners = set()

    for impact, ev in scored:
        corner = ev.get("corner_id", 0)
        if corner in seen_corners:
            continue  # one tip per corner

        etype = ev.get("event_type", "neutral")
        zone = ev.get("corner_phase", "mid")
        tip_list = _TIPS.get((etype, zone), [])

        if not tip_list:
            continue

        # Pick the first tip (most impactful advice)
        tips.append({
            "corner_number": corner + 1,
            "tip": tip_list[0],
            "type": etype,
            "zone": zone,
        })
        seen_corners.add(corner)

        if len(tips) >= max_tips:
            break

    return tips
