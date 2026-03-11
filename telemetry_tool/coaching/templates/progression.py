"""Multi-session progression text templates."""
from __future__ import annotations

# Keys: (trend_direction, metric_category)
# trend_direction: "improving", "plateau", "regressing"
# metric_category: "apex_speed", "exit_speed", "brake_point", "consistency", "general"

PROGRESSION_TEMPLATES: dict[tuple[str, str], list[str]] = {
    ("improving", "apex_speed"): [
        "Your apex speed at {corner_name} has increased {delta_kmh:.1f} km/h over {sessions} sessions — clear improvement. At this rate, you'll reach the target in approximately {eta_sessions} more sessions.",
        "Steady progress on apex speed: +{delta_kmh:.1f} km/h across {sessions} sessions. The technique changes are taking hold.",
    ],
    ("improving", "exit_speed"): [
        "Exit speed at {corner_name} is trending up: +{delta_kmh:.1f} km/h over {sessions} sessions. That's translating into real straight-line time gains.",
        "Your exit speed improvements are compounding — each session gets a bit more. {delta_kmh:.1f} km/h gained so far.",
    ],
    ("improving", "brake_point"): [
        "Your brake point at {corner_name} has moved {delta_m:.0f}m closer to the optimal over {sessions} sessions. The confidence is building naturally.",
    ],
    ("improving", "consistency"): [
        "Consistency improving: your lap time variation has dropped from {old_std:.2f}s to {new_std:.2f}s over {sessions} sessions. The technique is consolidating.",
    ],
    ("improving", "general"): [
        "Clear upward trajectory across the last {sessions} sessions. Keep the focus narrow and the improvements will continue.",
    ],
    ("plateau", "apex_speed"): [
        "Your apex speed at {corner_name} has stabilized around {current_kmh:.1f} km/h for the last {sessions} sessions. This might mean: (a) you've found the limit, or (b) a technique change is needed to break through. Try the drill below.",
        "Apex speed plateau at {current_kmh:.1f} km/h — this is common when one technique compensates for another. Focus on the root cause, not the speed number.",
    ],
    ("plateau", "exit_speed"): [
        "Exit speed has plateaued at {current_kmh:.1f} km/h. Check: is your throttle application early enough? Is your line opening up the exit?",
    ],
    ("plateau", "brake_point"): [
        "Brake point hasn't changed in {sessions} sessions. You may need a confidence-building drill to push past the current comfort zone.",
    ],
    ("plateau", "consistency"): [
        "Consistency has leveled off at {current_std:.2f}s variation. This is a good foundation — now you can safely push for speed without losing the repeatability.",
    ],
    ("plateau", "general"): [
        "Performance has plateaued. This is normal — it means the easy gains are done. The next improvement requires a specific technique change, not just more laps.",
    ],
    ("regressing", "apex_speed"): [
        "Apex speed at {corner_name} has dropped {delta_kmh:.1f} km/h over the last {sessions} sessions. This could be a confidence dip, fatigue, or a line change that isn't working. Consider a 'late apex reset' — go back to basics.",
    ],
    ("regressing", "exit_speed"): [
        "Exit speed trending down at {corner_name}. Check if a line change has inadvertently tightened the exit. Sometimes trying to carry more entry speed costs exit speed.",
    ],
    ("regressing", "brake_point"): [
        "Your brake point has moved earlier by {delta_m:.0f}m. If this was deliberate (working on trail braking), that's fine. If not, check if confidence has dipped.",
    ],
    ("regressing", "consistency"): [
        "Consistency has worsened from {old_std:.2f}s to {new_std:.2f}s. This often happens when changing technique — the old pattern is disrupted before the new one is solid. Stay the course.",
    ],
    ("regressing", "general"): [
        "Some areas have regressed slightly. Don't panic — this is often a sign of technique change in progress. The dip before the rise is normal.",
    ],
}
