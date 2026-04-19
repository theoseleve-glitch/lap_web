"""Map handling event patterns to kart/car setup change recommendations.

Rule-based lookup: groups fused handling events by (event_type, zone),
ranks patterns by frequency * confidence * severity, then returns
prioritized setup changes from a domain knowledge base.
"""
from __future__ import annotations

from collections import defaultdict

_SEVERITY_WEIGHT = {"severe": 3.0, "moderate": 2.0, "mild": 1.0, "none": 0.0}

# ── Knowledge bases ──────────────────────────────────────────────────

_KART_KB: dict[tuple[str, str], list[str]] = {
    ("understeer", "entry"): [
        "Increase front caster angle (adds front mechanical trail)",
        "Soften front axle / stiffen rear axle (transfers weight to front on turn-in)",
        "Narrow rear track width (reduces rear grip, helps rotation)",
        "Lower front ride height (increases front grip via CG shift)",
        "Check front tire pressures (too high = less grip)",
    ],
    ("understeer", "mid"): [
        "Increase overall caster",
        "Widen front track width (more front lateral grip)",
        "Soften front bar if applicable",
        "Check front tire compound (may need softer)",
    ],
    ("oversteer", "exit"): [
        "Stiffen rear axle (reduces rear flex under power)",
        "Widen rear track width (more rear grip)",
        "Raise rear ride height (increases rear weight transfer)",
        "Check rear tire pressures (too low = overheating)",
        "Reduce engine torque if adjustable (less power oversteer)",
    ],
    ("oversteer", "entry"): [
        "Reduce front caster (less aggressive turn-in)",
        "Stiffen front / soften rear (less rotation on entry)",
        "Widen rear track width",
        "Check rear tire temperatures (could be cold/hard)",
    ],
    ("oversteer", "mid"): [
        "Widen rear track width",
        "Stiffen rear axle",
        "Lower CG if possible",
        "Check chassis alignment",
    ],
}

_CAR_KB: dict[tuple[str, str], list[str]] = {
    ("understeer", "entry"): [
        "Check front tire pressures (reduce if too high)",
        "Stiffen front anti-roll bar",
        "Add front negative camber",
    ],
    ("understeer", "mid"): [
        "Soften front springs or add front camber",
        "Check front tire compound",
    ],
    ("oversteer", "exit"): [
        "Reduce rear anti-roll bar stiffness",
        "Add rear wing downforce (if aero car)",
        "Check differential preload / ramp settings",
    ],
    ("oversteer", "entry"): [
        "Increase rear anti-roll bar stiffness",
        "Reduce front anti-roll bar",
        "Check rear tire pressures",
    ],
    ("oversteer", "mid"): [
        "Stiffen rear springs",
        "Add rear downforce (if aero car)",
    ],
}


def recommend_setup_changes(
    events: list[dict], vehicle_class: str = "kart",
) -> dict:
    """Generate prioritized setup recommendations from fused handling events.

    Args:
        events: List of ``FusedEvent.to_dict()`` outputs.
        vehicle_class: ``"kart"`` or ``"car"``.

    Returns:
        Dict with ``n_events_analyzed``, ``primary_issue``,
        ``recommendations``, and ``summary``.
    """
    if not events:
        return {
            "n_events_analyzed": 0,
            "primary_issue": "none",
            "recommendations": [],
            "summary": "No handling events detected.",
        }

    # ── 1. Group by (event_type, zone) ────────────────────────────────
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for ev in events:
        et = ev.get("event_type", "neutral")
        zone = ev.get("corner_phase", "mid")
        if et in ("understeer", "oversteer"):
            groups[(et, zone)].append(ev)

    if not groups:
        return {
            "n_events_analyzed": len(events),
            "primary_issue": "balanced",
            "recommendations": [],
            "summary": "Handling is balanced — no dominant understeer or oversteer pattern.",
        }

    # ── 2. Score each pattern: frequency * avg_confidence * avg_severity
    scored: list[tuple[float, tuple[str, str], list[dict]]] = []
    for key, evts in groups.items():
        freq = len(evts)
        avg_conf = sum(e.get("confidence", 0) for e in evts) / freq
        avg_sev = sum(_SEVERITY_WEIGHT.get(e.get("severity", "none"), 0) for e in evts) / freq
        score = freq * avg_conf * max(avg_sev, 0.5)
        scored.append((score, key, evts))
    scored.sort(key=lambda t: t[0], reverse=True)

    # ── 3. Build recommendations for top 3 patterns ───────────────────
    kb = _CAR_KB if vehicle_class == "car" else _KART_KB
    recommendations: list[dict] = []
    priority = 1

    for _score, (et, zone), evts in scored[:3]:
        changes = kb.get((et, zone), [])
        if not changes:
            continue
        corners = sorted({e["corner_id"] for e in evts})
        avg_conf = sum(e.get("confidence", 0) for e in evts) / len(evts)
        reason = (
            f"{et.capitalize()} detected at {len(corners)} corner(s) on {zone} "
            f"(avg confidence {avg_conf:.0%})"
        )
        for change in changes:
            recommendations.append({
                "priority": priority,
                "change": change,
                "reason": reason,
                "affected_corners": corners,
            })
        priority += 1

    primary_et, primary_zone = scored[0][1]
    primary_issue = f"{primary_zone}_{primary_et}"

    # ── 4. Human-readable summary ─────────────────────────────────────
    top_evts = scored[0][2]
    top_corners = sorted({e["corner_id"] for e in top_evts})
    corner_str = ", ".join(str(c) for c in top_corners)
    first_change = recommendations[0]["change"] if recommendations else "review setup"

    summary = (
        f"The {vehicle_class} shows {primary_et} on {primary_zone} at "
        f"turn(s) {corner_str}. Primary recommendation: {first_change.split('(')[0].strip().lower()}."
    )

    return {
        "n_events_analyzed": len(events),
        "primary_issue": primary_issue,
        "recommendations": recommendations,
        "summary": summary,
    }
