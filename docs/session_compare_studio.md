# Session Compare Studio

> Lap-vs-lap comparison and coaching analysis. The first operator-facing analysis product in the telemetry viewer.

## Purpose

The Session Compare Studio answers the five questions a driver asks after every run:

1. **Where am I losing time?** — Per-corner time-delta breakdown, colour-coded on the 3D track map.
2. **Why am I losing it?** — Per-corner cause attribution (braking, minimum speed, throttle pickup, exit build, line deviation).
3. **What changed between my best lap and this lap?** — Aligned speed trace, throttle trace, line offset, and lateral demand, synchronized by distance.
4. **What is the highest-value fix for the next run?** — Top 3 fixes ranked by time delta, each with a specific coaching sentence and evidence.
5. **What should I not try to fix yet?** — Uncertain zones explicitly flagged so the driver doesn't chase noise.

## Canonical vs experimental behaviour

The compare engine operates on **Bronze-canonical signals only**: speed, throttle, line offset, lateral demand. These are the same arrays the viewer has always rendered.

Gold Lab signals (bank-corrected beta, grade, etc.) are NOT consumed by the coaching engine. They are available in the Gold Lab sidebar for engineers who want to cross-reference, but the coaching conclusions come from canonical data exclusively.

## How it works

### Alignment

Both laps are projected to a shared uniform distance grid (spacing = 1.5 m). Each per-sample array (speed_kph, throttle, n_offset, lat_demand_g) is resampled by linear interpolation onto this grid. The reference lap and candidate lap then share the same x-axis (distance along track) so every metric can be compared point-by-point.

### Time-delta accumulation

At each grid segment:

```
dt = ds × (1/v_candidate − 1/v_reference)
```

Cumulating `dt` gives a running time-delta trace. Positive = candidate is slower at this point. The total accumulated delta approximates the lap-time difference; small discrepancies arise from trace downsampling and distance differences between the two paths.

### Corner segmentation

Corners are identified from the track's signed curvature array: contiguous regions where `|κ| > 0.025 1/m` form a corner, with a minimum length of 15 m and a merge gap of 10 m (so chicanes stay as one corner). The resulting corner list has `s_entry`, `s_exit`, `peak_curvature`, and a sequential `corner_id` starting from 1.

### Per-corner analysis

For each corner, the engine computes:

| Metric | How |
|---|---|
| **time_delta_ms** | Cumulative delta at exit minus cumulative delta at entry. |
| **min speed** | Minimum speed inside the corner bounds for both laps. |
| **brake point** | First sample in the 50 m approach zone where deceleration > 0.15 G. |
| **throttle pickup** | First sample after apex where throttle > 40%. |
| **exit speed** | Speed 30 m after corner exit. |
| **line deviation** | RMS of `n_offset_candidate − n_offset_reference` inside the corner. |

Each metric delta is ranked by estimated time impact. The top two become `primary_cause` and `secondary_cause`.

### Deceleration (no brake pressure)

The raw data has no brake-pressure channel. Deceleration is derived from the speed trace: `decel_g = −v × (dv/ds) / g`. This gives a signed longitudinal force estimate — positive = braking, negative = accelerating. It's honest but less precise than a real brake-pressure sensor.

### Time-loss attribution

The total cumulative delta is split into four phase buckets plus an uncertain remainder:

| Bucket | Mask |
|---|---|
| **braking** | reference deceleration > 0.15 G |
| **corner** | `|κ| > 0.02` AND not braking |
| **exit_traction** | reference accelerating AND not in corner |
| **straight_carry** | everything else |
| **uncertain** | total − sum of above (should be ≈ 0 if masks are exhaustive) |

The buckets are disjoint and sum to the accumulated delta.

### Coaching text generation

Each corner's coaching sentence is generated from the actual evidence fields — never from a template alone. The logic selects the primary cause, reads the specific numbers from the evidence dict (e.g. "17.9 km/h lower", "12 m earlier"), and assembles a sentence that references those exact values. If no clear cause dominates, the sentence says "Cause is mixed or unclear from available signals."

