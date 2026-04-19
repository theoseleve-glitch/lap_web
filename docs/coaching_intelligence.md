# Coaching Intelligence

> Transforms compare evidence + development intelligence into actionable, evidence-backed coaching interventions.

## What it does

The Coaching Intelligence engine answers: **"What should I change, where, and how?"**

It takes the existing canonical outputs (corner packets from Session Compare, weakness patterns from Development Intelligence) and produces structured **coaching actions** — each scoped to specific corners, specific driving phases, and specific measurable outcomes.

## Intervention classes

The engine detects 6 distinct intervention types:

| Class | Phase | What it detects | Trainability |
|---|---|---|---|
| `entry_speed_surrender` | entry | Braking starts >5m early AND min speed >3kph low | 0.85 |
| `conservative_brake_release` | brake_release | Brake point is OK but min speed is >5kph low — holding too long | 0.90 |
| `apex_speed_deficit` | apex | Min speed low despite normal brake/throttle timing — commitment issue | 0.75 |
| `late_throttle_application` | exit | Throttle pickup >5m later than reference | 0.90 |
| `weak_exit_build` | exit | Exit speed >5kph low despite normal throttle timing | 0.85 |
| `path_variance` | apex | Line deviation RMS >1.5m — inconsistent geometry | 0.70 |

Each detection uses the existing evidence fields from corner packets — no new physics computation.

## Coaching action structure

Every action contains 5 coaching elements, all derived from measured evidence:

1. **HYPOTHESIS** — what is happening, with specific numbers
2. **INSTRUCTION** — what to change, operationalized
3. **PROTOCOL** — how to test it on the next 3–5 laps
4. **SUCCESS METRIC** — how to measure improvement
5. **PRIORITY SCORE** — `mean_gain × affected_corners × confidence × trainability × recurrence`

## Priority ranking

Actions are ranked by `priority_score` and assigned status:
- `focus_now` — highest priority, the ONE thing to work on first
- `secondary` — ranks 2–3, work on after the primary
- `monitor` — detected but lower priority; track for later

## Corner family detection

When the same intervention type spans 3+ corners, it's flagged as a **systemic habit** — likely a driver behavior rather than a corner-specific issue. This means fixing it in any one corner should transfer to others.

## Estimated gain

Each action reports `estimated_gain_ms` = 30% of the raw theoretical time delta across affected corners. This is deliberately conservative — it accounts for the fact that you won't recover 100% of the reference gap on the first attempt.

## JSON schema

Under `data.coaching_intelligence`:

```json
{
  "version": "1.0",
  "actions": [{
    "id": "action_conservative_brake_release_2",
    "title": "Brake release too conservative",
    "problem_type": "conservative_brake_release",
    "corners": [2, 3, 5, 7, 8, 9],
    "phase": "brake_release",
    "evidence": {
      "time_cost_ms": 4416.0,
      "mean_per_corner_ms": 735.9,
      "affected_corners": 6,
      "recurrence": 249,
      "trend": "improving",
      "confidence": 0.82,
      "supporting_metrics": { ... }
    },
    "coach_hypothesis": "At T2, T3, T5..., the brake point is close to reference but minimum speed is 9.2 km/h lower...",
    "driver_instruction": "Focus on the RELEASE, not the initial application. Begin trailing off brake pressure 4 m earlier...",
    "attempt_protocol": "On the next 3 laps, treat T2, T3, T5... as 'release practice' corners...",
    "success_metric": "Success = minimum speed rises by 3+ km/h without moving the brake point earlier.",
    "estimated_gain_ms": 1324.8,
    "trainability": 0.9,
    "confidence": 0.82,
    "priority_score": 4.237,
    "status": "focus_now",
    "canonical_basis": true
  }],
  "corner_families": [...],
  "focus_summary": "PRIMARY: Brake release too conservative at T2, T3, T5, T7. Estimated recoverable: 1325 ms...",
  "secondary_summary": "NEXT: Weak exit speed build (T1, T3, T7); Path variance too high (T1, T2, T3).",
  "confidence_note": "Based on 5 sessions at Ouest Karting. Pattern evidence is strong for this track.",
  "sessions_context": "5 sessions at Ouest Karting"
}
```

## Known limits

1. **No steering data.** "Commitment" and "rotation" interventions are inferred from speed patterns, not from a direct steering trace.
2. **Throttle is approximate.** Derived from speed gradient, not CAN-bus. Throttle-timing interventions are directionally correct but may be off by a few meters.
3. **Single reference.** Currently compares against the session-best lap only. A composite best-sectors reference would give tighter coaching.
4. **Conservative gain estimates.** 30% of raw delta is the default — intentionally low so the driver isn't misled about expected improvement.
