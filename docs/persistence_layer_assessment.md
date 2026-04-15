# Persistence + Accumulation Layer — Phase 2 Assessment

**Date:** 2026-04-15
**Modules:**
  - `telemetry_tool/track_surface/vehicle_calibration_registry.py`
  - `telemetry_tool/track_surface/cross_session_accumulator.py` (incl. `layered_query`)
**Tests:** 45 in `telemetry_tool/tests/test_persistence_layer.py`
**Demo data:** Two McLaren 570S GT4 Daytona sessions (different days, same car/track)

This document closes Phase 2 of the architectural roadmap that the
cross-track validation set in Phase 1. It addresses the two
infrastructure gaps that were blocking product-readiness:

  1. Per-vehicle calibration storage with explicit versioning + provenance
  2. Cross-session evidence accumulation with safe merge semantics

The third roadmap item — multi-criterion transition gate — is
deliberately deferred. The recommendation at the bottom of this
document explains why.

---

## What was built

### Vehicle calibration registry

A first-class persistent record of fitted parameters per vehicle.

**Schema** (one JSON file, e.g. `data/vehicle_calibrations.json`):
- `CalibrationProfile` — top-level versioned record with
  `profile_id`, `vehicle_key`, `vehicle_class`, `active`, `deprecated`
- `TireCalibration` — `d1_lat / d1_long / d2_lat / d2_long / k_lat_scale`
  + `FitQuality` (n_samples, residual, fit_std)
- `RoadStateCalibration` — `roll_compliance / pitch_compliance / smooth_window /
  transition_threshold` + `FitQuality`
- `FitProvenance` — `session_id / fit_method / harness_version /
  fit_date / n_samples`

**Resolution rule** (the everyday path):
1. Active profile for exact `vehicle_key`
2. Active profile for any vehicle in the same `vehicle_class`
3. Default fallback (constructed on the fly, never persisted, never `active=True`)

The default fallback is explicit so callers always know they got it
(returned via `ResolvedCalibration.source`). This makes
"my pipeline used a default because I forgot to register the car" a
visible state, not a silent one.

### Cross-session accumulator

Per-`(track, calibration_profile)` persistent dense field with
Bayesian Kalman per-cell merge.

**Storage** (one accumulator per file pair):
- `{accumulator_dir}/{key}.npz` — dense arrays per active bucket
  (`mean`, `variance`, `n_obs`, `total_confidence`)
- `{accumulator_dir}/{key}.json` — sidecar with track fingerprint,
  config, contributions list, rejections list, per-cell session attribution

**Merge guards (any failure rejects the whole session)**:
1. `track_fingerprint` — name + layout match exactly; length within ±50 m
2. `calibration_profile_id` — must equal the accumulator's
3. `n_valid_samples` — minimum 1000
4. Grid shape match — same s_bins / n_bins arrays

**Per-bucket guards (failure rejects only that bucket from that session)**:
- TRANSITION_BUCKET — never accumulates
- Cell observation floor — `n_obs >= min_obs_per_cell` (default 3)
- Bucket divergence — if session bucket mean differs from accumulator
  mean by > N σ (default 3.0), the bucket is rejected for that session

The merge is precision-weighted Kalman per cell:
`1/var = 1/var_acc + 1/var_session`. Counts and confidences add.

### Layered query (`layered_query`)

The single combined query that downstream code uses. Resolution order:
1. `current_exact` (current bucket, conf >= 0.05) — but with strong-current override
2. `accumulated_exact` (accumulator bucket, conf >= 0.05)
3. `current_section` (section-merged from current)
4. `accumulated_section` (section-merged from accumulator)
5. `prior` (global)

Returns `AccumulatedQueryResult` with `evidence_source` enum +
contributing session ids, so any planner cell is fully traceable.

### Wiring

The validation harness now:
- Resolves `entry.vehicle.name → vehicle_key → CalibrationProfile`
  (registry, class fallback, or default)
- Loads/creates the matching `CrossSessionAccumulator`
- After the bucketed field is built, attempts to merge → records `merge_outcome`
- Re-computes the planner-grid fallback distribution via `layered_query`
- Saves the accumulator

CLI flags: `--registry PATH --accumulator-dir DIR`. Both are off by
default — the harness still works without persistence.

---

## The before/after demo

Two real Daytona McLaren GT4 sessions, run in sequence with the
calibration registry (one `mclaren570sgt4_v1` profile) and an
initially-empty accumulator directory:

| Run | Acc Before | Acc After | Merge | FB(cur) | FB(acc) | Δ |
|-----|-----------|-----------|-------|---------|---------|---|
| Session 1 (cold) | 0 | 1 | accepted | 65.0% | 65.0% | 0.0 |
| Session 2 (warm) | 1 | 2 | accepted | 69.5% | 65.0% | **+4.55 pp** |

