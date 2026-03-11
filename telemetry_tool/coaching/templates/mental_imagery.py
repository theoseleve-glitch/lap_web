"""Mental imagery / visualization prompts for pre-session and in-session use."""
from __future__ import annotations

# Keys: cause category or general theme
# Values: dict with "pre_session" (full visualization script) and "in_session" (short cue)
MENTAL_IMAGERY: dict[str, dict[str, str]] = {
    "braking_confidence": {
        "pre_session": "Close your eyes. Picture yourself approaching the braking zone. You see your brake marker clearly — it's fixed, reliable, always in the same place. Your foot moves to the brake pedal smoothly, decisively. You feel the car pitch forward as you brake firmly. The deceleration is strong but controlled. You're in command. As you approach the turn-in point, your brake pressure eases gradually — not all at once, but like dimming a light. The car settles, the front tyres grip, and you flow into the corner. This is your braking. Confident, precise, repeatable.",
        "in_session": "See the marker. Brake firm. Trail smooth. You know this.",
    },
    "trail_braking": {
        "pre_session": "Visualize the corner entry. You're braking in a straight line — firm, committed. Now the turn-in point arrives. Instead of releasing the brake completely, you keep gentle pressure — maybe 20%. Feel the weight on the front tyres. They're loaded, gripping, pulling you into the corner. As you add steering, you slowly release the brake. By the apex, it's fully released. The transition is seamless — brake pressure out, steering angle in. Like a seesaw. One goes up as the other goes down. Smooth, continuous, connected.",
        "in_session": "Hold the brake. Feel the front grip. Release like a dimmer switch.",
    },
    "exit_speed": {
        "pre_session": "Picture the apex. You clip it perfectly — inside wheels brushing the kerb. Now look ahead to the exit. Your eyes are already there. As you pass the apex, your right foot begins to squeeze the throttle. Not suddenly — progressively. Squeeze, squeeze, more, more. The car accelerates, unwinding towards the outside of the track. You use all the road. Every metre of track width is speed on the straight. The exit kerb passes under your outside wheels. You're on full throttle, the straight opens up, and you carry that exit speed all the way to the next braking zone.",
        "in_session": "Eyes to exit. Squeeze the throttle. Use all the road.",
    },
    "cornering_flow": {
        "pre_session": "Imagine the perfect corner as water flowing through a pipe. The water doesn't jerk or stop — it flows continuously. Your car is that water. You enter the corner, curve through the apex, and flow out to the exit in one continuous motion. No corrections, no sudden inputs. The steering wheel moves once — in, hold, unwind. Your speed drops smoothly on entry, reaches its minimum at the apex, and builds smoothly on exit. It's a U-shape in the speed trace, not a V. Smooth, flowing, efficient.",
        "in_session": "Flow like water. One smooth arc. No corrections.",
    },
    "consistency_focus": {
        "pre_session": "Before you go out, replay your best lap in your mind. Every corner, every brake point, every throttle application. See it clearly — the track surface, the reference points, the feel of the car. Now commit: you will drive THIS lap, every lap. Not faster, not slower. The same. Like a musician playing a rehearsed piece. The notes are set. You just play them cleanly, every time. Consistency is the foundation. Speed is built on top of it.",
        "in_session": "Same lap. Same inputs. Play the rehearsed piece.",
    },
    "weight_transfer": {
        "pre_session": "Feel the car's weight. It's not static — it moves. Under braking, it surges forward, pressing the front tyres into the ground. That's extra grip for turning. Under acceleration, it shifts rearward, loading the rear tyres for traction. Your job is to manage this invisible force. Brake → weight forward → front grips → turn in. Trail brake → weight stays forward → front keeps gripping through the corner. Throttle → weight shifts back → rear grips → accelerate hard. You're not just steering — you're conducting the weight.",
        "in_session": "Feel the weight shift. Use it. Front for turning, rear for traction.",
    },
    "race_start_calm": {
        "pre_session": "The lights are about to go out. Your heart rate is up — that's normal, that's adrenaline working for you. Take three slow breaths. In... out... in... out... in... out. Feel your hands relax on the wheel. Your vision widens. You see the lights, you see the track ahead, you see the space you're going to drive into. When the lights go out, your reactions will be sharp because you're calm, not because you're tense. Calm is fast. Tense is slow.",
        "in_session": "Breathe. Calm is fast.",
    },
    "error_recovery": {
        "pre_session": "You've made a mistake in a corner. It happens. What matters is what you do next. In your mind, see yourself making the mistake — maybe you turn in too early, maybe you brake too late. Now see yourself recovering: you don't panic, you don't overcorrect. You accept the time loss in this corner, minimize the damage, and set up the next corner perfectly. The mistake cost you 0.2 seconds. Panicking would cost you 0.5. Calm recovery is your superpower.",
        "in_session": "Mistake happened. Let it go. Next corner is clean.",
    },
}
