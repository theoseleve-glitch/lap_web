"""Session narrative templates — grade-band × theme combinations."""
from __future__ import annotations

# Keys: (grade_band, theme)
# grade_band: "S-A", "B-C", "D-F"
# theme: "pace", "consistency", "technique", "improvement", "general"
# Values: list of variant strings with {placeholders}

SESSION_NARRATIVES: dict[tuple[str, str], list[str]] = {
    # ── S-A band (excellent) ──
    ("S-A", "pace"): [
        "Outstanding pace today. Your raw speed is at the sharp end — {time_delta_s:.2f}s off theoretical shows you're extracting most of what the {vehicle_class} has to offer. The focus now shifts from finding speed to making it repeatable.",
        "Impressive speed. You're consistently within {time_delta_s:.2f}s of the theoretical optimum. At this level, gains come from the margins — exit speed optimization and braking point precision.",
    ],
    ("S-A", "consistency"): [
        "Your consistency is a real strength — {std_dev_s:.2f}s variation across {clean_laps} clean laps shows strong technical consolidation. This kind of repeatability is what separates quick drivers from fast ones.",
        "Metronome-like consistency today. {std_dev_s:.2f}s standard deviation tells the story — you've built this track into muscle memory. Time to push the envelope slightly to find the next tenth.",
    ],
    ("S-A", "technique"): [
        "Technically excellent session. Your inputs are clean and your weight management shows real understanding of the {vehicle_class}'s dynamics. {primary_strength} is particularly strong.",
        "Very polished driving. The data shows smooth input transitions and efficient grip usage. Your {primary_strength} stands out as a real asset.",
    ],
    ("S-A", "improvement"): [
        "Clear improvement from your previous sessions. The progression in {improved_area} shows your practice is paying off. You've moved from working on it to owning it.",
    ],
    ("S-A", "general"): [
        "Strong session overall. You're driving at a level where small refinements yield the remaining gains. Let's focus on the 1-2 areas where tenths are still hiding.",
    ],

    # ── B-C band (good, room for improvement) ──
    ("B-C", "pace"): [
        "Solid pace with clear room to grow. You're {time_delta_s:.2f}s off theoretical — that gap is addressable through the focus areas below. Most of it comes from {primary_weakness}.",
        "Good speed foundation. The {time_delta_s:.2f}s gap to theoretical is mainly concentrated in {corner_count} corners. Fix those and you'll see a meaningful lap time drop.",
    ],
    ("B-C", "consistency"): [
        "Your consistency is developing — {std_dev_s:.2f}s variation shows you're building the right habits. The occasional outlier lap suggests concentration dips in certain sections.",
        "Consistency is your next unlock. {std_dev_s:.2f}s variation means some laps are great and some leave time on the table. Narrowing that band is worth more than raw speed right now.",
    ],
    ("B-C", "technique"): [
        "Good technical foundation with specific areas to polish. Your {primary_strength} is working well, but {primary_weakness} is costing you time at {corner_count} corners.",
        "The technique is there in places — particularly {primary_strength}. Applying that same approach to {primary_weakness} will close the gap significantly.",
    ],
    ("B-C", "improvement"): [
        "Positive trajectory. Your {improved_area} has improved noticeably, and maintaining that trend will pull your overall times down. Keep the focus narrow and deliberate.",
    ],
    ("B-C", "general"): [
        "A productive session with clear takeaways. You have genuine speed — the task now is cleaning up the areas that give time back. Focus on the top 2 items below.",
    ],

    # ── D-F band (developing, significant gaps) ──
    ("D-F", "pace"): [
        "There's meaningful time to find, and that's actually good news — the gains available to you are larger than what faster drivers are chasing. {time_delta_s:.2f}s off theoretical means big improvements are within reach through the fundamentals.",
        "Don't be discouraged by the gap to theoretical ({time_delta_s:.2f}s). At this stage, technique improvements will yield huge lap time gains. One corner fixed properly can be worth 0.5-1.0s per lap.",
    ],
    ("D-F", "consistency"): [
        "Consistency is a priority right now. {std_dev_s:.2f}s variation between laps means the technique isn't yet consolidated. Before pushing for speed, build a repeatable baseline.",
        "Your lap time spread ({std_dev_s:.2f}s) shows the potential is there on your good laps — the challenge is making every lap a good lap. That comes from deliberate repetition.",
    ],
    ("D-F", "technique"): [
        "Some fundamentals need attention, but that's normal at this stage. Focus on {primary_weakness} — fixing this one thing will cascade into improvements everywhere else.",
        "The building blocks are forming. {primary_strength} is a positive sign. Directing the same attention to {primary_weakness} will transform your corner performance.",
    ],
    ("D-F", "improvement"): [
        "Every session you're getting better. The improvement in {improved_area} proves that focused practice works. Keep at it — the biggest gains come early in the learning curve.",
    ],
    ("D-F", "general"): [
        "A learning session with clear direction. Focus on just the top item below — master one thing at a time. Speed will come naturally as the fundamentals improve.",
        "This is a building session. Don't try to fix everything at once — pick the single biggest item from the focus areas and work on that alone next time out.",
    ],
}
