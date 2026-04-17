# Prescriptive Coaching

> Converts canonical evidence into structured coaching playbooks with measurable targets and next-run validation logic.

## What it does

The prescriptive coaching engine takes the outputs of Session Compare (corner packets) and Development Intelligence (recurring weaknesses) and produces:

1. **Weakness playbook matches** — for each detected weakness, a full coaching prescription with likely causes, specific actions, driver cues, measurable targets, and sensor-honest notes
2. **Per-corner coaching** — which weaknesses apply to which corners, linked back to the compare evidence
3. **Next-run plan** — max 3 priorities (technical focus, execution focus, validation metric) plus an anti-overload note
4. **Validation checks** — measurable criteria to verify improvement after applying the coaching
5. **Storyline** — narrative context about what to focus on and what is already improving

## Data source contract

**Reads ONLY from canonical Bronze-derived outputs:**
- `data.session_compare.corner_packets`
- `data.development_intelligence.recurring_weaknesses`
- `data.development_intelligence.priority_focuses`
- `data.development_intelligence.storyline`

**Does NOT read from:**
- Gold Lab, beta candidates, bank-corrected overlays, grade channels, shadow products, or any diagnostic/experimental data

This is enforced by a source-import test in the test suite.

## Weakness taxonomy

5 weakness types with full playbook definitions:

| Key | Title | Phase | Playbook includes |
|---|---|---|---|
| `low_minimum_speed` | Low minimum speed through apex | apex | 4 likely causes, 3 actions, 3 cues |
| `early_braking` | Early braking on entry | entry | 3 likely causes, 3 actions, 2 cues |
| `late_throttle_pickup` | Late throttle pickup on exits | exit | 3 likely causes, 3 actions, 2 cues |
| `weak_exit_build` | Weak exit speed build | exit | 3 likely causes, 3 actions, 2 cues |
| `line_deviation` | Inconsistent line / path deviation | apex | 3 likely causes, 3 actions, 2 cues |

Each playbook entry has parameterized templates that are filled with actual measured values from the evidence (e.g., `{brake_adjust_m}` becomes `4` based on the median brake-point delta).

## Prescription structure

```json
{
  "weakness_key": "low_minimum_speed",
  "title": "Low minimum speed through apex",
  "corner_ids": [1, 2, 3, 4, 5, 6],
  "severity": "high",
  "recurrence": 249,
  "estimated_cost_ms": 478.6,
  "likely_causes": ["Over-rotating...", "Releasing brake too abruptly...", ...],
  "coaching_actions": ["Protect minimum speed: aim to carry 6 more through the middle...", ...],
  "driver_cues": ["Feel: the kart should feel 'loaded'...", ...],
  "measurable_targets": ["Minimum speed rises by 6+ km/h", ...],
  "next_stint_validation": ["After 3 focused laps, check: ...", ...],
  "evidence_confidence": 1.0,
  "portability": "possibly portable",
  "data_support": "249 occurrences across 6 corners in 5 sessions. Trend: improving.",
  "sensor_note": "Minimum speed measured from GPS speed trace (speed-derived, no wheel speed sensor)"
}
```

## Next-run plan

Max 3 items + 1 anti-overload note:

| Rank | Type | Purpose |
|---|---|---|
| 1 | `technical_focus` | The ONE thing to change technique-wise |
| 2 | `execution_focus` | The second priority, add only after #1 is stable |
| 3 | `validation_metric` | Monitor only — do not actively change; check if it improves passively |
| 0 | `anti_overload` | "Do not try to fix everything at once" — explicit cognitive load guard |

## Validation checks

Each check specifies:
- Which metric to measure
- At which corners
- What the target is
- How the measurement works (sensor note)
- Confidence level

## Explicit limits

Every output includes a `limits` block declaring:
- Brake data: "speed-derived deceleration proxy only"
- Throttle data: "speed-derived acceleration proxy only"
- Steering data: "not available"
- Cross-track portability: "unknown — single track"
- Weather conditions: "not tracked"
- Reference basis: "session-overall best lap"
- Confidence floor: prescriptions with < 3 occurrences are omitted

## Known limits

1. **No brake pressure sensor.** All braking advice uses speed-derived deceleration onset. Brake-point accuracy is ±3–5 m.
2. **No throttle position sensor.** Throttle timing uses speed-derived acceleration onset. Similarly ±3–5 m.
3. **No steering angle.** "Rotation", "commitment", and "turn-in" advice is inferred from speed + line patterns, not measured steering.
4. **Single track.** Portability is tagged but cannot be validated.
5. **Parameterized targets are conservative.** Targets use 30% of the measured delta (e.g., if min speed is 10 kph low, target is +3 kph) to avoid over-promising.
