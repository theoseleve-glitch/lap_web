"""Confidence framing templates — rewrite weaknesses as strengths-in-progress."""
from __future__ import annotations

# Keys: root_cause type
# Values: dict with "reframe" and "encouragement" templates
CONFIDENCE_FRAMES: dict[str, dict[str, str]] = {
    "confidence": {
        "reframe": "You're being appropriately cautious at {corner_name} — that's actually a sign of good self-awareness. The next step is building confidence through repetition, not forcing bravery.",
        "encouragement": "Confidence comes from doing, not deciding. Each lap where you push the brake point 1m later builds real, earned confidence. You're on the right path.",
    },
    "technique": {
        "reframe": "The technique at {corner_name} needs refinement, but you already have the right instincts — you're just not executing them consistently yet. That's a practice gap, not a talent gap.",
        "encouragement": "Technical skills are learned, not innate. The fact that you can do it right sometimes proves you have the ability. Now it's about making it automatic.",
    },
    "line": {
        "reframe": "Your line through {corner_name} isn't optimal yet, but line choice is the easiest thing to improve — it's knowledge, not skill. Once you see the right line, you'll wonder why you ever drove it differently.",
        "encouragement": "Walk the corner in your mind. Visualize the three points: turn-in, apex, track-out. The line will click, and when it does, it's permanent.",
    },
    "balance": {
        "reframe": "The car balance at {corner_name} is unsettled, which means you're on the edge of a breakthrough — learning to manage weight transfer is what separates intermediate from advanced drivers.",
        "encouragement": "Feel the car, don't fight it. Smooth inputs let the weight transfer work FOR you. You're close to understanding this — a few more sessions and it'll click.",
    },
    "aggression": {
        "reframe": "Your commitment at {corner_name} is impressive — you're not afraid to push. The refinement is channeling that aggression into precision. Aggressive AND accurate is the goal.",
        "encouragement": "Your willingness to push is an asset most drivers lack. Now fine-tune it: same commitment, better placement. That's the recipe for fast AND safe.",
    },
    "fitness": {
        "reframe": "The fade in the last third of the session is normal — it shows you're pushing hard. Building physical endurance is an off-track project that will pay dividends on-track.",
        "encouragement": "Even F1 drivers train physically for this exact reason. A 15-minute daily routine will extend your peak window. The speed is there — you just need it to last longer.",
    },
    "management": {
        "reframe": "Vehicle management is the invisible skill — nobody sees it, but everyone benefits from it. Learning to preserve the car while maintaining pace is a sign of maturity in racing.",
        "encouragement": "Think long-term: the driver who finishes with tyres left has options. The one who used them all is just hanging on. You're building race-craft, not just lap speed.",
    },
    "awareness": {
        "reframe": "Track awareness develops with seat time. You're still learning what to look for and where to look — that's completely normal. Each session adds to your mental map.",
        "encouragement": "Your awareness will sharpen with repetition. Soon you'll notice brake markers, surface changes, and reference points without thinking about them.",
    },
    "fear": {
        "reframe": "Healthy respect for speed is not a weakness — it's what keeps you safe while you learn. The goal isn't to eliminate caution, it's to move the boundary gradually.",
        "encouragement": "Push the boundary by 1%, not 20%. Small, incremental steps build sustainable confidence. Rush it and you'll set yourself back. Patient drivers go fastest in the end.",
    },
}