### Top 3 fixes

From all corners where the candidate lost time (positive delta), the three with the largest `time_delta_ms` become the top fixes. Each fix is a dict with `corner_id`, `time_delta_ms`, `primary_cause`, `confidence`, and the full `coach_text`. No duplicate corners appear.

## Known limits

1. **Only 2 laps compared.** The build pipeline stores best and median; future work should compare any lap pair.
2. **No brake pressure.** Deceleration from speed derivative is a proxy — it can't distinguish trail-braking from engine-braking.
3. **No steering angle.** Turn-in timing is inferred from curvature + speed, not from a direct steering trace.
4. **Throttle is approximate.** Derived from speed gradient (`dv > 0 → throttle`), not from a CAN-bus signal. On-off binary, not proportional.
5. **Attribution sums to accumulated delta, not external lap_time_delta.** The external delta is `candidate.lap_time − reference.lap_time` (precise); the accumulated delta is from speed-trace integration (approximate). They agree within ~10% for laps with similar path length.
6. **No aero, setup, or tire-model claims.** Every coaching output is kinematic — it says what happened on track, not why the kart behaved that way mechanically.

## JSON schema

Under `data.session_compare`:

```json
{
  "version": "1.0",
  "reference_lap_id": "best (70.462s, OK_R4)",
  "candidate_lap_id": "median (85.819s, OK_R2)",
  "alignment_basis": "distance_s",
  "traces": {
    "s_grid":           [float],
    "ref_speed_kph":    [float],
    "cand_speed_kph":   [float],
    "ref_throttle":     [float],
    "cand_throttle":    [float],
    "ref_n_offset":     [float],
    "cand_n_offset":    [float],
    "ref_lat_demand_g": [float],
    "cand_lat_demand_g":[float],
    "delta_speed_kph":  [float],
    "delta_time_s":     [float],
    "ref_decel_g":      [float],
    "cand_decel_g":     [float]
  },
  "global_summary": {
    "lap_time_delta_s": float,
    "accumulated_delta_s": float,
    "time_lost_by_phase": { braking_s, corner_s, exit_traction_s, straight_carry_s, uncertain_s, total_s },
    "n_corners_detected": int,
    "top_gain_corner": int,
    "top_loss_corner": int,
    "analysis_confidence": float
  },
  "corner_packets": [{
    "corner_id": int,
    "s_entry_m": float,
    "s_apex_m": float,
    "s_exit_m": float,
    "time_delta_ms": float,
    "primary_cause": string,
    "secondary_cause": string,
    "confidence": float,
    "evidence": {
      "min_speed_ref_kph": float,
      "min_speed_cand_kph": float,
      "min_speed_delta_kph": float,
      "brake_point_delta_m": float | null,
      "throttle_pickup_delta_m": float | null,
      "exit_speed_ref_kph": float,
      "exit_speed_cand_kph": float,
      "exit_speed_delta_kph": float,
      "line_deviation_rms_m": float
    },
    "coach_text": string
  }],
  "top_fixes": [{ corner_id, s_entry_m, s_apex_m, s_exit_m, time_delta_ms, primary_cause, confidence, coach_text }],
  "improved_zones": [{ corner_id, s_entry_m, s_exit_m, time_delta_ms, primary_cause }],
  "worse_zones": [...],
  "uncertain_zones": [...]
}
```

## Future extensions

- **Multi-lap picker.** Store all laps in the JSON; let the user select any pair.
- **Best-sectors reference.** Composite reference from the fastest sector of each corner across all laps.
- **Brake pressure.** When CAN data is available, replace decel proxy with real brake channel.
- **Steering angle.** When available, add turn-in timing and steering-rate comparison.
- **Gold Lab experimental assist.** Optional toggle to annotate coaching with bank-corrected insights as a secondary note, never rewriting the canonical conclusion.