Session 2's depth distribution shifted: **4 cells moved into
`accumulated_exact` and 22 into `accumulated_section`** thanks to
session 1's evidence at locations session 2 didn't observe directly.
Provenance is fully traceable — `accumulator.cell_sessions(bucket, s, n)`
returns the session ids that contributed to any cell.

`current_exact` still answered 166 of 199 non-transition cells. The
strong-current override was never triggered as a tie-break (no live
signal was overridden by historical data — the layered path only ever
*added* evidence, never replaced it).

The accumulator JSON sidecar shows zero rejections — both sessions
passed all merge guards (track + profile + grid + sample count + per-
bucket divergence).

---

## Acceptance criteria — line by line

| Criterion | Result |
|-----------|--------|
| Excessive-fallback warnings decrease on related sessions | ✅ Session 2: 69.5% → 65.0% (–4.55 pp) |
| Confidence improves in sparse buckets without losing honesty | ✅ Layered query never returns deeper fallback than current alone (verified by alignment of confidence thresholds) |
| Provenance is explicit and debuggable | ✅ Per-cell session attribution + sidecar JSON + `evidence_source` per query |
| Incompatible sessions safely rejected | ✅ 4 distinct rejection reasons tested; tracked in `rejections` list |
| Vehicle-specific calibration consistently applied | ✅ Both runs show `calibration_source: registry_active` |
| Current-session behavior not washed out | ✅ 166/199 cells answered by `current_exact`; strong-current override at conf ≥ 0.20 |
| No regressions in planner invariants | ✅ Zero `planner_infeasibility` warnings across all runs in this work |

All seven hold.

---

## Tests

`test_persistence_layer.py` — 45 tests covering:

- **Registry** (18): empty resolution, exact match, class fallback,
  no-cross-class contamination, single-active invariant, deprecation,
  save/load round-trip, schema version guard, duplicate id guard,
  validation invariants
- **TrackFingerprint** (5): name / layout / length compatibility
- **Accumulator merge guards** (5): track / calibration / quality / grid
- **Accumulator merge behavior** (5): first session populates,
  second adds evidence, divergent bucket rejected, per-cell
  provenance, transition exclusion
- **Accumulator isolation** (1): flat and banked stay independent
- **Persistence** (3): npz+json round-trip, schema version guard,
  AccumulatorRegistry get_or_create
- **Layered query** (6): strong current beats accumulated, sparse
  current uses accumulated, prior fallback, transition→prior, section
  fallback, confidence increases honestly
- **End-to-end** (2): two sessions reduce fallback, reproducibility

Full sweep: **216 tests pass** (45 persistence + 46 cross-track +
125 friction-pipeline regression).

---

## What this does NOT solve (yet)

The persistence layer fixed the two infrastructure gaps. It did not
change the physics. So:

- **Tire model shape (B/C/E)** is still wrong for non-GT cars. The
  registry now stores that the BMW M2 and Audi RS3 LMS would each
  need their own profile — but until those profiles are *fit* (not
  just registered), the FAIL on `lambda_out_of_band` for those cars
  remains.
- **Road-state estimator's bank confusion on flat tracks with
  elevation** is unchanged. The transition gate (Phase-1 item #3)
  was the proposed fix and still hasn't been built.
- **`excessive_fallback` continues to FAIL on cold-cache runs** —
  the very first session at any track always pays the prior tax.
  This is structural and acceptable; the win is on subsequent runs.

---

## Recommendation: build the multi-criterion transition gate

The Phase-1 assessment listed three architectural gaps. Two are
closed (registry + accumulator). The third — multi-criterion
transition gate — is the next one to build, for these reasons:

1. **It's the largest remaining honest-loss.** Daytona quarantines
   38% of samples, Spa 32%, Okayama 20%. That's data we throw away
   because the bank-gradient threshold is a single-axis cliff. A
   multi-criterion gate (`bank_grad > X AND road_quality < Y`, or
   similar) keeps high-quality samples in even when bank gradient
   has noise.
2. **It compounds with the accumulator.** Lower transition discard
   rate → more samples per session → richer accumulator → faster
   convergence on subsequent sessions. The two changes multiply.
3. **It's still no-new-physics.** The transition gate is a
   data-quality decision, not a model. Same constraint that has
   guided this entire arc.
4. **The validation harness is ready to measure it.** The
   `transition_contamination` warning category already exists with
   a named threshold. Switching the gate logic and re-running the
   suite will produce a clean before/after comparison without any
   new instrumentation work.

After the transition gate ships, the next decision is **stop and
productize** — the architectural gaps will be closed, the validation
harness will be the regression guard, and any remaining work
(per-vehicle B/C/E tire fits, more datasets in the manifest,
richer reporting) is operational rather than structural.

If product pressure is higher than physics-completeness pressure,
**productize first**. The system as it stands today (calibration
registry + accumulator + frozen-pass validation harness) is
already useful — the transition gate is an optimization, not a gate.
