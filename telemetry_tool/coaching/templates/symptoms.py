"""Symptom diagnosis text templates — human-readable symptom descriptions."""
from __future__ import annotations

# Keys: symptom_id
# Values: dict with "diagnosis_text" and "what_to_feel" templates

SYMPTOM_TEXTS: dict[str, dict[str, str]] = {
    "early_apex": {
        "diagnosis_text": "You're turning in too early at {corner_name}, reaching the apex before the optimal point. This tightens your exit line and forces you to either lift or run out of road.",
        "what_to_feel": "If you feel like you're running out of road on exit, or the corner 'tightens up' as you go through it, you're apexing too early. The fix: wait. Be patient on the turn-in.",
    },
    "late_apex_excessive": {
        "diagnosis_text": "Your apex at {corner_name} is too late — you're sacrificing mid-corner speed beyond the point of benefit. Late apex is good in principle, but excessive delay costs more than it gains.",
        "what_to_feel": "If you have lots of road left at exit but your mid-corner speed feels very low, the apex is too late. You should clip the inside at the point that balances entry sacrifice with exit gain.",
    },
    "understeer_entry": {
        "diagnosis_text": "Understeer detected at corner entry for {corner_name}. High steering angle with low lateral acceleration means the front tyres are saturated — you're asking for more grip than they have.",
        "what_to_feel": "The car feels 'heavy' or 'pushy' as you turn in. The front end doesn't respond to more steering lock. More steering makes it worse, not better.",
    },
    "mid_corner_speed_loss": {
        "diagnosis_text": "Significant speed drop at the apex of {corner_name}. You're either over-slowing on entry or hesitating mid-corner, both of which cost time through the corner and on exit.",
        "what_to_feel": "If the car feels like it 'stalls' at the apex — neither accelerating nor decelerating, just coasting at low speed — you've lost too much momentum.",
    },
    "no_trail_braking": {
        "diagnosis_text": "No brake-to-steer overlap detected at {corner_name}. You're releasing the brake completely before turning in, which unloads the front tyres and reduces turn-in grip.",
        "what_to_feel": "The car might feel 'floaty' or 'light' at turn-in. That's the weight shifting rearward when you release the brake. Trail braking keeps the weight on the front where you need it.",
    },
    "abrupt_brake_release": {
        "diagnosis_text": "Brake release at {corner_name} is too sudden. Instead of trailing off the brake progressively, you're snapping off it, causing a sharp weight transfer that destabilizes the car.",
        "what_to_feel": "Feel for a 'lurch' or 'pitch' at turn-in — that's the weight snapping rearward. A smooth release feels like the car gently settles rather than lurching.",
    },
    "mid_corner_lift": {
        "diagnosis_text": "Throttle lift detected mid-corner at {corner_name}. Lifting off throttle while cornering shifts weight forward and can cause oversteer, or at minimum, costs exit speed.",
        "what_to_feel": "If you're on throttle and then back off, the car's rear will lighten. On a kart this can cause snap oversteer. On a car, you'll feel the nose dip and the rear get loose.",
    },
    "tightening_radius": {
        "diagnosis_text": "Your line through {corner_name} is tightening — the radius decreases as you go through the corner. This forces increasing steering lock and speed reduction.",
        "what_to_feel": "You keep needing to add more steering through the corner. The exit feels 'tight' and you might run out of road. This means you turned in too early.",
    },
    "poor_exit_speed": {
        "diagnosis_text": "Exit speed at {corner_name} is {delta_kmh:.1f} km/h below theoretical. This is the most expensive kind of time loss because it cascades onto the following straight.",
        "what_to_feel": "If the car in front (or your data) pulls away from you on the straight, your exit speed is the culprit. The straight just amplifies what happened at corner exit.",
    },
    "inconsistent_brake_point": {
        "diagnosis_text": "Your brake point at {corner_name} varies by {variance_m:.0f}m between laps. This variation cascades through the entire corner — inconsistent entry leads to inconsistent everything.",
        "what_to_feel": "Some laps the corner feels easy, some laps it feels hectic. That's brake point variation. Fix the brake point and the rest of the corner stabilizes.",
    },
}
