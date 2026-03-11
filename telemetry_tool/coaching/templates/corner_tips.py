"""Corner coaching tip templates -- 156 parameterized tips for all cause x severity x vehicle combinations.

26 cause IDs x 3 severities (mild, moderate, severe) x 2 vehicles (kart, car) = 156 entries.

Each value is a dict with:
  - tip: parameterized coaching string with {placeholders}
  - progressive_steps: list of 3 incremental improvement steps
  - symptom_check: short description of telemetry signature to confirm the cause

Placeholders available: {corner_name}, {delta_m}, {variance_m}, {step_m},
{current_m}, {step1_m}, {step2_m}, {target_delta_m}, {time_loss_s},
{exit_speed_loss_kmh}, {cascade_time_s}, {pct_increase}, {throttle_drop_pct},
{lift_duration_s}, {grip_pct}, {weight_shift_kg}, {yaw_spike}
"""

CORNER_TIPS: dict[tuple[str, str, str], dict] = {
    # -------------------------------------------------------------------------
    # 1. early_braking_confidence
    # -------------------------------------------------------------------------
    ("early_braking_confidence", "mild", "kart"): {
        "tip": (
            "At {corner_name} you are braking {delta_m}m earlier than the reference. "
            "Trust the grip -- the kart will stop in time. Eyes up to the turn-in "
            "point and let the braking marker come to you."
        ),
        "progressive_steps": [
            "Move your braking point {step1_m}m later on the next three laps and hold it there.",
            "Once comfortable, move another {step2_m}m later while keeping the same pedal pressure.",
            "Target the reference point at {target_delta_m}m and focus on feeling the front tyres load up.",
        ],
        "symptom_check": "Brake trace starts {delta_m}m before reference with similar peak pressure.",
    },
    ("early_braking_confidence", "mild", "car"): {
        "tip": (
            "At {corner_name} you are braking {delta_m}m earlier than optimal. "
            "Feel the weight transfer onto the front axle and trust the ABS or "
            "threshold zone. Keep your eyes fixed on the turn-in cone."
        ),
        "progressive_steps": [
            "Delay braking by {step1_m}m for three consecutive laps to build confidence.",
            "Move another {step2_m}m later and notice how the car still rotates cleanly.",
            "Aim for the reference brake point at {target_delta_m}m with smooth initial application.",
        ],
        "symptom_check": "Brake application begins {delta_m}m before reference; decel profile is normal.",
    },
    ("early_braking_confidence", "moderate", "kart"): {
        "tip": (
            "You are giving up {time_loss_s}s at {corner_name} by braking {delta_m}m too early. "
            "This is a confidence issue, not a speed issue. Breathe, look ahead, and "
            "let the kart carry speed deeper before squeezing the brake."
        ),
        "progressive_steps": [
            "Pick a new visual marker {step1_m}m later and commit to it for five laps.",
            "Add {step2_m}m more once the first marker feels routine.",
            "Close the full {target_delta_m}m gap -- you will feel the kart bite harder and rotate better.",
        ],
        "symptom_check": "Consistent early brake onset across laps; no lock-up or overshoot events.",
    },
    ("early_braking_confidence", "moderate", "car"): {
        "tip": (
            "At {corner_name} you are losing {time_loss_s}s per lap from braking {delta_m}m early. "
            "The car has more grip than you are using. Focus on smooth initial pedal "
            "application and feel the weight transfer build progressively."
        ),
        "progressive_steps": [
            "Move your marker {step1_m}m later and brake with the same pressure profile.",
            "Shift another {step2_m}m and begin adding light trail-brake into the corner.",
            "Reach the reference point at {target_delta_m}m -- expect the car to rotate more willingly.",
        ],
        "symptom_check": "Brake onset {delta_m}m early; peak decel below car capability; no ABS activation.",
    },
    ("early_braking_confidence", "severe", "kart"): {
        "tip": (
            "You are leaving {time_loss_s}s on the table at {corner_name} -- braking {delta_m}m "
            "before the reference. This cascades into {cascade_time_s}s of total loss "
            "through the following straight. Reset your mental marker now."
        ),
        "progressive_steps": [
            "On the next outing, use the reference marker and brake at {step1_m}m later -- commit fully.",
            "Hold that for ten laps, then push to {step2_m}m later.",
            "Close to {target_delta_m}m and focus on a smooth, progressive squeeze rather than a stab.",
        ],
        "symptom_check": "Large early-brake delta every lap; exit speed deficit of {exit_speed_loss_kmh} km/h.",
    },
    ("early_braking_confidence", "severe", "car"): {
        "tip": (
            "At {corner_name} you are braking {delta_m}m too early, costing {time_loss_s}s per lap "
            "and {exit_speed_loss_kmh} km/h on exit. This is the single biggest gain available. "
            "Trust the car, look further ahead, and commit to a later marker."
        ),
        "progressive_steps": [
            "Move to {step1_m}m later immediately -- the car can handle it with current tyre grip.",
            "After five clean laps, shift another {step2_m}m and start trailing the brake to apex.",
            "Target {target_delta_m}m -- combine with trail-braking for a complete corner transformation.",
        ],
        "symptom_check": "Brake onset {delta_m}m early every lap; significant exit speed loss; no lock-ups.",
    },

    # -------------------------------------------------------------------------
    # 2. late_braking_aggressive
    # -------------------------------------------------------------------------
    ("late_braking_aggressive", "mild", "kart"): {
        "tip": (
            "At {corner_name} you are braking {delta_m}m past the optimal point. "
            "You are carrying great speed in but sacrificing exit drive. "
            "Ease the braking point back slightly and focus on a clean turn-in."
        ),
        "progressive_steps": [
            "Brake {step1_m}m earlier on the next run and keep the same pedal shape.",
            "Check that you can get back to full throttle at the same point as the reference.",
            "Settle at {target_delta_m}m and prioritise smooth steering input over late braking.",
        ],
        "symptom_check": "Brake onset {delta_m}m late; higher peak decel; compromised minimum speed.",
    },
    ("late_braking_aggressive", "mild", "car"): {
        "tip": (
            "You are braking {delta_m}m later than optimal at {corner_name}. "
            "The extra entry speed is costing you corner speed and exit traction. "
            "Pull the brake point back slightly and feel how the car settles earlier."
        ),
        "progressive_steps": [
            "Move your braking reference {step1_m}m earlier for three laps.",
            "Focus on getting to throttle earlier and compare exit speeds.",
            "Settle at {target_delta_m}m where entry and exit balance out.",
        ],
        "symptom_check": "Late brake onset with higher peak G; slight understeer at turn-in.",
    },
    ("late_braking_aggressive", "moderate", "kart"): {
        "tip": (
            "At {corner_name} you are over-driving the braking zone by {delta_m}m, losing "
            "{time_loss_s}s from poor mid-corner and exit speed. The kart needs to be "
            "settled before turn-in -- breathe and be smooth on entry."
        ),
        "progressive_steps": [
            "Brake {step1_m}m earlier and concentrate on a smooth, progressive brake release.",
            "Work on carrying higher minimum speed through the apex.",
            "Target {target_delta_m}m and verify exit speed improves by {exit_speed_loss_kmh} km/h.",
        ],
        "symptom_check": "Late braking with tyre scrub at entry; minimum speed {exit_speed_loss_kmh} km/h below reference.",
    },
    ("late_braking_aggressive", "moderate", "car"): {
        "tip": (
            "You are over-braking into {corner_name} by {delta_m}m, which costs {time_loss_s}s. "
            "The car is unsettled at turn-in and you lose exit traction. "
            "Ease the brake point back and feel the weight transfer arrive more gently."
        ),
        "progressive_steps": [
            "Brake {step1_m}m earlier and note how much calmer the car feels at turn-in.",
            "Use the extra stability to carry {step2_m} km/h more through the apex.",
            "Settle at {target_delta_m}m and trail-brake smoothly to apex.",
        ],
        "symptom_check": "ABS or lock-up events at entry; understeer or snap oversteer at turn-in.",
    },
    ("late_braking_aggressive", "severe", "kart"): {
        "tip": (
            "At {corner_name} you are braking {delta_m}m too late, causing {time_loss_s}s loss "
            "and a {cascade_time_s}s cascade into the next section. The kart is sliding "
            "through the corner. Pull the brake point back and be patient."
        ),
        "progressive_steps": [
            "Move braking {step1_m}m earlier -- this alone will recover most of the time.",
            "Focus on a progressive brake release to settle the rear.",
            "Once at {target_delta_m}m, compare your exit speed to the reference lap.",
        ],
        "symptom_check": "Heavy lock-up or rear slide on entry; severely compromised exit speed.",
    },
    ("late_braking_aggressive", "severe", "car"): {
        "tip": (
            "You are over-driving the brake zone at {corner_name} by {delta_m}m, losing "
            "{time_loss_s}s. The car is beyond its grip envelope at turn-in and you are "
            "scrubbing speed through the entire corner. Pull back significantly."
        ),
        "progressive_steps": [
            "Brake {step1_m}m earlier immediately -- this is a safety and pace issue.",
            "Use the calmer entry to trail-brake properly and rotate the car.",
            "Settle at {target_delta_m}m and verify ABS events are eliminated.",
        ],
        "symptom_check": "Repeated ABS intervention; tyre flat-spotting; exit speed well below reference.",
    },

    # -------------------------------------------------------------------------
    # 3. insufficient_brake_pressure
    # -------------------------------------------------------------------------
    ("insufficient_brake_pressure", "mild", "kart"): {
        "tip": (
            "At {corner_name} your peak brake pressure is {pct_increase}% below the reference. "
            "Squeeze the pedal harder at initial application -- the kart can take more "
            "and you will shed speed faster, allowing a shorter braking zone."
        ),
        "progressive_steps": [
            "Increase initial brake pressure by {step1_m}% on the next run.",
            "Hold peak pressure briefly before beginning the release phase.",
            "Target full reference pressure and note how the braking zone shortens.",
        ],
        "symptom_check": "Peak decel {pct_increase}% below reference; longer braking distance.",
    },
    ("insufficient_brake_pressure", "mild", "car"): {
        "tip": (
            "Your brake pressure at {corner_name} is {pct_increase}% below optimal. "
            "Apply the brakes more aggressively on the initial hit, then modulate. "
            "Feel the weight transfer snap onto the front axle."
        ),
        "progressive_steps": [
            "Increase initial hit by {step1_m}% and hold for a beat before trailing off.",
            "Check that peak decel reaches the reference value.",
            "Combine the firmer initial hit with a smooth trail-brake release.",
        ],
        "symptom_check": "Peak longitudinal G {pct_increase}% low; braking zone is elongated.",
    },
    ("insufficient_brake_pressure", "moderate", "kart"): {
        "tip": (
            "You are not braking hard enough at {corner_name} -- peak pressure is {pct_increase}% "
            "low, costing {time_loss_s}s. The kart decelerates slowly so you arrive at "
            "the apex carrying too much or too little speed. Hit the brake harder."
        ),
        "progressive_steps": [
            "Stamp the brake pedal to {step1_m}% of your current max on the initial hit.",
            "Immediately begin a smooth release as you approach the turn-in point.",
            "Target reference pressure and feel how the kart rotates better with proper weight on the front.",
        ],
        "symptom_check": "Decel profile is flat and extended; time lost in braking zone.",
    },
    ("insufficient_brake_pressure", "moderate", "car"): {
        "tip": (
            "At {corner_name} your brake pressure is {pct_increase}% below target, losing "
            "{time_loss_s}s. The car is not decelerating efficiently and the braking zone "
            "stretches into the corner. Be aggressive on the initial pedal application."
        ),
        "progressive_steps": [
            "Hit the brake hard enough to feel slight ABS intervention, then modulate.",
            "Shorten the braking zone by {step1_m}m with the higher pressure.",
            "Use the gained distance for a smoother, longer trail-brake phase.",
        ],
        "symptom_check": "Peak G {pct_increase}% below car limit; no ABS events; long decel phase.",
    },
    ("insufficient_brake_pressure", "severe", "kart"): {
        "tip": (
            "Your braking at {corner_name} is far too gentle -- {pct_increase}% below reference "
            "pressure, losing {time_loss_s}s. You are coasting into the corner. "
            "The kart needs a firm, decisive brake application."
        ),
        "progressive_steps": [
            "Practice full-pressure stops on a straight to calibrate your pedal feel.",
            "Apply that same pressure at {corner_name} and release progressively.",
            "Close the pressure gap and verify braking distance matches the reference.",
        ],
        "symptom_check": "Very low peak decel; effectively coasting into the corner.",
    },
    ("insufficient_brake_pressure", "severe", "car"): {
        "tip": (
            "At {corner_name} you are braking at {pct_increase}% below the car's capability, "
            "losing {time_loss_s}s. The car has significant untapped braking grip. "
            "Be brave on the initial hit -- the tyres and ABS can handle it."
        ),
        "progressive_steps": [
            "Practice threshold braking on the main straight to learn the pedal limit.",
            "Apply that limit at {corner_name} and trail off smoothly.",
            "Combine proper pressure with a later brake point for a compound gain.",
        ],
        "symptom_check": "Peak G far below tyre capability; no ABS, no lock; long braking zone.",
    },

    # -------------------------------------------------------------------------
    # 4. no_trail_braking
    # -------------------------------------------------------------------------
    ("no_trail_braking", "mild", "kart"): {
        "tip": (
            "At {corner_name} you release the brake fully before turn-in. "
            "Carry a small amount of brake pressure past the turn-in point to keep "
            "weight on the front axle and help the kart rotate."
        ),
        "progressive_steps": [
            "Hold 10% brake pressure through the first third of the corner.",
            "Gradually increase the trail zone until you feel the rear begin to lighten.",
            "Blend brake release with throttle application for a seamless transition.",
        ],
        "symptom_check": "Brake pressure drops to zero before steering angle begins.",
    },
    ("no_trail_braking", "mild", "car"): {
        "tip": (
            "You are releasing the brake completely before turning into {corner_name}. "
            "Maintain light brake pressure through the initial steering input to keep "
            "the front tyres loaded and improve rotation."
        ),
        "progressive_steps": [
            "Hold 5-10% brake pressure past the turn-in point.",
            "Feel the car rotate more willingly as front grip increases.",
            "Release the brake fully as you approach the apex and transition to throttle.",
        ],
        "symptom_check": "Zero brake overlap with steering; slight understeer at turn-in.",
    },
    ("no_trail_braking", "moderate", "kart"): {
        "tip": (
            "At {corner_name} you are losing {time_loss_s}s because the kart pushes wide "
            "at entry with no trail-brake. Keeping pressure through the turn-in "
            "is the single most effective technique for kart corner speed."
        ),
        "progressive_steps": [
            "Maintain 15% brake into the first quarter of the corner.",
            "As the kart rotates, smoothly release the brake and pick up the throttle.",
            "The kart should feel like it pivots around the inside wheel.",
        ],
        "symptom_check": "Abrupt brake release before turn-in; understeer on entry; slow rotation.",
    },
    ("no_trail_braking", "moderate", "car"): {
        "tip": (
            "You are losing {time_loss_s}s at {corner_name} by not trail-braking. "
            "The car understeers on entry because the front tyres are unloaded. "
            "Trail the brake gently past the turn-in point and feel the difference."
        ),
        "progressive_steps": [
            "Apply a gentle 10-15% brake trail from turn-in toward the apex.",
            "Release progressively as steering angle increases.",
            "Combine with earlier turn-in to exploit the improved front grip.",
        ],
        "symptom_check": "No brake-steer overlap; front tyre temps lower than rear at entry.",
    },
    ("no_trail_braking", "severe", "kart"): {
        "tip": (
            "At {corner_name} the absence of trail-braking is costing {time_loss_s}s and "
            "causing heavy understeer. The kart cannot rotate without front-axle load. "
            "This is the top priority technique to develop."
        ),
        "progressive_steps": [
            "Start with a slow-speed corner and hold brake pressure through the first half.",
            "Feel the rear go light and the kart pivot -- that is the trail-brake working.",
            "Transfer the technique to {corner_name} at race speed.",
        ],
        "symptom_check": "No brake-steer overlap in any corner; persistent entry understeer.",
    },
    ("no_trail_braking", "severe", "car"): {
        "tip": (
            "You are losing {time_loss_s}s at {corner_name} and the car is fundamentally "
            "unbalanced on entry without trail-braking. This is a foundational technique "
            "for any car with front-weight bias. Commit to learning it now."
        ),
        "progressive_steps": [
            "Practice at 80% speed: brake, then trail 20% pressure into the corner.",
            "Increase pace once the hand-foot coordination becomes natural.",
            "At full speed, the trail-brake should last from turn-in to just before the apex.",
        ],
        "symptom_check": "Zero brake-steer overlap; heavy understeer; excessive steering correction.",
    },

    # -------------------------------------------------------------------------
    # 5. abrupt_brake_release
    # -------------------------------------------------------------------------
    ("abrupt_brake_release", "mild", "kart"): {
        "tip": (
            "At {corner_name} you are snapping off the brake rather than releasing it "
            "progressively. This unsettles the kart at turn-in. Think of the brake "
            "release as a gentle squeeze in reverse."
        ),
        "progressive_steps": [
            "Focus on taking twice as long to release the brake pedal.",
            "Feel the weight transfer settle before adding steering angle.",
            "Blend the last 10% of brake pressure into the corner entry.",
        ],
        "symptom_check": "Brake pressure drops from peak to zero in under 50ms.",
    },
    ("abrupt_brake_release", "mild", "car"): {
        "tip": (
            "Your brake release at {corner_name} is too abrupt, causing {weight_shift_kg}kg "
            "of weight to shift off the front axle suddenly. Ease the pedal out "
            "smoothly to maintain front grip through the turn-in."
        ),
        "progressive_steps": [
            "Visualise lifting your foot off the pedal in slow motion.",
            "Maintain 5% brake as you begin to steer.",
            "Release the final brake pressure at the apex or just before.",
        ],
        "symptom_check": "Sharp drop in brake pressure trace; pitch oscillation at turn-in.",
    },
    ("abrupt_brake_release", "moderate", "kart"): {
        "tip": (
            "At {corner_name} the abrupt brake release is costing {time_loss_s}s because "
            "the kart snaps to oversteer or pushes wide. The transition from braking "
            "to cornering must be smooth. Breathe and release slowly."
        ),
        "progressive_steps": [
            "Practice a three-count brake release: full, half, trail.",
            "Feel the kart settle progressively as you release.",
            "Once smooth, the kart will carry more speed through the corner.",
        ],
        "symptom_check": "Fast brake release with subsequent yaw spike of {yaw_spike} deg/s.",
    },
    ("abrupt_brake_release", "moderate", "car"): {
        "tip": (
            "Your brake release at {corner_name} destabilises the car, losing {time_loss_s}s. "
            "The {weight_shift_kg}kg of weight snapping rearward overloads the rear tyres "
            "momentarily. Smooth is fast -- release the brake progressively."
        ),
        "progressive_steps": [
            "Take at least 200ms from peak pressure to full release.",
            "Feel the car pitch stabilise before adding steering lock.",
            "Blend the release into a trail-brake for an even smoother transition.",
        ],
        "symptom_check": "Brake release in under 100ms; yaw rate spike; driver correction after turn-in.",
    },
    ("abrupt_brake_release", "severe", "kart"): {
        "tip": (
            "At {corner_name} you are dumping the brake, causing {time_loss_s}s loss and "
            "a {yaw_spike} deg/s yaw spike. The kart is uncontrollable at turn-in. "
            "This must be fixed before any other technique can help."
        ),
        "progressive_steps": [
            "Practice at 60% speed: brake hard, then take a full second to release.",
            "Increase pace while keeping the release smooth and progressive.",
            "At race speed the release should take 150-300ms from peak to zero.",
        ],
        "symptom_check": "Brake dump in under 50ms; large yaw spike; frequent corrections.",
    },
    ("abrupt_brake_release", "severe", "car"): {
        "tip": (
            "Your brake release at {corner_name} is dangerously abrupt, causing {time_loss_s}s loss "
            "and {yaw_spike} deg/s of yaw. The car is snapping on entry. "
            "This is a safety and pace priority -- develop a progressive release."
        ),
        "progressive_steps": [
            "Practice threshold braking to a stop, focusing only on release smoothness.",
            "Transfer the technique to {corner_name} at 80% speed.",
            "Build to full speed once the car remains stable through the transition.",
        ],
        "symptom_check": "Brake dump under 80ms; severe pitch/yaw transient; loss of control risk.",
    },

    # -------------------------------------------------------------------------
    # 6. inconsistent_brake_point
    # -------------------------------------------------------------------------
    ("inconsistent_brake_point", "mild", "kart"): {
        "tip": (
            "Your braking point at {corner_name} varies by {variance_m}m lap to lap. "
            "Pick a fixed visual reference -- a crack, a marker, a kerb edge -- "
            "and hit it every lap."
        ),
        "progressive_steps": [
            "Identify a specific reference mark on the track surface.",
            "Brake at that exact point for five consecutive laps.",
            "Once consistent, tune the point earlier or later as needed.",
        ],
        "symptom_check": "Brake onset variance of {variance_m}m across laps.",
    },
    ("inconsistent_brake_point", "mild", "car"): {
        "tip": (
            "At {corner_name} your brake point varies by {variance_m}m. "
            "Consistency is the foundation of fast driving. Choose a fixed marker "
            "and commit to it every lap before trying to optimise."
        ),
        "progressive_steps": [
            "Pick a distance board or trackside feature as your brake marker.",
            "Hit it within 2m for ten consecutive laps.",
            "Only then begin moving the marker to find the optimal point.",
        ],
        "symptom_check": "Brake point variance {variance_m}m across a stint.",
    },
    ("inconsistent_brake_point", "moderate", "kart"): {
        "tip": (
            "Your brake point at {corner_name} wanders by {variance_m}m, costing {time_loss_s}s "
            "in lost consistency. Your body cannot learn the corner if the inputs "
            "change every lap. Lock in a reference point now."
        ),
        "progressive_steps": [
            "Choose the most conservative brake point you have been using.",
            "Hit it exactly for ten laps to build muscle memory.",
            "Once locked in, move it {step1_m}m later if there is margin.",
        ],
        "symptom_check": "Brake onset scatter of {variance_m}m; entry speed varies accordingly.",
    },
    ("inconsistent_brake_point", "moderate", "car"): {
        "tip": (
            "At {corner_name} your brake point varies by {variance_m}m, losing {time_loss_s}s "
            "in consistency. The car feels different every lap because the entry conditions "
            "are different. Commit to a fixed marker and build from there."
        ),
        "progressive_steps": [
            "Use the distance board as an absolute reference for five laps.",
            "Tighten the variance to under 3m.",
            "Only adjust the marker once consistency is established.",
        ],
        "symptom_check": "High brake-point variance; speed at turn-in varies by more than 5 km/h.",
    },
    ("inconsistent_brake_point", "severe", "kart"): {
        "tip": (
            "Your braking at {corner_name} has {variance_m}m of scatter, costing {time_loss_s}s. "
            "You are guessing where to brake each lap. This makes every other technique "
            "impossible to build. Fix this first."
        ),
        "progressive_steps": [
            "Use a physical marker -- tape on the track edge or a kerb segment.",
            "Brake at that exact point for twenty laps regardless of feel.",
            "Once locked in, begin optimising other parts of the corner.",
        ],
        "symptom_check": "Brake point scatter exceeds {variance_m}m; entry speed is unpredictable.",
    },
    ("inconsistent_brake_point", "severe", "car"): {
        "tip": (
            "At {corner_name} your brake point wanders by {variance_m}m, causing {time_loss_s}s of "
            "inconsistency. No technique can be developed on an inconsistent foundation. "
            "Lock in a fixed brake marker as your top priority."
        ),
        "progressive_steps": [
            "Choose the earliest brake point you have used -- that is your temporary anchor.",
            "Hit it within 2m for every lap of the next stint.",
            "Once the variance is under 3m, shift the marker later in {step1_m}m increments.",
        ],
        "symptom_check": "Massive brake-point scatter; entry speed varies by over 10 km/h.",
    },

    # -------------------------------------------------------------------------
    # 7. braking_while_turning
    # -------------------------------------------------------------------------
    ("braking_while_turning", "mild", "kart"): {
        "tip": (
            "At {corner_name} you still have significant brake pressure while at high "
            "steering angle. Complete the majority of braking before turn-in, then "
            "use only a light trail. The kart tyres cannot do both jobs at once."
        ),
        "progressive_steps": [
            "Focus on finishing braking {step1_m}m before adding steering.",
            "Allow only a light trail of 5-10% pressure past the turn-in.",
            "Feel the kart grip improve as you separate braking from steering.",
        ],
        "symptom_check": "Brake pressure above 30% coincides with steering angle above 15 degrees.",
    },
    ("braking_while_turning", "mild", "car"): {
        "tip": (
            "At {corner_name} you are carrying too much brake into the corner. "
            "The tyres are overloaded, losing {grip_pct}% of available grip. "
            "Separate the heavy braking from the turning phase."
        ),
        "progressive_steps": [
            "Complete 90% of braking before the turn-in point.",
            "Use only a light trail of residual pressure past turn-in.",
            "Monitor front tyre temps -- they should even out as you improve the overlap.",
        ],
        "symptom_check": "Heavy brake with high steering angle; front tyre overload signature.",
    },
    ("braking_while_turning", "moderate", "kart"): {
        "tip": (
            "You are braking heavily while turning at {corner_name}, costing {time_loss_s}s. "
            "The kart is scrubbing speed through tyre overload. Finish the braking "
            "earlier and let the kart flow through the corner."
        ),
        "progressive_steps": [
            "Brake {step1_m}m earlier so you can release before the turn-in point.",
            "Keep only 10% pressure as a trail-brake, not a full braking effort.",
            "Feel the kart respond to steering inputs much more crisply.",
        ],
        "symptom_check": "High brake pressure overlaps mid-corner steering; scrub speed loss {time_loss_s}s.",
    },
    ("braking_while_turning", "moderate", "car"): {
        "tip": (
            "At {corner_name} you are overloading the front tyres by braking heavily while "
            "turning, losing {time_loss_s}s. The friction circle is exceeded and the car "
            "pushes wide. Separate the inputs cleanly."
        ),
        "progressive_steps": [
            "Move braking earlier by {step1_m}m to finish heavy braking before turn-in.",
            "Use a gentle trail-brake, not a full braking effort, through the corner.",
            "The understeer should disappear as the front tyres have grip for steering.",
        ],
        "symptom_check": "Front tyre saturation; understeer with high brake pressure mid-corner.",
    },
    ("braking_while_turning", "severe", "kart"): {
        "tip": (
            "At {corner_name} you are braking hard while at full steering lock, losing "
            "{time_loss_s}s and risking a spin. The kart tyres are completely overloaded. "
            "You must separate these inputs -- brake in a straight line, then turn."
        ),
        "progressive_steps": [
            "Practice braking only in a straight line for an entire session.",
            "Add steering only after the brake is fully released.",
            "Gradually introduce trail-braking once the separation is instinctive.",
        ],
        "symptom_check": "Full brake plus full steering simultaneously; spin or heavy scrub.",
    },
    ("braking_while_turning", "severe", "car"): {
        "tip": (
            "You are braking hard while turning at {corner_name}, losing {time_loss_s}s "
            "and exceeding the tyre friction circle by a wide margin. This is a safety "
            "issue. Brake in a straight line first, then turn."
        ),
        "progressive_steps": [
            "Complete all heavy braking before any steering input.",
            "Once stable, add a light trail-brake of no more than 10% pressure.",
            "Build the overlap gradually over multiple sessions.",
        ],
        "symptom_check": "ABS plus high steering angle; heavy understeer or snap oversteer.",
    },

    # -------------------------------------------------------------------------
    # 8. early_apex
    # -------------------------------------------------------------------------
    ("early_apex", "mild", "kart"): {
        "tip": (
            "At {corner_name} you are clipping the apex {delta_m}m too early. "
            "This tightens the exit and costs you {exit_speed_loss_kmh} km/h on the "
            "following straight. Eyes up to the exit -- let the apex come to you."
        ),
        "progressive_steps": [
            "Delay your turn-in by {step1_m}m and aim for a later apex cone.",
            "Verify that the exit opens up and you can unwind the wheel earlier.",
            "Target the apex at {target_delta_m}m for maximum exit speed.",
        ],
        "symptom_check": "Apex clipping {delta_m}m early; exit requires additional steering input.",
    },
    ("early_apex", "mild", "car"): {
        "tip": (
            "You are apexing {delta_m}m early at {corner_name}, losing {exit_speed_loss_kmh} km/h "
            "on exit. Delay the turn-in point and look further through the corner to "
            "find the later, faster apex."
        ),
        "progressive_steps": [
            "Delay turn-in by {step1_m}m and aim for a visual reference later in the corner.",
            "Check that you can get to full throttle earlier on exit.",
            "Settle at the apex point that maximises exit speed.",
        ],
        "symptom_check": "Apex {delta_m}m early; tighter exit line; reduced exit speed.",
    },
    ("early_apex", "moderate", "kart"): {
        "tip": (
            "At {corner_name} your early apex is costing {time_loss_s}s because you "
            "run out of road on exit and have to lift. Patience on entry is the key -- "
            "hold a wider line longer and let the apex come to you."
        ),
        "progressive_steps": [
            "Turn in {step1_m}m later and keep your eyes on the exit kerb.",
            "The kart should brush the apex naturally without you aiming for it.",
            "Target {target_delta_m}m later apex for optimal exit speed.",
        ],
        "symptom_check": "Early apex with exit track-out issues; throttle lift on exit.",
    },
    ("early_apex", "moderate", "car"): {
        "tip": (
            "You are apexing {delta_m}m too early at {corner_name}, costing {time_loss_s}s. "
            "The exit tightens and you either lift or run wide. Be patient -- delay "
            "the turn-in and keep your eyes on the exit point."
        ),
        "progressive_steps": [
            "Delay turn-in by {step1_m}m and hold a wider entry line.",
            "Aim the car at a later apex point and feel the exit open up.",
            "Get to full throttle {step2_m}m earlier than before.",
        ],
        "symptom_check": "Early apex; tight exit; either track limit breach or throttle lift.",
    },
    ("early_apex", "severe", "kart"): {
        "tip": (
            "At {corner_name} your early apex costs {time_loss_s}s and {exit_speed_loss_kmh} km/h "
            "on exit. The kart cannot accelerate because you are still turning. "
            "You must move the apex point significantly later."
        ),
        "progressive_steps": [
            "Aim for an apex point {step1_m}m later than your current one.",
            "The entry will feel slow but watch the exit speed climb.",
            "Verify the improvement with sector times and top speed on the next straight.",
        ],
        "symptom_check": "Very early apex; car still turning at exit; large exit speed deficit.",
    },
    ("early_apex", "severe", "car"): {
        "tip": (
            "Your early apex at {corner_name} is costing {time_loss_s}s and {exit_speed_loss_kmh} km/h. "
            "The car cannot straighten for a full-throttle exit. This is a fundamental "
            "line error that must be corrected immediately."
        ),
        "progressive_steps": [
            "Move the apex {step1_m}m later and accept a wider, slower entry.",
            "Focus on getting the car straight and applying full throttle as early as possible.",
            "Verify exit speed matches reference and carry it down the following straight.",
        ],
        "symptom_check": "Very early apex; still cornering at track-out; massive exit speed loss.",
    },

    # -------------------------------------------------------------------------
    # 9. late_apex_excessive
    # -------------------------------------------------------------------------
    ("late_apex_excessive", "mild", "kart"): {
        "tip": (
            "At {corner_name} you are apexing {delta_m}m too late. While a late apex "
            "is generally good, over-doing it costs entry speed and makes the mid-corner "
            "too tight. Aim for a slightly earlier clip point."
        ),
        "progressive_steps": [
            "Bring the apex {step1_m}m earlier and maintain the same entry speed.",
            "The mid-corner should feel less tight and more flowing.",
            "Balance the apex point where entry and exit speed are both maximised.",
        ],
        "symptom_check": "Apex {delta_m}m late; mid-corner speed drops below reference.",
    },
    ("late_apex_excessive", "mild", "car"): {
        "tip": (
            "You are apexing {delta_m}m too late at {corner_name}. The excessively late "
            "apex tightens the mid-corner and costs you overall time despite good exit "
            "speed. Find the balance point slightly earlier."
        ),
        "progressive_steps": [
            "Move the apex {step1_m}m earlier on the next run.",
            "Check that mid-corner minimum speed improves.",
            "Settle at the point where total corner time is lowest.",
        ],
        "symptom_check": "Late apex; low mid-corner speed; excessive steering mid-corner.",
    },
    ("late_apex_excessive", "moderate", "kart"): {
        "tip": (
            "At {corner_name} your over-late apex is costing {time_loss_s}s. You are "
            "scrubbing too much speed mid-corner even though the exit is clean. "
            "The kart needs a more balanced line through the middle of the corner."
        ),
        "progressive_steps": [
            "Bring the apex {step1_m}m earlier and carry more momentum through the mid-corner.",
            "The entry will feel faster and the mid-corner less strained.",
            "Compare total corner times, not just exit speed.",
        ],
        "symptom_check": "Very late apex; tight mid-corner; low minimum speed despite good exit.",
    },
    ("late_apex_excessive", "moderate", "car"): {
        "tip": (
            "Your apex at {corner_name} is {delta_m}m too late, costing {time_loss_s}s. "
            "The car bogs down mid-corner because the line is too tight. "
            "Bring the apex earlier to carry more momentum."
        ),
        "progressive_steps": [
            "Move the apex {step1_m}m earlier and maintain a smoother arc.",
            "Feel the car carry more speed through the middle of the corner.",
            "Verify with sector times that the earlier apex is faster overall.",
        ],
        "symptom_check": "Over-late apex; low minimum speed; tight mid-corner radius.",
    },
    ("late_apex_excessive", "severe", "kart"): {
        "tip": (
            "At {corner_name} your excessively late apex costs {time_loss_s}s. The kart "
            "almost stops mid-corner. You have gone too far with the late-apex concept. "
            "Bring it back significantly."
        ),
        "progressive_steps": [
            "Move the apex {step1_m}m earlier -- it will feel like you are apexing too early but you are not.",
            "Carry {step2_m} km/h more through the mid-corner.",
            "Compare overall corner times to find the optimal balance.",
        ],
        "symptom_check": "Excessively late apex; near-stop mid-corner; wasted entry speed.",
    },
    ("late_apex_excessive", "severe", "car"): {
        "tip": (
            "Your apex at {corner_name} is {delta_m}m too late, costing {time_loss_s}s. "
            "The car is nearly stationary mid-corner despite a good exit. The total "
            "time lost is greater than the exit speed gained. Rebalance the line."
        ),
        "progressive_steps": [
            "Bring the apex {step1_m}m earlier and accept slightly less exit speed.",
            "The mid-corner speed gain will more than compensate.",
            "Find the apex point where total corner time is minimised.",
        ],
        "symptom_check": "Extreme late apex; very low minimum speed; car bogs mid-corner.",
    },

    # -------------------------------------------------------------------------
    # 10. mid_corner_speed_loss
    # -------------------------------------------------------------------------
    ("mid_corner_speed_loss", "mild", "kart"): {
        "tip": (
            "At {corner_name} your minimum speed is {exit_speed_loss_kmh} km/h below the "
            "reference. Carry more momentum through the apex by keeping your hands "
            "smooth and looking to the exit."
        ),
        "progressive_steps": [
            "Focus on a smooth steering input with no sudden corrections.",
            "Carry {step1_m} km/h more through the apex on the next attempt.",
            "Eyes up to the exit and let the kart flow.",
        ],
        "symptom_check": "Minimum corner speed {exit_speed_loss_kmh} km/h below reference.",
    },
    ("mid_corner_speed_loss", "moderate", "kart"): {
        "tip": (
            "You are losing {time_loss_s}s at {corner_name} from low mid-corner speed. "
            "The kart is slowing too much at the apex. Keep your hands smooth, "
            "look to the exit, and trust the grip."
        ),
        "progressive_steps": [
            "Reduce steering angle by taking a slightly wider line.",
            "Carry {step1_m} km/h more through the corner.",
            "Combine with proper trail-braking to maintain front grip.",
        ],
        "symptom_check": "Significant minimum speed drop; excessive steering angle at apex.",
    },
    ("mid_corner_speed_loss", "severe", "kart"): {
        "tip": (
            "At {corner_name} you are losing {time_loss_s}s from very low mid-corner speed. "
            "The kart is practically stopping at the apex. Rethink your line entirely -- "
            "a wider, flowing arc will carry far more speed."
        ),
        "progressive_steps": [
            "Take a wider entry line and reduce peak steering angle.",
            "Focus on maintaining momentum -- smooth, round, flowing.",
            "Build speed progressively once the new line feels natural.",
        ],
        "symptom_check": "Very low minimum speed; near-stop at apex; tight line.",
    },
    ("mid_corner_speed_loss", "mild", "car"): {
        "tip": (
            "At {corner_name} your minimum speed is {exit_speed_loss_kmh} km/h below optimal. "
            "Carry more speed through the apex by looking to the exit and keeping "
            "the steering inputs smooth and progressive."
        ),
        "progressive_steps": [
            "Focus on smooth steering: no sudden inputs.",
            "Carry {step1_m} km/h more through the apex.",
            "Use trail-braking to maintain front grip and speed simultaneously.",
        ],
        "symptom_check": "Minimum speed {exit_speed_loss_kmh} km/h below reference at apex.",
    },
    ("mid_corner_speed_loss", "moderate", "car"): {
        "tip": (
            "You are losing {time_loss_s}s at {corner_name} from low minimum speed. "
            "The car scrubs speed mid-corner because of excess steering angle or "
            "a line that is too tight. Widen the arc slightly."
        ),
        "progressive_steps": [
            "Take a slightly wider line and reduce peak steering angle.",
            "Carry {step1_m} km/h more minimum speed.",
            "Combine with proper trail-braking for an additional boost.",
        ],
        "symptom_check": "Low minimum speed; high steering angle; scrubbing through the apex.",
    },
    ("mid_corner_speed_loss", "severe", "car"): {
        "tip": (
            "At {corner_name} you are losing {time_loss_s}s from critically low mid-corner "
            "speed. The car is bogging down at the apex. Your line, speed, or "
            "technique needs a fundamental rethink at this corner."
        ),
        "progressive_steps": [
            "Study the reference line and compare your GPS trace overlay.",
            "Take a wider, rounder arc that flows through the corner.",
            "Build speed incrementally once the new line is established.",
        ],
        "symptom_check": "Very low minimum speed; car nearly stops; heavy tyre scrub.",
    },

    # -------------------------------------------------------------------------
    # 11. excess_steering_angle
    # -------------------------------------------------------------------------
    ("excess_steering_angle", "mild", "kart"): {
        "tip": (
            "At {corner_name} you are using more steering angle than necessary. "
            "The kart responds better to small, precise inputs. Less is more -- "
            "straighten the wheel slightly and let the kart track a wider arc."
        ),
        "progressive_steps": [
            "Reduce your steering input by 10% and note how the kart responds.",
            "Focus on smooth, gradual turns rather than sharp inputs.",
            "Find the minimum steering angle that clips the apex.",
        ],
        "symptom_check": "Steering angle exceeds reference by {pct_increase}%; slight scrub.",
    },
    ("excess_steering_angle", "mild", "car"): {
        "tip": (
            "You are oversteering the wheel at {corner_name} by {pct_increase}%. "
            "The front tyres are past their slip angle optimum. Dial back the "
            "steering input and let the car follow a natural arc."
        ),
        "progressive_steps": [
            "Reduce steering angle by {step1_m}% on the next lap.",
            "Feel the front tyres grip better with less input.",
            "Find the sweet spot where the car turns without scrubbing.",
        ],
        "symptom_check": "Steering angle {pct_increase}% above optimal; front tyre scrub.",
    },
    ("excess_steering_angle", "moderate", "kart"): {
        "tip": (
            "At {corner_name} excess steering angle is scrubbing speed and costing "
            "{time_loss_s}s. The kart wheels are fighting the surface. Use less lock "
            "and carry more speed -- let the kart flow."
        ),
        "progressive_steps": [
            "Take a wider entry to reduce the required steering angle.",
            "Focus on one smooth steering movement, not sawing back and forth.",
            "Verify that minimum speed improves with less steering input.",
        ],
        "symptom_check": "High steering angle; audible tyre scrub; low mid-corner speed.",
    },
    ("excess_steering_angle", "moderate", "car"): {
        "tip": (
            "You are oversteering at {corner_name} by {pct_increase}%, costing {time_loss_s}s. "
            "The front tyres are past their optimal slip angle and generating drag "
            "instead of grip. Reduce lock and carry more corner speed."
        ),
        "progressive_steps": [
            "Widen the entry line to reduce the steering angle required.",
            "Apply the steering in one smooth motion -- no corrections.",
            "Feel the front tyres grip as you reduce the angle.",
        ],
        "symptom_check": "Front tyres past optimal slip; understeer despite high steering angle.",
    },
    ("excess_steering_angle", "severe", "kart"): {
        "tip": (
            "At {corner_name} your steering angle is so excessive that the kart is "
            "scrubbing heavily, costing {time_loss_s}s. The front wheels are dragging "
            "rather than gripping. Fundamentally change your approach to this corner."
        ),
        "progressive_steps": [
            "Take the widest possible entry and use minimal steering.",
            "Let the kart arc through the corner with a flowing line.",
            "Build steering angle gradually as grip confidence grows.",
        ],
        "symptom_check": "Very high steering angle; heavy scrub; kart visibly slowing mid-corner.",
    },
    ("excess_steering_angle", "severe", "car"): {
        "tip": (
            "Your steering angle at {corner_name} is {pct_increase}% above optimal, "
            "costing {time_loss_s}s. The front tyres are completely saturated. "
            "The car would go faster with less lock. Reduce inputs significantly."
        ),
        "progressive_steps": [
            "Take a much wider entry and barely turn the wheel.",
            "Feel how much faster the car goes with the front tyres in their grip window.",
            "Progressively find the optimal steering angle for maximum corner speed.",
        ],
        "symptom_check": "Front tyres saturated; heavy understeer; high temperature on fronts.",
    },

    # -------------------------------------------------------------------------
    # 12. corner_entry_too_fast
    # -------------------------------------------------------------------------
    ("corner_entry_too_fast", "mild", "kart"): {
        "tip": (
            "At {corner_name} you are entering {exit_speed_loss_kmh} km/h too fast, which "
            "causes a slight push at the apex. Scrub a touch more speed on entry "
            "to carry better flow through the corner."
        ),
        "progressive_steps": [
            "Reduce entry speed by {step1_m} km/h and note the improved apex grip.",
            "Focus on a smooth turn-in without the front washing out.",
            "Carry the improved rotation into a stronger exit.",
        ],
        "symptom_check": "Entry speed {exit_speed_loss_kmh} km/h above reference; slight understeer.",
    },
    ("corner_entry_too_fast", "mild", "car"): {
        "tip": (
            "You are entering {corner_name} {exit_speed_loss_kmh} km/h too fast. The extra "
            "entry speed creates understeer and costs exit speed. Shed a little more "
            "speed on the brakes and feel the car rotate better."
        ),
        "progressive_steps": [
            "Reduce entry speed by {step1_m} km/h.",
            "The car will turn in more crisply without the front washing.",
            "The net result is faster overall corner time despite slower entry.",
        ],
        "symptom_check": "Entry speed above reference; understeer at turn-in.",
    },
    ("corner_entry_too_fast", "moderate", "kart"): {
        "tip": (
            "At {corner_name} you carry too much entry speed, losing {time_loss_s}s from "
            "the resulting understeer and poor exit. Slow down to go faster -- "
            "the kart needs to be set before the corner."
        ),
        "progressive_steps": [
            "Brake {step1_m}m earlier or harder to reduce entry speed by {step2_m} km/h.",
            "Feel the kart grip and rotate through the corner cleanly.",
            "Compare exit speed and verify the overall time is faster.",
        ],
        "symptom_check": "High entry speed; understeer; compromised mid-corner and exit.",
    },
    ("corner_entry_too_fast", "moderate", "car"): {
        "tip": (
            "You are entering {corner_name} too fast, losing {time_loss_s}s. The car "
            "pushes wide at the apex and you cannot get on the throttle. "
            "Slow down to go faster -- control the entry speed."
        ),
        "progressive_steps": [
            "Scrub {step1_m} km/h more before turn-in.",
            "Turn in with confidence and aim for the apex.",
            "Get to full throttle earlier and carry the speed down the straight.",
        ],
        "symptom_check": "High entry speed; persistent understeer; delayed throttle application.",
    },
    ("corner_entry_too_fast", "severe", "kart"): {
        "tip": (
            "At {corner_name} your entry speed is far too high, costing {time_loss_s}s "
            "and {exit_speed_loss_kmh} km/h on exit. The kart washes wide and you lose "
            "everything gained on the straight. Brake properly."
        ),
        "progressive_steps": [
            "Slow down significantly -- brake hard enough to set the kart before the corner.",
            "Focus on a clean, controlled entry before building speed.",
            "Carry momentum through the corner rather than into the corner.",
        ],
        "symptom_check": "Very high entry speed; heavy understeer; poor exit; time lost everywhere.",
    },
    ("corner_entry_too_fast", "severe", "car"): {
        "tip": (
            "You are entering {corner_name} far too fast, losing {time_loss_s}s. "
            "The car exceeds the front tyre grip limit and ploughs through the corner. "
            "This is both a pace and safety issue. Slow down."
        ),
        "progressive_steps": [
            "Reduce entry speed by at least {step1_m} km/h.",
            "Focus on getting the car rotated and pointed at the exit.",
            "Build entry speed back up gradually once the line is correct.",
        ],
        "symptom_check": "Entry speed far above limit; heavy understeer; potential track excursion.",
    },

    # -------------------------------------------------------------------------
    # 13. tightening_radius
    # -------------------------------------------------------------------------
    ("tightening_radius", "mild", "kart"): {
        "tip": (
            "At {corner_name} your line is tightening through the corner. "
            "This means you are adding steering mid-corner, which scrubs speed. "
            "Open the entry slightly to create a line that opens up on exit."
        ),
        "progressive_steps": [
            "Enter {step1_m}m wider and aim for a slightly later apex.",
            "The steering angle should decrease through the corner, not increase.",
            "Feel the kart accelerate naturally as the line opens up.",
        ],
        "symptom_check": "GPS trace shows decreasing radius; steering angle increases mid-corner.",
    },
    ("tightening_radius", "mild", "car"): {
        "tip": (
            "Your line at {corner_name} tightens through the corner, adding drag. "
            "Aim for a line where the radius increases from apex to exit. "
            "This allows you to unwind the steering and get on the power earlier."
        ),
        "progressive_steps": [
            "Enter wider by {step1_m}m and aim for a later apex.",
            "Unwind the steering as you pass the apex.",
            "Get on the throttle earlier as the line opens up.",
        ],
        "symptom_check": "GPS trace shows decreasing radius; additional steering input mid-corner.",
    },
    ("tightening_radius", "moderate", "kart"): {
        "tip": (
            "At {corner_name} your tightening line costs {time_loss_s}s. You are adding "
            "steering angle after the apex, fighting the kart. Change the entry to "
            "create a line that opens up on exit."
        ),
        "progressive_steps": [
            "Enter {step1_m}m wider and delay the apex by {step2_m}m.",
            "The mid-corner should feel wider and more open.",
            "Verify that exit speed improves as the line opens up.",
        ],
        "symptom_check": "Tightening radius; increasing steering angle; time lost on exit.",
    },
    ("tightening_radius", "moderate", "car"): {
        "tip": (
            "Your line at {corner_name} tightens and costs {time_loss_s}s. The car "
            "bogs down because you keep adding lock. Enter wider and aim for a "
            "constant or increasing radius through the corner."
        ),
        "progressive_steps": [
            "Widen entry by {step1_m}m and delay the apex.",
            "Unwind the wheel smoothly from apex to exit.",
            "Get on the power progressively as the line opens.",
        ],
        "symptom_check": "Tightening line; additional steering; exit speed well below reference.",
    },
    ("tightening_radius", "severe", "kart"): {
        "tip": (
            "At {corner_name} your line tightens severely, costing {time_loss_s}s. "
            "You are essentially driving a decreasing radius that kills all momentum. "
            "Completely rethink the entry and apex point."
        ),
        "progressive_steps": [
            "Enter from the widest possible position.",
            "Delay the apex by {step1_m}m and aim for the exit kerb.",
            "The kart should be accelerating from the apex onward, not scrubbing speed.",
        ],
        "symptom_check": "Severely tightening line; near-stop at exit; constant steering addition.",
    },
    ("tightening_radius", "severe", "car"): {
        "tip": (
            "Your line at {corner_name} is severely tightening, costing {time_loss_s}s. "
            "The car is on a spiral that gets tighter and tighter. This must be "
            "fixed with a completely different entry and apex geometry."
        ),
        "progressive_steps": [
            "Study the reference line -- note how it opens up from apex to exit.",
            "Enter wider, apex later, and aim for the exit kerb.",
            "The steering wheel should unwind from apex to exit, never tighten.",
        ],
        "symptom_check": "Severely decreasing radius; car bogs down; potential track limit breach.",
    },

    # -------------------------------------------------------------------------
    # 14. mid_corner_correction
    # -------------------------------------------------------------------------
    ("mid_corner_correction", "mild", "kart"): {
        "tip": (
            "At {corner_name} you are making a small steering correction mid-corner. "
            "This breaks the flow and scrubs speed. The goal is one smooth steering "
            "arc from turn-in to exit."
        ),
        "progressive_steps": [
            "Focus on a single, deliberate steering input at turn-in.",
            "Hold the angle through the corner without adjustments.",
            "If you need to correct, your turn-in speed or angle was wrong -- fix the cause.",
        ],
        "symptom_check": "Small steering correction visible mid-corner; slight speed dip.",
    },
    ("mid_corner_correction", "mild", "car"): {
        "tip": (
            "You make a small steering correction mid-corner at {corner_name}. "
            "This unsettles the car and costs momentum. Aim for one smooth arc "
            "and fix the root cause if corrections are needed."
        ),
        "progressive_steps": [
            "Turn in once with a deliberate, committed steering input.",
            "Hold the angle through the apex without sawing at the wheel.",
            "If corrections happen, adjust entry speed or turn-in point instead.",
        ],
        "symptom_check": "Small steering reversal mid-corner; minor yaw disturbance.",
    },
    ("mid_corner_correction", "moderate", "kart"): {
        "tip": (
            "At {corner_name} your mid-corner correction costs {time_loss_s}s. "
            "The kart changes direction mid-corner because your initial steering "
            "input was not right. Fix the turn-in to eliminate the correction."
        ),
        "progressive_steps": [
            "Slow the entry by {step1_m} km/h to get the initial steering right.",
            "Commit to one steering input and hold it.",
            "Once clean, build entry speed back up incrementally.",
        ],
        "symptom_check": "Notable steering correction mid-corner; yaw spike; speed loss.",
    },
    ("mid_corner_correction", "moderate", "car"): {
        "tip": (
            "Your mid-corner correction at {corner_name} costs {time_loss_s}s. "
            "The car wobbles and loses grip during the correction. Fix the initial "
            "turn-in angle and entry speed to eliminate it."
        ),
        "progressive_steps": [
            "Reduce entry speed slightly to get the turn-in angle right first time.",
            "Commit to one smooth steering arc.",
            "Build speed back once the correction disappears.",
        ],
        "symptom_check": "Steering correction mid-corner; yaw spike of {yaw_spike} deg/s.",
    },
    ("mid_corner_correction", "severe", "kart"): {
        "tip": (
            "At {corner_name} you are making large corrections mid-corner, costing "
            "{time_loss_s}s. The kart is never settled. Your entry is fundamentally "
            "wrong -- slow down and get the initial inputs correct."
        ),
        "progressive_steps": [
            "Slow the entry to 70% and focus on one clean steering input.",
            "Hold the arc and exit cleanly with no corrections.",
            "Build speed over five laps until the correction reappears, then back off.",
        ],
        "symptom_check": "Large steering corrections; multiple direction changes; kart unsettled.",
    },
    ("mid_corner_correction", "severe", "car"): {
        "tip": (
            "Your mid-corner corrections at {corner_name} cost {time_loss_s}s and risk "
            "a spin. The car is never balanced because the initial inputs are wrong. "
            "Slow down, fix the turn-in, and rebuild speed."
        ),
        "progressive_steps": [
            "Reduce entry speed significantly and focus on a clean, single steering arc.",
            "Eliminate all corrections before increasing speed.",
            "Build back to race pace incrementally over multiple runs.",
        ],
        "symptom_check": "Large corrections; potential snap oversteer; car never settled mid-corner.",
    },

    # -------------------------------------------------------------------------
    # 15. late_throttle_application
    # -------------------------------------------------------------------------
    ("late_throttle_application", "mild", "kart"): {
        "tip": (
            "At {corner_name} you are getting on the throttle {delta_m}m later than "
            "the reference. As soon as you pass the apex, eyes up and squeeze the "
            "throttle progressively. Every metre of delay costs exit speed."
        ),
        "progressive_steps": [
            "Start throttle application {step1_m}m earlier -- even a light squeeze counts.",
            "Build to full throttle progressively as the kart straightens.",
            "Target throttle application at {target_delta_m}m past the apex.",
        ],
        "symptom_check": "Throttle application {delta_m}m later than reference after apex.",
    },
    ("late_throttle_application", "mild", "car"): {
        "tip": (
            "You apply the throttle {delta_m}m later than optimal at {corner_name}. "
            "Trust the rear grip and begin squeezing the throttle as you unwind "
            "the steering. Every metre of delay costs you on the following straight."
        ),
        "progressive_steps": [
            "Apply initial throttle {step1_m}m earlier -- start with 10% and build.",
            "Feel the rear tyres load up and the car pull out of the corner.",
            "Target full throttle at {target_delta_m}m after the apex.",
        ],
        "symptom_check": "Throttle onset {delta_m}m after reference; lower exit speed.",
    },
    ("late_throttle_application", "moderate", "kart"): {
        "tip": (
            "At {corner_name} your late throttle costs {time_loss_s}s. You are coasting "
            "from the apex to where you pick up the throttle. Get on the gas -- "
            "the kart needs drive to settle the rear."
        ),
        "progressive_steps": [
            "Apply throttle {step1_m}m earlier -- even maintenance throttle is better than coasting.",
            "Build to full throttle progressively.",
            "The kart should be accelerating from the apex onward.",
        ],
        "symptom_check": "Coast phase between apex and throttle; {time_loss_s}s of dead time.",
    },
    ("late_throttle_application", "moderate", "car"): {
        "tip": (
            "You are losing {time_loss_s}s at {corner_name} from late throttle application. "
            "The car coasts through the exit zone. Be brave -- squeeze the throttle "
            "as you unwind the steering."
        ),
        "progressive_steps": [
            "Apply 20% throttle {step1_m}m earlier and build from there.",
            "Blend throttle application with steering unwind.",
            "The car should accelerate smoothly from apex to track-out.",
        ],
        "symptom_check": "Significant coast phase after apex; delayed throttle onset.",
    },
    ("late_throttle_application", "severe", "kart"): {
        "tip": (
            "At {corner_name} your late throttle costs {time_loss_s}s and {exit_speed_loss_kmh} km/h "
            "on exit. The kart coasts through almost the entire exit. "
            "You must get on the power at the apex -- this is a major gain."
        ),
        "progressive_steps": [
            "Apply throttle at the apex, not after it.",
            "Build to full throttle aggressively as the kart straightens.",
            "Carry the improved exit speed down the entire following straight.",
        ],
        "symptom_check": "Long coast phase; large exit speed deficit; delayed throttle.",
    },
    ("late_throttle_application", "severe", "car"): {
        "tip": (
            "You are losing {time_loss_s}s and {exit_speed_loss_kmh} km/h at {corner_name} "
            "from very late throttle application. The car coasts through the exit. "
            "This cascades into {cascade_time_s}s on the following straight."
        ),
        "progressive_steps": [
            "Begin throttle at the apex point -- even 10% is better than nothing.",
            "Build progressively and aggressively toward full throttle.",
            "Verify exit speed matches reference and carries through to the next brake point.",
        ],
        "symptom_check": "Very late throttle; long coast; major exit and straight-line speed deficit.",
    },

    # -------------------------------------------------------------------------
    # 16. hesitant_throttle
    # -------------------------------------------------------------------------
    ("hesitant_throttle", "mild", "kart"): {
        "tip": (
            "At {corner_name} your throttle application is hesitant -- you apply, "
            "lift slightly, then reapply. Commit to a smooth, progressive squeeze "
            "once you decide to go."
        ),
        "progressive_steps": [
            "Once you apply throttle, do not lift -- only add more.",
            "Build from 20% to 100% in one smooth ramp.",
            "If you need to lift, the corner entry was too fast -- fix that instead.",
        ],
        "symptom_check": "Throttle trace shows a dip of {throttle_drop_pct}% after initial application.",
    },
    ("hesitant_throttle", "mild", "car"): {
        "tip": (
            "Your throttle trace at {corner_name} shows a {throttle_drop_pct}% hesitation "
            "mid-application. Commit to a smooth ramp once you begin. "
            "Trust the rear grip and keep building."
        ),
        "progressive_steps": [
            "Apply throttle and only add more -- never lift mid-corner.",
            "Build smoothly from initial application to full throttle.",
            "If the rear feels loose, reduce initial application rather than lifting.",
        ],
        "symptom_check": "Throttle dip of {throttle_drop_pct}% after initial application.",
    },
    ("hesitant_throttle", "moderate", "kart"): {
        "tip": (
            "At {corner_name} your hesitant throttle costs {time_loss_s}s. The kart "
            "surges and settles as you pump the throttle. Pick a throttle rate "
            "and commit to it smoothly."
        ),
        "progressive_steps": [
            "Start with a lower initial throttle that you can commit to.",
            "Build smoothly without any lifts or dips.",
            "Once confident, increase the initial application rate.",
        ],
        "symptom_check": "Multiple throttle oscillations on exit; speed fluctuations.",
    },
    ("hesitant_throttle", "moderate", "car"): {
        "tip": (
            "Your throttle hesitation at {corner_name} costs {time_loss_s}s. The car "
            "lurches as you pump the throttle, unsettling the rear. "
            "Commit to a smooth, progressive application."
        ),
        "progressive_steps": [
            "Start with 15% throttle and build smoothly to full.",
            "Never lift once you have started applying.",
            "If the rear is loose, fix the line or entry speed, not the throttle.",
        ],
        "symptom_check": "Throttle oscillation; rear tyre temp spikes from on-off loading.",
    },
    ("hesitant_throttle", "severe", "kart"): {
        "tip": (
            "At {corner_name} your throttle pumping costs {time_loss_s}s. The kart is "
            "constantly unsettled on exit because the throttle is on-off-on. "
            "This must be replaced with one smooth ramp."
        ),
        "progressive_steps": [
            "Practice exits at 60% speed with one smooth throttle ramp.",
            "Once the technique is ingrained, build to race speed.",
            "The kart should feel planted and progressive on exit.",
        ],
        "symptom_check": "Heavy throttle pumping; kart unstable on exit; large exit speed loss.",
    },
    ("hesitant_throttle", "severe", "car"): {
        "tip": (
            "Your throttle at {corner_name} is severely hesitant, costing {time_loss_s}s. "
            "The car lurches and the rear tyres cycle between grip and slip. "
            "This is a confidence issue -- commit to a smooth ramp."
        ),
        "progressive_steps": [
            "Practice smooth throttle application in a straight line first.",
            "Transfer the technique to corner exits at reduced speed.",
            "Build to full speed once the throttle trace is clean.",
        ],
        "symptom_check": "Severe throttle pumping; rear instability; traction control intervention.",
    },

    # -------------------------------------------------------------------------
    # 17. mid_corner_lift
    # -------------------------------------------------------------------------
    ("mid_corner_lift", "mild", "kart"): {
        "tip": (
            "At {corner_name} you lift the throttle briefly mid-corner for {lift_duration_s}s. "
            "This shifts weight to the front and can cause a snap. "
            "Maintain steady throttle through the corner."
        ),
        "progressive_steps": [
            "Hold maintenance throttle through the entire corner.",
            "If the kart pushes, reduce entry speed rather than lifting mid-corner.",
            "Eliminate the lift and feel the kart stay balanced.",
        ],
        "symptom_check": "Brief throttle lift of {lift_duration_s}s mid-corner.",
    },
    ("mid_corner_lift", "mild", "car"): {
        "tip": (
            "You lift the throttle briefly at {corner_name} mid-corner for {lift_duration_s}s. "
            "This weight transfer destabilises the car. Maintain a constant throttle "
            "through the corner and address the root cause."
        ),
        "progressive_steps": [
            "Hold 5-10% throttle through the corner as maintenance.",
            "If the car is loose, reduce entry speed.",
            "Keep the throttle trace flat through the mid-corner.",
        ],
        "symptom_check": "Brief throttle lift mid-corner; weight transfer to front.",
    },
    ("mid_corner_lift", "moderate", "kart"): {
        "tip": (
            "At {corner_name} your mid-corner lift costs {time_loss_s}s. The kart "
            "unsettles and you lose momentum. Keep your foot steady through the "
            "corner -- the lift is making things worse, not better."
        ),
        "progressive_steps": [
            "Reduce entry speed so you do not need to lift mid-corner.",
            "Maintain constant throttle from turn-in to the exit phase.",
            "Once stable, begin adding throttle progressively from the apex.",
        ],
        "symptom_check": "Throttle lift of {lift_duration_s}s; speed dip; weight shift.",
    },
    ("mid_corner_lift", "moderate", "car"): {
        "tip": (
            "Your mid-corner lift at {corner_name} costs {time_loss_s}s. The car "
            "snaps forward under deceleration and unsettles the rear. "
            "Fix the entry speed or line to eliminate the need to lift."
        ),
        "progressive_steps": [
            "Enter slower to maintain throttle through the corner.",
            "Hold a constant 10-15% throttle through the mid-corner.",
            "Build to a clean throttle ramp from apex to exit.",
        ],
        "symptom_check": "Significant throttle lift; weight shift; rear grip loss.",
    },
    ("mid_corner_lift", "severe", "kart"): {
        "tip": (
            "At {corner_name} your prolonged mid-corner lift of {lift_duration_s}s costs "
            "{time_loss_s}s. The kart is completely unsettled. This is usually "
            "caused by entering too fast. Slow down and keep the throttle steady."
        ),
        "progressive_steps": [
            "Reduce entry speed by {step1_m} km/h to eliminate the need to lift.",
            "Maintain constant throttle through the entire corner.",
            "Build speed only once the lift is completely gone.",
        ],
        "symptom_check": "Long throttle lift; kart destabilised; major speed loss.",
    },
    ("mid_corner_lift", "severe", "car"): {
        "tip": (
            "Your prolonged mid-corner lift at {corner_name} costs {time_loss_s}s and "
            "destabilises the car dangerously. The rear loses grip under the "
            "sudden weight transfer. Fix the entry to eliminate this."
        ),
        "progressive_steps": [
            "Slow the entry significantly to avoid needing to lift.",
            "Hold constant throttle through the entire corner.",
            "Rebuild entry speed gradually once the lift is eliminated.",
        ],
        "symptom_check": "Prolonged throttle lift; snap oversteer risk; large time loss.",
    },

    # -------------------------------------------------------------------------
    # 18. poor_exit_speed
    # -------------------------------------------------------------------------
    ("poor_exit_speed", "mild", "kart"): {
        "tip": (
            "At {corner_name} your exit speed is {exit_speed_loss_kmh} km/h below the "
            "reference. Get your eyes up to the exit, straighten the wheel, and "
            "squeeze the throttle early."
        ),
        "progressive_steps": [
            "Apply throttle {step1_m}m earlier than current.",
            "Unwind the steering as you add throttle.",
            "Carry the extra speed down the following straight.",
        ],
        "symptom_check": "Exit speed {exit_speed_loss_kmh} km/h below reference.",
    },
    ("poor_exit_speed", "mild", "car"): {
        "tip": (
            "Your exit speed at {corner_name} is {exit_speed_loss_kmh} km/h below optimal. "
            "Combine an earlier throttle application with smooth steering unwind "
            "to maximise drive out of the corner."
        ),
        "progressive_steps": [
            "Get on the throttle {step1_m}m earlier.",
            "Unwind the steering progressively to straighten the car.",
            "Verify the speed gain carries through to the next corner.",
        ],
        "symptom_check": "Exit speed {exit_speed_loss_kmh} km/h low; throttle application delayed.",
    },
    ("poor_exit_speed", "moderate", "kart"): {
        "tip": (
            "At {corner_name} your poor exit speed costs {time_loss_s}s and cascades "
            "into the next section. The kart needs drive from the apex onward. "
            "Fix the line and throttle application together."
        ),
        "progressive_steps": [
            "Ensure you apex late enough that the exit opens up.",
            "Apply throttle at the apex and build progressively.",
            "The kart should be at full throttle before the track-out point.",
        ],
        "symptom_check": "Low exit speed; late throttle; tight exit line.",
    },
    ("poor_exit_speed", "moderate", "car"): {
        "tip": (
            "Your exit speed at {corner_name} is {exit_speed_loss_kmh} km/h low, costing "
            "{time_loss_s}s. The car is not driving out of the corner properly. "
            "Combine a better line with earlier throttle application."
        ),
        "progressive_steps": [
            "Fix the apex point to open up the exit.",
            "Apply throttle as you unwind the steering.",
            "Target full throttle before the track-out kerb.",
        ],
        "symptom_check": "Exit speed deficit; late throttle; restricted exit line.",
    },
    ("poor_exit_speed", "severe", "kart"): {
        "tip": (
            "At {corner_name} your exit speed is {exit_speed_loss_kmh} km/h below reference, "
            "costing {time_loss_s}s and cascading {cascade_time_s}s into the straight. "
            "This is likely a combination of early apex, late throttle, and a "
            "tightening line. Fix all three together."
        ),
        "progressive_steps": [
            "Move the apex later to open the exit.",
            "Get on the throttle at the apex.",
            "Unwind the steering and get the kart straight as early as possible.",
        ],
        "symptom_check": "Very low exit speed; multiple contributing causes; large cascade loss.",
    },
    ("poor_exit_speed", "severe", "car"): {
        "tip": (
            "Your exit speed at {corner_name} is {exit_speed_loss_kmh} km/h below reference, "
            "costing {time_loss_s}s with a {cascade_time_s}s cascade. This is the "
            "biggest single gain available. Fix the line, apex, and throttle together."
        ),
        "progressive_steps": [
            "Late apex to open the exit geometry.",
            "Apply throttle at the apex and build aggressively.",
            "Unwind steering and point the car at the track-out kerb.",
        ],
        "symptom_check": "Severe exit speed deficit; cascade through straight; multiple root causes.",
    },

    # -------------------------------------------------------------------------
    # 19. track_out_not_used
    # -------------------------------------------------------------------------
    ("track_out_not_used", "mild", "kart"): {
        "tip": (
            "At {corner_name} you are not using the full track width on exit. "
            "There is {delta_m}m of unused tarmac. Let the kart drift to the "
            "outside on exit -- this straightens the line and adds exit speed."
        ),
        "progressive_steps": [
            "Allow the kart to run {step1_m}m wider on exit.",
            "Use the kerb as a reference -- aim to brush it.",
            "Feel the line straighten and the exit speed improve.",
        ],
        "symptom_check": "GPS trace {delta_m}m inside the track-out kerb.",
    },
    ("track_out_not_used", "mild", "car"): {
        "tip": (
            "You are leaving {delta_m}m of track unused on exit at {corner_name}. "
            "Let the car drift to the outside and use every centimetre of tarmac. "
            "A wider exit means a straighter line and more speed."
        ),
        "progressive_steps": [
            "Allow the car to run {step1_m}m wider on exit.",
            "Aim for the exit kerb as your target.",
            "The wider line lets you straighten the wheel and apply full throttle earlier.",
        ],
        "symptom_check": "GPS trace {delta_m}m inside track-out; tighter exit than needed.",
    },
    ("track_out_not_used", "moderate", "kart"): {
        "tip": (
            "At {corner_name} you leave {delta_m}m of track unused on exit, costing "
            "{time_loss_s}s. The kart is on a tighter exit arc than necessary. "
            "Open up and use the full width."
        ),
        "progressive_steps": [
            "Aim for the outside kerb on exit.",
            "Let the kart drift out naturally under power.",
            "Feel the exit speed improve as the line straightens.",
        ],
        "symptom_check": "Track-out {delta_m}m narrow; exit line is restricted.",
    },
    ("track_out_not_used", "moderate", "car"): {
        "tip": (
            "You leave {delta_m}m of track unused at {corner_name}, costing {time_loss_s}s. "
            "The car is on a tight exit arc. Use the full width to straighten "
            "the line and carry more exit speed."
        ),
        "progressive_steps": [
            "Target the exit kerb -- let the car drift out under power.",
            "Unwind the steering fully and use the whole road.",
            "Verify exit speed improves by {exit_speed_loss_kmh} km/h.",
        ],
        "symptom_check": "Narrow track-out; still turning at exit; speed left on the table.",
    },
    ("track_out_not_used", "severe", "kart"): {
        "tip": (
            "At {corner_name} you use only half the track on exit, costing {time_loss_s}s. "
            "The kart is still cornering when it should be accelerating. "
            "Aim for the outside kerb and use every centimetre."
        ),
        "progressive_steps": [
            "On the next lap, force yourself to reach the exit kerb.",
            "Let the kart drift out naturally -- do not steer it back.",
            "Feel the massive exit speed gain as the line opens up.",
        ],
        "symptom_check": "GPS shows half track unused on exit; severe exit speed deficit.",
    },
    ("track_out_not_used", "severe", "car"): {
        "tip": (
            "You leave a huge amount of track unused at {corner_name}, costing {time_loss_s}s. "
            "The car is on a very tight exit arc. This is a major gain -- aim for "
            "the exit kerb and let the car use the full road."
        ),
        "progressive_steps": [
            "Commit to reaching the exit kerb on every lap.",
            "Unwind the steering fully and apply full throttle.",
            "The exit speed gain will compound down the entire following straight.",
        ],
        "symptom_check": "Very narrow track-out; still heavily cornering at exit; big time loss.",
    },

    # -------------------------------------------------------------------------
    # 20. lap_time_variation
    # -------------------------------------------------------------------------
    ("lap_time_variation", "mild", "kart"): {
        "tip": (
            "Your lap times vary by {variance_m}s, which is slightly above the "
            "consistency target. Focus on repeating the same inputs at every corner "
            "rather than pushing for ultimate pace."
        ),
        "progressive_steps": [
            "Pick a target lap time and aim for it within 0.3s for ten laps.",
            "Identify which corner has the most variation and stabilise it.",
            "Once consistent, begin pushing the target time lower.",
        ],
        "symptom_check": "Lap time standard deviation of {variance_m}s across a stint.",
    },
    ("lap_time_variation", "mild", "car"): {
        "tip": (
            "Your lap time variation of {variance_m}s is above the target for consistency. "
            "Before chasing outright speed, build repeatability. "
            "Consistent inputs produce consistent results."
        ),
        "progressive_steps": [
            "Set a target time and hit it within 0.3s for ten consecutive laps.",
            "Use sector times to identify the least consistent section.",
            "Stabilise that section before pushing harder.",
        ],
        "symptom_check": "Lap time variation {variance_m}s; inconsistent sector times.",
    },
    ("lap_time_variation", "moderate", "kart"): {
        "tip": (
            "Your lap times vary by {variance_m}s, costing you race positions through "
            "unpredictability. A consistent driver is harder to overtake and easier "
            "to strategise with. Smooth out the inputs."
        ),
        "progressive_steps": [
            "Lock in your braking points and throttle application points.",
            "Drive at 95% and focus on repeating the same lap.",
            "Once consistent, push one corner at a time to lower the target.",
        ],
        "symptom_check": "Moderate lap time scatter; inconsistency across multiple corners.",
    },
    ("lap_time_variation", "moderate", "car"): {
        "tip": (
            "Your lap time variation of {variance_m}s is costing you race pace. "
            "Inconsistency means you are fast on some laps but slow on others, "
            "and the slow laps are the ones that matter. Build consistency first."
        ),
        "progressive_steps": [
            "Drive at 90-95% for a full stint and monitor the spread.",
            "Identify the two corners with the most variation.",
            "Lock in consistent inputs at those corners before pushing.",
        ],
        "symptom_check": "Large lap time variation; sector time inconsistency.",
    },
    ("lap_time_variation", "severe", "kart"): {
        "tip": (
            "Your lap times vary by {variance_m}s, which is far too much. "
            "You are essentially driving a different lap every time. "
            "Slow down to a sustainable pace and build from a consistent base."
        ),
        "progressive_steps": [
            "Drive five laps at 80% and aim for identical times.",
            "Add 2% pace every five laps while maintaining consistency.",
            "Stop adding pace when the variation exceeds 0.5s.",
        ],
        "symptom_check": "Severe lap time scatter; no two laps are the same.",
    },
    ("lap_time_variation", "severe", "car"): {
        "tip": (
            "Your lap time variation of {variance_m}s is extremely high. "
            "No meaningful improvement can be made until you are repeatable. "
            "Slow down significantly and build a consistent base."
        ),
        "progressive_steps": [
            "Drive at 75% for ten laps and aim for identical times.",
            "Increase pace by 5% every five laps.",
            "Stop when variation exceeds 0.5s and consolidate.",
        ],
        "symptom_check": "Extreme variation; different inputs every lap; no pattern.",
    },

    # -------------------------------------------------------------------------
    # 21. corner_speed_variation
    # -------------------------------------------------------------------------
    ("corner_speed_variation", "mild", "kart"): {
        "tip": (
            "At {corner_name} your speed varies by {variance_m} km/h lap to lap. "
            "This makes it hard to build on improvements. Lock in a consistent "
            "entry and mid-corner speed before optimising."
        ),
        "progressive_steps": [
            "Hit the same entry speed within 1 km/h for five laps.",
            "Monitor minimum speed for consistency.",
            "Once stable, begin pushing the speeds higher.",
        ],
        "symptom_check": "Corner speed varies by {variance_m} km/h across laps.",
    },
    ("corner_speed_variation", "mild", "car"): {
        "tip": (
            "Your speed at {corner_name} varies by {variance_m} km/h, indicating "
            "inconsistent inputs. Consistency at each corner compounds into consistent "
            "lap times. Stabilise this corner first."
        ),
        "progressive_steps": [
            "Fix your braking point and entry speed within 2 km/h.",
            "Verify minimum speed is consistent.",
            "Push the speeds higher once the variation is under 1 km/h.",
        ],
        "symptom_check": "Speed variation {variance_m} km/h at this corner.",
    },
    ("corner_speed_variation", "moderate", "kart"): {
        "tip": (
            "At {corner_name} your speed varies by {variance_m} km/h, making this "
            "corner unpredictable. You cannot improve what you cannot repeat. "
            "Lock in the same inputs every lap."
        ),
        "progressive_steps": [
            "Choose a conservative, repeatable speed for five laps.",
            "Tighten the variation to under 1 km/h.",
            "Then push the speed higher while maintaining consistency.",
        ],
        "symptom_check": "Moderate speed variation; different entry conditions each lap.",
    },
    ("corner_speed_variation", "moderate", "car"): {
        "tip": (
            "Your speed at {corner_name} varies by {variance_m} km/h. The car experiences "
            "different conditions every lap because your inputs change. "
            "Build consistency before chasing outright speed."
        ),
        "progressive_steps": [
            "Drive at 90% and aim for the same speed every lap.",
            "Reduce variation to under 2 km/h.",
            "Increase pace incrementally once consistent.",
        ],
        "symptom_check": "Significant speed variation; inconsistent corner performance.",
    },
    ("corner_speed_variation", "severe", "kart"): {
        "tip": (
            "At {corner_name} your speed varies by {variance_m} km/h, which is far "
            "too much. Every lap is different. Slow down and find a repeatable "
            "speed before anything else."
        ),
        "progressive_steps": [
            "Drive the corner at 70% and repeat ten times identically.",
            "Increase speed by 2 km/h and repeat.",
            "Stop when variation exceeds 2 km/h.",
        ],
        "symptom_check": "Extreme speed variation; no repeatable baseline.",
    },
    ("corner_speed_variation", "severe", "car"): {
        "tip": (
            "Your speed at {corner_name} varies by {variance_m} km/h -- each lap is "
            "fundamentally different. No technique can be developed without "
            "repeatability. Slow down and find a stable baseline."
        ),
        "progressive_steps": [
            "Drive the corner well below the limit and repeat for ten laps.",
            "Verify speed variation is under 2 km/h.",
            "Build speed incrementally from that stable base.",
        ],
        "symptom_check": "Extreme speed scatter; no two laps are comparable.",
    },

    # -------------------------------------------------------------------------
    # 22. late_session_degradation
    # -------------------------------------------------------------------------
    ("late_session_degradation", "mild", "kart"): {
        "tip": (
            "Your lap times drift up by {time_loss_s}s in the final third of the "
            "session. This may be fatigue or tyre wear. Focus on staying smooth "
            "and disciplined as the session progresses."
        ),
        "progressive_steps": [
            "Monitor your braking points in the final ten minutes -- are they drifting earlier?",
            "Stay hydrated and focused; take a breath on the straights.",
            "If tyres are degrading, adjust your driving to be gentler on them.",
        ],
        "symptom_check": "Lap times increase by {time_loss_s}s in the final third.",
    },
    ("late_session_degradation", "mild", "car"): {
        "tip": (
            "Your pace drops by {time_loss_s}s in the last third of the session. "
            "This is common and often caused by tyre degradation or driver fatigue. "
            "Manage both proactively."
        ),
        "progressive_steps": [
            "Monitor tyre grip: are you braking earlier or carrying less speed?",
            "Adjust your inputs slightly to compensate for reduced grip.",
            "Stay mentally sharp -- use the straights to reset your focus.",
        ],
        "symptom_check": "Pace degrades by {time_loss_s}s late in the session.",
    },
    ("late_session_degradation", "moderate", "kart"): {
        "tip": (
            "Your lap times drop off by {time_loss_s}s in the final third. "
            "You are either physically fatigued or over-driving degraded tyres. "
            "Both problems have the same solution: be smoother."
        ),
        "progressive_steps": [
            "Reduce effort by 5% in the final third to maintain consistency.",
            "Focus on smooth inputs rather than aggressive ones.",
            "Track which corners degrade most and adapt your approach.",
        ],
        "symptom_check": "Moderate pace loss; braking earlier; less corner speed late in stint.",
    },
    ("late_session_degradation", "moderate", "car"): {
        "tip": (
            "Your pace drops {time_loss_s}s in the final third. The car has less grip "
            "and you may be physically tired. Adapt your driving style to the "
            "conditions rather than fighting them."
        ),
        "progressive_steps": [
            "Back off your inputs by 5% to match the reduced grip.",
            "Be gentler on the tyres to slow the degradation.",
            "Stay hydrated and use breathing techniques to maintain focus.",
        ],
        "symptom_check": "Pace drops; tyre performance degrades; driver inputs become less precise.",
    },
    ("late_session_degradation", "severe", "kart"): {
        "tip": (
            "Your lap times degrade by {time_loss_s}s in the final third -- this is "
            "a major issue. You are either physically unfit, over-driving the tyres, "
            "or losing concentration. Address all three."
        ),
        "progressive_steps": [
            "Improve physical fitness: neck, arms, core conditioning.",
            "Drive the first two-thirds at 95% to preserve tyres for the end.",
            "Practice mental focus exercises to maintain concentration.",
        ],
        "symptom_check": "Severe pace loss late; multiple corners affected; inputs degraded.",
    },
    ("late_session_degradation", "severe", "car"): {
        "tip": (
            "Your pace drops {time_loss_s}s in the final third -- a severe degradation. "
            "This is a combination of physical fatigue, tyre wear, and potentially "
            "overheating brakes. Manage the session as a whole, not just the fast laps."
        ),
        "progressive_steps": [
            "Build physical endurance: cardio + strength training.",
            "Manage tyre life by being smoother earlier in the session.",
            "Use cool-down laps strategically to manage brake and tyre temperatures.",
        ],
        "symptom_check": "Major pace loss; brakes fading; tyres gone; driver fatigued.",
    },

    # -------------------------------------------------------------------------
    # 23. sector_imbalance
    # -------------------------------------------------------------------------
    ("sector_imbalance", "mild", "kart"): {
        "tip": (
            "Your sector times show a mild imbalance -- you are strong in one "
            "section but leaving time in another. Balance your effort across "
            "the whole lap for a lower overall time."
        ),
        "progressive_steps": [
            "Identify the weakest sector from the telemetry.",
            "Spend three laps focusing only on that sector.",
            "Balance effort until all sectors are within 0.2s of their target.",
        ],
        "symptom_check": "Sector time imbalance; one sector significantly slower.",
    },
    ("sector_imbalance", "mild", "car"): {
        "tip": (
            "Your sector times show mild imbalance. Focusing on the weakest sector "
            "will yield more lap time than polishing the strongest one. "
            "Balance your effort across the whole lap."
        ),
        "progressive_steps": [
            "Review sector-by-sector comparisons with the reference.",
            "Prioritise the weakest sector for the next session.",
            "Aim for balanced sector times rather than one standout sector.",
        ],
        "symptom_check": "Sector imbalance; one sector significantly behind reference.",
    },
    ("sector_imbalance", "moderate", "kart"): {
        "tip": (
            "Your sectors are noticeably unbalanced, losing {time_loss_s}s in your "
            "weakest section. You are over-focusing on your strongest corners "
            "and neglecting others. Redistribute your attention."
        ),
        "progressive_steps": [
            "Identify the two weakest corners within the slow sector.",
            "Focus exclusively on those corners for the next outing.",
            "Balance all sectors within 0.3s of their targets.",
        ],
        "symptom_check": "One sector significantly slower; effort concentrated elsewhere.",
    },
    ("sector_imbalance", "moderate", "car"): {
        "tip": (
            "Your sector imbalance costs {time_loss_s}s. The weakest sector has "
            "clear issues that are easier to fix than squeezing more from the "
            "strong sectors. Focus your practice where the gains are."
        ),
        "progressive_steps": [
            "Analyse the weakest sector corner by corner.",
            "Apply the specific tips for each corner in that sector.",
            "Rebalance until no sector is more than 0.3s off target.",
        ],
        "symptom_check": "Clear sector imbalance; easy gains available in weak sector.",
    },
    ("sector_imbalance", "severe", "kart"): {
        "tip": (
            "Your sectors are severely unbalanced, with {time_loss_s}s lost in the "
            "weakest section. You are fast in one part of the track and slow in "
            "another. Dedicate entire sessions to the weak sector."
        ),
        "progressive_steps": [
            "Spend an entire session focusing only on the weak sector.",
            "Apply all relevant corner tips for that section.",
            "Bring the weak sector within 0.5s of the target before moving on.",
        ],
        "symptom_check": "Severe sector imbalance; large time loss concentrated in one area.",
    },
    ("sector_imbalance", "severe", "car"): {
        "tip": (
            "Your sector imbalance costs {time_loss_s}s, concentrated in the weakest "
            "section. This is your biggest opportunity. The strong sectors show "
            "you have the skill -- apply it to the weak ones."
        ),
        "progressive_steps": [
            "Study the weak sector in detail: braking, lines, throttle at each corner.",
            "Spend entire sessions on that sector.",
            "Balance all sectors before pursuing outright pace.",
        ],
        "symptom_check": "Severe sector imbalance; skill is present but unevenly applied.",
    },

    # -------------------------------------------------------------------------
    # 24. tyre_abuse
    # -------------------------------------------------------------------------
    ("tyre_abuse", "mild", "kart"): {
        "tip": (
            "You are slightly over-working the tyres at {corner_name}, showing "
            "{pct_increase}% excess slip. Be gentler with your inputs to preserve "
            "the tyre surface and maintain grip later in the session."
        ),
        "progressive_steps": [
            "Reduce peak steering angle slightly.",
            "Smooth your throttle application on exit.",
            "Monitor tyre temps and aim for even wear.",
        ],
        "symptom_check": "Tyre slip {pct_increase}% above optimal; slight graining.",
    },
    ("tyre_abuse", "mild", "car"): {
        "tip": (
            "At {corner_name} you are generating {pct_increase}% excess tyre slip. "
            "The tyres are working harder than they need to. Smoother inputs "
            "will preserve grip for the entire stint."
        ),
        "progressive_steps": [
            "Reduce peak steering input by 5%.",
            "Apply throttle more progressively on exit.",
            "Compare tyre degradation rates across stints.",
        ],
        "symptom_check": "Excess tyre slip; early degradation signs; slight overheating.",
    },
    ("tyre_abuse", "moderate", "kart"): {
        "tip": (
            "You are abusing the tyres at {corner_name}, showing {pct_increase}% "
            "excess slip and losing grip mid-session. Smoother driving is faster "
            "over a full stint. Treat the tyres as a resource."
        ),
        "progressive_steps": [
            "Reduce aggressive inputs at entry and exit.",
            "Focus on smooth weight transfers.",
            "Monitor grip level changes across the session.",
        ],
        "symptom_check": "Significant excess slip; tyre degradation visible mid-session.",
    },
    ("tyre_abuse", "moderate", "car"): {
        "tip": (
            "At {corner_name} you are significantly over-working the tyres with "
            "{pct_increase}% excess slip, losing grip noticeably by mid-stint. "
            "The fast drivers are smooth to preserve their tyres."
        ),
        "progressive_steps": [
            "Be 10% smoother on all inputs at this corner.",
            "Reduce peak slip angle by adjusting your line.",
            "Compare your tyre life to the reference driver.",
        ],
        "symptom_check": "Tyre overheating; grip drop-off mid-stint; high wear rate.",
    },
    ("tyre_abuse", "severe", "kart"): {
        "tip": (
            "You are destroying the tyres at {corner_name} with {pct_increase}% excess slip. "
            "The grip falls off dramatically and your late-session pace suffers. "
            "You must be much gentler -- smooth is fast."
        ),
        "progressive_steps": [
            "Reduce all inputs by 15% at this corner.",
            "Focus on flowing through the corner rather than fighting it.",
            "Monitor grip retention across a full session.",
        ],
        "symptom_check": "Severe tyre abuse; rapid degradation; large pace drop-off.",
    },
    ("tyre_abuse", "severe", "car"): {
        "tip": (
            "At {corner_name} your driving is destroying the tyres -- {pct_increase}% "
            "excess slip. The grip window closes rapidly and late-stint pace "
            "is severely compromised. Fundamentally change your approach."
        ),
        "progressive_steps": [
            "Reduce all inputs significantly -- drive at 85% effort.",
            "Observe how much longer the tyres last.",
            "Build speed back gradually while preserving tyre life.",
        ],
        "symptom_check": "Severe tyre abuse; rapid overheating; grip collapses.",
    },

    # -------------------------------------------------------------------------
    # 25. fuel_weight_unadjusted
    # -------------------------------------------------------------------------
    ("fuel_weight_unadjusted", "mild", "kart"): {
        "tip": (
            "Your driving does not account for the fuel load change during the "
            "session. As the kart gets lighter, you can brake later and carry "
            "more speed. Adjust your reference points as fuel burns off."
        ),
        "progressive_steps": [
            "Note your lap time trend -- it should improve as fuel burns.",
            "Move braking points {step1_m}m later as the session progresses.",
            "Carry {step2_m} km/h more corner speed in the final third.",
        ],
        "symptom_check": "Lap times do not improve as fuel weight decreases.",
    },
    ("fuel_weight_unadjusted", "mild", "car"): {
        "tip": (
            "You are not adjusting for fuel weight as the stint progresses. "
            "The car gets lighter and faster -- your braking points and corner "
            "speeds should evolve accordingly."
        ),
        "progressive_steps": [
            "Move braking points {step1_m}m later every 10 laps.",
            "Carry progressively more corner speed as weight drops.",
            "Target lap times that improve in line with fuel burn rate.",
        ],
        "symptom_check": "Flat lap time trend despite decreasing fuel weight.",
    },
    ("fuel_weight_unadjusted", "moderate", "kart"): {
        "tip": (
            "You are losing {time_loss_s}s by not adjusting for fuel weight. "
            "The kart is lighter but you drive it the same way. Adapt your "
            "reference points as the session progresses."
        ),
        "progressive_steps": [
            "After 10 laps, move all braking points {step1_m}m later.",
            "Increase corner speeds by 1-2 km/h as the kart lightens.",
            "Target a natural lap-time improvement curve.",
        ],
        "symptom_check": "Lap times flat despite {weight_shift_kg}kg of fuel burned.",
    },
    ("fuel_weight_unadjusted", "moderate", "car"): {
        "tip": (
            "You are leaving {time_loss_s}s on the table by not adjusting for "
            "fuel burn. As the car sheds {weight_shift_kg}kg, the braking distances "
            "shorten and corner speeds increase. Adapt your driving."
        ),
        "progressive_steps": [
            "Adjust braking points {step1_m}m later per 10kg of fuel burned.",
            "Carry more speed in corners as weight decreases.",
            "Monitor the gap between actual and expected pace improvement.",
        ],
        "symptom_check": "Pace does not improve with fuel burn; static reference points.",
    },
    ("fuel_weight_unadjusted", "severe", "kart"): {
        "tip": (
            "You lose {time_loss_s}s from not adapting to fuel weight changes. "
            "At the end of the session the kart is significantly lighter but "
            "you brake at the same points and carry the same speed. Adapt."
        ),
        "progressive_steps": [
            "Learn the weight delta from full to empty.",
            "Adjust all references progressively through the session.",
            "Your final laps should be your fastest if tyres allow.",
        ],
        "symptom_check": "Significant pace left on table; no adaptation to fuel burn.",
    },
    ("fuel_weight_unadjusted", "severe", "car"): {
        "tip": (
            "You are losing {time_loss_s}s by not adapting to fuel burn. "
            "The car sheds {weight_shift_kg}kg over the stint but your driving "
            "stays the same. This is free lap time -- take it."
        ),
        "progressive_steps": [
            "Calculate the expected pace improvement per 10kg of fuel.",
            "Adjust braking points and corner speeds progressively.",
            "Your final laps should approach your best if tyres are managed.",
        ],
        "symptom_check": "Large pace deficit late in stint; static inputs despite lighter car.",
    },

    # -------------------------------------------------------------------------
    # 26. kerb_avoidance
    # -------------------------------------------------------------------------
    ("kerb_avoidance", "mild", "kart"): {
        "tip": (
            "At {corner_name} you are avoiding the kerbs by {delta_m}m. "
            "Using the kerbs extends the effective track width and straightens "
            "your line. They are there to be used."
        ),
        "progressive_steps": [
            "Approach the inside kerb by {step1_m}m on the next lap.",
            "Brush the kerb lightly at the apex.",
            "Use the outside kerb on exit to widen the line.",
        ],
        "symptom_check": "GPS trace {delta_m}m away from kerbs; narrow line.",
    },
    ("kerb_avoidance", "mild", "car"): {
        "tip": (
            "You are avoiding the kerbs at {corner_name} by {delta_m}m. "
            "Using the kerbs extends the track and opens up the line. "
            "Start using them progressively to straighten your path."
        ),
        "progressive_steps": [
            "Move {step1_m}m closer to the inside kerb.",
            "Use the kerb at the apex to widen the effective radius.",
            "Include the exit kerb in your track-out to straighten the line.",
        ],
        "symptom_check": "GPS trace {delta_m}m away from kerbs; not using full track.",
    },
    ("kerb_avoidance", "moderate", "kart"): {
        "tip": (
            "At {corner_name} you are {delta_m}m away from the kerbs, costing "
            "{time_loss_s}s. The kart can handle the kerbs -- they widen the "
            "effective track and open up faster lines."
        ),
        "progressive_steps": [
            "Move onto the inside kerb at the apex.",
            "Ride the kerb with confidence -- the kart is designed for it.",
            "Use the exit kerb to maximise track-out width.",
        ],
        "symptom_check": "Significant kerb avoidance; narrow line; time left on table.",
    },
    ("kerb_avoidance", "moderate", "car"): {
        "tip": (
            "You avoid the kerbs at {corner_name} by {delta_m}m, losing {time_loss_s}s. "
            "The kerbs extend the usable track by up to a metre on each side. "
            "Use them to straighten the line and carry more speed."
        ),
        "progressive_steps": [
            "Attack the inside kerb at the apex -- mount it fully.",
            "Use the exit kerb for maximum track-out.",
            "Verify the wider line carries more speed and lowers corner time.",
        ],
        "symptom_check": "Significant kerb avoidance; restricted line; pace left behind.",
    },
    ("kerb_avoidance", "severe", "kart"): {
        "tip": (
            "At {corner_name} you stay {delta_m}m away from all kerbs, costing {time_loss_s}s. "
            "You are effectively driving on a narrower track than everyone else. "
            "The kerbs are safe and fast -- use them aggressively."
        ),
        "progressive_steps": [
            "Commit to riding the inside kerb at every apex.",
            "Use the exit kerb on every corner exit.",
            "Feel the extra track width translate directly into faster lap times.",
        ],
        "symptom_check": "Severe kerb avoidance; very narrow line; large time loss.",
    },
    ("kerb_avoidance", "severe", "car"): {
        "tip": (
            "You avoid all kerbs at {corner_name} by {delta_m}m, costing {time_loss_s}s. "
            "You are racing on a track that is effectively metres narrower than "
            "your competitors. Use the kerbs -- they are part of the racing surface."
        ),
        "progressive_steps": [
            "Start using the flattest kerbs first to build confidence.",
            "Progress to all kerbs at this corner.",
            "Feel the lap time drop as the effective track widens.",
        ],
        "symptom_check": "Severe kerb avoidance at all corners; narrow, slow line.",
    },
}
