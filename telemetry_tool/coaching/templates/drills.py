"""Drill library — 20+ drill types with 3 difficulty levels each."""
from __future__ import annotations

DRILL_LIBRARY: dict[str, dict] = {
    "brake_point_consistency": {
        "title": "Brake Point Anchor Drill",
        "applicable_causes": ["early_braking_confidence", "late_braking_aggressive", "inconsistent_brake_point"],
        "difficulty_levels": {
            "beginner": {
                "description": "Pick one corner. Choose a fixed brake marker (cone, kerb edge, crack in tarmac). Brake at exactly that point for 5 laps. Don't worry about speed — just hit the marker.",
                "success_criteria": "5 consecutive laps with brake point within 3m of marker",
                "lap_count": 5,
            },
            "intermediate": {
                "description": "Same marker, but now push entry speed up by 2 km/h each lap until you can't make the corner cleanly. Note your limit, then back off 1 km/h and repeat 5 times.",
                "success_criteria": "5 consecutive laps with brake point within 1.5m of marker at target speed",
                "lap_count": 8,
            },
            "advanced": {
                "description": "Alternate between two corners with different brake points. The goal is instant mental switching — no warm-up lap needed for either corner.",
                "success_criteria": "8 consecutive laps with both brake points within 1m",
                "lap_count": 10,
            },
        },
    },
    "trail_brake_introduction": {
        "title": "Trail Brake Feel Drill",
        "applicable_causes": ["no_trail_braking", "abrupt_brake_release"],
        "difficulty_levels": {
            "beginner": {
                "description": "At one corner, brake normally but hold 10% brake as you turn in. Feel the nose tuck into the corner. Release the last 10% over 2 car lengths after turn-in.",
                "success_criteria": "Can feel the weight on the front tyres during turn-in on 3 consecutive laps",
                "lap_count": 5,
            },
            "intermediate": {
                "description": "Increase trail brake to 30% at turn-in, releasing linearly to 0% by apex. Count 'one-two-three' as you release — that's your release rhythm.",
                "success_criteria": "Smooth release with no steering correction needed, 5 consecutive laps",
                "lap_count": 8,
            },
            "advanced": {
                "description": "Vary trail brake pressure corner by corner: 15% for fast sweepers, 40% for tight hairpins. The release rate should match the corner radius — slower release for tighter corners.",
                "success_criteria": "Trail brake adapted to corner type with no mid-corner corrections, 8 laps",
                "lap_count": 10,
            },
        },
    },
    "throttle_progression": {
        "title": "Throttle Application Drill",
        "applicable_causes": ["late_throttle_application", "hesitant_throttle", "poor_exit_speed"],
        "difficulty_levels": {
            "beginner": {
                "description": "Focus on one corner. As soon as you pass the apex, begin applying throttle — even just 10%. The goal is timing, not aggression. Say 'apex-go' out loud.",
                "success_criteria": "Throttle application begins within 5m of apex on 5 consecutive laps",
                "lap_count": 5,
            },
            "intermediate": {
                "description": "Same corner, but now progressively increase throttle rate: 20% at apex, 50% at mid-exit, 100% at track-out. Think 'squeeze, squeeze, full'.",
                "success_criteria": "Progressive throttle curve with no lift or hesitation, 5 laps",
                "lap_count": 8,
            },
            "advanced": {
                "description": "Link two consecutive corners. Exit throttle from corner 1 becomes entry speed for corner 2. Maximize exit speed from corner 1 while still making corner 2.",
                "success_criteria": "Exit speed within 2 km/h of theoretical for both corners, 5 laps",
                "lap_count": 10,
            },
        },
    },
    "vision_and_reference": {
        "title": "Eyes Up Reference Point Drill",
        "applicable_causes": ["early_apex", "tightening_radius", "inconsistent_brake_point"],
        "difficulty_levels": {
            "beginner": {
                "description": "Before each corner, look at the apex point BEFORE you start braking. Your hands follow your eyes. Pick a physical marker at the apex (kerb paint, cone, rubber mark).",
                "success_criteria": "Can identify apex marker for every corner on the track",
                "lap_count": 3,
            },
            "intermediate": {
                "description": "As you approach the apex, shift your eyes to the exit point. By the time you reach the apex, you should already be looking at track-out. 'Look where you want to go, not where you are.'",
                "success_criteria": "Eyes on exit by apex on 5 consecutive laps at target corner",
                "lap_count": 5,
            },
            "advanced": {
                "description": "Chain three reference points per corner: brake marker → apex → exit. Your eyes should move smoothly between them like reading a book. No fixating.",
                "success_criteria": "Smooth visual chain on all corners, no fixation, 8 laps",
                "lap_count": 8,
            },
        },
    },
    "apex_placement": {
        "title": "Apex Geometry Drill",
        "applicable_causes": ["early_apex", "late_apex_excessive", "tightening_radius"],
        "difficulty_levels": {
            "beginner": {
                "description": "Place a mental marker at the geometric apex of one corner. On each lap, try to clip that point with your inside wheels. Forget about speed — just hit the apex.",
                "success_criteria": "Inside wheels within 0.5m of apex marker on 5 laps",
                "lap_count": 5,
            },
            "intermediate": {
                "description": "Move your apex 1-2m later than geometric. This opens up the exit and lets you get on throttle earlier. Check: are you using more road at exit?",
                "success_criteria": "Late apex with full road used at exit on 5 laps",
                "lap_count": 8,
            },
            "advanced": {
                "description": "Experiment with three different apex points: early, geometric, and late. Time each and feel the difference in exit speed. Pick the fastest and commit.",
                "success_criteria": "Can identify optimal apex point and repeat it consistently",
                "lap_count": 10,
            },
        },
    },
    "smooth_inputs": {
        "title": "Smooth Hands Drill",
        "applicable_causes": ["excess_steering_angle", "mid_corner_correction", "abrupt_brake_release"],
        "difficulty_levels": {
            "beginner": {
                "description": "Drive 3 laps at 80% pace focusing only on smooth steering. No sudden movements. Imagine the steering wheel is connected to a sleeping baby. Gentle, progressive inputs only.",
                "success_criteria": "3 laps with no jerky steering corrections visible in data",
                "lap_count": 3,
            },
            "intermediate": {
                "description": "Combine smooth steering with smooth pedal transitions. One input at a time: release brake → turn → apply throttle. No overlapping inputs yet.",
                "success_criteria": "Clean input separation on 5 consecutive laps",
                "lap_count": 5,
            },
            "advanced": {
                "description": "Now overlap: trail brake into turn-in, throttle blended with steering unwind. All transitions should be progressive — no steps, no spikes.",
                "success_criteria": "Smooth overlapping inputs with no data spikes, 8 laps",
                "lap_count": 8,
            },
        },
    },
    "exit_speed_maximizer": {
        "title": "Exit Speed Focus Drill",
        "applicable_causes": ["poor_exit_speed", "late_throttle_application", "track_out_not_used"],
        "difficulty_levels": {
            "beginner": {
                "description": "Sacrifice entry speed to maximize exit speed at one corner. Brake earlier, turn in slower, but get on the power as early as possible. Compare straight-end speed.",
                "success_criteria": "Exit speed within 5 km/h of theoretical for target corner",
                "lap_count": 5,
            },
            "intermediate": {
                "description": "Use ALL the road on exit. Your outside wheels should touch the exit kerb or track edge. If you have road left, you turned in too early or didn't unwind enough.",
                "success_criteria": "Full road used at exit with increasing throttle, 5 laps",
                "lap_count": 8,
            },
            "advanced": {
                "description": "Optimize the exit-to-straight-end speed chain. Every 1 km/h gained at exit becomes 2-3 km/h at the end of the straight. Feel the cascade effect.",
                "success_criteria": "Exit speed within 2 km/h of theoretical, straight-end speed improved",
                "lap_count": 10,
            },
        },
    },
    "weight_transfer_awareness": {
        "title": "Weight Transfer Feel Drill",
        "applicable_causes": ["no_trail_braking", "mid_corner_lift", "abrupt_brake_release"],
        "difficulty_levels": {
            "beginner": {
                "description": "Drive 3 laps at moderate pace. On each brake application, feel the car pitch forward. On throttle, feel it squat rearward. Just notice — don't try to change anything yet.",
                "success_criteria": "Can describe the weight transfer at 3 different corners",
                "lap_count": 3,
            },
            "intermediate": {
                "description": "Use weight transfer deliberately: brake to load the fronts, then turn in while they're still loaded. Feel how the car rotates better with front grip.",
                "success_criteria": "Trail brake to load fronts at turn-in, 5 corners per lap",
                "lap_count": 5,
            },
            "advanced": {
                "description": "Control weight transfer through all phases: brake (load front), trail (keep front loaded through turn), throttle (load rear for traction). Seamless transitions.",
                "success_criteria": "Continuous weight management through full corner, 8 laps",
                "lap_count": 8,
            },
        },
    },
    "consistency_builder": {
        "title": "Metronome Consistency Drill",
        "applicable_causes": ["lap_time_variation", "corner_speed_variation", "inconsistent_brake_point"],
        "difficulty_levels": {
            "beginner": {
                "description": "Drive 5 laps at 90% pace — not flat out. Focus on repeating the SAME lap every time. Same braking, same lines, same throttle. Consistency > speed.",
                "success_criteria": "5 consecutive laps within 0.5s of each other",
                "lap_count": 5,
            },
            "intermediate": {
                "description": "Same 90% approach, but now maintain it for 10 laps. Track your focus — when does your mind wander? That's where mistakes creep in.",
                "success_criteria": "10 laps within 0.3s variation",
                "lap_count": 10,
            },
            "advanced": {
                "description": "Push to 95% pace while maintaining consistency. The goal: your fast laps should look identical to your medium laps, just slightly quicker everywhere.",
                "success_criteria": "10 laps within 0.2s at 95% pace",
                "lap_count": 12,
            },
        },
    },
    "sector_focus": {
        "title": "Sector Isolation Drill",
        "applicable_causes": ["sector_imbalance", "corner_speed_variation"],
        "difficulty_levels": {
            "beginner": {
                "description": "Identify your weakest sector. Drive 5 laps where you cruise the other sectors and push ONLY in the weak sector. Eliminate distractions.",
                "success_criteria": "Weak sector time within 0.3s of best sector (relative to theoretical)",
                "lap_count": 5,
            },
            "intermediate": {
                "description": "Break the weak sector into individual corners. Which corner costs the most time? Attack that one corner for 5 laps.",
                "success_criteria": "Targeted corner within 0.1s of theoretical",
                "lap_count": 8,
            },
            "advanced": {
                "description": "Link the targeted corners back into the full sector. Flow from one improvement to the next. The sector should feel natural, not forced.",
                "success_criteria": "Full sector time matches or beats personal best",
                "lap_count": 10,
            },
        },
    },
    "tyre_management": {
        "title": "Tyre Preservation Drill",
        "applicable_causes": ["tyre_abuse", "late_session_degradation"],
        "difficulty_levels": {
            "beginner": {
                "description": "Drive 5 laps focusing on smooth inputs. No sliding, no kerb-hopping, no aggressive weight transfers. Imagine the tyres are expensive and you're paying for them.",
                "success_criteria": "No visible tyre marks or squealing, 5 laps",
                "lap_count": 5,
            },
            "intermediate": {
                "description": "Drive a 10-lap stint. First 3 laps are warm-up, next 7 are push. Compare lap 7 to lap 4 — is there degradation? If so, you're too aggressive.",
                "success_criteria": "Less than 0.3s degradation from lap 4 to lap 10",
                "lap_count": 10,
            },
            "advanced": {
                "description": "Full stint simulation. Push from lap 1 but manage inputs to maintain grip throughout. The last lap should be within 0.5s of the first push lap.",
                "success_criteria": "Full stint with <0.5s first-to-last degradation",
                "lap_count": 15,
            },
        },
    },
    "kerb_usage": {
        "title": "Kerb Comfort Drill",
        "applicable_causes": ["kerb_avoidance", "track_out_not_used"],
        "difficulty_levels": {
            "beginner": {
                "description": "At one corner, deliberately ride the inside kerb at the apex. Start gently — just a wheel width. Feel how the car reacts. Most kerbs are your friend.",
                "success_criteria": "Inside wheels on kerb at apex, 5 consecutive laps",
                "lap_count": 5,
            },
            "intermediate": {
                "description": "Add the exit kerb. Use both inside and outside kerbs — this is the widest possible line through the corner and therefore the fastest.",
                "success_criteria": "Both kerbs used, car stable, 5 laps",
                "lap_count": 8,
            },
            "advanced": {
                "description": "Learn which kerbs to attack and which to respect. Flat kerbs = attack. Sausage kerbs = brush only. High kerbs at speed = avoid. Map every kerb on the circuit.",
                "success_criteria": "Appropriate kerb usage at every corner, 8 laps",
                "lap_count": 10,
            },
        },
    },
    "mental_reset": {
        "title": "Corner Reset Drill",
        "applicable_causes": ["mid_corner_correction", "mid_corner_lift", "corner_entry_too_fast"],
        "difficulty_levels": {
            "beginner": {
                "description": "After each corner, take a deep breath on the straight. Reset your mental state. Each corner is independent — a mistake in Turn 3 doesn't affect Turn 4.",
                "success_criteria": "No carry-over errors between corners for 5 laps",
                "lap_count": 5,
            },
            "intermediate": {
                "description": "If you make an error, don't try to 'make up time' in the next corner. Drive the next corner normally. Overdriving after errors compounds the problem.",
                "success_criteria": "No reactive overdriving after errors, monitored over 8 laps",
                "lap_count": 8,
            },
            "advanced": {
                "description": "Practice 'letting go' of a bad corner mid-corner. If you've entered wrong, accept it, minimize the loss, and set up the next corner perfectly.",
                "success_criteria": "Damage limitation on bad entries without cascading errors",
                "lap_count": 10,
            },
        },
    },
    "entry_speed_calibration": {
        "title": "Entry Speed Ladder Drill",
        "applicable_causes": ["corner_entry_too_fast", "mid_corner_speed_loss", "early_braking_confidence"],
        "difficulty_levels": {
            "beginner": {
                "description": "At one corner, enter deliberately slow (80% of your normal speed). Each lap, add 2 km/h of entry speed. Find where the car starts to push or you lose confidence.",
                "success_criteria": "Identify the entry speed limit without spinning or running wide",
                "lap_count": 8,
            },
            "intermediate": {
                "description": "Repeat the ladder but note apex speed and exit speed at each entry speed. Find the entry speed that maximizes EXIT speed, not entry speed.",
                "success_criteria": "Identify optimal entry speed for best exit speed",
                "lap_count": 10,
            },
            "advanced": {
                "description": "Apply optimal entry speeds to all corners in one lap. Different corners have different optimal entries — some are entry-speed sensitive, some are exit-speed sensitive.",
                "success_criteria": "Correct entry speed strategy at every corner type",
                "lap_count": 10,
            },
        },
    },
    "endurance_focus": {
        "title": "Endurance Consistency Drill",
        "applicable_causes": ["late_session_degradation", "lap_time_variation"],
        "difficulty_levels": {
            "beginner": {
                "description": "Drive a 15-minute session at 85% pace. Track when your concentration drops. Are the last 5 minutes worse? That's your endurance limit.",
                "success_criteria": "Identify concentration drop-off point",
                "lap_count": 15,
            },
            "intermediate": {
                "description": "Same 15 minutes, but when you feel concentration drop, use a trigger word ('focus', 'smooth', 'eyes') to reset. Build a mental anchor.",
                "success_criteria": "Use reset trigger to maintain pace in final third",
                "lap_count": 15,
            },
            "advanced": {
                "description": "Extend to 25 minutes. Maintain lap time consistency throughout. Physical fitness matters — if your arms are tired, your inputs get lazy.",
                "success_criteria": "25-minute stint with <0.3s variation throughout",
                "lap_count": 25,
            },
        },
    },
    "fuel_adaptation": {
        "title": "Fuel Load Adaptation Drill",
        "applicable_causes": ["fuel_weight_unadjusted"],
        "difficulty_levels": {
            "beginner": {
                "description": "Note your brake point with a full tank. After 10 laps, try braking 1m later. The car is lighter now — it stops faster. Adjust gradually.",
                "success_criteria": "Brake point adjusted by at least 1m over a stint",
                "lap_count": 10,
            },
            "intermediate": {
                "description": "Track three things as fuel burns: brake point (moves later), corner speed (increases slightly), throttle application point (moves earlier). Adjust all three.",
                "success_criteria": "All three parameters adjusted mid-stint",
                "lap_count": 15,
            },
            "advanced": {
                "description": "Pre-calculate expected brake point adjustments per stint based on fuel burn rate. Apply proactively rather than reactively.",
                "success_criteria": "Proactive adjustments with lap time improving as fuel decreases",
                "lap_count": 20,
            },
        },
    },
    "line_optimization": {
        "title": "Racing Line Refinement Drill",
        "applicable_causes": ["tightening_radius", "early_apex", "late_apex_excessive"],
        "difficulty_levels": {
            "beginner": {
                "description": "Walk the track (or slowly drive it) and identify the ideal line for 3 key corners. Mark brake point, turn-in, apex, and track-out mentally.",
                "success_criteria": "Can describe the ideal line for 3 corners from memory",
                "lap_count": 3,
            },
            "intermediate": {
                "description": "Drive those 3 corners at 85% pace, focusing only on the line. Is your radius constant or tightening? A tightening radius means your turn-in was too early.",
                "success_criteria": "Constant or opening radius through all 3 corners, 5 laps",
                "lap_count": 5,
            },
            "advanced": {
                "description": "Optimize the line for the corner AFTER each target corner. Sometimes the fastest line through corner 1 compromises corner 2. Think one corner ahead.",
                "success_criteria": "Optimized line for corner combinations, not individual corners",
                "lap_count": 8,
            },
        },
    },
    "throttle_lift_elimination": {
        "title": "Committed Throttle Drill",
        "applicable_causes": ["mid_corner_lift", "hesitant_throttle"],
        "difficulty_levels": {
            "beginner": {
                "description": "At one corner, commit to this rule: once you start applying throttle after the apex, you do NOT lift. If you need to lift, you entered too fast. Slow the entry instead.",
                "success_criteria": "No throttle lifts between apex and exit, 5 laps",
                "lap_count": 5,
            },
            "intermediate": {
                "description": "Reduce entry speed by 3 km/h to give yourself margin. Now apply throttle progressively from apex — no lifts. Gradually increase entry speed back up.",
                "success_criteria": "Full progressive throttle from apex at normal entry speed",
                "lap_count": 8,
            },
            "advanced": {
                "description": "Link multiple corners: committed throttle from C1 exit through the straight to C2 braking. No hesitation between corners — the car should never coast.",
                "success_criteria": "Zero coasting between connected corners, 8 laps",
                "lap_count": 10,
            },
        },
    },
    "friction_circle_awareness": {
        "title": "Traction Budget Drill",
        "applicable_causes": ["braking_while_turning", "excess_steering_angle", "corner_entry_too_fast"],
        "difficulty_levels": {
            "beginner": {
                "description": "Think of the tyres as a budget. Braking uses budget. Turning uses budget. You can't spend 100% on both. Practice sequential inputs: brake, THEN turn.",
                "success_criteria": "Clean separation of braking and turning phases, 5 laps",
                "lap_count": 5,
            },
            "intermediate": {
                "description": "Now blend the inputs: as brake decreases, steering increases. The total grip used stays near 100% throughout. This is trail braking's purpose.",
                "success_criteria": "Smooth brake-to-steer transition using most of the grip budget",
                "lap_count": 8,
            },
            "advanced": {
                "description": "Map your friction circle usage at entry, apex, and exit. Entry: 70% brake + 30% steer. Apex: 100% lateral. Exit: 30% steer + 70% throttle. Fill the circle.",
                "success_criteria": "Grip utilization >80% at all corner phases",
                "lap_count": 10,
            },
        },
    },
    "breathing_and_rhythm": {
        "title": "Breathing Rhythm Drill",
        "applicable_causes": ["late_session_degradation", "mid_corner_correction", "mid_corner_lift"],
        "difficulty_levels": {
            "beginner": {
                "description": "On the straights, take a deep breath. Exhale as you brake. This prevents breath-holding under stress, which tenses your muscles and reduces feel.",
                "success_criteria": "Conscious breathing pattern on every straight, 5 laps",
                "lap_count": 5,
            },
            "intermediate": {
                "description": "Extend the breathing to corners: inhale on approach, steady exhale through the corner. Your breathing rhythm should match the corner rhythm.",
                "success_criteria": "Relaxed breathing throughout corners, no breath-holding, 8 laps",
                "lap_count": 8,
            },
            "advanced": {
                "description": "Use breathing as a reset trigger. If something goes wrong, one deep breath on the next straight resets your state. The breath IS the mental reset.",
                "success_criteria": "Automatic breathing reset after any error, full session",
                "lap_count": 12,
            },
        },
    },
}
