"""
development_plan.py
-------------------
Driver development plan management with pre-built templates.

Provides 5 plan templates (beginner, intermediate, advanced, race-prep,
consistency-focus), each with a 4-week structured curriculum of drills
and focus areas. Progress tracking per-drill.

Public API:
    get_plan_templates() -> list[dict]
    create_plan_from_template(conn, driver_id, template_id, plan_name) -> dict
    create_custom_plan(conn, driver_id, plan_name, weeks, level) -> dict
    get_plans(conn, driver_id) -> list[dict]
    get_plan(conn, plan_id) -> dict | None
    update_plan_progress(conn, plan_id, week_index, drill_index, completed) -> dict | None
    delete_plan(conn, plan_id) -> bool
    get_plan_completion_pct(plan) -> float
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Plan Templates ──────────────────────────────────────────────

_PLAN_TEMPLATES = {
    "beginner": {
        "id": "beginner",
        "name": "Beginner Foundations",
        "description": "Build core skills: smooth inputs, consistent lines, basic racecraft. This 4-week program takes a new driver from first track days through to confident, repeatable lapping. Each week builds on the previous one — master the fundamentals before chasing speed.",
        "level": "beginner",
        "prerequisites": "Basic car control at road-driving level. You should be comfortable with pedal placement and mirror usage. No prior track experience required.",
        "equipment_needed": "Data-logging device (GPS lap timer minimum), notebook for session notes, hydration and snacks for full-day sessions.",
        "weeks": [
            {
                "week": 1,
                "title": "Smooth Inputs",
                "focus": "This week is about your relationship with the controls. Every input you give the car — throttle, brake, steering — should be smooth, progressive, and deliberate. Jerky inputs unsettle the car and rob you of grip. Think of your hands and feet as communicating with the tyres.",
                "coaching_notes": "Resist the urge to go fast this week. Speed is a byproduct of smoothness. If you feel the car sliding or snapping, you are being too aggressive with your inputs. Slow down and focus on technique.",
                "warmup": "Start each session with 3 easy sighting laps at 60% pace. Focus on vision — look as far ahead as possible through each corner. Get comfortable with the track layout before any drill work.",
                "drills": [
                    {
                        "name": "Throttle Linearity Drill",
                        "description": "Focus on progressive throttle application through 10 laps. No sudden inputs.",
                        "detailed_instructions": "The throttle is not an on/off switch. Your goal is to apply throttle in a smooth, linear ramp from 0% to 100%. Imagine you are squeezing water from a sponge — gradually increasing pressure, never slamming.",
                        "steps": [
                            "Complete 2 warm-up laps at 70% pace, paying attention to how you use the throttle.",
                            "For the next 10 laps, focus ONLY on throttle application. Forget about lap times.",
                            "At each corner exit, begin with 10% throttle as you unwind the steering wheel.",
                            "Progressively increase throttle as the steering straightens — full throttle only when the wheel is straight.",
                            "If the rear steps out or tyres squeal on exit, you applied throttle too aggressively. Back off 5% and try again.",
                            "On straights, practice smooth lift-off before braking zones — don't snap off the throttle.",
                            "After 10 laps, park and review your data. Look for spikes in the throttle trace — these are your enemies."
                        ],
                        "tips": [
                            "Wear thin-soled shoes so you can feel the pedal travel.",
                            "Think of the throttle pedal as having 100 individual positions, not just 'on' and 'off'.",
                            "Your right foot should roll smoothly from heel to toe — never stomp.",
                            "If the car has traction control, turn it ON for this drill. You want to focus on technique, not catching slides.",
                            "Listen to the engine — smooth throttle means smooth engine note rise."
                        ],
                        "common_mistakes": [
                            "Snapping to full throttle the moment the car points straight (binary throttle).",
                            "Lifting off throttle abruptly mid-corner when scared — this unsettles the car.",
                            "Applying throttle before unwinding steering, causing understeer or power oversteer.",
                            "Focusing on speed instead of smoothness — remember, this drill is about technique."
                        ],
                        "success_criteria": "Your throttle trace on the data should show smooth ramps with no sudden spikes. Aim for the trace to look like gentle hills, not jagged mountains.",
                        "duration": "25–35 minutes (including warm-up)",
                        "difficulty": 2,
                        "metric": "throttle_onset_delay_m",
                        "target": "< 15m avg"
                    },
                    {
                        "name": "Brake Modulation",
                        "description": "Practice trail braking into turn 1. Gradually release brake as you approach apex.",
                        "detailed_instructions": "Braking is not just about slowing the car — it is about transferring weight to the front tyres to give them more grip for turning. The key technique is 'trail braking': applying firm initial pressure, then gradually releasing the brake as you turn into the corner. This keeps the front loaded and responsive.",
                        "steps": [
                            "Choose the heaviest braking zone on the track (usually Turn 1 or the corner after the longest straight).",
                            "On your first 3 laps, brake earlier than necessary. Focus on FEEL, not speed.",
                            "Apply the brake firmly (not violently) at your chosen marker. You should feel the weight pitch forward.",
                            "As you begin turning the steering wheel, start slowly releasing brake pressure — like easing off a handshake.",
                            "By the time you reach the apex, brake pressure should be down to about 10-20%, or fully released.",
                            "Repeat for 15 laps, gradually braking a little later each time as confidence builds.",
                            "After the session, check your brake trace. It should show a sharp initial spike that tapers off smoothly — a 'shark fin' shape."
                        ],
                        "tips": [
                            "Your initial brake application should be the hardest point — then it is all about release.",
                            "Think of it as '100% brake → turn in → 60% brake → apex → 20% brake → exit → 0% brake'.",
                            "Left-foot braking is not required at this stage. Use whichever foot is comfortable.",
                            "If the front tyres lock or ABS activates heavily, you are braking too hard for your entry speed.",
                            "Breathe. Many beginners hold their breath during braking. Exhale as you brake."
                        ],
                        "common_mistakes": [
                            "Braking in a straight line and then turning — this is 'brake and turn' rather than 'trail braking'. You want overlap.",
                            "Releasing the brake all at once ('dumping' the brake), which unloads the front tyres suddenly.",
                            "Braking too deep and running wide — start with earlier brake points and work forwards.",
                            "Tensing your whole body under braking — keep your arms relaxed, only your leg should work."
                        ],
                        "success_criteria": "Your brake trace should show consistent 'shark fin' shapes: strong initial application tapering smoothly to zero. Brake point variation should be within 3 metres across laps.",
                        "duration": "30–40 minutes",
                        "difficulty": 3,
                        "metric": "brake_point_consistency",
                        "target": "< 3m std dev"
                    },
                    {
                        "name": "Steering Smoothness",
                        "description": "Complete 5 laps minimizing steering corrections mid-corner.",
                        "detailed_instructions": "Good steering technique means turning the wheel once and holding a constant arc through the corner. Every correction you make mid-corner scrubs speed and unsettles the car. The goal is 'one input, one arc' — turn in, hold it, unwind. No sawing back and forth.",
                        "steps": [
                            "Warm up for 2 laps. On each corner, notice if you are making small adjustments after your initial turn-in.",
                            "Pick the 3 slowest corners on the track. These are easiest to practice steering on.",
                            "For each corner: look at the apex as you approach. Turn the wheel smoothly in one motion to the angle needed.",
                            "HOLD that angle through the corner. Do not adjust. If you miss the apex, accept it and correct on the next lap.",
                            "As you pass the apex, smoothly unwind the steering at the same rate you wound it in.",
                            "Complete 5 focused laps. Count your mid-corner corrections — the goal is zero.",
                            "Extend to 3 more laps on medium-speed corners, applying the same principle.",
                            "Review your steering trace: it should look like smooth bell curves, not zigzag patterns."
                        ],
                        "tips": [
                            "Your eyes lead your hands. Look where you want to go — the apex, then the exit — and your hands will follow.",
                            "Grip the wheel at 9-and-3 (or quarter-to-three) with a firm but relaxed hold. Death grip causes corrections.",
                            "If you consistently miss the apex inside, you are turning in too late. If you run wide, too early.",
                            "Smooth steering starts with smooth braking. Jerky brakes = jerky steering.",
                            "Imagine the steering wheel is connected to a sleeping baby. Turn gently."
                        ],
                        "common_mistakes": [
                            "Sawing the wheel left-right through the corner (target fixation on the kerb causes this).",
                            "Turning in too aggressively and then having to correct — use less initial input, add more if needed.",
                            "Looking at the bonnet or the kerb instead of far ahead through the corner.",
                            "White-knuckling the wheel — loosen your grip, let the car talk back to you through the wheel."
                        ],
                        "success_criteria": "Zero mid-corner steering corrections on slow corners for at least 3 consecutive laps. Steering trace shows smooth, single arcs.",
                        "duration": "15–25 minutes",
                        "difficulty": 2,
                        "metric": "smoothness_composite",
                        "target": "> 0.7"
                    },
                ],
            },
            {
                "week": 2,
                "title": "Consistent Lines",
                "focus": "Now that your inputs are smoother, it is time to drive the same line every lap. Consistency is the foundation of speed — you cannot improve what you cannot repeat. This week you will build a mental map of reference points and develop the discipline to hit them every single lap.",
                "coaching_notes": "Speed differences between laps come from two sources: line variation and input variation. By fixing your line this week (after fixing inputs in Week 1), you isolate the variables and can start making intentional improvements. Patience is key — boring consistency is fast consistency.",
                "warmup": "3 laps at 75% pace. On each corner, mentally note three things: where you turn in, where the apex is, and where you exit. These become your references.",
                "drills": [
                    {
                        "name": "Reference Point Laps",
                        "description": "Pick 3 visual reference points per corner. Hit them every lap for 15 laps.",
                        "detailed_instructions": "Every corner needs a plan: where to brake, where to turn in, where to aim. By choosing fixed physical markers on the track (cracks, kerb marks, sign posts, access roads), you create a repeatable recipe for each corner. This drill builds the habit of using external references rather than 'feel'.",
                        "steps": [
                            "Before going out, walk or drive a slow reconnaissance lap. For each corner, choose 3 reference points: (1) a braking marker, (2) a turn-in point, (3) an apex marker.",
                            "Write these down in your notebook — e.g., 'T3: Brake at the 50m board, turn in at the drain cover, apex at the start of the kerb.'",
                            "Go out for 15 laps. On every corner, talk to yourself: 'Brake HERE, turn HERE, apex HERE.'",
                            "Do NOT try to go faster. Drive at 80% pace and focus entirely on nailing the reference points.",
                            "After 5 laps, pull in and check: are you actually hitting the points? Adjust if a reference point does not match reality.",
                            "Complete the remaining 10 laps. By lap 12-15, the points should feel automatic.",
                            "After the session, review your line variation data. Did the consistency of your lines improve from laps 1-5 to laps 11-15?"
                        ],
                        "tips": [
                            "Choose FIXED objects as references, not shadows or rubber marks that change.",
                            "Kerb paint stripes, access road markings, and distance boards are excellent reference points.",
                            "Do not choose references that require you to look sideways — everything should be ahead of you.",
                            "Verbalise your references out loud while driving. This keeps you focused and builds neural pathways.",
                            "If a corner has no obvious markers, count car lengths from a known feature."
                        ],
                        "common_mistakes": [
                            "Choosing too many reference points — 3 per corner is the maximum for a beginner. Start with 2 if needed.",
                            "Using the car in front as a reference (they may be on the wrong line).",
                            "Abandoning reference discipline when you feel fast — stick to the plan, always.",
                            "Picking markers you cannot see at speed — test them at pace before committing."
                        ],
                        "success_criteria": "You can name all your reference points from memory for every corner, and your line variation index drops below 0.3 for the session.",
                        "duration": "35–45 minutes",
                        "difficulty": 2,
                        "metric": "line_variation_index",
                        "target": "< 0.3"
                    },
                    {
                        "name": "Apex Hunting",
                        "description": "Focus on hitting the geometric apex consistently. Use curbing as reference.",
                        "detailed_instructions": "The apex is the innermost point of your line through a corner. For most standard corners, the geometric apex (the middle of the inside kerb) is a good starting point. Hitting it consistently is the single biggest factor in repeatable lap times. Later you will learn about early and late apexes, but first — hit the geometric one every time.",
                        "steps": [
                            "Identify the apex point for every corner on the track. For simple corners, it is the midpoint of the inside kerb.",
                            "For each corner, choose a specific kerb feature as your apex target: a paint mark, a join between kerb sections, or a rumble strip start point.",
                            "Drive 5 laps focusing only on apexes. Your inside wheels should clip the inside kerb at the apex point.",
                            "Grade yourself: did you hit the apex, miss it by a car width, or miss it by more? Mental score: Hit = 2, Close = 1, Miss = 0.",
                            "After 5 laps, calculate your apex score (max = 2 × number of corners × 5 laps). Target 70%+ of maximum.",
                            "Drive 10 more laps. Your score should improve each set of 5.",
                            "Focus especially on corners where you consistently miss — these reveal line or braking issues."
                        ],
                        "tips": [
                            "Look at the apex from the turn-in point, then shift your eyes to the exit as you arrive at the apex.",
                            "You do not need to ride the kerb aggressively. Just getting the inside wheels within 30cm of the inside edge is 'hitting the apex'.",
                            "If you consistently miss the apex on the inside (undercut), you are turning in too early.",
                            "If you consistently miss on the outside (wide), you are turning in too late or carrying too much speed.",
                            "Some corners have false apexes where the kerb is not at the real turning point — use data to verify."
                        ],
                        "common_mistakes": [
                            "Looking at the apex too late — your eyes should be on it BEFORE you turn in.",
                            "Trying to use the kerb aggressively on every corner. Some kerbs are aggressive and can upset the car.",
                            "Apexing at the same point regardless of corner type — double-apex corners have TWO apex points.",
                            "Sacrificing entry control for apex accuracy — it is better to be smooth and close than ragged and exact."
                        ],
                        "success_criteria": "Hit 80%+ of apexes within 30cm of the inside kerb across 10 consecutive laps. Apex speed ratio > 0.85.",
                        "duration": "30–40 minutes",
                        "difficulty": 2,
                        "metric": "apex_speed_ratio",
                        "target": "> 0.85"
                    },
                    {
                        "name": "Exit Consistency",
                        "description": "Track-out to the same point every lap on 3 key corners.",
                        "detailed_instructions": "The corner exit is where you convert all your hard work (smooth braking, good turn-in, nailed apex) into speed. Using all the available track on exit maximises your exit speed, which then carries down the entire following straight. Even half a km/h extra on exit can mean a significant time gain on a long straight.",
                        "steps": [
                            "Identify the 3 corners that lead onto the longest straights. These are your priority exit corners.",
                            "For each corner, identify the track-out point: the exact spot on the outside of the track where your outside wheels should end up after unwinding the steering.",
                            "Drive 5 laps focused only on these 3 exits. After the apex, let the car drift out to the track-out point. Use ALL the road.",
                            "The key sequence is: Apex → begin throttle → unwind steering → car drifts to outside → full throttle when wheel is straight.",
                            "Check: are you reaching the outside edge consistently? If not, you may be applying throttle too aggressively (causing the car to push wide too early) or not enough (not using the whole track).",
                            "Drive 10 more laps, now linking all 3 exits with the rest of the track.",
                            "After the session, compare your exit speeds on these 3 corners across all laps. The variation should decrease."
                        ],
                        "tips": [
                            "The exit point should be the same every lap. Inconsistent exits mean inconsistent corner speeds.",
                            "Do not be afraid to use all the track. If there is rumble strip on the outside, it is there for a reason — use it gently.",
                            "Your eyes should be looking at the exit point (or down the next straight) well before you arrive there.",
                            "Exit speed matters more than mid-corner speed for lap time. Prioritise a good exit over a dramatic entry.",
                            "If you consistently run out of road on exit, your apex is too early. Try a slightly later apex."
                        ],
                        "common_mistakes": [
                            "Not using all the track on exit — leaving a car width of road unused is throwing away free speed.",
                            "Snapping to full throttle at the apex, causing wheelspin or understeer that pushes you off line.",
                            "Looking at the outside kerb instead of down the straight — you go where you look.",
                            "Tightening the steering after the apex ('double apex-ing' by accident) instead of smoothly unwinding."
                        ],
                        "success_criteria": "Exit within 50cm of the same track-out point on all 3 target corners for 8 of 10 consecutive laps. Exit acceleration efficiency > 0.75.",
                        "duration": "30–40 minutes",
                        "difficulty": 2,
                        "metric": "exit_acceleration_efficiency",
                        "target": "> 0.75"
                    },
                ],
            },
            {
                "week": 3,
                "title": "Speed Building",
                "focus": "You have smooth inputs and consistent lines. Now it is time to carefully add speed. The key word is 'carefully' — you will add pace in small, measurable increments while maintaining everything you learned in Weeks 1 and 2. If your lines or smoothness deteriorate, you have gone too fast too soon.",
                "coaching_notes": "This is where many beginners make the biggest mistake: they try to find speed by being more aggressive. The real speed comes from carrying MORE speed into corners while maintaining smoothness. Think of it as 'raising the floor' not 'raising the ceiling'. Each lap should feel only slightly faster than the last.",
                "warmup": "5 laps at your comfortable 'Week 2 pace'. Lock in your lines and smoothness before adding any speed. These laps are your baseline for today.",
                "drills": [
                    {
                        "name": "Progressive Pace Increase",
                        "description": "Start at 90% pace, increase 1% per lap over 10 laps while maintaining line.",
                        "detailed_instructions": "This drill teaches you to find speed gradually rather than lunging for it. By increasing pace in small increments, you stay in control and learn where the extra time comes from. The moment your lines become inconsistent, you have exceeded your current ability — back off one step and repeat until that pace becomes comfortable.",
                        "steps": [
                            "Start with 3 laps at what feels like 90% — comfortable but purposeful. Note your lap time as your baseline.",
                            "On lap 4, push just 1% harder. Where does the extra speed come from? Braking a tiny bit later? Carrying a little more mid-corner speed? Note what changed.",
                            "On each subsequent lap (5-13), add another 1%. This means by lap 13 you are at '100%'. But remember — true 100% for a beginner still has a large safety margin.",
                            "After each lap, mentally grade yourself: Did I maintain my lines? Were my inputs smooth? If yes → push another 1%. If no → stay at this pace for 2 more laps.",
                            "If at any point the car feels out of control or you miss multiple reference points, REDUCE pace by 3% and rebuild from there.",
                            "Record the lap where you feel 'this is my comfortable fast pace'. This is your current working pace for the rest of the week.",
                            "Complete the session with 3 cool-down laps at 85% pace."
                        ],
                        "tips": [
                            "The 1% increase should feel almost imperceptible. If it feels dramatic, you are jumping too much.",
                            "Speed comes from later braking, higher minimum corner speeds, and earlier throttle. In that order of safety.",
                            "Watch your sector times, not just total lap time. If sector 1 improved but sector 3 got worse, you are overdriving by sector 3.",
                            "You might find that 'trying harder' actually makes you slower. This is normal — tension kills smoothness.",
                            "If you plateau, focus on ONE corner where you feel the most margin. Gain time there, then move on."
                        ],
                        "common_mistakes": [
                            "Jumping from 90% to 100% in two laps — the point is GRADUAL progression.",
                            "Adding speed through aggression (harder braking, more steering) rather than precision (later braking, higher carry speed).",
                            "Ignoring deteriorating lines because 'the lap time is improving'. Fast sloppy laps are not sustainable.",
                            "Getting frustrated by small improvements — gaining 0.2s per lap is actually excellent progress."
                        ],
                        "success_criteria": "End the session within 2.0s of your personal best while maintaining line variation and smoothness within Week 2 standards.",
                        "duration": "35–45 minutes",
                        "difficulty": 3,
                        "metric": "pace_delta_s",
                        "target": "< 2.0s from best"
                    },
                    {
                        "name": "Corner Entry Speed",
                        "description": "Gradually increase entry speed on 2 corners. Note where grip limit is.",
                        "detailed_instructions": "Corner entry speed is where most time is gained and lost. This drill focuses on carrying more speed INTO corners by braking a little less or a little later. You will learn to feel the front tyres' grip level and understand how much speed you can carry before the car starts to push (understeer) or rotate (oversteer).",
                        "steps": [
                            "Choose 2 medium-speed corners with good runoff. Do NOT practice on high-speed corners or corners with barriers.",
                            "Drive 5 baseline laps. Note your entry speed at these 2 corners (from data or feel).",
                            "On lap 6, carry 2 km/h more entry speed into corner 1. Do this by either braking 1m later or releasing the brake 5% more before turn-in.",
                            "Note the result: Did the car still turn in OK? Did you hit the apex? Did you run wide on exit?",
                            "If all was fine, add another 2 km/h on the next lap. Continue until you notice the front tyres starting to wash out (understeer) or the rear getting light (oversteer).",
                            "When you feel the limit, BACK OFF 3 km/h from that point. This is your safe fast entry speed.",
                            "Repeat the process for corner 2.",
                            "Spend 5 laps locking in these new entry speeds as your new 'normal' for these corners."
                        ],
                        "tips": [
                            "The limit does not come all at once. You will hear the tyres start to sing/squeal before they let go. This is your warning.",
                            "If the car understeers (pushes wide), you have too much entry speed for your steering input. Try a tiny bit less speed OR a slightly earlier turn-in.",
                            "If the car oversteers (rear slides), you have too much speed for the rear grip level. This usually means you lifted throttle or braked mid-corner.",
                            "Do not practice this drill in the rain or on a damp track — grip levels are unpredictable.",
                            "2 km/h is a surprisingly large increment at corner entry. Even 1 km/h makes a measurable difference."
                        ],
                        "common_mistakes": [
                            "Choosing high-speed corners or ones with no runoff for this drill. Always practice at corners where a mistake is forgivable.",
                            "Adding entry speed without adjusting the rest of the corner — more speed in requires more trail braking or a wider arc.",
                            "Panicking at the first sign of understeer and lifting completely — a small steering adjustment is usually enough.",
                            "Only focusing on corner entry and neglecting the exit — a fast entry with a slow exit is slower overall."
                        ],
                        "success_criteria": "Establish a new comfortable entry speed on both target corners that is within 5% of your fastest entry, with consistent apex hits.",
                        "duration": "30–40 minutes",
                        "difficulty": 3,
                        "metric": "entry_speed_mps",
                        "target": "within 5% of best"
                    },
                    {
                        "name": "Braking Point Progression",
                        "description": "Move brake point 1m later each lap until you find the limit.",
                        "detailed_instructions": "Late braking is one of the most intuitive ways to find time, but it must be done methodically. This drill progressively moves your braking point later in 1-metre increments until you find the latest point where you can still make the corner while maintaining your line. Once found, you back off 2m for your 'race' brake point.",
                        "steps": [
                            "Pick the heaviest braking zone (longest straight into slowest corner). Note your current braking marker.",
                            "Drive 3 laps at your current brake point. This is your baseline. Note the lap time and entry speed.",
                            "On lap 4, move your braking point 1 metre later (e.g., from 100m board to 99m). It should feel almost the same.",
                            "Each subsequent lap, move 1m later. Keep a mental count: 'I am now braking at [baseline] minus 5 metres.'",
                            "Monitor what happens: Are you still making the apex? Is your entry speed changing? Do you need to brake harder?",
                            "The first sign of the limit: you miss the apex by more than half a car width, or ABS activates aggressively, or the car will not turn in.",
                            "When you reach the limit, note the exact position. Now back off 2 metres — THIS is your working brake point.",
                            "Complete 5 laps at the new working brake point to commit it to muscle memory.",
                            "If time allows, repeat for a second braking zone."
                        ],
                        "tips": [
                            "1 metre is about the length of your arm. It is a very small increment — this is intentional.",
                            "As you brake later, you may need to brake HARDER to achieve the same deceleration in less distance.",
                            "Your brake point might vary with tyre temperature and fuel load. Re-calibrate throughout the day.",
                            "Mark your final brake point with a physical landmark you can see at speed.",
                            "Do not brake late AND trail brake deep on the same lap until you are comfortable with each independently."
                        ],
                        "common_mistakes": [
                            "Moving the brake point 5-10m at once — this is dangerous and does not teach you anything about the progression.",
                            "Not braking hard enough when braking later — the same deceleration in less distance requires more pedal pressure.",
                            "Continuing to push later even after clear signs of reaching the limit (ego overtakes judgment).",
                            "Forgetting that brake points are track-condition dependent — what works on warm tyres may not work on cold ones."
                        ],
                        "success_criteria": "Find a new brake point at least 3m later than your baseline, achievable consistently within 2m variation across 5 consecutive laps.",
                        "duration": "25–35 minutes",
                        "difficulty": 3,
                        "metric": "brake_point_m",
                        "target": "consistent within 2m"
                    },
                ],
            },
            {
                "week": 4,
                "title": "Putting It Together",
                "focus": "This is graduation week. You will combine smooth inputs, consistent lines, and your new speed into complete, repeatable laps. The goal is to prove that you can put together everything from the last 3 weeks into a cohesive package. After this week, you are no longer a beginner — you are a developing driver with real foundations.",
                "coaching_notes": "This week should feel like a celebration of your progress, not a stressful test. You have built the skills — now you are simply demonstrating them in combination. If anything feels like it is falling apart, go back to the specific Week 1-3 drill that addresses it. There is no shame in revision.",
                "warmup": "5 laps at 80% pace. Use these to consciously run through your checklist: smooth throttle, progressive braking, reference points, apex hits, full track-out. Every element in every corner.",
                "drills": [
                    {
                        "name": "Full Session Consistency",
                        "description": "Complete 20 laps targeting < 1.5% lap time variation.",
                        "detailed_instructions": "This is the ultimate test of everything you have learned. 20 consecutive laps where every single one is close to the same time. This requires sustained concentration, consistent technique, and the ability to recover from small errors without losing the whole lap. In racing, the driver who can do this wins championships.",
                        "steps": [
                            "Complete your standard 5-lap warm-up.",
                            "Begin the 20-lap run. Set a target pace based on your average from Week 3 — NOT your best lap.",
                            "Focus on process, not outcome. Each corner is: brake reference → turn-in reference → apex → exit to track-out point → throttle progression.",
                            "After every 5 laps, do a quick mental check: Am I still hitting my references? Is my breathing controlled? Am I tense anywhere?",
                            "If one lap is significantly slower (more than 2%), do NOT try to make it up on the next lap. Reset and return to your process.",
                            "Track your mental state: by lap 15-20, fatigue will affect concentration. This is normal — fight it with discipline and routine.",
                            "After 20 laps, cool down for 3 laps.",
                            "Review your data: calculate CV% (coefficient of variation). Plot lap times on a chart — you want a flat line, not a trend."
                        ],
                        "tips": [
                            "Hydrate before starting. 20 laps of concentration requires physical and mental energy.",
                            "If you cannot maintain focus for 20 laps, break it into 2 sets of 10 with a 5-minute break.",
                            "Consistency does not mean slow. It means every lap at the SAME pace — and that pace can be fast.",
                            "Traffic can disrupt consistency. If you encounter slower cars, do not fight them — let the lap go and refocus on the next one.",
                            "Set small mental goals: 'The next 5 laps will all be within 0.5s of each other.'"
                        ],
                        "common_mistakes": [
                            "Trying to set a personal best during a consistency drill — these are different goals.",
                            "Getting frustrated after a bad lap and overdriving the next one, creating a see-saw pattern.",
                            "Not accounting for traffic — exclude disrupted laps from your consistency calculation.",
                            "Stopping after 15 laps because 'it felt good' — the discipline to complete 20 is part of the exercise."
                        ],
                        "success_criteria": "20 clean laps with coefficient of variation (CV%) below 1.5%. No lap more than 2.5% slower than the average.",
                        "duration": "45–55 minutes",
                        "difficulty": 3,
                        "metric": "consistency_cv_pct",
                        "target": "< 1.5%"
                    },
                    {
                        "name": "Personal Best Attempt",
                        "description": "After warm-up, attempt 5 push laps. Analyze best vs avg gap.",
                        "detailed_instructions": "Now it is time to see what you are truly capable of. After all the disciplined work of Weeks 1-3, this drill gives you permission to push. But pushing intelligently — not recklessly. You will do 5 maximum-effort laps and analyze where the time came from. The gap between your push lap and your average tells you about your 'speed reserve'.",
                        "steps": [
                            "Complete a thorough warm-up: 5 laps building from 70% to 95% pace.",
                            "On lap 6, it is go time. Push to YOUR 100%. Not someone else's 100%. YOUR maximum controlled effort.",
                            "On each of the 5 push laps, focus on one thing: carrying speed. Brake at your latest safe point, carry maximum entry speed, get on throttle as early as possible.",
                            "If a lap goes wrong (missed braking point, big slide, mistake), DO NOT abort. Finish the lap and learn from it.",
                            "After 5 push laps, do 2 cool-down laps.",
                            "Park and immediately review: What was your best time? What was your worst? What was the gap?",
                            "Identify which corners gained you the most time vs your average. These are your 'potential corners'.",
                            "Identify which corners cost you time vs your average. These are your 'risk corners'.",
                            "Write down your personal best and the date. This is your benchmark."
                        ],
                        "tips": [
                            "A push lap should feel 'quick but composed'. If it feels ragged and scary, you are overdriving.",
                            "The first push lap is rarely the best. Lap 2 or 3 typically is, as your tyres are at optimal temperature.",
                            "Do not stare at the lap timer. Focus on the process and let the time come to you.",
                            "If your best push lap is more than 3% faster than your average, there is a lot of consistency work still to do.",
                            "Celebrate your PB. No matter what the time is, it represents YOUR current best — and you will beat it next month."
                        ],
                        "common_mistakes": [
                            "Going 'over the limit' on lap 1 and spending laps 2-5 with damaged confidence (or tyres).",
                            "Only looking at the final time, not the sector breakdown. The sector data tells you WHERE you went fast.",
                            "Comparing your PB to other drivers instead of tracking your own improvement trajectory.",
                            "Not recording the conditions (track temp, tyre condition, fuel level) — PBs are context-dependent."
                        ],
                        "success_criteria": "Set a new personal best. Your best lap should be no more than 1.5% faster than your 5-lap average (indicating you are consistently fast, not just lucky once).",
                        "duration": "20–30 minutes",
                        "difficulty": 3,
                        "metric": "best_lap_time_s",
                        "target": "new PB"
                    },
                    {
                        "name": "Self-Assessment & Review",
                        "description": "Review your data. Identify your strongest and weakest corner.",
                        "detailed_instructions": "Data review is where real learning happens. This final drill is about sitting down with your telemetry from the entire 4-week program, understanding your progress, and setting goals for the future. The best drivers spend as much time analyzing data as they do driving. This is your first proper data review session.",
                        "steps": [
                            "Open your telemetry dashboard and load your most recent session.",
                            "Review the Session Summary: what is your overall score? Which categories are strongest?",
                            "Look at the Corner Analysis: rank corners from best (least time loss) to worst (most time loss).",
                            "For your BEST corner: what are you doing right? Is it smooth braking? Good line? Fast exit? Write it down.",
                            "For your WORST corner: what is going wrong? Compare your data to your best lap through that corner.",
                            "Look at the Consistency Heatmap: are there corners where you are consistent but slow, or fast but inconsistent?",
                            "Compare your Week 1 data to Week 4 data: How much has your pace improved? How much has your consistency improved?",
                            "Write a 3-point action plan for the next month: (1) maintain one strength, (2) improve one weakness, (3) learn one new skill.",
                            "Set a lap time target for next month based on your improvement trajectory."
                        ],
                        "tips": [
                            "Be honest with yourself. The data does not lie. If a corner is bad, own it and plan to fix it.",
                            "Do not try to fix everything at once. Pick your ONE weakest corner for focused improvement next month.",
                            "Save screenshots or exports of your key data. You will want to compare these to future sessions.",
                            "If you have access to a coach or faster driver's data, overlay your traces for comparison. The differences will be obvious.",
                            "Celebrate your improvement. Even small gains compound over time into massive speed."
                        ],
                        "common_mistakes": [
                            "Skipping data review because 'I know how it felt'. Perception and data often disagree.",
                            "Only looking at lap times and ignoring corner-level data. The details matter.",
                            "Getting discouraged by gaps to faster drivers instead of tracking your own improvement.",
                            "Not writing anything down. Memory fades — written notes persist."
                        ],
                        "success_criteria": "Completed written review with: best corner identified, worst corner identified, 3-point action plan documented. Overall session score > 60.",
                        "duration": "30–45 minutes (off-track)",
                        "difficulty": 1,
                        "metric": "total_score",
                        "target": "> 60"
                    },
                ],
            },
        ],
    },
    "intermediate": {
        "id": "intermediate",
        "name": "Intermediate Refinement",
        "description": "Refine technique: trail braking, corner linking, adapting to conditions. You have the basics — now it is time to unlock the next level. This program bridges the gap between a competent track day driver and a competitive racer by developing the subtle skills that separate fast from truly fast.",
        "level": "intermediate",
        "prerequisites": "Completed Beginner Foundations or equivalent experience. You should be able to lap consistently within 2% CV and have a solid understanding of racing lines, reference points, and basic braking technique.",
        "equipment_needed": "Data-logging device with speed/GPS trace, access to telemetry review software, notebook. Optional: GoPro or similar for visual analysis.",
        "weeks": [
            {
                "week": 1,
                "title": "Trail Braking Mastery",
                "focus": "Trail braking is the single most important advanced technique you will learn. It is the art of continuing to brake while turning into the corner, which keeps the front tyres loaded with extra grip. Mastering this transforms your corner entry from 'turn in and hope' to a controlled, deliberate process where YOU decide how the car rotates.",
                "coaching_notes": "Trail braking is counterintuitive — your brain says 'if I brake while turning, I will spin.' The truth is the opposite: trail braking gives you MORE control. Start gently. The key is the ratio between brake pressure and steering angle — as steering increases, brake pressure decreases. Think of it as a seesaw.",
                "warmup": "5 laps at 85% pace. On each corner, notice your current brake-to-turn transition. Are you finishing braking completely before turning? That is what we are going to change.",
                "drills": [
                    {
                        "name": "Trail Brake Depth",
                        "description": "Extend trail braking 5m deeper into each corner. Maintain balance.",
                        "detailed_instructions": "Currently you probably finish braking before you turn in. This drill teaches you to carry brake pressure past the turn-in point — 'trailing' the brake into the corner. The front tyres get extra load from the braking, which gives them more grip for turning. This is free performance that costs nothing.",
                        "steps": [
                            "Choose 3 medium-speed corners. Note where you currently release the brake fully (the 'brake release point').",
                            "On your first attempt, keep 30% brake pressure PAST your current release point by 5 metres while turning in.",
                            "Feel what happens: the front of the car should feel sharper, more eager to turn. The car rotates more willingly.",
                            "If the rear feels loose or twitchy, you are carrying too much brake pressure. Reduce to 20% and try again.",
                            "Once comfortable at 5m deeper, try 8m deeper. Then 10m. Your goal is to carry some brake to within 2-3 metres of the apex.",
                            "After 10 laps of practice, drive 5 laps and compare your corner entry speeds and apex speeds to your baseline. They should be higher.",
                            "For each corner, note your new trail brake depth. This becomes your updated technique.",
                            "Practice all 3 corners for 5 more laps to solidify the new habit."
                        ],
                        "tips": [
                            "The brake pressure during trail braking is much lighter than initial braking — think 15-30% pressure, not 80%.",
                            "Your foot should be easing off the brake like slowly lifting a feather, not releasing a spring.",
                            "The car should feel like it is rotating around the front tyres during trail braking. This is called 'rotation' and it is your friend.",
                            "If the car pushes wide (understeer) during trail braking, you need MORE brake pressure, not less — the front needs more load.",
                            "Trail braking depth varies by corner type: deep trail braking for slow corners, light for fast corners."
                        ],
                        "common_mistakes": [
                            "Carrying too much brake pressure and locking the inside front wheel mid-corner.",
                            "Trail braking the same amount in every corner — slow corners need deep trail braking, fast corners need gentle.",
                            "Releasing the brake too abruptly mid-corner, causing the front to unload suddenly and the car to push wide.",
                            "Thinking trail braking means braking later. It means braking LONGER, not necessarily later."
                        ],
                        "success_criteria": "Successfully carry brake pressure past the turn-in point on all 3 target corners without rear instability. Trail braking depth score > 0.6.",
                        "duration": "30–40 minutes",
                        "difficulty": 4,
                        "metric": "trail_braking_depth",
                        "target": "> 0.6"
                    },
                    {
                        "name": "Brake Release Precision",
                        "description": "Practice smooth brake release matching steering input. 15 laps.",
                        "detailed_instructions": "The brake release is the most critical moment of every corner. Release too fast and the front unloads, causing understeer. Release too slow and you over-rotate or carry too little speed. The perfect release is a smooth, gradual taper that exactly matches the rate of steering input — as you add steering, you remove brake. This drill trains that coordination to become automatic.",
                        "steps": [
                            "Pick 2 corners where you trail brake (from the previous drill).",
                            "On lap 1-3, focus on your RIGHT FOOT only. How quickly are you releasing the brake? Time it mentally.",
                            "On lap 4, slow the release by 50%. Take TWICE as long to go from 30% brake to 0%. Feel the car stay planted longer.",
                            "On lap 5-7, synchronise: as your LEFT hand adds 10 degrees of steering, your RIGHT foot releases 10% of brake. Match the rates.",
                            "On lap 8-10, experiment with the release rate: slightly faster release → car rotates less. Slightly slower → car rotates more.",
                            "Find the release rate where the car transitions from braking to coasting to accelerating without any 'dead zone' or jerk.",
                            "Complete 5 more laps (11-15) locking in this release rate.",
                            "Check your data: the brake trace should show a smooth, gradual decay — not a cliff edge."
                        ],
                        "tips": [
                            "Think of the brake release as a volume knob being turned down slowly, not a light switch being flicked off.",
                            "If the car 'snaps' oversteer at turn-in, your brake release is too slow — you are over-rotating the car.",
                            "If the car pushes wide at turn-in, your brake release is too fast — the front tyres lost their grip advantage.",
                            "The perfect brake release is different for each corner. Slow corners need slower release. Fast corners need faster release.",
                            "Record a few laps and watch your brake trace overlay on the steering trace. They should mirror each other like a reflection."
                        ],
                        "common_mistakes": [
                            "Dumping the brake in one motion — this is the single most common intermediate-level error.",
                            "Not connecting brake release to steering input — they must be synchronised like two parts of one motion.",
                            "Overthinking the release rate and becoming tense — it should become natural after 10 repetitions.",
                            "Ignoring the car's feedback — if the car feels unstable, adjust the release rate before pushing harder."
                        ],
                        "success_criteria": "Brake release traces show smooth, gradual decay on 12+ of 15 laps. Brake point consistency below 2m standard deviation.",
                        "duration": "30–40 minutes",
                        "difficulty": 4,
                        "metric": "brake_point_consistency",
                        "target": "< 2m std dev"
                    },
                    {
                        "name": "Late Apex Application",
                        "description": "Experiment with later apexes on 3 slow corners. Compare exit speeds.",
                        "detailed_instructions": "A late apex means hitting the inside of the corner AFTER the geometric midpoint. Why? Because a late apex opens up the exit, allowing you to get on the throttle earlier and carry more speed down the following straight. For slow corners especially, a late apex almost always produces a faster overall time — you sacrifice a tiny bit of mid-corner speed for a significant gain on exit.",
                        "steps": [
                            "Identify the 3 slowest corners on the track. These are where late apex technique has the biggest impact.",
                            "Drive 3 baseline laps. For each corner, note: (a) where you currently apex, (b) your exit speed, (c) your time through the corner+following straight.",
                            "On lap 4, on corner 1, aim for an apex point 2 car lengths LATER than your current one. This means a slightly tighter entry angle.",
                            "Notice what happens on exit: can you straighten the wheel earlier? Can you apply throttle sooner? Does the car feel less 'wound up' on exit?",
                            "If the exit feels better, commit to this new apex on corner 1 for the next 5 laps.",
                            "Repeat for corners 2 and 3: move the apex 2 car lengths later, assess the exit speed improvement.",
                            "After all 3 corners are updated, drive 5 complete laps with the new late apexes integrated.",
                            "Compare your exit speed data: late apex exits should be 1-3 km/h faster."
                        ],
                        "tips": [
                            "Late apex requires a later turn-in point too. If you turn in at the same place but aim for a later apex, you will apex too tight and run out of road.",
                            "The biggest gain from a late apex comes in corners that lead onto long straights. 2 km/h extra at corner exit can be worth 0.3-0.5s by the end of a long straight.",
                            "Not every corner benefits from a late apex. Fast, sweeping corners often work better with a geometric or even early apex. Focus on slow corners for this drill.",
                            "A late apex feels 'wrong' at first because you are deliberately missing what looks like the ideal line. Trust the data.",
                            "Late apex and trail braking work together perfectly: trail brake deep, rotate the car, hit the late apex, fire out straight."
                        ],
                        "common_mistakes": [
                            "Moving the apex later without moving the turn-in later — this creates a very tight mid-corner arc that kills minimum speed.",
                            "Over-doing the late apex and ending up on the inside kerb with no room to accelerate out.",
                            "Applying the late apex technique to fast corners where it actually hurts performance.",
                            "Forgetting that a late apex means a different braking point — you may need to trail brake deeper to make the tighter angle work."
                        ],
                        "success_criteria": "Exit speeds on 3 target slow corners improve by at least 2% compared to baseline. Exit acceleration feels earlier and more confident.",
                        "duration": "30–35 minutes",
                        "difficulty": 3,
                        "metric": "exit_speed_mps",
                        "target": "improve by 2%"
                    },
                ],
            },
            {
                "week": 2,
                "title": "Corner Linking",
                "focus": "Individual corner speed is only half the battle. Real lap time comes from linking corners together — making sure that what you do in one corner sets up the next one perfectly. This week you will learn to think about corners not as isolated events but as connected sequences where every action has consequences downstream.",
                "coaching_notes": "The biggest leap in this week comes from thinking 2 corners ahead. When you approach a hairpin before a chicane, your hairpin exit directly determines your chicane entry. If you sacrifice 0.1s in the hairpin to gain 0.3s in the chicane, that is net 0.2s gained. This is strategic thinking that separates racers from track day drivers.",
                "warmup": "5 laps at 80% pace. Instead of thinking corner-by-corner, try to think in SEQUENCES: 'turn 3 leads to turn 4 leads to turn 5.' Identify the connected sequences.",
                "drills": [
                    {
                        "name": "Complex Sequence Flow",
                        "description": "Practice the fastest 3-corner complex without lifting. Chain entries and exits.",
                        "detailed_instructions": "Most tracks have at least one complex of 3+ corners that flow together. In these sections, the exit of each corner IS the entry of the next one. There is no 'reset' — you must plan the entire sequence as one continuous arc. The key insight: sometimes being slower in corner 1 of the sequence lets you be faster in corners 2 and 3.",
                        "steps": [
                            "Identify the track's fastest multi-corner complex (usually an S-bend or chicane sequence). Minimum 3 connected corners.",
                            "Walk through the complex in your mind: What is the ideal line through ALL 3 corners if you treat them as one?",
                            "Drive 5 baseline laps. Note your time through the ENTIRE complex (not individual corners).",
                            "On lap 6, focus on the EXIT of corner 1: make sure your exit puts you in the perfect position for corner 2 entry.",
                            "On lap 7, sacrifice corner 1 speed by 5% if it means a better corner 2 entry. Does the sequence time improve?",
                            "On lap 8-10, find the rhythm. The throttle-brake-steer pattern through the sequence should feel like a dance — each movement flowing into the next.",
                            "Drive 5 more laps targeting zero throttle lift through the entire complex (if geometry allows).",
                            "Review data: compare your best sequence time to your baseline. Note which individual corners improved and which were sacrificed."
                        ],
                        "tips": [
                            "In a chicane, the key is NOT the first part — it is the EXIT of the last part onto the straight. Always prioritise the final exit.",
                            "Sometimes the fastest sequence involves a non-intuitive line through corner 1 — wider, or tighter — to set up corners 2-3.",
                            "Smooth transitions are critical: any abrupt input between corners breaks the flow and costs time.",
                            "Listen to the engine note through the sequence. A smooth, connected sequence sounds different from a choppy one.",
                            "If you cannot complete the sequence without lifting, focus on reducing the lift duration and harshness rather than eliminating it immediately."
                        ],
                        "common_mistakes": [
                            "Optimising each corner individually and ignoring the connections between them.",
                            "Lifting off the throttle between connected corners when a steady throttle would maintain better flow.",
                            "Getting fixated on one corner's apex at the expense of the overall sequence geometry.",
                            "Not backing off when the sequence falls apart — a failed sequence often cascades into errors in the following corners."
                        ],
                        "success_criteria": "Sequence time through the target 3-corner complex improves by at least 0.2s. Total time loss across the complex < 50ms compared to ideal.",
                        "duration": "30–40 minutes",
                        "difficulty": 4,
                        "metric": "time_loss_ms",
                        "target": "< 50ms total loss"
                    },
                    {
                        "name": "Weight Transfer Management",
                        "description": "Focus on smooth transitions between braking and acceleration zones.",
                        "detailed_instructions": "The car is always in one of three weight states: nose-heavy (braking), neutral (coasting), or rear-heavy (accelerating). The transitions between these states are where most car instability occurs. This drill teaches you to manage these transitions so smoothly that the car never has an abrupt weight shift — which means it always has maximum grip available.",
                        "steps": [
                            "Drive 3 laps paying attention to weight shifts. Where do you feel the car rock forward and back? Those are your transitions.",
                            "Pick the 3 corners with the most noticeable weight transitions.",
                            "On lap 4-6, focus on the brake-to-coast transition: instead of releasing the brake and coasting, try to maintain a tiny bit of brake pressure (5%) as you begin to coast. This prevents the nose from lifting abruptly.",
                            "On lap 7-9, focus on the coast-to-throttle transition: apply throttle so gently at first that you cannot feel the car react. Then ramp up. The car should accelerate without squatting.",
                            "On lap 10-12, combine: brake → ease off → coast briefly → gentle throttle → ramp up. The car should feel like it is on rails through the entire sequence.",
                            "Drive 3 more laps at increased pace. Does the car feel more stable? It should.",
                            "Review your data: look at the speed trace through corners. Smooth weight transfer shows as a smooth, continuous curve with no sharp kinks."
                        ],
                        "tips": [
                            "Think of the car as a pendulum. Smooth transitions keep the pendulum moving slowly. Abrupt transitions make it swing violently.",
                            "A 'dead zone' between braking and acceleration (coasting too long) wastes time. The goal is minimal coasting.",
                            "The car has the least grip during transitions. By making transitions smoother, you maintain higher grip throughout.",
                            "Weight transfer timing changes with speed: at high speed, the car reacts faster to weight shifts. Be even smoother at high speed.",
                            "If you are getting understeer on corner entry, the nose is probably unloading too fast from an abrupt brake release."
                        ],
                        "common_mistakes": [
                            "Releasing the brake completely before applying any throttle, creating a 'dead zone' with no load on either axle.",
                            "Applying throttle too aggressively out of corners, shifting all weight rearward and causing front end to wash out.",
                            "Not connecting brake release to weight transfer — thinking of them as separate actions instead of cause and effect.",
                            "Being smooth but slow. Smoothness should not sacrifice commitment — you can be smooth AND decisive."
                        ],
                        "success_criteria": "Speed traces through target corners show smooth, continuous curves with no sharp kinks. Smoothness composite > 0.8.",
                        "duration": "30–35 minutes",
                        "difficulty": 3,
                        "metric": "smoothness_composite",
                        "target": "> 0.8"
                    },
                    {
                        "name": "Throttle-Brake Overlap",
                        "description": "Minimize time between brake release and throttle application.",
                        "detailed_instructions": "In an ideal corner, there is zero time gap between taking your foot off the brake and putting it on the throttle. This does not mean stomping from one to the other — it means the transition is so smooth that one input fades as the other builds. The gap between brake release and throttle application is 'dead time' where the car is not being driven — it is just rolling. Every metre of dead time is wasted potential.",
                        "steps": [
                            "Drive 3 laps and on each corner, mentally count the time between your foot leaving the brake pedal and touching the throttle pedal.",
                            "Note: for most intermediate drivers, this gap is 0.3-0.8 seconds. That is 5-15 metres of 'nobody is driving the car.'",
                            "On lap 4-6, practice on 3 corners: as your brake foot lifts, your throttle foot should be moving SIMULTANEOUSLY. One lifts, the other falls.",
                            "Start with 10% throttle overlap: apply a tiny bit of throttle while still on 5% brake. This is called 'blipping' and it keeps the car loaded.",
                            "On lap 7-9, increase the overlap: as brake reduces from 30% to 0%, throttle should increase from 0% to 20%. They should cross over smoothly.",
                            "On lap 10-12, try to eliminate any coasting phase entirely on 2 corners. Go directly from trail braking to acceleration.",
                            "Drive 3 final laps integrating this across the whole lap."
                        ],
                        "tips": [
                            "Left-foot braking makes this much easier because you can operate brake and throttle simultaneously. But it is not required.",
                            "The overlap is most critical in slow corners where the speed difference between braking and accelerating is largest.",
                            "Some overlap is normal in high-performance driving. Professional drivers often have 5-15% throttle while still on brake.",
                            "Do NOT try this with ABS active — if the ABS is working, you have bigger problems than overlap.",
                            "The goal distance of < 8m means less than half a second of gap at typical corner speeds."
                        ],
                        "common_mistakes": [
                            "Trying to eliminate the gap by being aggressive with throttle, rather than smooth with both pedals.",
                            "Overlapping throttle and brake too much, overheating the brakes or confusing the ABS system.",
                            "Focusing only on the throttle-on moment and ignoring the brake-off moment — both need to be smooth.",
                            "Not being aware that different corners have different ideal overlap amounts — slow corners allow more overlap than fast ones."
                        ],
                        "success_criteria": "Average distance between brake release and throttle application < 8m across all corners. No corner with > 15m gap.",
                        "duration": "25–35 minutes",
                        "difficulty": 4,
                        "metric": "throttle_onset_delay_m",
                        "target": "< 8m avg"
                    },
                ],
            },
            {
                "week": 3,
                "title": "Adaptability",
                "focus": "Real driving happens in an imperfect world: track conditions change, traffic appears, setups are adjusted. An intermediate driver who can only perform in perfect conditions will struggle in real sessions. This week develops your ability to adapt — to recognise changes, adjust your approach, and maintain performance regardless of circumstances.",
                "coaching_notes": "Adaptability is a mental skill more than a physical one. The key mindset shift is: stop expecting the track to be the same as your last session and start expecting it to be different. The best drivers adjust within 2-3 laps of any change. This week trains that ability.",
                "warmup": "5 laps at 80% pace. Pay attention to how the track FEELS today compared to your last session. Is it grippier? More slippery? Windier? Note the differences.",
                "drills": [
                    {
                        "name": "Changing Conditions Drill",
                        "description": "If track evolves (rubber/temp), adjust lines by lap 3. Track pace delta.",
                        "detailed_instructions": "Track grip changes constantly: temperature, rubber buildup, dust, moisture — all affect grip levels. This drill develops your ability to sense grip changes and adjust within 3 laps. The fastest drivers do not wait for the car to bite them — they feel the first subtle signs and proactively adjust.",
                        "steps": [
                            "At the start of a session (when the track is 'green' or cold), drive 5 laps and note your pace at this grip level.",
                            "As the session progresses (tyres warm up, rubber builds), notice how the grip changes. Are you braking later? Carrying more speed?",
                            "When you notice a grip change, immediately adjust: if grip increases, brake 1m later and carry 2 km/h more entry speed. If grip decreases, add 2m to brake points.",
                            "Your target: achieve within 0.5s of your baseline pace within 3 laps of noticing the change.",
                            "Track the adjustment in your head: 'Grip is up, I have braked 2m later in turn 3 and carried 3 km/h more in turn 7.'",
                            "If conditions change again (cloud cover, temperature drop), repeat the adjustment process.",
                            "After the session, note how quickly you adapted. Target: within 3 laps for a confident pace."
                        ],
                        "tips": [
                            "Your first indicator of grip change is the steering wheel: more grip = heavier steering. Less grip = lighter steering.",
                            "Tyre noise is a great indicator: quiet tyres have grip. Squealing tyres are at the limit. Scrubbing tyres have exceeded it.",
                            "Track temperature changes throughout the day: cold in the morning (less grip), hot in the afternoon (more grip, then sometimes LESS as it gets too hot).",
                            "Rubber buildup follows the racing line. If you go off-line, grip drops dramatically. Use this knowledge when overtaking.",
                            "Rain does not mean zero grip. It means different grip. The racing line often LOSES grip in rain because of the rubber buildup, while the off-line actually has MORE grip."
                        ],
                        "common_mistakes": [
                            "Ignoring changing conditions and driving the same way regardless — fast on day 1, off the pace on day 2.",
                            "Over-reacting to a single corner feeling different — wait for 2-3 corners to confirm before making wholesale changes.",
                            "Only adjusting for less grip (braking earlier) and never for more grip (braking later). You should adjust both ways.",
                            "Blaming the car for inconsistency when it is actually you not adapting to changing conditions."
                        ],
                        "success_criteria": "Achieve within 0.5s of optimal pace within 3 laps of any grip level change. Adaptation score > 0.8.",
                        "duration": "Full session observation",
                        "difficulty": 3,
                        "metric": "adaptation_score",
                        "target": "> 0.8"
                    },
                    {
                        "name": "Traffic Management",
                        "description": "In traffic, maintain within 2% of clear-air pace. Practice patience.",
                        "detailed_instructions": "Traffic is inevitable in all but qualifying. Learning to maintain your pace while dealing with slower (or faster) cars is a crucial race skill. The goal is not to get frustrated — it is to stay composed, maintain YOUR rhythm, and minimise the time lost while safely navigating traffic.",
                        "steps": [
                            "In a busy session, record your clear-air pace for the first 3 laps (no traffic).",
                            "When you catch a slower car, DO NOT immediately try to pass. Instead, match their pace for 1 lap while studying their line.",
                            "Identify where they are slow (usually corner exits) and where they are fast (usually straights, where passing is safest).",
                            "Plan your pass for the safest opportunity: end of a straight, into a heavy braking zone. Signal your intent with positioning.",
                            "After passing, immediately resume YOUR pace. Do not try to 'make up' lost time — that leads to errors.",
                            "Track your pace during traffic laps vs clear laps. The goal: no more than 2% slower in traffic.",
                            "If a faster car approaches you, maintain your line predictably. Let them pass where it is safe. Do not 'defend' in a practice session.",
                            "After the session, count how many laps were affected by traffic and by how much."
                        ],
                        "tips": [
                            "Patience is a competitive advantage. Drivers who get frustrated in traffic make mistakes. Stay calm, stay fast.",
                            "Give slower cars plenty of room. They may not see you or may be unpredictable. Assume the worst.",
                            "The 'dirty air' behind another car can reduce your downforce and grip. If following closely, you may need to adjust brake points.",
                            "Flashing headlights is a REQUEST to pass, not a demand. Always pass safely.",
                            "Use traffic as practice for race situations. Every slow car is a potential rival you need to get past cleanly."
                        ],
                        "common_mistakes": [
                            "Getting emotionally frustrated by traffic, leading to aggressive driving and mistakes.",
                            "Trying to pass in dangerous places (mid-corner, over blind crests) because of impatience.",
                            "Losing all concentration on your own driving while focused on the car ahead.",
                            "Tailgating slower cars, which ruins your own aero and gives you less reaction time."
                        ],
                        "success_criteria": "Traffic-affected laps are within 2% of clear-air pace. Zero unsafe passes. Consistency CV% remains < 2.0% even in traffic.",
                        "duration": "Full session",
                        "difficulty": 3,
                        "metric": "consistency_cv_pct",
                        "target": "< 2.0% in traffic"
                    },
                    {
                        "name": "Setup Change Response",
                        "description": "After a setup change, achieve baseline pace within 5 laps.",
                        "detailed_instructions": "When the car's setup changes (tyre pressures, wing angles, spring rates, ride height), it changes HOW the car behaves. An adaptable driver can adjust their technique to match the new behaviour within a few laps. This drill teaches you to read the car's new character and modify your inputs accordingly, rather than fighting the car.",
                        "steps": [
                            "Start with 5 laps to establish your baseline pace on the current setup. Record your time.",
                            "Make a deliberate setup change (or have your engineer/mechanic do it). Good options: adjust tyre pressures +/- 2 PSI, or change rear anti-roll bar stiffness.",
                            "On your first lap after the change, DO NOT push. Drive at 70% and FEEL what is different. Is the car tighter? Looser? Less grip? More?",
                            "On lap 2, identify what needs to change in YOUR technique: 'The car is understeering more, so I need to trail brake deeper to rotate it.'",
                            "On laps 3-5, implement your technique adjustments progressively. Aim to reach baseline pace by lap 5.",
                            "If you cannot reach baseline pace by lap 5, the setup change may be fundamentally slower — or you have not found the right technique adjustment yet.",
                            "Record what the setup change was and what technique adjustment you made. This builds your setup-sensitivity database.",
                            "If time allows, reverse the setup change and verify you return to baseline immediately."
                        ],
                        "tips": [
                            "The first lap on a new setup should be about LISTENING to the car, not driving fast. What is it telling you?",
                            "Common adjustments: more understeer → trail brake deeper and use a later apex. More oversteer → smoother throttle application and earlier throttle.",
                            "Tyre pressure changes affect turn-in response first, then overall grip. Higher pressure = sharper turn-in but less total grip.",
                            "Keep a setup diary. After 10 changes, you will start to predict how each adjustment will feel before you drive it.",
                            "If the car feels worse after a change, that is also valuable data. Knowing what does NOT work is as important as knowing what does."
                        ],
                        "common_mistakes": [
                            "Going out at full speed immediately after a change and getting surprised by different car behaviour.",
                            "Not adjusting your driving technique and instead blaming the setup for poor performance.",
                            "Making the setup change too extreme (e.g., 10 PSI tyre pressure change) which makes adaptation impossible.",
                            "Not recording what was changed and what you adjusted, losing the learning opportunity."
                        ],
                        "success_criteria": "Achieve within 0.5s of baseline pace within 5 laps of any setup change. Documented what changed and how you adapted.",
                        "duration": "25–30 minutes per setup change",
                        "difficulty": 3,
                        "metric": "pace_delta_s",
                        "target": "< 0.5s within 5 laps"
                    },
                ],
            },
            {
                "week": 4,
                "title": "Race Simulation",
                "focus": "Everything from Weeks 1-3 comes together in race conditions. Race driving is different from practice: you must maintain pace over long distances, manage resources (tyres, fuel, mental energy), and make tactical decisions under pressure. This week simulates race conditions to prepare you for competition.",
                "coaching_notes": "A race is not a sprint — it is a marathon at sprint pace. The driver who wins is usually not the fastest on any single lap, but the one who maintains the highest AVERAGE pace over the full distance while making the fewest mistakes. This week is about proving you can sustain everything you have learned for a full race distance.",
                "warmup": "5 laps building from 60% to 90% pace. Treat this as your formation/warm-up lap sequence. Warm the tyres evenly, check the brakes, and get mentally into 'race mode'.",
                "drills": [
                    {
                        "name": "Race Distance Run",
                        "description": "Complete a full race distance. Target < 1% pace drop in final quarter.",
                        "detailed_instructions": "This is a simulated race. You will drive a full race distance (or equivalent, typically 20-30 laps) and your goal is to maintain consistent pace from start to finish. In real races, pace typically drops in the final quarter due to tyre wear, fuel load change, and driver fatigue. Your target is to limit this drop to less than 1%.",
                        "steps": [
                            "Calculate your race distance: typically 20-30 laps. Set this as your target before going out.",
                            "Laps 1-3: Use these as 'race start' laps. Drive at 95% — aggressive but controlled. Set a fast early pace.",
                            "Laps 4-10: Settle into 'race pace'. This is 93-95% effort — fast enough to be competitive but sustainable.",
                            "Laps 11-15: 'Mid-race'. Fatigue may start to appear. Focus on your reference points and routines to maintain concentration.",
                            "Laps 16-20: 'Final stint'. This is where discipline matters most. Do NOT push harder — maintain the same pace.",
                            "Laps 21+: 'Last push'. If you have energy, use the final 3-5 laps to push to 97%. If not, maintain pace.",
                            "After the run, compare your first quarter pace to your last quarter pace. The delta should be < 1%.",
                            "Review your lap time chart: a flat line is ideal. A gradual decline is acceptable. A cliff is a problem."
                        ],
                        "tips": [
                            "Hydrate before the session. Dehydration causes concentration lapses, which cause inconsistency.",
                            "Use consistent breathing patterns. Exhale on braking, inhale on straights. This maintains focus.",
                            "If you feel concentration fading, increase your self-talk: verbalise every reference point aloud.",
                            "Monitor tyre degradation through corner feel. If the car starts pushing mid-session, reduce entry speed slightly rather than fighting it.",
                            "A 1% pace drop over 20 laps is only about 0.7s — that is excellent endurance. Do not beat yourself up for small drops."
                        ],
                        "common_mistakes": [
                            "Starting too fast and having nothing left for the second half of the race distance.",
                            "Not pacing yourself — treating a race distance run like a qualifying session.",
                            "Ignoring tyre degradation and continuing to push the same way on worn tyres.",
                            "Getting mentally drained by lap 15 and making a concentration error that ruins the rest of the run."
                        ],
                        "success_criteria": "Complete full race distance with < 1% pace drop between first quarter and last quarter averages. No major incidents.",
                        "duration": "50–70 minutes",
                        "difficulty": 4,
                        "metric": "early_vs_late_stint_pace",
                        "target": "< 1% drop"
                    },
                    {
                        "name": "Attack and Defend Laps",
                        "description": "Alternate between push laps and conservation laps. Maintain control.",
                        "detailed_instructions": "In a race, you will alternate between attacking (pushing to close a gap or make a pass) and defending (conserving tyres, managing a gap, or recovering from a mistake). This drill teaches you to switch between these modes smoothly — going from 97% effort to 90% and back without losing composure or making errors during the transitions.",
                        "steps": [
                            "Drive 3 warm-up laps at 85% pace.",
                            "Laps 4-5: PUSH. 97% effort. These are your 'attack' laps. Go as fast as you safely can.",
                            "Laps 6-7: CONSERVE. Drop to 90% effort. These are your 'management' laps. Focus on clean driving and tyre conservation.",
                            "Laps 8-9: PUSH again. Can you match your earlier push lap times?",
                            "Laps 10-11: CONSERVE again. Is the drop from push to conserve smooth or does it feel disorienting?",
                            "Repeat this alternating pattern for 20 laps total (5 cycles of push-conserve).",
                            "Monitor: your push laps should be within 0.3s of each other, and your conserve laps within 0.3s of each other.",
                            "After the session, review the pace chart: it should look like a clean square wave, not a jagged mess."
                        ],
                        "tips": [
                            "The transition from conserve to push is harder than you think. Allow 1 corner to 'switch on' before expecting peak pace.",
                            "During conserve laps, focus on a specific technical element: smoothness, or line precision, or brake release. Make conserve laps educational.",
                            "The difference between push and conserve should be about 2-3% effort, not a dramatic shift.",
                            "In a real race, you might push for 1-2 laps and conserve for 5-6. This drill uses equal intervals for practice.",
                            "If you cannot maintain control during the transitions, the gap between your push and conserve pace is too large. Narrow it."
                        ],
                        "common_mistakes": [
                            "Conserve laps becoming mentally lazy rather than intentionally managed. Conservation is active, not passive.",
                            "Push laps becoming ragged and mistake-prone because you are 'trying too hard' after a conserve period.",
                            "Not having a clear mental switch between modes — you should be able to articulate which mode you are in at any moment.",
                            "Over-attacking on push laps and damaging tyres, making the next conserve period insufficient for recovery."
                        ],
                        "success_criteria": "Push laps within 0.3s of each other. Conserve laps within 0.3s of each other. Total session score > 75.",
                        "duration": "40–50 minutes",
                        "difficulty": 4,
                        "metric": "total_score",
                        "target": "> 75"
                    },
                    {
                        "name": "Cool-Down Analysis",
                        "description": "Review session, identify 3 actionable improvements for next session.",
                        "detailed_instructions": "The post-session review is where the learning crystallises. This is not just 'looking at data' — it is a structured analysis process that identifies specific, actionable improvements you can implement in your next session. Without this step, you are just logging miles instead of building skill.",
                        "steps": [
                            "While the session is fresh in your mind (within 30 minutes), open your telemetry data.",
                            "Overall review: What was your best lap time? Average pace? Consistency (CV%)? How do these compare to last session?",
                            "Identify your TOP 3 time-loss corners: where are you leaving the most time on the table?",
                            "For each time-loss corner, diagnose WHY: Is it late braking? Poor trail braking? Inconsistent line? Slow exit? Use the data traces to confirm.",
                            "For each diagnosis, write one SPECIFIC action: not 'be faster in T5' but 'trail brake 3m deeper into T5, targeting apex speed of 85 km/h.'",
                            "Look at your race simulation data: where did pace drop? Was it physical fatigue, mental fatigue, or tyre degradation?",
                            "Write 3 actionable improvements: (1) one technique fix, (2) one consistency improvement, (3) one mental/physical improvement.",
                            "Rate your overall session on a 1-10 scale and note one thing you are proud of.",
                            "Save this review — you will reference it at the start of your next session."
                        ],
                        "tips": [
                            "Write improvements as specific, measurable actions — vague goals like 'drive better' are useless.",
                            "Always include one positive in your review. Progress motivation requires acknowledging wins, not just failures.",
                            "Compare to your PREVIOUS self, not to faster drivers. Your improvement trajectory is what matters.",
                            "If you consistently identify the same weakness over multiple sessions, it may need dedicated drill work rather than just 'trying harder'.",
                            "Share your analysis with a coach or experienced driver if possible. A second perspective often reveals blind spots."
                        ],
                        "common_mistakes": [
                            "Skipping the review because you are tired. Discipline yourself to do it while the session is fresh.",
                            "Being too self-critical. The review should be analytical, not emotional.",
                            "Only looking at lap times instead of corner-level data. The details reveal the path to improvement.",
                            "Writing improvements but never reviewing them before the next session — use your notes!"
                        ],
                        "success_criteria": "Documented session review with 3 specific, measurable improvement actions. Each action references a specific corner or technique. Written plan for next session.",
                        "duration": "30–45 minutes (off-track)",
                        "difficulty": 2,
                        "metric": "total_score",
                        "target": "documented plan"
                    },
                ],
            },
        ],
    },
    "advanced": {
        "id": "advanced",
        "name": "Advanced Performance",
        "description": "Extract maximum performance: limit exploitation, data-driven optimisation, mental fortitude, and race strategy. This program is for experienced drivers who are already fast and consistent, and want to find the final tenths that separate good from great. Every drill operates at or near the performance limit.",
        "level": "advanced",
        "prerequisites": "Completed Intermediate Refinement or equivalent. You should trail brake confidently, link corners fluently, and lap consistently within 1% CV. Your telemetry should show clean, purposeful traces with minimal corrections.",
        "equipment_needed": "Full data-logging suite (speed, GPS, throttle, brake traces minimum). Access to overlay/comparison software. Ideally: rival data for comparison analysis.",
        "weeks": [
            {
                "week": 1,
                "title": "Limit Exploitation",
                "focus": "At the advanced level, the car spends significant time at or near the grip limit. This week is about learning to live at that limit consistently — not just touching it occasionally, but spending 90%+ of each lap within 5% of maximum grip. The G-G diagram is your roadmap: every point where it is not filled represents unused performance.",
                "coaching_notes": "This is physically and mentally demanding. The concentration required to operate at the limit for extended periods is enormous. Take breaks between stints. Hydrate constantly. If you feel your reactions slowing, stop — fatigue at the limit is dangerous.",
                "warmup": "5 laps building to 95% pace. Use these to calibrate your senses: what does the car feel like at 90%? At 95%? You need a precise internal speedometer for the work ahead.",
                "drills": [
                    {
                        "name": "G-G Diagram Filling",
                        "description": "Maximize the G-G envelope utilization. Target 95%+ grip usage.",
                        "detailed_instructions": "The G-G diagram (also called friction circle) shows the relationship between longitudinal forces (braking/acceleration) and lateral forces (cornering). A perfectly driven car fills the diagram to its edges at all times — meaning you are always using all available grip in some combination. Gaps in the diagram represent moments where grip is being wasted. This drill systematically fills those gaps.",
                        "steps": [
                            "Review your most recent session's G-G diagram. Identify the empty quadrants or gaps.",
                            "Common gap 1: TRANSITION ZONES (between braking and cornering). This gap fills with better trail braking. Practice entering corners with combined braking + turning.",
                            "Common gap 2: CORNER EXIT (between cornering and acceleration). This fills with earlier, smoother throttle application while still carrying steering angle.",
                            "Common gap 3: PEAK LATERAL (maximum cornering G). This fills with higher minimum corner speeds — you are not using all the lateral grip available.",
                            "Drive 5 laps focusing on gap 1. Your brake traces should overlap with your steering traces more than before.",
                            "Drive 5 laps focusing on gap 2. Your throttle traces should start earlier, while steering angle is still present.",
                            "Drive 5 laps focusing on gap 3. Carry 1-2 km/h more through mid-corner. Does the car accept it? If yes, the gap was real.",
                            "Drive 5 final laps combining all three. Review your new G-G diagram — it should be more filled.",
                            "Calculate your grip utilization percentage. Target: 95%+ of the theoretical envelope."
                        ],
                        "tips": [
                            "The G-G diagram has a LIMIT shape determined by tyre grip, weight distribution, and aero. You cannot exceed it — but you should fill it.",
                            "The quadrant between braking and left turn, and braking and right turn, should be well-populated. If they are empty, you are not trail braking effectively.",
                            "At high speed, aero increases the G-G envelope. At low speed, it shrinks. Your technique must adapt to both.",
                            "Professional drivers spend 85-95% of a lap within 5% of the grip limit. Club racers are typically at 60-75%. Your target is 90%+.",
                            "The most wasted grip is usually in transition zones (brake to corner, corner to throttle). Focus there first."
                        ],
                        "common_mistakes": [
                            "Exceeding the G-G limit (spinning, locking up) in pursuit of filling the diagram. The goal is to approach the limit, not exceed it.",
                            "Only focusing on peak G values instead of the CONTINUITY of the envelope. Every point on the lap should be near the edge.",
                            "Ignoring straight-line braking quality — even on straights, you should be using near-maximum braking force.",
                            "Treating the G-G diagram as static. It changes with tyre wear, fuel load, and temperature throughout a session."
                        ],
                        "success_criteria": "G-G diagram shows 95%+ envelope utilization. Transition zones (brake-to-corner, corner-to-throttle) are well-populated with no large gaps.",
                        "duration": "40–50 minutes",
                        "difficulty": 5,
                        "metric": "grip_utilization",
                        "target": "> 0.95"
                    },
                    {
                        "name": "Micro-Sector Optimisation",
                        "description": "Identify 3 sectors with largest gap to theoretical. Attack each individually.",
                        "detailed_instructions": "Your theoretical best lap is the sum of your best sector times from different laps. The gap between your actual best lap and your theoretical best represents time lost in transitions between good sectors. This drill identifies your 3 weakest micro-sectors and attacks each one individually to close the gap to theoretical.",
                        "steps": [
                            "Calculate your theoretical best: sum of your best time in each sector/micro-sector from your last session.",
                            "Compare to your actual best lap. The gap is your 'time on the table'. Typically 0.3-0.8s for advanced drivers.",
                            "Rank all micro-sectors by time loss: time in sector vs best-ever time in that sector.",
                            "Take the 3 worst micro-sectors. These are your targets. Analyse each: what is causing the time loss? Late braking? Poor line? Slow exit?",
                            "Stint 1 (8 laps): Focus ONLY on micro-sector 1. Drive the rest of the lap at 90%. Put all attention on this section.",
                            "Stint 2 (8 laps): Focus on micro-sector 2. Same approach.",
                            "Stint 3 (8 laps): Focus on micro-sector 3. Same approach.",
                            "Final stint (5 laps): Combine all three improvements into a complete lap attempt.",
                            "Compare your new theoretical best to your old one. Target: 30% reduction in the gap."
                        ],
                        "tips": [
                            "The theoretical best is always faster than what you can achieve in a single lap — maintaining peak performance in ALL sectors simultaneously is the ultimate challenge.",
                            "Sometimes a slow micro-sector is caused by a poor exit from the PREVIOUS sector, not by anything in the sector itself.",
                            "Video analysis combined with data is incredibly powerful here. Watch your in-car footage for the 3 target sectors.",
                            "If you cannot improve a micro-sector after 8 laps of focus, the issue may be setup-related rather than driving-related.",
                            "A 30% reduction in gap is significant. At advanced level, even 0.1s is a meaningful improvement."
                        ],
                        "common_mistakes": [
                            "Trying to improve ALL sectors simultaneously — this leads to zero improvement because attention is diluted.",
                            "Not diagnosing the ROOT CAUSE of time loss before attacking the sector. Driving harder in a sector where the line is wrong will not help.",
                            "Improving a target sector but losing time in adjacent sectors because of changed momentum. Always check the full picture.",
                            "Getting frustrated by small gains. At advanced level, 0.05s per sector is genuine progress."
                        ],
                        "success_criteria": "30% reduction in gap between actual best lap and theoretical best. At least 2 of 3 target micro-sectors show measurable improvement.",
                        "duration": "50–60 minutes",
                        "difficulty": 5,
                        "metric": "time_loss_ms",
                        "target": "reduce by 30%"
                    },
                    {
                        "name": "Tyre Management at Limit",
                        "description": "Push at 98% for 10 laps. Monitor tyre temp and grip degradation.",
                        "detailed_instructions": "The ability to maintain performance while managing tyre degradation separates professional-level drivers from amateurs. This drill teaches you to drive at 98% effort while monitoring and responding to tyre degradation in real-time. You will learn to feel the grip fading and adjust your technique by micro-amounts to extend tyre life without sacrificing pace.",
                        "steps": [
                            "Drive 3 laps at 95% to establish your baseline grip level. Note the car's behaviour: turn-in response, mid-corner balance, traction on exit.",
                            "Laps 4-13: Drive at 98% effort for 10 consecutive laps. This is near your maximum sustainable pace.",
                            "After every 2 laps, mentally assess: is the car doing the same thing? Or is it starting to push (understeer) more? Or is the rear less stable?",
                            "When you notice the first sign of degradation (usually lap 5-7): begin micro-adjustments. Trail brake 1m less deep. Carry 1 km/h less entry speed. Apply throttle 5% more gently.",
                            "The goal: your lap time should NOT drop by more than 0.3s over the 10 laps, even as the tyres degrade.",
                            "After the 10-lap stint, do 2 cool-down laps. Note how much grip has been lost compared to the start.",
                            "Review the data: plot your 10 lap times. A flat line = excellent management. A steady decline = you are overusing the tyres. A cliff = catastrophic.",
                            "Compare tyre degradation to your pace: how much time did you lose per lap to degradation, and how much did you recover through technique?"
                        ],
                        "tips": [
                            "Tyre degradation is not linear. There is usually a 'cliff' point where grip drops suddenly. Your job is to never reach that cliff.",
                            "Fronts and rears degrade differently. If the fronts go first, you will get understeer. If the rears go first, oversteer. Adjust accordingly.",
                            "Tyre temperature is a leading indicator of degradation. Overheated tyres degrade faster. If your in-lap pirep says temps are high, back off 2%.",
                            "Smoother inputs degrade tyres less. Aggressive braking and sharp steering generate more heat, more slip angle, and more degradation.",
                            "In real races, tyre management is often the decisive factor. A driver who can maintain pace 2% longer than their rival on the same tyres has a huge strategic advantage."
                        ],
                        "common_mistakes": [
                            "Ignoring early signs of degradation and driving the same way until grip falls off a cliff.",
                            "Over-compensating for degradation and slowing down too much — the goal is micro-adjustments, not backing off.",
                            "Only monitoring one axle when both front and rear tyres degrade at different rates.",
                            "Not correlating your driving style to degradation rate. Aggressive trail braking kills fronts. Wheelspin kills rears."
                        ],
                        "success_criteria": "10-lap stint at 98% with < 0.8% CV. Lap time drop from first to last lap < 0.5s. No sudden grip loss.",
                        "duration": "30–40 minutes",
                        "difficulty": 5,
                        "metric": "consistency_cv_pct",
                        "target": "< 0.8%"
                    },
                ],
            },
            {
                "week": 2,
                "title": "Data-Driven Gains",
                "focus": "At the advanced level, feel alone is not enough. The differences between fast and fastest are too small to perceive without data. This week is about becoming a data analyst as much as a driver — using overlays, comparative analysis, and rival data to find time that is invisible to the naked eye.",
                "coaching_notes": "Data analysis is a skill that improves with practice, just like driving. The first time you overlay two laps, you might only see gross differences. After 50 overlays, you will spot a 0.02s brake point difference by eye. Invest time in learning your analysis software — it pays dividends for years.",
                "warmup": "5 laps at 90% to collect clean data for today's analysis work. These laps should be your 'reference' set.",
                "drills": [
                    {
                        "name": "Overlay Analysis",
                        "description": "Compare your best 3 laps. Find the composite ideal lap time.",
                        "detailed_instructions": "Take your 3 fastest laps from the most recent session and overlay them. The composite of the best sections from each lap represents your theoretical achievable time. The differences between laps reveal where inconsistency or sub-optimal technique is costing you time. This is surgical-level performance extraction.",
                        "steps": [
                            "Load your 3 fastest laps from the last session into overlay/comparison mode.",
                            "Compare speed traces: where do the lines diverge? Every divergence point is either a gain or a loss.",
                            "For each divergence: identify which lap is fastest in that section. Why is it fastest? Earlier braking? More carry speed? Better exit?",
                            "Build the 'ideal composite': best section of lap 1 + best section of lap 2 + best section of lap 3. Calculate the theoretical time.",
                            "Identify the TOP 5 sections where you have the most variance between your 3 best laps. These are your consistency gaps.",
                            "For each consistency gap, diagnose the root cause using brake, throttle, and steering traces.",
                            "Drive 10 laps targeting the composite ideal. On each lap, focus on the section where you lost the most time on the previous lap.",
                            "After 10 laps, overlay your new best against the composite ideal. How close did you get?"
                        ],
                        "tips": [
                            "Speed trace is the most useful view for overlay analysis. Every speed difference directly translates to time.",
                            "Zoom in to individual corners. At the full-lap view, small differences are invisible. Corner-level zoom reveals everything.",
                            "If two laps have the same corner speed but different times, the difference is in the transitions (braking or acceleration zones).",
                            "The theoretical composite is usually 0.3-0.8s faster than any single lap for advanced drivers. Getting within 0.3s is the target.",
                            "Save your composite ideal as a reference — you can overlay it against future sessions to track improvement."
                        ],
                        "common_mistakes": [
                            "Only overlaying 2 laps instead of 3+. More laps reveal more consistent patterns and reduce noise.",
                            "Looking only at speed and ignoring brake/throttle traces. The CAUSE of speed differences is in the input traces.",
                            "Not accounting for draft or traffic effects that can make a lap artificially fast or slow in certain sectors.",
                            "Getting discouraged by the gap to theoretical. The theoretical is a target, not an expectation."
                        ],
                        "success_criteria": "Achieve a lap within 0.3s of your theoretical composite ideal. Identify and diagnose at least 5 specific variance points between your best laps.",
                        "duration": "45–60 minutes (mixed driving and analysis)",
                        "difficulty": 4,
                        "metric": "theoretical_time_s",
                        "target": "< 0.3s from theoretical"
                    },
                    {
                        "name": "Corner-Specific Attack",
                        "description": "Pick your 2 weakest corners (highest time loss). Dedicate 15 min each.",
                        "detailed_instructions": "Pareto principle applies to lap time: 20% of your corners contain 80% of your time loss. This drill identifies your 2 worst corners and applies focused, surgical improvement work to each one. By dedicating 15 minutes of pure focus per corner, you can make more progress than hours of general lapping.",
                        "steps": [
                            "From your overlay analysis, rank all corners by time loss (gap between your average and your best through each corner).",
                            "Select the 2 corners with the largest time loss. These are your targets for today.",
                            "For corner 1: analyse the data. What is the specific cause? Break it into components: brake point, entry speed, apex speed, exit speed, line.",
                            "Identify the ONE component that contributes most to the time loss. This is your focus.",
                            "Drive 8 laps focusing ONLY on corner 1 and the one component you identified. Ignore everything else.",
                            "After 8 laps, check the data: has the time loss in corner 1 reduced? By how much?",
                            "Repeat for corner 2: analyse, identify, focus, drive 8 laps, verify.",
                            "Drive 5 final laps integrating both corner improvements into a complete lap.",
                            "Calculate the total time saved from both corners. Target: reduce the combined time loss by 50%."
                        ],
                        "tips": [
                            "The weakest corner is not always the one that feels hardest. Data often reveals that your 'comfortable' corners are actually your slowest.",
                            "Single-component focus is critical. If you try to fix braking AND line AND exit simultaneously, you fix nothing.",
                            "8 laps of focused practice on one corner is more effective than 80 laps of general practice. Quality over quantity.",
                            "Record video of the target corner before and after. The visual comparison often reveals improvements you cannot feel.",
                            "If after 8 focused laps the time loss has not improved, your diagnosis was wrong. Re-analyse the data."
                        ],
                        "common_mistakes": [
                            "Selecting corners based on feel rather than data. Your perception of 'hard' corners often differs from your actual weakest corners.",
                            "Trying to fix too many things at once in each corner. One issue per session per corner.",
                            "Not verifying improvement with data. If you feel faster but the data says otherwise, believe the data.",
                            "Improving the target corners but regressing in others because focus was diverted. Always check the full picture."
                        ],
                        "success_criteria": "50% reduction in time loss at both target corners. Total lap time improvement of at least 0.2s from corner improvements alone.",
                        "duration": "40–50 minutes",
                        "difficulty": 4,
                        "metric": "time_loss_ms",
                        "target": "reduce weakest by 50%"
                    },
                    {
                        "name": "Rival Study",
                        "description": "Analyse a rival's data if available. Find where they gain and lose.",
                        "detailed_instructions": "If you have access to a rival or benchmark driver's data, this drill is incredibly powerful. By overlaying your data against a faster driver, you can see exactly WHERE they gain time and HOW they do it. This bypasses years of experimentation by showing you the answer directly. Even without rival data, you can use published data or the fastest driver in your series.",
                        "steps": [
                            "Obtain a rival's data from the same track (same session is ideal, same conditions is acceptable).",
                            "Overlay speed traces for a complete lap. Identify every point where the rival is faster (above your trace) or slower (below).",
                            "Categorise each difference: (a) braking zone differences, (b) mid-corner speed differences, (c) exit speed differences, (d) line differences.",
                            "For each section where the rival is faster, measure the time gain. Rank them from largest to smallest.",
                            "For the top 3 sections, deep-dive into the traces: what specifically is the rival doing? Braking later? Carrying more speed? Different line?",
                            "Identify which of the rival's techniques are safe to adopt and which are beyond your current car's capability.",
                            "Drive 10 laps implementing the rival's technique in your top 2 imitation targets.",
                            "Compare your new data: did you close the gap? By how much?",
                            "Also note sections where YOU are faster than the rival — these are your strengths to protect."
                        ],
                        "tips": [
                            "The biggest gains from rival study are usually in braking zones and corner exit — these are where technique matters most.",
                            "If the rival is faster everywhere, focus on the sections where the gap is largest. Small gaps might be car difference, not driver difference.",
                            "A rival who is faster in straight-line speed but slower in corners probably has a power/aero advantage. Focus on where the gap is driver-controlled.",
                            "Studying a rival also reveals their weaknesses — useful intelligence for race day.",
                            "If you cannot obtain rival data, use your own best laps from different sessions as a 'virtual rival'."
                        ],
                        "common_mistakes": [
                            "Attributing all speed differences to driving technique when some may be car setup or power differences.",
                            "Trying to copy everything the rival does instead of focusing on the 2-3 biggest gains.",
                            "Only studying drivers who are much faster — a driver 0.3s ahead is more useful to study than one 3s ahead.",
                            "Not acknowledging your own advantages. The goal is to close gaps while maintaining your existing strengths."
                        ],
                        "success_criteria": "Close the gap to your rival by at least 30% in the studied sections. Identify at least 3 specific technique differences.",
                        "duration": "45–60 minutes (mixed analysis and driving)",
                        "difficulty": 4,
                        "metric": "pace_delta_s",
                        "target": "close gap by 30%"
                    },
                ],
            },
            {
                "week": 3,
                "title": "Mental Performance",
                "focus": "At the advanced level, the difference between your best and worst laps is almost entirely mental. Your body knows the technique — what varies is your mental state: confidence, focus, pressure management, and recovery from errors. This week trains the mental skills that unlock your peak physical performance on demand.",
                "coaching_notes": "Mental performance is the most under-trained aspect of motorsport. Elite drivers in Formula 1, WEC, and GT racing all work with psychologists or mental coaches. This week introduces techniques used at the highest levels of the sport — adapted for you to practice independently.",
                "warmup": "5 laps with a specific mental focus: on each lap, rate your mental state from 1-10. How present are you? How focused? How calm? This self-awareness is the foundation of mental performance.",
                "drills": [
                    {
                        "name": "Pressure Laps",
                        "description": "Simulate qualifying: 3 warm-up laps then 1 push lap. Repeat 5 times.",
                        "detailed_instructions": "Qualifying is the purest test of driving skill — one lap, maximum attack, with everything on the line. This drill simulates qualifying pressure: you must 'switch on' for a single push lap, deliver peak performance, then reset and do it again. The ability to produce your best on demand is what separates professionals from amateurs.",
                        "steps": [
                            "Run 1: Drive 3 warm-up laps at 85%. On lap 4, push to YOUR absolute maximum. This is attempt 1. Note the time.",
                            "Cool down for 3 laps. During cool-down, review mentally: what went well? What could improve?",
                            "Run 2: Repeat — 3 warm-up laps, 1 push lap. Try to beat Run 1. Note the time.",
                            "Cool down and repeat for Runs 3, 4, and 5. Each run should be a fresh qualifying attempt.",
                            "After all 5 runs, analyse: which was your fastest? Your slowest? What was the gap between best and worst?",
                            "Target: your best push lap should be within 0.1s of your personal best. The gap between your best and worst push laps should be < 0.3s.",
                            "Note which run was fastest — this tells you about your peak performance window (fresh and cold? Or warmed up and committed?).",
                            "If Run 1 was fastest, you perform best when fresh. If Run 3-4, you need warm-up. This is valuable self-knowledge."
                        ],
                        "tips": [
                            "The qualifying mindset is not 'try harder'. It is 'execute perfectly'. Relax your body, sharpen your mind.",
                            "Develop a pre-push-lap routine: specific breathing pattern, mental image of the perfect lap, a trigger word or phrase.",
                            "The warm-up laps serve dual purpose: warming tyres AND warming your brain into the focused state.",
                            "If you spin or make a big error on a push lap, use it as data. What were you thinking when it happened? Over-commitment? Distraction?",
                            "Elite qualifying is about CONFIDENCE, not aggression. You need to believe the car can do it, then just let it."
                        ],
                        "common_mistakes": [
                            "Trying harder on each subsequent run instead of resetting mentally. Each run should feel like your FIRST attempt.",
                            "Not properly cooling down between runs — both tyres and brain need to reset.",
                            "Letting a bad push lap affect the next one. Each run is independent. Forget the last one.",
                            "Over-driving on push laps: pushing beyond the limit instead of driving at the limit. The car is fast — let it be fast."
                        ],
                        "success_criteria": "Best push lap within 0.1s of personal best. Gap between best and worst push laps < 0.3s across 5 attempts.",
                        "duration": "40–50 minutes",
                        "difficulty": 5,
                        "metric": "best_lap_time_s",
                        "target": "PB within 0.1s"
                    },
                    {
                        "name": "Recovery Drill",
                        "description": "After a mistake (simulate lock-up), recover pace within 2 laps.",
                        "detailed_instructions": "Mistakes happen at every level. What defines an advanced driver is not the absence of mistakes, but the speed of recovery. This drill practices recovering from errors: a lock-up, a slide, a missed apex — and returning to peak pace within 2 laps. The goal is to build mental resilience so that errors do not cascade into lost confidence and lost time.",
                        "steps": [
                            "Establish your baseline pace: 5 laps at 95% effort. Note your average time.",
                            "On lap 6, DELIBERATELY make a small mistake: brake too late into one corner (simulate lock-up), or carry too much speed (simulate a slide).",
                            "The error lap will be slow. That is OK. Focus on WHAT HAPPENS NEXT.",
                            "On lap 7 (recovery lap 1): focus on executing the basics perfectly. Smooth braking, correct lines, clean exits. Target: within 1% of baseline.",
                            "On lap 8 (recovery lap 2): push back to 95%. Target: within 0.3s of your baseline average.",
                            "Repeat the cycle: 3 clean laps → 1 deliberate error → 2 recovery laps. Do this 4 times total.",
                            "Track your recovery speed: how many laps does it take to return to baseline pace after each error?",
                            "Your goal: achieve full recovery within 2 laps, every time. The error should not affect anything beyond the error lap itself."
                        ],
                        "tips": [
                            "The key mental skill is compartmentalisation: the mistake is IN THE PAST. Your next braking point is in the future. Stay present.",
                            "After an error, your body will tense up and your brain will say 'be careful'. Fight this by taking a deep breath and resetting.",
                            "Do NOT try to 'make up' the time lost to the error. This leads to more errors. Just return to your normal pace.",
                            "In a race, a 2-lap recovery from a mistake might cost you 0.5s total. A 5-lap recovery costs 2-3s. Speed of recovery matters enormously.",
                            "Pro drivers typically recover within 1-2 corners, not laps. Your target is 2 laps — the pro target is the next corner."
                        ],
                        "common_mistakes": [
                            "Making the deliberate error too dramatic (full spin, off-track) instead of realistic (small lock-up, slight oversteer).",
                            "Carrying the emotional impact of the error into the recovery laps. The error is DONE. Move on.",
                            "Overdriving on recovery laps in an attempt to compensate, creating a second error.",
                            "Not practising this drill because 'I should not practise mistakes'. Recovery is the skill, not the mistake."
                        ],
                        "success_criteria": "Full pace recovery within 2 laps of every deliberate error. CV% of clean laps remains < 1.0% despite the inserted errors.",
                        "duration": "30–40 minutes",
                        "difficulty": 4,
                        "metric": "consistency_cv_pct",
                        "target": "< 1.0% post-error"
                    },
                    {
                        "name": "Visualisation Session",
                        "description": "Walk the track mentally. Note every braking marker, apex, exit point.",
                        "detailed_instructions": "Mental rehearsal is used by every elite athlete in every sport. For racing, it means being able to drive an entire lap in your mind — in real-time — with perfect accuracy of every brake point, turn-in, apex, exit, and throttle application. Studies show that mental rehearsal activates the same neural pathways as physical driving, making your on-track performance more automatic and consistent.",
                        "steps": [
                            "Find a quiet space. Sit comfortably with your eyes closed. Set a timer equal to your lap time.",
                            "Begin the lap in your mind. Start from the start/finish line. SEE the track ahead of you.",
                            "As you approach each braking zone: visualise your braking marker. Feel your foot press the pedal. Feel the car decelerate.",
                            "Turn in: feel the steering wheel. See the apex approaching. Feel the car rotate.",
                            "Exit: feel the throttle application. See the exit kerb. Feel the car accelerate.",
                            "Continue through every corner, every straight, every transition. DO NOT skip any part.",
                            "When you finish the lap, check your timer. If your mental lap time is close to your real lap time (+/- 2%), your visualisation is accurate.",
                            "Repeat the lap 5 times. Each time, add more detail: the sound of the engine, the vibration of the kerbs, the G-forces.",
                            "If you cannot visualise a specific section, that reveals a gap in your mental map. Focus on that section during your next track visit."
                        ],
                        "tips": [
                            "Visualise in FIRST PERSON (through your own eyes), not third person (watching yourself from outside). First person is more effective.",
                            "Include sensory details: the sound of gravel if you go slightly wide, the feel of the steering loading up under braking, the smell of brake dust.",
                            "Time your mental laps. If they are too fast, you are skipping sections. If too slow, you are over-thinking. Match real-time.",
                            "Do this before bed — research shows sleep consolidates mental rehearsal into long-term motor memory.",
                            "You can visualise anywhere: on a plane, in a hotel, at work. Elite drivers visualise laps dozens of times between races."
                        ],
                        "common_mistakes": [
                            "Rushing through the visualisation. Each corner should take the same time as it does in reality.",
                            "Only visualising the 'good' laps. Include visualisations of recovering from mistakes — this trains your recovery response.",
                            "Doing it once and thinking it is done. Visualisation is a PRACTICE — it gets better (and more effective) with repetition.",
                            "Not using all senses. Just 'seeing' the track is not enough. You need to feel, hear, and even smell it."
                        ],
                        "success_criteria": "Complete 5 mental laps with real-time accuracy (+/- 2% of actual lap time). Can name every braking marker, apex, and exit point from memory without hesitation.",
                        "duration": "20–30 minutes (off-track)",
                        "difficulty": 2,
                        "metric": "n/a",
                        "target": "complete walkthrough"
                    },
                ],
            },
            {
                "week": 4,
                "title": "Competition Readiness",
                "focus": "The final week integrates everything: physical technique at the limit, data-driven optimisation, and mental performance under pressure. These drills simulate actual competition conditions — qualifying attempts, race strategy execution, and comprehensive debriefing. After this week, you are ready to compete at your highest level.",
                "coaching_notes": "This is the culmination of months of work. Trust your preparation. The driver who shows up to a race with a structured development plan, proven techniques, and mental routines will outperform a driver with more natural talent but no structure. Preparation is your competitive advantage.",
                "warmup": "5 laps at 90% with full mental routines active. Visualise each corner before you arrive. Execute your breathing pattern. This is your race warm-up procedure.",
                "drills": [
                    {
                        "name": "Full Qualifying Simulation",
                        "description": "3 runs: warm-up + push lap. Best of 3 is your benchmark.",
                        "detailed_instructions": "This is a full qualifying simulation with race-realistic procedures. You will complete 3 qualifying runs, each consisting of warm-up laps and a push lap, mimicking the format of a real qualifying session. The goal is to produce a time within 0.2s of your absolute personal best — on demand, under pressure.",
                        "steps": [
                            "Begin with your pre-qualifying mental routine: 2 minutes of breathing exercises, visualise one perfect lap, set your intention.",
                            "Run 1: 3 warm-up laps building to 95%, then 1 MAXIMUM push lap. Note the time immediately.",
                            "In-lap: cool down and debrief mentally. Rate the lap 1-10. What worked? What did not?",
                            "Wait 3-5 minutes. Hydrate. Reset mentally.",
                            "Run 2: Same format. Try to BEAT Run 1. Use your debrief insights.",
                            "In-lap, debrief, wait, reset.",
                            "Run 3: Final attempt. This is it. Leave nothing on the table.",
                            "After all 3 runs, analyse: your best time is your qualifying benchmark. Compare to your personal best.",
                            "Debrief the entire session: which run was best? What was different about that run compared to the others?",
                            "Your target: best of 3 within 0.2s of your absolute personal best."
                        ],
                        "tips": [
                            "Treat this EXACTLY like a real qualifying session. No casual laps. Every lap has purpose.",
                            "Your mental state before each run matters enormously. Develop a consistent pre-run ritual.",
                            "If Run 1 is your best, your warm-up procedure is working perfectly. If Run 3, you need more time to build confidence.",
                            "Do not change your approach between runs. Small refinements only. Big changes under pressure lead to errors.",
                            "After the session, write down your lap time and the conditions. This becomes your qualifying benchmark for this track."
                        ],
                        "common_mistakes": [
                            "Treating the simulation casually because 'it is just practice'. The whole point is to simulate pressure.",
                            "Changing your approach dramatically between runs based on one result. Consistency of method matters.",
                            "Not implementing a proper cool-down and reset between runs. Your brain needs the break.",
                            "Being disappointed with a time that is 0.2s off your best. That is actually an EXCELLENT result under simulated pressure."
                        ],
                        "success_criteria": "Best push lap within 0.2s of absolute personal best. 3 runs completed with full qualifying procedure.",
                        "duration": "35–45 minutes",
                        "difficulty": 5,
                        "metric": "best_lap_time_s",
                        "target": "< 0.2s from absolute best"
                    },
                    {
                        "name": "Race Strategy Execution",
                        "description": "Practice planned race strategy: tyre management, fuel saving, overtaking.",
                        "detailed_instructions": "A race is not won on pace alone — it is won on strategy execution. This drill simulates a race with a pre-planned strategy: tyre management targets, fuel saving requirements, and overtaking zone execution. You must balance peak performance with strategic discipline — fast enough to be competitive, controlled enough to execute the plan.",
                        "steps": [
                            "Before going out, write your race strategy: (a) target lap time range, (b) tyre management plan (push early or save for late?), (c) fuel management targets, (d) 2 planned overtaking zones.",
                            "Laps 1-3: Race start simulation. Execute a strong start with controlled aggression. Hit your target pace immediately.",
                            "Laps 4-8: Tyre management phase. Drive at 93-95% while monitoring degradation. Adjust brake points and entry speeds to manage tyre life.",
                            "Laps 9-12: Fuel management phase. Lift-and-coast on 2 straights to save fuel (simulate fuel-limited scenarios). Maintain lap time within 0.5s of target.",
                            "Laps 13-15: Overtaking execution. Simulate overtaking at your 2 planned zones. Execute the moves you practised in earlier weeks.",
                            "Laps 16-20: Final stint push. All management off — push to your limit for the final laps. How much pace do you have in reserve?",
                            "After the session, score yourself: did you execute the strategy? Did you hit your lap time targets? Did the overtaking moves work?",
                            "Review the overall race simulation: pace chart, tyre management effectiveness, strategy compliance."
                        ],
                        "tips": [
                            "Strategy compliance is a DISCIPLINE, not a talent. It requires conscious effort to follow a plan when your instinct says 'push harder'.",
                            "Lift-and-coast saves more fuel than you think. A 1-second lift before each braking zone can save 3-5% fuel over a race distance.",
                            "The driver who switches between management and push modes most efficiently usually wins endurance races.",
                            "Practice your radio communication during the simulation: call out your fuel status, tyre condition, and gap to yourself.",
                            "The best race strategies are simple. Complex strategies fail under pressure. Your plan should fit on a Post-it note."
                        ],
                        "common_mistakes": [
                            "Abandoning the strategy when things are going well ('I am faster than planned, let me push'). Stick to the plan.",
                            "Not practising fuel management because 'I am not in an endurance series'. Fuel management is a universal skill.",
                            "Over-complicating the strategy with too many phases and targets. Simplicity is robust under pressure.",
                            "Not debriefing strategy compliance — only looking at pace. The strategy execution is the skill being trained."
                        ],
                        "success_criteria": "Complete race simulation with strategy compliance score > 85%. Lap times within target range. Successful execution of at least 1 overtaking manoeuvre.",
                        "duration": "50–60 minutes",
                        "difficulty": 5,
                        "metric": "total_score",
                        "target": "> 85"
                    },
                    {
                        "name": "Comprehensive Debrief & Goal Setting",
                        "description": "Complete comprehensive debrief. Set 3 goals for competition.",
                        "detailed_instructions": "This is the capstone of the entire Advanced Performance program. You will conduct a comprehensive review of your development journey: what you have learned, how much you have improved, what your remaining weaknesses are, and what your competition goals should be. This debrief transforms 4 weeks of work into a concrete competition plan.",
                        "steps": [
                            "Review your data from Week 1 (limit exploitation): what is your current grip utilization? How close to theoretical best?",
                            "Review Week 2 (data-driven gains): what were your biggest time-loss areas? How much did you reduce them?",
                            "Review Week 3 (mental performance): what is your qualifying simulation consistency? How fast is your error recovery?",
                            "Review Week 4 (competition readiness): how did your qualifying sim and race strategy execution go?",
                            "Calculate your TOTAL improvement over 4 weeks: lap time delta, consistency delta, and overall score delta.",
                            "Identify your TOP 3 STRENGTHS to leverage in competition.",
                            "Identify your TOP 3 WEAKNESSES to continue working on.",
                            "Set 3 SMART competition goals: (1) a pace target, (2) a consistency target, (3) a strategic target.",
                            "Write a pre-race checklist: mental routine, warm-up procedure, qualifying approach, race strategy framework.",
                            "Commit to your goals by writing them down and sharing with your team, coach, or accountability partner."
                        ],
                        "tips": [
                            "SMART goals: Specific, Measurable, Achievable, Relevant, Time-bound. 'Be faster' is not a goal. 'Achieve within 0.3s of fastest in class by Round 3' is.",
                            "Strengths are as important as weaknesses. Your race strategy should maximise your strengths, not just fix weaknesses.",
                            "The pre-race checklist should become automatic with repetition. Every race weekend starts with the same routine.",
                            "Set one 'stretch' goal that excites you and one 'safety' goal you are confident you can achieve. This balances motivation and confidence.",
                            "Review this debrief before every race weekend. It is your development roadmap."
                        ],
                        "common_mistakes": [
                            "Setting vague goals ('do well') instead of specific, measurable ones.",
                            "Only focusing on weaknesses in the debrief and not acknowledging progress and strengths.",
                            "Not writing anything down. A debrief in your head is worth 10% of a written debrief.",
                            "Setting goals that depend on others (e.g., 'beat driver X') instead of controllable goals (e.g., 'achieve CV < 0.8%')."
                        ],
                        "success_criteria": "Comprehensive written debrief covering all 4 weeks. 3 SMART competition goals documented. Pre-race checklist written and tested.",
                        "duration": "45–60 minutes (off-track)",
                        "difficulty": 2,
                        "metric": "total_score",
                        "target": "written debrief"
                    },
                ],
            },
        ],
    },
    "race_prep": {
        "id": "race_prep",
        "name": "Race Weekend Preparation",
        "description": "4-week countdown to race day: building speed, race craft, and confidence. This structured countdown programme takes you from initial track learning to race-day readiness. Each week targets a specific phase of preparation, building progressively toward peak performance on race day.",
        "level": "intermediate",
        "prerequisites": "Basic track driving competence. You should be comfortable at speed and have completed at least one track day. If this is a new track, allow extra time in Week 1.",
        "equipment_needed": "Data logger, track map printout, notebook, stopwatch for mental timing exercises. Recommended: GoPro for reviewing racecraft.",
        "weeks": [
            {
                "week": 1,
                "title": "Baseline & Track Learning",
                "focus": "Week 1 is about LEARNING, not speed. Whether this is a track you have never visited or one you know well, the goal is to build (or rebuild) a complete mental map of every corner, braking zone, and reference point. Speed will come — but only after a solid foundation of track knowledge.",
                "coaching_notes": "Resist ALL temptation to chase lap times this week. The driver who spends Week 1 learning the track properly will be faster by Week 3 than the driver who pushed from lap 1. Trust the process. Walk the track if possible before driving it.",
                "warmup": "3 very slow reconnaissance laps. Look at everything: kerb paint, surface changes, gradient, camber, walls, runoff. Build your mental map.",
                "drills": [
                    {
                        "name": "Track Familiarisation",
                        "description": "Complete 30 laps focusing on learning the layout. No timing pressure.",
                        "detailed_instructions": "Your brain needs repetition to build a track map. 30 laps provides enough repetition for the layout to start feeling 'automatic'. During these laps, you should be looking ahead, identifying landmarks, and building a corner-by-corner mental database. The lap timer should be OFF or ignored.",
                        "steps": [
                            "Before driving, study the track map. Identify the number of corners, their types (hairpin, chicane, fast sweep), and the pit entry/exit.",
                            "If possible, walk the track or cycle it. Ground-level perspective reveals details invisible from the car.",
                            "Laps 1-5: Drive at 60% pace. Focus on the LAYOUT: which way does each corner go? Where are the straights?",
                            "Laps 6-10: Increase to 70%. Start identifying reference points: brake markers, kerb features, sign posts.",
                            "Laps 11-15: 75% pace. Assign reference points to every corner: brake point, turn-in, apex, exit.",
                            "Laps 16-20: 80% pace. Notice surface details: bumps, camber changes, grip variations between corners.",
                            "Laps 21-25: 85% pace. Drive with eyes FURTHER ahead. Can you anticipate the next corner before you see it?",
                            "Laps 26-30: 85-90% pace. The track should feel familiar now. Are there any corners still surprising you?",
                            "After the session, close your eyes and mentally drive a lap. Can you do it? Any gaps mean those sections need more study."
                        ],
                        "tips": [
                            "Talk to yourself during the laps: 'Long straight, brake at the 100m board, tight left, up hill, fast right...' This verbalisation accelerates learning.",
                            "Note the track surface: new tarmac has different grip from old tarmac. Patched sections behave differently. Paint markings can be slippery.",
                            "Pay attention to camber (track banking). Positive camber (track tilts into the corner) gives more grip. Negative camber (tilts away) reduces grip.",
                            "Note the wind direction. Headwind on straights means later braking. Crosswind on high-speed corners affects stability.",
                            "Take photos or videos of key reference points. Review them before your next session."
                        ],
                        "common_mistakes": [
                            "Trying to go fast on lap 1. You do not know the track yet — fast laps on an unknown layout are dangerous.",
                            "Only focusing on the corners and ignoring the straights. Straight-line approach angles to braking zones matter hugely.",
                            "Not studying the track map beforehand. Arriving blind means wasting the first 10 laps just figuring out which way to turn.",
                            "Comparing your pace to other drivers on track. Week 1 pace is irrelevant. Track knowledge is the goal."
                        ],
                        "success_criteria": "Complete 30 laps with progressively increasing confidence. Can mentally drive a full lap from memory with correct corner sequence.",
                        "duration": "60–75 minutes",
                        "difficulty": 2,
                        "metric": "n_laps",
                        "target": "> 30 laps"
                    },
                    {
                        "name": "Baseline Pace Setting",
                        "description": "After familiarisation, set 10 timed laps as your benchmark.",
                        "detailed_instructions": "Now that you know the track, it is time to set a baseline. This is your starting pace — the number you will improve upon over the next 3 weeks. These 10 laps should be clean, controlled, and REPRESENTATIVE of your current ability. No heroics, no drama — just solid, clean laps.",
                        "steps": [
                            "Complete 5 warm-up laps at 80% to confirm your track knowledge from the familiarisation drill.",
                            "Turn on your lap timer or ensure your data logger is recording.",
                            "Drive 10 consecutive timed laps at YOUR comfortable fast pace. Not qualifying effort — sustainable pace.",
                            "Focus on clean execution: hitting reference points, smooth inputs, consistent lines.",
                            "If a lap is disrupted by traffic, mentally mark it but do not try to compensate.",
                            "After 10 laps, cool down for 3 laps.",
                            "Review your data: what was your best time? Average time? CV%? These three numbers are your baseline.",
                            "Write down: Best Lap = X, Average = Y, CV% = Z, Date, Conditions (temp, track state).",
                            "This baseline is your Week 1 benchmark. Every improvement will be measured against these numbers."
                        ],
                        "tips": [
                            "Your baseline pace should feel sustainable. If you could not maintain it for 20 laps, you are pushing too hard for a baseline.",
                            "Exclude any traffic-affected laps from your calculations. You want clean-air baseline data.",
                            "Note the conditions carefully: a baseline set in 30C heat is different from one set in 15C cold. Track temperature matters.",
                            "Do not be disappointed by your baseline time. It is a starting point, not a judgment of your ability.",
                            "If your CV% is above 3%, consistency should be a priority focus for Week 2."
                        ],
                        "common_mistakes": [
                            "Setting a baseline during an exceptionally good or bad session — try for representative conditions.",
                            "Pushing too hard and setting a baseline you cannot consistently repeat.",
                            "Not recording conditions (temp, wind, tyre type/age) that affect the baseline's validity.",
                            "Comparing your baseline to published track records or online times. Those are not relevant to your development."
                        ],
                        "success_criteria": "10 clean timed laps with baseline pace established. Best, average, and CV% recorded with conditions noted.",
                        "duration": "30–40 minutes",
                        "difficulty": 2,
                        "metric": "best_lap_time_s",
                        "target": "establish baseline"
                    },
                    {
                        "name": "Corner Categorisation",
                        "description": "Classify each corner: slow/medium/fast. Note key challenges.",
                        "detailed_instructions": "Every corner on a track has a character. Understanding and categorising each corner allows you to apply the right technique to each one. Slow corners reward late apexes and strong exits. Fast corners reward commitment and smooth inputs. Medium corners are the most technique-dependent. This analysis forms the basis for your speed development in Week 2.",
                        "steps": [
                            "Print or draw a track map. Number every corner.",
                            "For each corner, classify: SLOW (requires heavy braking, < 80 km/h minimum), MEDIUM (moderate braking, 80-130 km/h), FAST (light or no braking, > 130 km/h).",
                            "For each corner, note the key challenge: elevation change? Camber? Blind entry? Late apex needed? Surface change?",
                            "Identify which corners lead onto long straights — these are your PRIORITY corners (exit speed matters most here).",
                            "Identify which corners are part of sequences — these require linked-corner thinking.",
                            "For each corner, rate your personal confidence: GREEN (comfortable), AMBER (developing), RED (uncomfortable/scary).",
                            "Any RED corners need special attention in Week 2. These are limiting your overall pace.",
                            "Write a 1-sentence strategy for each corner: 'T5: Slow hairpin, late apex, priority exit onto main straight.'",
                            "Keep this document accessible — you will reference it every session for the next 3 weeks."
                        ],
                        "tips": [
                            "The categorisation may change as you get faster. A corner that feels 'slow' now might become 'medium' when you carry more speed.",
                            "RED corners are often RED because of unfamiliarity, not difficulty. Focused practice usually turns them AMBER within one session.",
                            "Priority corners (those leading onto straights) should receive the most practice time. A 1 km/h exit speed gain compounds over the full straight.",
                            "Note any corners where your line differs from the rubber marks on track. The racing line is usually indicated by the darkest rubber.",
                            "If you have access to an on-board video of the track, watch it and verify your categorisation."
                        ],
                        "common_mistakes": [
                            "Not doing the categorisation at all, and instead just 'driving and hoping'. The analytical approach is more efficient.",
                            "Over-complicating the categorisation with too many categories. Slow/Medium/Fast is sufficient at this stage.",
                            "Ignoring the 'key challenge' column. Every corner has something unique — knowing what it is prevents surprises.",
                            "Not updating the categorisation as your pace improves. What was fast at Week 1 pace may become medium at Week 3 pace."
                        ],
                        "success_criteria": "Complete corner categorisation document with: classification, key challenge, confidence rating, and 1-sentence strategy for every corner.",
                        "duration": "20–30 minutes (off-track analysis)",
                        "difficulty": 1,
                        "metric": "n/a",
                        "target": "documented notes"
                    },
                ],
            },
            {
                "week": 2,
                "title": "Speed Development",
                "focus": "With a solid track knowledge foundation, Week 2 is about finding speed. You will systematically attack each sector, push your braking zones, and experiment with alternative lines. The goal is to reduce your baseline time by a significant margin through focused technical improvement.",
                "coaching_notes": "Speed development should be SYSTEMATIC, not random. Pick one sector or technique per stint, attack it, measure the result, and move on. Scattered effort yields scattered results. Focused effort yields focused gains.",
                "warmup": "5 laps rebuilding to your Week 1 baseline pace. This should feel easier than Week 1 — that means your track knowledge has solidified.",
                "drills": [
                    {
                        "name": "Sector-by-Sector Improvement",
                        "description": "Focus on one sector per stint. Target personal best in each.",
                        "detailed_instructions": "Divide the track into sectors (usually 3, as per the timing system). Dedicate one stint to each sector, driving at maximum effort in that sector while cruising through the others. This isolates where your time is being gained and allows surgical improvement.",
                        "steps": [
                            "Identify your 3 sectors (use the timing system's splits if available, or divide the track into 3 roughly equal sections).",
                            "Note your current best sector times from the baseline session.",
                            "Stint 1 (10 laps): Focus exclusively on Sector 1. Push to 100% in S1, drive at 80% in S2 and S3.",
                            "After the stint, check: did you set a new S1 personal best? By how much? What specifically was faster?",
                            "Stint 2 (10 laps): Focus on Sector 2. Same approach — 100% in S2, 80% elsewhere.",
                            "Stint 3 (10 laps): Focus on Sector 3.",
                            "After all 3 stints, calculate your new theoretical best (sum of best sectors). Compare to your baseline.",
                            "Final stint (5 laps): Try to combine all 3 sector improvements into one complete lap."
                        ],
                        "tips": [
                            "The sector you find hardest to improve usually contains your biggest technique gap. It deserves extra focus time.",
                            "Sometimes sector improvement comes from the transition INTO the sector — a good exit from the previous sector gives a better entry.",
                            "Record which specific corners improved within each sector. This helps target further practice.",
                            "If one sector is already near its limit, do not waste a full stint on it. Redistribute that time to your weaker sectors.",
                            "Your combined theoretical time should be 1-3% faster than your baseline after this drill. That is significant progress."
                        ],
                        "common_mistakes": [
                            "Pushing all 3 sectors simultaneously instead of isolating one at a time. Focus is key.",
                            "Not recording sector times, making it impossible to measure improvement.",
                            "Getting frustrated when a sector does not improve. Some sectors need setup changes, not just driving changes.",
                            "Forgetting to attempt the combined lap at the end. The real test is putting all sectors together."
                        ],
                        "success_criteria": "Personal best in at least 2 of 3 sectors. New theoretical best time significantly faster than baseline.",
                        "duration": "45–55 minutes",
                        "difficulty": 3,
                        "metric": "time_loss_ms",
                        "target": "PB each sector"
                    },
                    {
                        "name": "Braking Confidence",
                        "description": "Push braking zones 1m deeper until limit. Build confidence.",
                        "detailed_instructions": "Braking is often the easiest place to find time because it is the most fear-dependent. This drill systematically builds your braking confidence by moving your brake points later in small increments. By the end, you will have found your true braking limit on the 3 heaviest braking zones — and your race brake point will be 2m before that limit.",
                        "steps": [
                            "Identify the 3 heaviest braking zones on the track (usually the end of the 3 longest straights).",
                            "On each zone, note your current brake marker from Week 1.",
                            "Start the drill on Zone 1. Brake at your current marker for 2 laps. This is your comfort zone.",
                            "On lap 3, move the brake point 1m later. Execute cleanly. Did you still make the corner?",
                            "Continue moving 1m later each lap until you feel one of these: ABS activating hard, locking a wheel, missing the apex by more than 1m, or the car not rotating.",
                            "When you find the limit, note the position. Now move 2m earlier — this is your working race brake point.",
                            "Lock in the new brake point with 3 repetitions. It should feel confident, not scary.",
                            "Repeat for Zones 2 and 3.",
                            "After all 3 zones, do 5 complete laps with the new brake points integrated. Note your overall time improvement."
                        ],
                        "tips": [
                            "1m increments are tiny — barely noticeable. This is deliberate. Big jumps are dangerous and do not build confidence.",
                            "The limit brake point is NOT your race brake point. Always keep a 2m safety margin for variable conditions.",
                            "As you brake later, you need to brake HARDER. Pedal pressure must increase to maintain the same deceleration distance.",
                            "Braking confidence on race day comes from having done this drill. When a rival brakes late beside you, you KNOW your brake point works.",
                            "Tyre temperature and fuel load affect braking performance. Your race brake point may need 1-2m adjustment depending on conditions."
                        ],
                        "common_mistakes": [
                            "Moving the brake point 5-10m at once instead of 1m. This is dangerous and counterproductive.",
                            "Not braking harder when braking later. Same pedal pressure + later application = missing the corner.",
                            "Setting the race brake point AT the limit instead of 2m before it. You need margin for race-day variables.",
                            "Only practising on one braking zone. Each zone has different characteristics and requires individual calibration."
                        ],
                        "success_criteria": "New race brake points established on all 3 zones, each at least 3m later than Week 1 baseline. Consistent execution across 3+ repetitions.",
                        "duration": "30–40 minutes",
                        "difficulty": 3,
                        "metric": "brake_point_m",
                        "target": "consistent late braking"
                    },
                    {
                        "name": "Race Line Optimisation",
                        "description": "Experiment with alternative lines in 2 corners. Data compare.",
                        "detailed_instructions": "The 'obvious' line is not always the fastest. This drill identifies 2 corners where an alternative approach might be faster and uses data to verify. You will drive multiple laps on each alternative line and let the data decide which is genuinely faster — removing the guesswork and replacing it with evidence.",
                        "steps": [
                            "From your corner categorisation, select 2 corners where you suspect an alternative line might work. Good candidates: slow corners where a later apex could help, or fast corners where a different entry angle might carry more speed.",
                            "For Corner 1, define 2 alternative lines: Line A (your current line) and Line B (the alternative — e.g., later apex, wider entry, different turn-in point).",
                            "Drive 5 laps on Line A. Record: corner time, exit speed, and subsequent straight speed.",
                            "Drive 5 laps on Line B. Record the same metrics.",
                            "Compare the data: which line produced the faster time through the corner + following straight COMBINED?",
                            "The winner is the line that produces the fastest combined time, NOT just the fastest corner time.",
                            "Repeat for Corner 2 with its own alternatives.",
                            "Adopt the faster line for each corner. Drive 5 complete laps to integrate the changes.",
                            "Review: did the alternative lines improve your overall lap time?"
                        ],
                        "tips": [
                            "The fastest line through a corner is not always the fastest for the LAP. A slightly slower corner with a much faster exit is almost always the better choice.",
                            "Rubber marks on the track show you the popular line, not necessarily the fastest line. Data is the arbiter.",
                            "Some alternative lines only work at certain speeds. As you get faster, the optimal line may change again.",
                            "Discuss line options with other drivers who know the track. They may have insights about camber or grip changes you have not noticed.",
                            "Take video of both lines and overlay them. Visual comparison combined with data is very powerful."
                        ],
                        "common_mistakes": [
                            "Only comparing mid-corner speed instead of the complete corner + exit + straight combination.",
                            "Not driving enough laps on each line to get consistent data. 5 laps minimum per alternative.",
                            "Choosing the line that FEELS faster instead of the one the DATA says is faster. Trust the data.",
                            "Trying to optimise too many corners at once. 2 corners per session is the maximum for meaningful comparison."
                        ],
                        "success_criteria": "Data-verified optimal line identified for both target corners. At least one corner shows measurable improvement with the alternative line.",
                        "duration": "35–45 minutes",
                        "difficulty": 3,
                        "metric": "line_variation_index",
                        "target": "find fastest variant"
                    },
                ],
            },
            {
                "week": 3,
                "title": "Race Craft",
                "focus": "Speed is only part of racing. This week develops the tactical skills you need on race day: defending your position, creating and executing overtaking opportunities, and maintaining race pace consistently. These are the skills that turn a fast driver into a race winner.",
                "coaching_notes": "Racecraft is best practised in traffic, so seek out busy sessions. Every car on track is a practice opportunity — a slower car to safely overtake, a faster car to observe and learn from. Change your mindset from 'traffic is annoying' to 'traffic is practice'.",
                "warmup": "5 laps at 90% pace. As you drive, identify the 3 best overtaking spots on the track: where is there room to go side-by-side? Where do braking zones allow a late-braking pass?",
                "drills": [
                    {
                        "name": "Defending Lines Practice",
                        "description": "Practice defensive lines through key overtaking zones.",
                        "detailed_instructions": "Defence is about positioning, not blocking. A defensive line takes away the inside line through the next braking zone, forcing any would-be overtaker to attempt a riskier outside move. This drill teaches you to drive defensive lines that protect your position while minimising your own time loss.",
                        "steps": [
                            "Identify the 2-3 main overtaking zones on the track. These are usually at the end of long straights into heavy braking zones.",
                            "For each zone, identify the normal racing line and the defensive line. The defensive line is typically further to the inside on the approach to the braking zone.",
                            "Drive 5 laps on the normal (racing) line through these zones. Time each zone.",
                            "Drive 5 laps on the defensive line through the same zones. Time each zone.",
                            "Calculate the time cost of the defensive line. A good defensive line costs less than 0.2s per corner.",
                            "Practice the transition: racing line for most of the lap, switch to defensive line only through the key zones.",
                            "Drive 5 more laps alternating between defensive and racing lines. The switch should be smooth and deliberate.",
                            "Note: you do not need another car to practice this. You are training the LINE, not the interaction."
                        ],
                        "tips": [
                            "Defence is about POSITIONING, not weaving. Choose your line early (before the braking zone) and commit to it.",
                            "The best defensive position is to the inside on the approach, forcing the attacker to the outside. The inside line has the shorter corner distance.",
                            "A defensive line costs time because it changes your corner entry angle. Minimise this cost by adjusting your braking point and line mid-corner.",
                            "Know the rules: you can change your line once on a straight. Two moves (weaving) is a penalty in most series.",
                            "Sometimes the best defence is a strong exit from the previous corner — if they cannot get close, they cannot attack."
                        ],
                        "common_mistakes": [
                            "Weaving or making multiple defensive moves — this is dangerous and against the rules in most series.",
                            "Defending too aggressively and compromising your own corner speed to the point where the attacker passes you on exit.",
                            "Not practising defensive lines before race day. The first time you defend should not be in the race.",
                            "Defending at every corner instead of the key overtaking zones. Most corners do not need defensive lines."
                        ],
                        "success_criteria": "Clean defensive lines practised through all key overtaking zones. Time cost of defensive line < 0.2s per zone.",
                        "duration": "25–30 minutes",
                        "difficulty": 3,
                        "metric": "n/a",
                        "target": "5 defensive laps"
                    },
                    {
                        "name": "Overtaking Zones Drill",
                        "description": "Identify and practice 2-3 overtaking opportunities.",
                        "detailed_instructions": "Overtaking is an art: you need to identify the opportunity, position the car, execute the pass, and complete the corner — all while another car is beside you. This drill practices the physical execution: the line, the braking, and the exit when going side-by-side. You do not need a partner car — you are practising the overtaking LINE, which is different from the racing line.",
                        "steps": [
                            "Identify 2-3 corners where overtaking is realistic. Usually: end of a long straight into a heavy braking zone with sufficient track width.",
                            "For each overtaking zone, plan the attack: (a) the positioning on the straight, (b) the braking point for the inside line, (c) the turn-in and apex for the tighter inside arc.",
                            "Drive 5 laps on the overtaking (inside) line through zone 1. Note your time and exit speed.",
                            "The overtaking line is tighter, with a later apex. Your braking must be later than the car you are passing, but you also have a tighter arc and need to brake harder.",
                            "Key metric: exit speed. If your exit speed on the overtaking line is too slow, you will lose the position on the next straight. Target: within 3 km/h of normal exit speed.",
                            "Repeat for zones 2 and 3.",
                            "Drive 5 complete laps alternating between racing line and overtaking line at the target corners. Practice switching on command.",
                            "Visualise an opponent beside you during the overtaking laps. Leave space — you need room for both cars."
                        ],
                        "tips": [
                            "The overtaking is complete when you exit the corner AHEAD. A great entry means nothing if you lose the position on exit.",
                            "On the inside line, your braking zone is SHORTER (because you are closer to the corner) but you need MORE deceleration. Brake later but harder.",
                            "Always leave a car width of space on the outside when practising the inside line. In a race, the other car will be there.",
                            "The best overtakes look easy — they are set up 2-3 corners before the actual pass, with superior exit speed creating the speed differential.",
                            "Practice the switchback too: if the inside does not work, use the other car's compromised exit to re-pass on the next straight."
                        ],
                        "common_mistakes": [
                            "Only practising the entry to the overtaking zone and not the exit. The exit determines whether the overtake sticks.",
                            "Not leaving space for the other car when practising — in a real overtake, the track is shared.",
                            "Lunging from too far back. A successful overtake starts with a speed advantage, not a prayer.",
                            "Practising dive-bombs instead of clean, calculated overtakes. Divebombing is a last resort, not a strategy."
                        ],
                        "success_criteria": "Clean overtaking line practised through 2-3 zones. Exit speed on overtaking line within 3 km/h of normal racing line exit speed.",
                        "duration": "30–35 minutes",
                        "difficulty": 3,
                        "metric": "exit_speed_mps",
                        "target": "maximize exit speed at overtaking zones"
                    },
                    {
                        "name": "Race Pace Consistency",
                        "description": "Complete 15 laps at 95% effort. Target < 1% variation.",
                        "detailed_instructions": "Race pace is not qualifying pace. It is the fastest pace you can maintain for the entire race distance while preserving tyres and concentration. This drill establishes your sustainable race pace and tests your ability to hold it consistently for 15 laps — which is approximately the length of many club races.",
                        "steps": [
                            "Complete 3 warm-up laps building to 95% effort.",
                            "Drive 15 consecutive laps at 95% effort. This should feel fast but controlled — you should have a small reserve.",
                            "Focus on repeating the SAME lap every time. Same braking points, same lines, same throttle application.",
                            "After every 5 laps, do a quick body scan: are your shoulders tense? Is your grip too tight? Release and reset.",
                            "If traffic affects a lap, reset mentally and refocus on the next one. Do not chase the lost time.",
                            "After 15 laps, cool down for 3 laps.",
                            "Review: what was your average lap time? CV%? How did your pace trend — flat, declining, or improving?",
                            "Your target: CV% below 1.0%. This means your laps are within about 0.7s of each other on a typical circuit."
                        ],
                        "tips": [
                            "95% effort should leave you feeling 'I could push a bit more if I needed to'. That reserve is your safety margin for race incidents.",
                            "A CV% under 1.0% puts you in the top tier of club racers for consistency. Most club racers are at 2-3%.",
                            "If you cannot maintain 95% for 15 laps, your fitness may be a limiting factor. Consider adding cardio and grip strength training.",
                            "Race pace consistency is the most valuable skill for race results. Consistent drivers finish on the podium more often than fast-but-inconsistent ones.",
                            "Monitor your sector split times, not just total laps. Consistency in one sector but variation in another reveals where to focus."
                        ],
                        "common_mistakes": [
                            "Pushing to 100% instead of 95%. Race pace must be sustainable — pushing at 100% guarantees inconsistency and fatigue.",
                            "Not maintaining concentration in the final 5 laps when fatigue sets in.",
                            "Treating this as a qualifying session instead of a race simulation.",
                            "Ignoring the data and only going by feel. Your perception of consistency and the data often disagree — trust the data."
                        ],
                        "success_criteria": "15 consecutive clean laps with CV% below 1.0%. Flat or slightly improving pace trend (no significant fade).",
                        "duration": "35–45 minutes",
                        "difficulty": 3,
                        "metric": "consistency_cv_pct",
                        "target": "< 1.0%"
                    },
                ],
            },
            {
                "week": 4,
                "title": "Final Preparation",
                "focus": "Race week. Everything from Weeks 1-3 is locked in. This week is about simulation, confirmation, and mental preparation. No new techniques, no experiments — only rehearsal of what you know works. The goal is to arrive at race day confident, prepared, and with a proven performance level.",
                "coaching_notes": "Do NOT change anything this week. No setup changes, no new lines, no different techniques. Race week is about confirmation and confidence. The time for experimentation was Weeks 1-3. Now you execute what you have practised. If something is not working, accept it and focus on executing what IS working.",
                "warmup": "5 laps exactly as you plan to warm up on race day. This is a rehearsal — practice your actual pre-race routine.",
                "drills": [
                    {
                        "name": "Qualifying Simulation",
                        "description": "Full qualifying practice: warm-up + 2 push laps. Repeat 4 times.",
                        "detailed_instructions": "This is a full-dress rehearsal of qualifying. You will complete 4 qualifying runs, each with a proper warm-up and 2 push laps. This simulates the format of most qualifying sessions and tests your ability to produce peak performance repeatedly under simulated pressure.",
                        "steps": [
                            "Before going out, execute your full pre-qualifying mental routine (breathing, visualisation, intention setting).",
                            "Run 1: 2 warm-up laps building to 95%, then 2 PUSH laps at maximum effort. Record both push lap times.",
                            "Cool-down lap, then pit for 3-5 minutes. Hydrate. Review your times mentally.",
                            "Run 2: Same format. Target: beat Run 1.",
                            "Cool-down, pit, reset.",
                            "Run 3: Same format. By now, tyres and driver should be at peak. This is often the fastest run.",
                            "Cool-down, pit, reset.",
                            "Run 4: Final attempt. Leave nothing on the table. This simulates the 'last chance' qualifying scenario.",
                            "After all 4 runs, analyse: best lap from all 8 push laps is your qualifying benchmark. Average of best push laps shows your consistency under pressure.",
                            "Target: your best push lap within 0.3s of your session best from all your practice."
                        ],
                        "tips": [
                            "Quality of warm-up laps matters. Tyre temperature, brake temperature, and mental focus all need the warm-up.",
                            "If Run 1 is your best, your warm-up process needs refinement. If Run 3-4 is best, you peak late and need more warm-up time.",
                            "Two push laps per run reduces pressure compared to a single-shot format. Use lap 1 to 'set the table' and lap 2 to push harder.",
                            "Do not change your approach between runs. Consistency of method is key. Small refinements only.",
                            "Record the conditions for your benchmark time: temperature, wind, tyre condition. You will need this on race day to calibrate expectations."
                        ],
                        "common_mistakes": [
                            "Going out without the mental preparation routine. This is a simulation — simulate EVERYTHING, including the mental prep.",
                            "Pushing too hard on warm-up laps and overheating tyres before the push laps.",
                            "Getting discouraged by Run 1 and carrying negativity into Run 2. Each run is a fresh start.",
                            "Not using all 4 runs. Some drivers give up after 2 runs. Complete all 4 — you are building mental endurance."
                        ],
                        "success_criteria": "Best push lap within 0.3s of overall session best. 4 complete qualifying runs executed with full procedure.",
                        "duration": "40–50 minutes",
                        "difficulty": 4,
                        "metric": "best_lap_time_s",
                        "target": "within 0.3s of session best"
                    },
                    {
                        "name": "Race Distance Simulation",
                        "description": "Complete full race distance at race pace.",
                        "detailed_instructions": "The final rehearsal. Drive a complete simulated race: race start, full distance at race pace, tyre management, and a late push. This drill proves to yourself that you can handle the physical and mental demands of the race distance. After this, you have done everything you can to prepare.",
                        "steps": [
                            "Calculate your full race distance (check the regulations or event format).",
                            "Lap 1: Simulate a race start. Drive the first lap at 97% — aggressive but clean. This sets the tone.",
                            "Laps 2-5: Settle into race pace. 93-95% effort. Focus on clean, consistent execution.",
                            "Mid-race: Maintain concentration. Use your self-talk and breathing routines to stay focused.",
                            "Final 3 laps: Push to 97%. Simulate a late-race attack for position. Can you find extra pace when fatigued?",
                            "Last lap: Give it everything. This is your race-end sprint.",
                            "Cool down for 3 laps. Hydrate immediately.",
                            "Review: compare your first-quarter pace to last-quarter pace. Target: less than 1.5% fade.",
                            "Review: was your CV% acceptable? Any major errors? How was your mental state by the end?"
                        ],
                        "tips": [
                            "This is as close to race-day as you can get in practice. Treat it seriously — full focus, full commitment.",
                            "If you cannot complete the full distance, your fitness needs attention. Add endurance training to your routine.",
                            "The late push (final 3 laps) simulates a fight for position. Can you switch from management to attack mode?",
                            "A 1.5% fade is good for club racing. Professionals target < 0.5%. Know your current level and set realistic expectations.",
                            "After this drill, you should feel CONFIDENT about race day. You have proven you can do the distance at competitive pace."
                        ],
                        "common_mistakes": [
                            "Not treating the simulation seriously because 'it is not the real race'. The practice gains come from treating it like one.",
                            "Starting too fast and fading badly in the second half.",
                            "Skipping the late push because 'I am already tired'. The late push is the most important part — it trains race-end resilience.",
                            "Not reviewing the data afterwards. The simulation data is your final preparation check."
                        ],
                        "success_criteria": "Complete race distance with < 1.5% pace fade from first to last quarter. CV% below 1.5%. No major incidents.",
                        "duration": "50–70 minutes",
                        "difficulty": 4,
                        "metric": "early_vs_late_stint_pace",
                        "target": "< 1.5% fade"
                    },
                    {
                        "name": "Pre-Race Confidence Builder",
                        "description": "Easy laps focusing on rhythm and consistency. Build positive mindset.",
                        "detailed_instructions": "The final session before race day should leave you feeling confident, prepared, and positive. This is NOT about finding more speed. It is about confirming what you already know, building rhythm, and ending on a high note. Think of it as a musician's final practice before a concert — not learning new pieces, but playing the ones they know perfectly.",
                        "steps": [
                            "Drive 3 gentle warm-up laps at 75% pace. Feel the car. Feel the track. Everything should be familiar and comfortable.",
                            "Drive 10 laps at 90% pace. Not pushing, not cruising — just flowing. Every corner should feel like you have done it a hundred times (because you have).",
                            "Focus on rhythm: the throttle-brake-steer pattern should feel like a dance. No fighting the car. No thinking. Just driving.",
                            "After 10 laps, check your times. They should be close to your race pace WITH LESS EFFORT. This is a good sign — speed with ease means confidence.",
                            "If any corner still feels uncertain, drive 3 extra laps focusing on that corner. Get it right. End on a positive note.",
                            "Cool down for 3 laps. On these laps, visualise the race: your start, your first lap, your race pace, your finish.",
                            "Park the car and sit quietly for 2 minutes. Set your intention for race day.",
                            "Write down 3 things: (1) I am proud of [something from your preparation]. (2) My goal is [specific]. (3) I will succeed because [reason]."
                        ],
                        "tips": [
                            "If you are nervous, that is NORMAL. Nerves mean you care. Channel them into focus, not anxiety.",
                            "End the session on a good lap. If your last lap was poor, do one more to finish on a positive note.",
                            "Do not make ANY changes after this session. No setup changes, no line experiments, no technique adjustments. You are READY.",
                            "Get good sleep before race day. Fatigue is the enemy of everything you have trained.",
                            "Trust your preparation. 4 weeks of structured work is more than most of your competitors have done."
                        ],
                        "common_mistakes": [
                            "Using the confidence builder to chase qualifying pace. This is counter-productive — the point is comfort, not speed.",
                            "Ending on a bad lap and not doing one more to reset the mental state.",
                            "Changing something after the session because of a moment of doubt. Trust the process.",
                            "Not doing the mental preparation (intention setting, visualisation). The mental side matters as much as the physical."
                        ],
                        "success_criteria": "10+ laps at 90% effort with CV% below 0.8%. Session ends with positive mental state and clear race-day intentions.",
                        "duration": "25–35 minutes",
                        "difficulty": 2,
                        "metric": "consistency_cv_pct",
                        "target": "< 0.8%"
                    },
                ],
            },
        ],
    },
    "consistency_focus": {
        "id": "consistency_focus",
        "name": "Consistency Mastery",
        "description": "Dedicated program to reduce lap time variation and build repeatability. Consistency is the single most important skill in motorsport — it wins more races than raw speed. This 4-week programme systematically eliminates the sources of variation in your driving, from individual corner inputs to full-lap consistency under fatigue.",
        "level": "intermediate",
        "prerequisites": "Basic track driving competence with known lap times. You should have data from at least one session to establish your current CV%. Ideally completed Beginner Foundations first.",
        "equipment_needed": "Data logger with lap timing (minimum). Ideally: speed trace, brake trace, throttle trace for corner-level analysis. Notebook for tracking progress.",
        "weeks": [
            {
                "week": 1,
                "title": "Understanding Variation",
                "focus": "Before you can fix inconsistency, you need to understand it. Where does your variation come from? Is it the same corners every time, or is it random? This week is diagnostic: measure your current consistency, identify the biggest sources of variation, and establish the reference points that will anchor your improvement.",
                "coaching_notes": "Most drivers are surprised by where their inconsistency actually is. They think they are inconsistent in the 'hard' corners, but data often reveals the 'easy' corners have more variation — because the driver is not paying attention to them. Data does not lie. Let it guide you.",
                "warmup": "3 laps at 80% pace. On each corner, notice if you are driving 'on autopilot' or actively thinking about your inputs. Autopilot = potential inconsistency source.",
                "drills": [
                    {
                        "name": "Baseline Consistency Test",
                        "description": "20 laps at comfortable pace. Measure your CV%. This is your starting point.",
                        "detailed_instructions": "This is a pure measurement drill. Drive 20 laps at a pace that feels comfortable and sustainable — not pushing, not cruising. Your goal is to capture your NATURAL consistency level without any special focus or effort. This baseline number is the starting point for all improvement over the next 4 weeks.",
                        "steps": [
                            "Complete 5 warm-up laps building to your comfortable pace. This should be about 90% effort.",
                            "Reset your data or mark the start point. Begin 20 timed laps.",
                            "Drive NATURALLY. Do not try to be consistent — drive as you normally would. This captures your true baseline.",
                            "Do not look at lap times during the 20 laps. Remove the timer display if possible.",
                            "Maintain the same effort level throughout. Do not push harder in the second half because you feel warmer.",
                            "After 20 laps, cool down for 3 laps.",
                            "Analyse: calculate your average lap time and coefficient of variation (CV% = standard deviation / average x 100).",
                            "Plot all 20 lap times on a chart. Look for patterns: do times improve? Degrade? Oscillate? Are there outliers?",
                            "Record: Average = X, CV% = Y, Best = Z, Worst = W. These are your Week 1 baseline numbers."
                        ],
                        "tips": [
                            "CV% benchmarks: > 3% = significant inconsistency. 2-3% = typical club driver. 1-2% = good. < 1% = excellent. < 0.5% = professional level.",
                            "Exclude any laps clearly affected by traffic or incidents. You want CLEAN laps only in the baseline.",
                            "The difference between your best and worst lap tells you your 'variation range'. Cutting this range in half is a realistic 4-week goal.",
                            "If your lap times show a clear improving or declining trend, your baseline is contaminated by a secondary factor (tyre temp, fuel level, learning).",
                            "Do this test at a similar time of day and similar conditions each week to track progress accurately."
                        ],
                        "common_mistakes": [
                            "Trying to be consistent during the baseline test. This defeats the purpose — you need your NATURAL level.",
                            "Using the best lap from the test as your target. The target should be the AVERAGE, achieved more consistently.",
                            "Not recording the conditions (temp, wind, tyre state) that affect the baseline's comparability to future tests.",
                            "Getting discouraged by a high CV%. Everyone starts somewhere — the program is designed to reduce it significantly."
                        ],
                        "success_criteria": "Complete 20 clean laps with baseline CV% measured and recorded. No intentional pace manipulation during the test.",
                        "duration": "40–50 minutes",
                        "difficulty": 2,
                        "metric": "consistency_cv_pct",
                        "target": "measure baseline"
                    },
                    {
                        "name": "Identify Inconsistent Corners",
                        "description": "Find 3 corners with highest time variation across laps.",
                        "detailed_instructions": "Inconsistency at the lap level is caused by inconsistency at the corner level. This drill uses your baseline data to identify which specific corners contribute the most variation to your lap times. These 'problem corners' are where your focused improvement work will deliver the biggest returns.",
                        "steps": [
                            "Load your baseline session data into your telemetry software.",
                            "If you have sector or mini-sector splits, examine the variation in each sector across all 20 laps.",
                            "Calculate the standard deviation of time through each sector or corner (if corner-level data is available).",
                            "Rank all corners/sectors from highest variation (most inconsistent) to lowest.",
                            "Select the top 3 most inconsistent sections. These are your 'problem corners'.",
                            "For each problem corner, look at the traces: what CHANGES between your best and worst passes through that corner?",
                            "Common causes: variable brake point (> 3m spread), variable entry speed (> 5% spread), variable line (visible in GPS trace), variable throttle application point.",
                            "For each problem corner, write down: (a) the corner, (b) the variation amount, (c) the suspected cause.",
                            "These 3 corners are your focus for Weeks 2-3. All improvement work will target these specific areas."
                        ],
                        "tips": [
                            "The most inconsistent corner is not always the one that feels hardest. 'Easy' corners are often neglected and therefore inconsistent.",
                            "If you do not have corner-level data, use sector splits. The sector with the most variation contains the problem corners.",
                            "Overlay your best and worst laps through each problem corner. The visual difference usually reveals the cause immediately.",
                            "Sometimes the inconsistency is in the TRANSITION between corners, not in the corners themselves. Check linking sections too.",
                            "If all corners show similar variation, the issue is likely a global technique problem (braking pressure, throttle smoothness) rather than corner-specific."
                        ],
                        "common_mistakes": [
                            "Guessing which corners are inconsistent instead of using data. Your perception and reality often disagree.",
                            "Only looking at total sector time and not examining individual corners within sectors.",
                            "Identifying too many problem areas. Focus on the TOP 3 only. Fix those, then reassess.",
                            "Not diagnosing the CAUSE of variation — just knowing which corner varies is not enough. You need to know WHY."
                        ],
                        "success_criteria": "Top 3 inconsistent corners identified with data evidence. For each, the suspected cause of variation is documented.",
                        "duration": "20–30 minutes (off-track data analysis)",
                        "difficulty": 2,
                        "metric": "time_loss_ms",
                        "target": "identify top 3"
                    },
                    {
                        "name": "Reference Point Discipline",
                        "description": "Set 2 reference points per corner. Hit every one for 15 laps.",
                        "detailed_instructions": "Reference points are the anchor of consistency. Every lap should be a carbon copy of the one before because you are driving to FIXED POINTS, not to feel. This drill establishes reference points for every corner and then trains you to hit them with robotic precision. After 15 laps of deliberate practice, the reference points start to become automatic.",
                        "steps": [
                            "For every corner on the track, define 2 reference points: (1) a BRAKE POINT (where you begin braking) and (2) an APEX POINT (where your inside wheels should be closest to the inside edge).",
                            "Choose FIXED, PERMANENT features as references: distance boards, kerb paint marks, barrier joints, access road markings. Never use shadows, rubber marks, or temporary objects.",
                            "Write all reference points on your track map. You should have 2 x [number of corners] reference points total.",
                            "Drive 5 laps at 80% pace, verbalising every reference point as you hit it: 'BRAKE at the drain... APEX at the kerb start...'",
                            "After 5 laps, assess: which references are you hitting consistently? Which are you missing? Adjust any that do not work at pace.",
                            "Drive 10 more laps at 85% pace, still verbalising. The verbalisation forces conscious attention and prevents autopilot.",
                            "After 15 laps, stop verbalising and drive 3 laps in silence. Did you still hit the references automatically?",
                            "If any reference was missed in the silent laps, you need more practice on that specific point."
                        ],
                        "tips": [
                            "Verbalisation is the most powerful consistency tool available. It feels silly, but it works because it keeps your brain engaged.",
                            "Choose references you can see at FULL SPEED from a reasonable distance. If you cannot spot the reference until you are on top of it, choose a different one.",
                            "If a corner has no obvious fixed features, use COUNTING: 'I brake 3 car lengths after the patch of dark tarmac.'",
                            "Reference points should be refined over time. If a reference does not work at racing speed, change it to one that does.",
                            "The best references are ones that naturally draw your eye — bright paint, contrasting surfaces, geometric features."
                        ],
                        "common_mistakes": [
                            "Choosing references that are not visible at speed or from the driver's eye-level.",
                            "Using too many references per corner. 2 is the maximum for consistency training. More than 2 overloads your attention.",
                            "Stopping the verbalisation too early. 15 laps is the minimum. 30 laps is ideal for building automatic habits.",
                            "Not adjusting references that do not work. If a reference is wrong, change it — do not force yourself to use a bad one."
                        ],
                        "success_criteria": "Reference points defined for every corner (2 per corner). Line variation index < 0.25 during the 15-lap focused practice.",
                        "duration": "30–40 minutes",
                        "difficulty": 2,
                        "metric": "line_variation_index",
                        "target": "< 0.25"
                    },
                ],
            },
            {
                "week": 2,
                "title": "Brake Point Precision",
                "focus": "The brake point is the single biggest source of lap time variation for most drivers. A 3-metre variation in braking point translates to 0.1-0.2s per corner — and that adds up to seconds per lap on a full circuit. This week drills braking precision to machine-like levels: same point, same pressure, same release — every lap.",
                "coaching_notes": "Braking precision is primarily a DISCIPLINE skill, not a talent skill. It comes from paying attention to the same reference point, every single lap, without exception. The drivers who brake consistently are the ones who never stop paying attention. Autopilot is the enemy of braking precision.",
                "warmup": "5 laps at 85% pace with deliberate attention to your braking points. On each braking zone, note: did I brake at my reference? Exactly? Or was I early/late?",
                "drills": [
                    {
                        "name": "Fixed Brake Marker Laps",
                        "description": "Pick a fixed marker for each corner. Brake at exactly that point 20 times.",
                        "detailed_instructions": "This is the most fundamental consistency drill. Choose a fixed physical marker for each braking zone, and brake at EXACTLY that point — not 1 metre early, not 1 metre late — for 20 consecutive laps. This builds the neural pathway that makes your braking point automatic and precise.",
                        "steps": [
                            "For each braking zone, choose your brake marker from your Week 1 references. It should be a SPECIFIC point, not an area.",
                            "Drive 3 warm-up laps at 80% pace, practising hitting each brake marker precisely.",
                            "Begin 20 timed laps. On every braking zone, focus on hitting the marker EXACTLY.",
                            "After each braking zone, mentally grade yourself: HIT (within 1m) or MISS (more than 1m error). Count your hits.",
                            "Your target: 80%+ hit rate on all braking zones across 20 laps.",
                            "If you consistently miss a particular brake marker, the marker may be wrong. Adjust it to match your natural braking point.",
                            "After 20 laps, review your data: calculate the standard deviation of your brake point position on each corner.",
                            "Target: < 1.5m standard deviation on all braking zones."
                        ],
                        "tips": [
                            "The marker should be at a distance where you can see it clearly at full approach speed. If it is too close, you react too late.",
                            "Use peripheral vision to spot the marker while looking ahead to the corner. You should not have to look DOWN at the marker.",
                            "Muscle memory develops after approximately 50 repetitions. 20 laps is a start — continue this practice in subsequent sessions.",
                            "If you find yourself consistently braking BEFORE the marker, you may be scared. Work on building confidence at the marker position.",
                            "Brake markers change with conditions. In the rain, move all markers 10-15% earlier."
                        ],
                        "common_mistakes": [
                            "Choosing markers that are not visible at speed. Test your markers at full pace before committing.",
                            "Braking early 'just to be safe' rather than at the marker. This defeats the purpose of precision training.",
                            "Not counting hits vs misses. Without measurement, you cannot track improvement.",
                            "Using different markers each session. Consistency of references leads to consistency of braking."
                        ],
                        "success_criteria": "80%+ hit rate on all brake markers across 20 laps. Standard deviation < 1.5m on all braking zones.",
                        "duration": "35–45 minutes",
                        "difficulty": 3,
                        "metric": "brake_point_consistency",
                        "target": "< 1.5m std dev"
                    },
                    {
                        "name": "Brake Pressure Consistency",
                        "description": "Apply the same brake pressure every lap. Focus on muscle memory.",
                        "detailed_instructions": "Consistent braking is not just about WHERE you brake — it is about HOW HARD. Variable brake pressure causes variable deceleration, which causes variable entry speeds, which causes variable corners. This drill trains your right foot to apply the same pressure, every braking zone, every lap — building deep muscle memory.",
                        "steps": [
                            "Choose the 3 heaviest braking zones for focused practice.",
                            "Drive 3 warm-up laps. On each braking zone, pay close attention to your pedal pressure. How hard are you pressing?",
                            "Choose a target pressure for each zone. It should be firm enough to decelerate properly, but not so hard that ABS activates.",
                            "Drive 20 laps focusing on matching your target pressure on every brake application.",
                            "The key feeling: your foot should hit the pedal and immediately reach the TARGET pressure, then hold or trail off. No building up slowly, no slamming.",
                            "After 10 laps, briefly check your data: is your peak brake pressure consistent across laps? The variation should be decreasing.",
                            "Complete the remaining 10 laps with even more focus on pressure matching.",
                            "After the session, calculate the variation in peak brake pressure across all 20 laps for each zone. Target: < 10% variation."
                        ],
                        "tips": [
                            "Your initial brake application should be the HARDEST point of the entire brake event. Everything after is a controlled release.",
                            "Think of braking in stages: Stage 1 (first 20% of pedal travel) = fast but controlled. Stage 2 (threshold) = firm hold. Stage 3 (trail) = gradual release.",
                            "The ABS should NOT be activating regularly. If it is, your initial application is too aggressive. Reduce by 10%.",
                            "Brake pressure feel comes through your leg. Keep your heel planted and use ankle and calf muscles for precise control.",
                            "In data, consistent brake pressure shows as brake traces that overlay perfectly. Variable pressure shows as traces at different heights."
                        ],
                        "common_mistakes": [
                            "Gradually building pressure instead of applying firm initial pressure immediately. The first instant of braking should be the strongest.",
                            "Using ABS as a 'consistency tool'. ABS means you have exceeded the tyre's grip — it is not a feature to rely on.",
                            "Not correlating brake pressure to deceleration. Higher pressure should produce proportionally higher deceleration — if it does not, the brakes may be fading.",
                            "Focusing only on initial pressure and ignoring the release phase. Both initial application AND trail-off must be consistent."
                        ],
                        "success_criteria": "Peak brake pressure variation < 10% across 20 laps on all 3 target zones. No ABS activation during normal braking.",
                        "duration": "35–45 minutes",
                        "difficulty": 3,
                        "metric": "brake_intensity",
                        "target": "< 10% variation"
                    },
                    {
                        "name": "Turn-In Consistency",
                        "description": "Turn in at the same point each lap. Focus on 3 key corners.",
                        "detailed_instructions": "The turn-in point determines everything about the corner: the arc, the apex position, the exit trajectory, and ultimately the corner time. A 1-metre variation in turn-in point cascades into a completely different corner. This drill fixes your turn-in to a specific point and trains you to hit it with the same precision as your brake point.",
                        "steps": [
                            "Select your 3 problem corners from Week 1 (the most inconsistent ones).",
                            "For each corner, define a precise turn-in reference: a kerb feature, surface change, or distance from the brake point.",
                            "Drive 3 warm-up laps, noting exactly where you naturally turn in on each target corner.",
                            "If your natural turn-in differs from your intended reference, adjust the reference to a point that makes sense biomechanically.",
                            "Drive 15 laps with deliberate focus on the 3 turn-in points. Verbalise: 'Turn... NOW' at each reference point.",
                            "After each corner, self-assess: did you turn in at the reference, or early/late?",
                            "Monitor the consequences: consistent turn-in should produce consistent apex hits and consistent exit speeds.",
                            "After the session, compare entry speed variation on the 3 target corners vs. non-target corners. The targets should show improvement.",
                            "Target: entry speed variation < 3% on all 3 target corners."
                        ],
                        "tips": [
                            "Your turn-in point is closely related to your brake point. If braking is inconsistent, turn-in will be too. Fix braking first.",
                            "Turn-in should be a single, decisive action — not a gradual drift into the corner. One motion to the required steering angle.",
                            "Look at the apex as you turn in, not at the turn-in point itself. Your peripheral vision handles the turn-in reference.",
                            "Turn-in timing varies with speed: at higher speeds, you need to turn in slightly earlier because the car takes longer to respond.",
                            "If you are consistently turning in too early, you will hit the apex too early and run wide on exit. Too late = you undercut the apex."
                        ],
                        "common_mistakes": [
                            "Not having a defined turn-in reference and relying on feel. Feel varies with mood, fatigue, and confidence. References do not.",
                            "Turning in gradually (drifting towards the apex) instead of with a single decisive input.",
                            "Focusing only on the turn-in and not checking the downstream effects (apex accuracy, exit trajectory).",
                            "Changing the turn-in reference when results are not immediate. Give it 10 laps before adjusting."
                        ],
                        "success_criteria": "Entry speed variation < 3% on all 3 target corners. Turn-in points consistent within 1m across 15 laps.",
                        "duration": "30–40 minutes",
                        "difficulty": 3,
                        "metric": "entry_speed_mps",
                        "target": "< 3% variation"
                    },
                ],
            },
            {
                "week": 3,
                "title": "Exit Consistency",
                "focus": "You have locked in your braking and turn-in. Now it is time to complete the picture: consistent exits. The corner exit is where you convert all your precise inputs into straightaway speed. A consistent exit means consistent speed down every straight, which means consistent lap times. This week targets throttle application, track-out, and apex speed matching.",
                "coaching_notes": "Exit consistency is the REWARD for good entry consistency. If your braking and turn-in are precise, the exit almost takes care of itself. If exits are still inconsistent after Weeks 1-2, there is usually a mid-corner issue: variable line, variable speed, or variable balance. Diagnose before treating.",
                "warmup": "5 laps at 85% pace. On each corner exit, note: am I using all the track? Am I applying throttle at the same point? Am I reaching the same speed on the following straight?",
                "drills": [
                    {
                        "name": "Throttle Application Point",
                        "description": "Apply throttle at the same corner phase every lap. 20 laps on 3 corners.",
                        "detailed_instructions": "The point where you apply throttle determines your exit speed, and therefore your speed down the entire following straight. Even a 5-metre variation in throttle application point translates to a measurable speed difference at the end of the straight. This drill fixes your throttle-on point to a specific corner phase and trains repeatability.",
                        "steps": [
                            "Select the 3 corners that lead onto the longest straights (priority corners for exit speed).",
                            "For each corner, identify your current throttle application point: is it at the apex? Just after? Well after? Note the position.",
                            "Choose your target throttle-on point for each corner. Usually: begin feathering throttle (10-20%) at the apex, full throttle as the steering unwinds.",
                            "Drive 5 laps focusing on corner 1 only. At the target point, begin throttle. Grade yourself: Hit or Miss.",
                            "Repeat for corners 2 and 3: 5 laps each with focused throttle-on timing.",
                            "Drive 5 final laps integrating all 3 corners. The throttle-on should now feel automatic.",
                            "After the session, check your data: the throttle trace should start at the same point on each lap through each target corner.",
                            "Calculate the standard deviation of throttle-on position. Target: < 2m on all 3 target corners."
                        ],
                        "tips": [
                            "Throttle application should be PROGRESSIVE, not binary. Think: 10% → 30% → 60% → 100% as the steering unwinds.",
                            "If you apply throttle too early and the car understeers on exit, you are overloading the front tyres. Wait 5m longer.",
                            "If you apply throttle too late, you are leaving free speed on the table. The car should be accelerating as soon as possible after the apex.",
                            "Use the steering angle as your trigger: 'When the wheel reaches 45 degrees unwound, begin throttle.' This creates a consistent physical cue.",
                            "Throttle-on points change with tyre grip. On fresh tyres, you can apply earlier. On worn tyres, wait slightly longer."
                        ],
                        "common_mistakes": [
                            "Applying full throttle all at once instead of progressively. This causes wheelspin or understeer.",
                            "Not having a defined throttle-on reference point and relying on feel. Feel varies — references do not.",
                            "Only focusing on WHEN you apply throttle and not HOW MUCH. The initial application amount matters as much as the timing.",
                            "Applying throttle while still adding steering input. Throttle should increase as steering DECREASES."
                        ],
                        "success_criteria": "Throttle application point standard deviation < 2m on all 3 target corners across 20 laps.",
                        "duration": "30–40 minutes",
                        "difficulty": 3,
                        "metric": "throttle_onset_delay_m",
                        "target": "< 2m std dev"
                    },
                    {
                        "name": "Track-Out Discipline",
                        "description": "Use all the track on exit consistently. Same exit point every lap.",
                        "detailed_instructions": "Using all the available track width on exit maximises your radius and therefore your exit speed. But you must use it CONSISTENTLY — sometimes using all the track and sometimes not creates variation. This drill trains you to reach the same track-out point on every lap: all the way to the outside edge, every single time.",
                        "steps": [
                            "For the 3 priority corners, identify the track-out point: the exact spot on the outside of the track where your outside wheels should reach.",
                            "Often this is a kerb, a white line, or a rumble strip. Choose a specific feature within that area.",
                            "Drive 5 laps at 85% pace, focusing on reaching the track-out point on every exit. Use ALL the road.",
                            "On each exit, grade yourself: FULL (reached the outside edge), PARTIAL (left more than a tyre width unused), NONE (stayed well inside).",
                            "If you are consistently PARTIAL, you are either applying throttle too aggressively (car pushes wide too early) or too timidly (car does not drift out).",
                            "Drive 10 more laps targeting 100% FULL exits on all 3 corners.",
                            "Check: is your exit speed consistent now? Using all the track consistently should produce consistent exit speeds.",
                            "After the session, calculate exit speed variation. Target: < 2% variation on all 3 priority corners."
                        ],
                        "tips": [
                            "Your eyes should be looking DOWN THE STRAIGHT (not at the kerb) as you reach the track-out point. The car goes where you look.",
                            "Using all the track is not the same as running off the track. You should be ON the outside edge, not OVER it.",
                            "On exits with aggressive kerbs, use the smooth part just before the kerb. Hitting big kerbs costs stability and time.",
                            "If the track-out point is naturally near a wall or barrier, leave 30cm of margin. Safety takes priority over the last 0.01s.",
                            "Consistent track-out is a sign of consistent mid-corner speed and throttle application. If exits vary, look upstream for the cause."
                        ],
                        "common_mistakes": [
                            "Leaving a full car width of road unused on exit — this is throwing away free speed.",
                            "Over-using the track and dropping two wheels off, which can spin the car on a dirty surface.",
                            "Targeting the track-out point but arriving there at different speeds each time. Speed AND position must be consistent.",
                            "Only focusing on straight-line exits and ignoring corners where the exit leads directly into the next corner."
                        ],
                        "success_criteria": "Exit speed variation < 2% on all 3 priority corners. Full track-out achieved on 80%+ of exits.",
                        "duration": "30–35 minutes",
                        "difficulty": 3,
                        "metric": "exit_speed_mps",
                        "target": "< 2% variation"
                    },
                    {
                        "name": "Apex Speed Matching",
                        "description": "Carry the same minimum speed through each corner, every lap.",
                        "detailed_instructions": "The minimum speed in a corner (apex speed) is determined by your entry speed, trail braking, and line. If any of those vary, your apex speed varies — and that cascades through the exit. This drill targets the apex speed directly: match a specific speed on every lap through each corner. When apex speed is locked, everything else follows.",
                        "steps": [
                            "From your data, find the AVERAGE minimum speed for each of the 3 target corners. This is your target apex speed.",
                            "Drive 3 warm-up laps. On each target corner, glance at the speedometer (or use a heads-up display if available) to check your apex speed.",
                            "Drive 15 laps targeting your average apex speed on each corner. Not faster, not slower — the AVERAGE.",
                            "If you are consistently faster than the target, your entry technique has changed (better trail braking?). Update the target upward.",
                            "If you are consistently slower, you are over-braking or turning in too early. Diagnose and correct.",
                            "The key is MATCHING: the same number, every lap, every corner. Variation should shrink with each set of 5 laps.",
                            "After 15 laps, check: what is the new variation in apex speed? It should be significantly less than your Week 1 baseline.",
                            "A secondary benefit: when apex speed is consistent, the car's balance mid-corner is consistent, making the exit much more predictable."
                        ],
                        "tips": [
                            "You do not need to stare at the speedometer. After a few laps, you will develop a FEEL for the target speed. The speedometer just calibrates that feel.",
                            "Apex speed is the RESULT of everything before it. If apex speed varies, the cause is in the braking zone or turn-in, not the apex itself.",
                            "On corners with elevation change, apex speed feels different from the number. Trust the number, not the sensation.",
                            "A 2% variation in apex speed translates to roughly 1-3 km/h depending on the corner speed. That is 1-2 car lengths difference at the exit.",
                            "Once apex speeds are matched, your corner-to-corner consistency should improve dramatically — this is the 'keystone' metric."
                        ],
                        "common_mistakes": [
                            "Staring at the speedometer through the entire corner instead of glancing once near the apex. Your eyes should be on the track.",
                            "Trying to carry MORE speed than the target. The goal is MATCHING the target, not exceeding it.",
                            "Only checking apex speed and not connecting it to the upstream cause. Apex speed is an effect, not a cause.",
                            "Getting frustrated by 1-2 km/h variations that are actually within measurement error. 2% is a realistic target, not 0%."
                        ],
                        "success_criteria": "Apex speed variation < 2% on all 3 target corners across 15 laps. Clearly reduced from Week 1 baseline.",
                        "duration": "30–40 minutes",
                        "difficulty": 3,
                        "metric": "apex_speed_mps",
                        "target": "< 2% variation"
                    },
                ],
            },
            {
                "week": 4,
                "title": "Full Lap Consistency",
                "focus": "This is graduation week. You have fixed your braking, turn-in, and exits individually. Now you will combine everything into full-lap consistency over extended runs. The ultimate test: 25 laps where every single one is within striking distance of your average. After this week, you will have transformed your consistency from a weakness into a superpower.",
                "coaching_notes": "Consistency under fatigue is the ultimate test. Anyone can be consistent for 5 laps. 25 laps at sub-1% CV requires physical fitness, mental discipline, and deeply ingrained technique. This week proves you have all three. Trust your training from Weeks 1-3 — it was building to this moment.",
                "warmup": "5 laps running through your complete consistency checklist: brake reference → hit it. Turn-in reference → hit it. Apex → hit it. Track-out → use all the road. Throttle → progressive from the same point. Every element, every corner.",
                "drills": [
                    {
                        "name": "25-Lap Consistency Run",
                        "description": "25 laps targeting the lowest possible CV%. This is your graduation test.",
                        "detailed_instructions": "This is the final exam. 25 consecutive laps where every ounce of consistency training comes together. The goal is to achieve a CV% that is significantly lower than your Week 1 baseline. This is a demanding test of concentration and discipline — your mind will wander, your body will fatigue, but your technique must remain constant.",
                        "steps": [
                            "Prepare as if for a race: hydrate, eat properly, warm up physically (stretching, grip exercises).",
                            "Complete your standard 5-lap warm-up to 90% pace.",
                            "Begin 25 timed laps at 90-93% effort. NOT pushing hard — driving at your consistent, sustainable pace.",
                            "Laps 1-5: focus on establishing the rhythm. Every corner should feel identical to the one before.",
                            "Laps 6-10: fatigue has not set in yet. Maintain discipline. Verbalise references if concentration starts to drift.",
                            "Laps 11-15: the middle of the run. This is where most drivers lose concentration. Actively refocus on your reference points.",
                            "Laps 16-20: fatigue starts. Your body will want to change things — maybe brake earlier, maybe carry less speed. RESIST. Maintain your trained inputs.",
                            "Laps 21-25: the final push. Concentration is critical. If you have trained well, muscle memory carries you through even when mental focus fades.",
                            "Cool down for 3 laps. Then immediately review: Average? CV%? Best? Worst? Compare to Week 1 baseline."
                        ],
                        "tips": [
                            "25 laps is approximately 25-40 minutes of continuous driving. This requires physical fitness. If you run out of energy, your consistency will collapse.",
                            "Break the run into mental blocks of 5 laps. Each block of 5 is a mini-goal. Completing 5 blocks = success.",
                            "If a lap goes badly (traffic, mistake, loss of focus), DO NOT try to compensate. Reset and drive the next lap cleanly.",
                            "Your breathing pattern is your anchor. When concentration fades, return to your breathing rhythm and the technique follows.",
                            "A CV% improvement of 30-50% from Week 1 is a realistic and excellent result after 4 weeks of focused work."
                        ],
                        "common_mistakes": [
                            "Starting too fast and fading in the second half, inflating CV%. Start at 90%, not 95%.",
                            "Getting upset about one bad lap and letting it affect the rest. Isolation is key — each lap is independent.",
                            "Not completing all 25 laps. Even if you are struggling, finishing builds mental resilience.",
                            "Comparing your CV% to professional standards. Under 1% after 4 weeks of focused work is genuinely outstanding."
                        ],
                        "success_criteria": "25 clean laps with CV% below 0.8%. Significant improvement from Week 1 baseline (target: 30%+ reduction in CV%).",
                        "duration": "50–65 minutes",
                        "difficulty": 4,
                        "metric": "consistency_cv_pct",
                        "target": "< 0.8%"
                    },
                    {
                        "name": "Pace Under Fatigue",
                        "description": "After 20 laps, complete 10 more. Monitor pace degradation.",
                        "detailed_instructions": "Fatigue is the enemy of consistency. When you are tired, your concentration fades, your inputs become less precise, and your lap times suffer. This drill deliberately pushes you into fatigue territory (30 laps total) to test and develop your ability to maintain pace when your body and mind want to slow down. This is the endurance component of consistency.",
                        "steps": [
                            "Start with 20 laps at 90-93% pace (this can be combined with or follow the 25-lap run on a separate day).",
                            "After 20 laps, check your mental and physical state. Rate fatigue on a 1-10 scale.",
                            "Now drive 10 MORE laps. This is the endurance test. You are already fatigued — can you maintain pace?",
                            "Focus all remaining concentration on your core references: brake points and apex points. If you can hit these, the rest follows.",
                            "After every 3 laps (laps 21, 24, 27, 30), do a body scan: relax shoulders, loosen grip, breathe.",
                            "Track your pace: compare laps 21-30 to laps 11-20. The target is < 0.5% degradation.",
                            "After all 30 laps, analyse: at which lap did fatigue first appear in the data? This is your endurance threshold.",
                            "Compare laps 1-10 average to laps 21-30 average. Less than 0.5% drop is excellent."
                        ],
                        "tips": [
                            "Physical fitness directly affects mental concentration. A fitter driver maintains focus longer. Consider adding cardio to your training.",
                            "Grip strength fades before cardiovascular fitness in most drivers. Hand/forearm exercises improve late-stint consistency.",
                            "Fatigue makes you conservative: braking earlier, carrying less speed, using less track on exit. Fight this by trusting your references.",
                            "Hydration is critical. A 2% body weight loss from dehydration can reduce concentration by 20%. Drink before you are thirsty.",
                            "If your endurance threshold is below 15 laps, fitness is a priority area for development outside of driving."
                        ],
                        "common_mistakes": [
                            "Pushing harder in the fatigue laps to 'prove' you are not tired. This accelerates fatigue and increases errors.",
                            "Not completing the full 30 laps. The value is in FINISHING fatigued, not just starting.",
                            "Ignoring physical symptoms of dehydration or muscle fatigue. Safety comes first — stop if you feel unwell.",
                            "Not linking late-stint pace drop to specific technique degradation. Identify WHAT changes when you are tired — then you can fight it."
                        ],
                        "success_criteria": "Complete 30 laps total (20 + 10). Pace degradation between early stint and late stint < 0.5%. Endurance threshold identified.",
                        "duration": "55–70 minutes",
                        "difficulty": 4,
                        "metric": "early_vs_late_stint_pace",
                        "target": "< 0.5% drop"
                    },
                    {
                        "name": "Consistency vs Pace Balance",
                        "description": "Find the fastest pace you can maintain with < 1% CV.",
                        "detailed_instructions": "The ultimate question: how fast can you go while staying consistent? This drill finds your 'consistent fast' pace — the maximum speed you can sustain with a CV% under 1%. This number is more important than your single-lap personal best because it represents your RACE pace: the speed you can actually deliver over a full race distance.",
                        "steps": [
                            "Warm up with 5 laps at 85% pace.",
                            "Drive 10 laps at 90% effort. Check your CV%. It should be well under 1%. Note the average time.",
                            "Increase to 92% effort for 10 laps. Check CV%. Still under 1%? Note the average.",
                            "Increase to 94% for 10 laps. Check CV%. If still under 1%, continue. If over 1%, back off to 93%.",
                            "Continue increasing by 1% increments until your CV% exceeds 1%. The PREVIOUS effort level is your consistent fast pace.",
                            "Lock in this pace level: drive 10 final laps at your consistent fast pace. Verify the CV% stays under 1%.",
                            "Record: 'My consistent fast pace is Xm Xs, achieved at Y% effort, with Z% CV.'",
                            "Compare to your personal best: the gap between your consistent pace and your PB is your 'speed reserve'. In races, this reserve is your weapon for overtaking.",
                            "This number is your most important benchmark. It is more useful than your PB for race planning."
                        ],
                        "tips": [
                            "Most drivers find their consistent fast pace is 2-4% slower than their personal best. This is normal and healthy.",
                            "If your consistent fast pace is more than 5% slower than your PB, you have a large speed reserve but inconsistent technique at higher speeds.",
                            "This number will improve as your overall technique improves. Track it monthly.",
                            "In a race, driving at your consistent fast pace is ALWAYS better than driving at your PB effort level. Consistency wins races.",
                            "Share this number with your engineer or coach. It helps them plan race strategy around your actual sustainable pace."
                        ],
                        "common_mistakes": [
                            "Trying to match your personal best while maintaining consistency. The PB is a single-lap peak; consistent pace is sustained performance.",
                            "Increasing effort too quickly (jumping from 90% to 97%). Use 1-2% increments for accurate calibration.",
                            "Not driving enough laps at each effort level. 10 laps minimum is needed for meaningful CV% calculation.",
                            "Being disappointed that your consistent pace is slower than your PB. This is COMPLETELY NORMAL and expected."
                        ],
                        "success_criteria": "Consistent fast pace identified: fastest average pace maintainable with < 1% CV over 10+ laps. Gap to personal best quantified.",
                        "duration": "50–60 minutes",
                        "difficulty": 3,
                        "metric": "best_lap_time_s",
                        "target": "fastest consistent pace"
                    },
                ],
            },
        ],
    },
}


def get_plan_templates() -> list[dict[str, Any]]:
    """Return all available plan templates."""
    templates = []
    for tid, tmpl in _PLAN_TEMPLATES.items():
        templates.append({
            "id": tid,
            "name": tmpl["name"],
            "description": tmpl["description"],
            "level": tmpl["level"],
            "n_weeks": len(tmpl["weeks"]),
            "n_drills": sum(len(w["drills"]) for w in tmpl["weeks"]),
        })
    return templates


def create_plan_from_template(
    conn: Any,
    driver_id: int,
    template_id: str,
    plan_name: Optional[str] = None,
) -> dict[str, Any]:
    """Create a development plan from a template."""
    tmpl = _PLAN_TEMPLATES.get(template_id)
    if not tmpl:
        raise ValueError(f"Unknown template: {template_id}")

    name = plan_name or tmpl["name"]
    weeks_json = json.dumps(tmpl["weeks"])

    # Initialize progress: all drills not completed
    progress = []
    for wi, week in enumerate(tmpl["weeks"]):
        week_progress = [False] * len(week["drills"])
        progress.append(week_progress)
    progress_json = json.dumps(progress)

    cur = conn.execute(
        "INSERT INTO development_plans (driver_id, plan_name, template_id, level, weeks_json, progress_json) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (driver_id, name, template_id, tmpl["level"], weeks_json, progress_json),
    )
    conn.commit()

    return {
        "id": cur.lastrowid,
        "driver_id": driver_id,
        "plan_name": name,
        "template_id": template_id,
        "level": tmpl["level"],
        "weeks": tmpl["weeks"],
        "progress": progress,
        "status": "active",
        "completion_pct": 0.0,
    }


def create_custom_plan(
    conn: Any,
    driver_id: int,
    plan_name: str,
    weeks: list[dict],
    level: str = "intermediate",
) -> dict[str, Any]:
    """Create a custom development plan with user-defined weeks and drills."""
    if not weeks:
        raise ValueError("Plan must have at least one week")

    weeks_json = json.dumps(weeks)
    progress = []
    for week in weeks:
        drills = week.get("drills", [])
        progress.append([False] * len(drills))
    progress_json = json.dumps(progress)

    cur = conn.execute(
        "INSERT INTO development_plans (driver_id, plan_name, template_id, level, weeks_json, progress_json) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (driver_id, plan_name, None, level, weeks_json, progress_json),
    )
    conn.commit()

    return {
        "id": cur.lastrowid,
        "driver_id": driver_id,
        "plan_name": plan_name,
        "level": level,
        "weeks": weeks,
        "progress": progress,
        "status": "active",
        "completion_pct": 0.0,
    }


def get_plans(conn: Any, driver_id: int) -> list[dict[str, Any]]:
    """Get all development plans for a driver."""
    rows = conn.execute(
        "SELECT * FROM development_plans WHERE driver_id = ? ORDER BY created_at DESC",
        (driver_id,),
    ).fetchall()

    plans = []
    for row in rows:
        d = dict(row)
        try:
            d["weeks"] = json.loads(d["weeks_json"]) if d.get("weeks_json") else []
        except (json.JSONDecodeError, TypeError):
            d["weeks"] = []
        try:
            d["progress"] = json.loads(d["progress_json"]) if d.get("progress_json") else []
        except (json.JSONDecodeError, TypeError):
            d["progress"] = []
        d["completion_pct"] = get_plan_completion_pct(d)
        plans.append(d)
    return plans


def get_plan(conn: Any, plan_id: int) -> Optional[dict[str, Any]]:
    """Get a single plan by ID."""
    row = conn.execute(
        "SELECT * FROM development_plans WHERE id = ?",
        (plan_id,),
    ).fetchone()

    if not row:
        return None

    d = dict(row)
    d["weeks"] = json.loads(d["weeks_json"]) if d.get("weeks_json") else []
    d["progress"] = json.loads(d["progress_json"]) if d.get("progress_json") else []
    d["completion_pct"] = get_plan_completion_pct(d)
    return d


def update_plan_progress(
    conn: Any,
    plan_id: int,
    week_index: int,
    drill_index: int,
    completed: bool = True,
) -> Optional[dict[str, Any]]:
    """Mark a specific drill as completed/uncompleted."""
    plan = get_plan(conn, plan_id)
    if not plan:
        return None

    progress = plan["progress"]
    if week_index < 0 or week_index >= len(progress):
        raise IndexError(f"Week index {week_index} out of range (0-{len(progress)-1})")
    if drill_index < 0 or drill_index >= len(progress[week_index]):
        raise IndexError(f"Drill index {drill_index} out of range (0-{len(progress[week_index])-1})")

    progress[week_index][drill_index] = completed
    progress_json = json.dumps(progress)

    conn.execute(
        "UPDATE development_plans SET progress_json = ?, updated_at = datetime('now') WHERE id = ?",
        (progress_json, plan_id),
    )
    conn.commit()

    return get_plan(conn, plan_id)


def delete_plan(conn: Any, plan_id: int) -> bool:
    """Delete a plan. Returns True if deleted."""
    cur = conn.execute("DELETE FROM development_plans WHERE id = ?", (plan_id,))
    conn.commit()
    return cur.rowcount > 0


def get_plan_completion_pct(plan: dict[str, Any]) -> float:
    """Calculate overall completion percentage of a plan."""
    progress = plan.get("progress", [])
    if not progress:
        return 0.0

    total = 0
    completed = 0
    for week in progress:
        for drill_done in week:
            total += 1
            if drill_done:
                completed += 1

    return round(100.0 * completed / total, 1) if total > 0 else 0.0


# ── Inline tests ────────────────────────────────────────────────

def _run_tests() -> None:
    """Self-contained test suite for development plans."""
    import sqlite3
    import traceback as tb

    passed: list[str] = []
    failed: list[tuple[str, str]] = []

    def _test(name, fn):
        try:
            fn()
            passed.append(name)
        except Exception:
            failed.append((name, tb.format_exc()))

    def _make_db():
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("""CREATE TABLE IF NOT EXISTS drivers (
            driver_id INTEGER PRIMARY KEY AUTOINCREMENT,
            driver_name TEXT NOT NULL UNIQUE,
            created_at TEXT DEFAULT (datetime('now')), notes TEXT)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS development_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            driver_id INTEGER NOT NULL,
            plan_name TEXT NOT NULL, template_id TEXT,
            level TEXT DEFAULT 'intermediate',
            weeks_json TEXT NOT NULL, progress_json TEXT,
            status TEXT DEFAULT 'active',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')))""")
        conn.execute("INSERT INTO drivers (driver_name) VALUES ('TestDriver')")
        conn.commit()
        return conn

    # Test 1: get templates
    def t_templates():
        templates = get_plan_templates()
        assert len(templates) == 5
        ids = {t["id"] for t in templates}
        assert "beginner" in ids
        assert "advanced" in ids
        assert "race_prep" in ids
        assert "consistency_focus" in ids
        for t in templates:
            assert t["n_weeks"] == 4
            assert t["n_drills"] >= 12  # 3 drills * 4 weeks

    _test("templates", t_templates)

    # Test 2: create from template
    def t_create_from_template():
        conn = _make_db()
        plan = create_plan_from_template(conn, 1, "beginner")
        assert plan["id"] is not None
        assert plan["plan_name"] == "Beginner Foundations"
        assert plan["level"] == "beginner"
        assert len(plan["weeks"]) == 4
        assert plan["completion_pct"] == 0.0
        conn.close()

    _test("create_from_template", t_create_from_template)

    # Test 3: create custom plan
    def t_custom_plan():
        conn = _make_db()
        weeks = [
            {"week": 1, "title": "Week 1", "drills": [
                {"name": "Drill A", "description": "Do A"},
                {"name": "Drill B", "description": "Do B"},
            ]},
        ]
        plan = create_custom_plan(conn, 1, "My Plan", weeks)
        assert plan["plan_name"] == "My Plan"
        assert len(plan["progress"]) == 1
        assert len(plan["progress"][0]) == 2
        conn.close()

    _test("custom_plan", t_custom_plan)

    # Test 4: update progress
    def t_progress():
        conn = _make_db()
        plan = create_plan_from_template(conn, 1, "beginner")
        assert plan["completion_pct"] == 0.0

        # Complete first drill
        updated = update_plan_progress(conn, plan["id"], 0, 0, True)
        assert updated["progress"][0][0] is True
        assert updated["completion_pct"] > 0.0

        # Complete all drills
        for wi, week in enumerate(updated["progress"]):
            for di in range(len(week)):
                update_plan_progress(conn, plan["id"], wi, di, True)

        final = get_plan(conn, plan["id"])
        assert final["completion_pct"] == 100.0
        conn.close()

    _test("progress", t_progress)

    # Test 5: get plans
    def t_get_plans():
        conn = _make_db()
        create_plan_from_template(conn, 1, "beginner")
        create_plan_from_template(conn, 1, "advanced")
        plans = get_plans(conn, 1)
        assert len(plans) == 2
        conn.close()

    _test("get_plans", t_get_plans)

    # Test 6: delete plan
    def t_delete():
        conn = _make_db()
        plan = create_plan_from_template(conn, 1, "beginner")
        assert delete_plan(conn, plan["id"]) is True
        assert get_plan(conn, plan["id"]) is None
        assert delete_plan(conn, 999) is False
        conn.close()

    _test("delete", t_delete)

    # Test 7: bad template
    def t_bad_template():
        conn = _make_db()
        try:
            create_plan_from_template(conn, 1, "nonexistent")
            assert False, "Should raise ValueError"
        except ValueError:
            pass
        conn.close()

    _test("bad_template", t_bad_template)

    # Test 8: progress bounds checking
    def t_bounds():
        conn = _make_db()
        plan = create_plan_from_template(conn, 1, "beginner")
        try:
            update_plan_progress(conn, plan["id"], 99, 0, True)
            assert False, "Should raise IndexError"
        except IndexError:
            pass
        try:
            update_plan_progress(conn, plan["id"], 0, 99, True)
            assert False, "Should raise IndexError"
        except IndexError:
            pass
        conn.close()

    _test("bounds", t_bounds)

    total = len(passed) + len(failed)
    status_str = "PASS" if not failed else "FAIL"
    print(f"\nDevelopment Plan Tests: {len(passed)}/{total} passed [{status_str}]")
    for n in passed:
        print(f"  OK {n}")
    for n, trace in failed:
        print(f"  FAIL {n}\n{trace}")
    if failed:
        raise AssertionError(f"{len(failed)} test(s) failed.")


if __name__ == "__main__":
    _run_tests()
