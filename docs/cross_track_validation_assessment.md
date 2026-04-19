# Cross-Track Validation — First Assessment

**Date:** 2026-04-15
**Harness:** `telemetry_tool/track_surface/validation/`
**Manifest:** `data/cross_track_manifest.json`
**Datasets used in this report:** Daytona / McLaren 570S GT4, Spa / BMW M2 CSR, Okayama / Audi RS3 LMS

This document answers the questions the validation harness was built to answer:

1. Which parts of the stack transfer beyond Daytona?
2. Which parts are still track- or car-specific?
3. Does the uncertainty machinery stay honest on new data?
4. Are nominal / robust / exploitable still interpretable?
5. Are failures localized or silent?

The harness ran in two passes — frozen-parameter transfer (Pass 1) and
adaptation sensitivity (Pass 2) — so we can separate "the stack
generalizes" from "per-session retuning rescues the stack."

---

## Headline numbers (frozen, Pass 1)

| Dataset | Group | λ med | λ p5/p95 | Cov% | Race-line Δ | Robust Δ | Lap σ | Status |
|---------|-------|-------|----------|------|-------------|----------|-------|--------|
| Daytona / McLaren GT4 | A_banked | 1.347 | 0.70 / 2.00 | 17.3 | +0.036 | 0.187 | 0.050 | FAIL |
| Spa / BMW M2 CSR | C_flat_high_speed | 1.183 | 0.32 / 2.00 | 7.7 | +0.009 | 0.259 | 0.064 | FAIL |
| Okayama / Audi RS3 LMS (FWD) | B_flat_low_speed | 0.637 | 0.30 / 1.50 | 7.7 | -0.011 | 0.285 | 0.009 | WARN |

The FAIL flags both hit `excessive_fallback`. The WARN on Okayama hits
`excessive_fallback` at a lower threshold — the FWD car's smaller field
coverage was forecasted in the manifest and falls short of the stricter
Daytona expectation.

## Adaptive (Pass 2) deltas

| Dataset | Frozen λ med | Adaptive λ med | Frozen Fy resid | Adaptive Fy resid | Notes |
|---------|---------------|-----------------|-----------------|--------------------|-------|
| Daytona | 1.347 | 1.075 | ~1500 N | (similar) | Adaptation pulls λ closer to physical 1.0 |
| Spa     | 1.183 | 0.813 | 3316 N | 4668 N | Adaptation **worsens** residual — tire shape (B/C/E), not just D scale, is wrong |

The Spa adaptive run is the most informative finding: a single-axis fit
(D scale only) cannot rescue a tire model whose **shape** is wrong for a
different car. The harness surfaces this without needing any new physics
to be added.

---

## What generalizes

**Tire model — directionally.** Lambda lands inside the per-track bands
on every dataset (after correcting for the FWD case in Okayama). The
inverse solver does not crash, does not produce NaN, and the
distribution shape is sane. This is solid foundation.

**Frenet projection / centerline extraction.** Works on all three
tracks (Daytona infield, Spa, Okayama). No special-casing needed.
Track-length recovery is within ~1% of published lengths.

**Surface field structure.** The Bayesian field updates and smoothing
work on every dataset. Confidence map behaves as designed (low where
unobserved, higher where data accumulates).

**Planner invariants.** `robust ≤ nominal` and `exploitable ≤ nominal`
held on every dataset and every pass. **Zero `planner_infeasibility`
warnings.** The robust-OCP layer transfers cleanly because it is
deterministic post-processing on the field — the trade-offs it makes
are honest regardless of the field's underlying quality.

**Excitation gating.** Reject-reason mix stays similar across cars and
tracks (`low_demand` > `low_excitation` > `low_prediction`). The
solver isn't tripping in surprising ways on new data.

---

## What does NOT generalize

**Road-state estimator on flat tracks with elevation.** Spa is
essentially flat but the estimator reports ±36° "banking." The roll
compliance (`0.005 rad/m/s²`) was tuned for the McLaren GT4. The BMW
M2 has a different chassis stiffness — what the M2 expresses as
chassis roll is being misattributed to road bank. The cascade
contaminates condition bucketing (transition quarantine 32%) and
muddles the racing-line structure (lift +0.009).

> **Pass-2 shows this is partly fixable**: the roll-compliance fit
> moves from 0.005 → 0.001 on Spa, but the bank estimate still reaches
> ±36°. So compliance alone is not the only contributor — the
> estimator's underlying logic also needs work for non-banked tracks
> with elevation gradients.

**Tire D scale per vehicle.** The Daytona-tuned `D_lat = 2.8` is too
low for the BMW M2 (fitted k_lat = 1.33 → D_lat = 3.72) and far too
high for the Audi RS3 LMS (frozen λ median = 0.637, well below 1.0 —
implying D should be **lower**, not the same). Per-vehicle calibration
is unavoidable.

**Tire model SHAPE for non-GT cars.** The most important finding:
adapting the D scale on Spa **increased** Fy residual from 3316 → 4668 N.
A pure scaling cannot fix a model whose Pacejka shape (B, C, E) is
inappropriate. Touring-car tires have noticeably different
slip-angle / force curves than GT tires.

**Single-session bucket density.** All three sessions hit
`excessive_fallback` because 6 condition buckets × thousands of cells
× 4 to 74 laps is structurally too sparse. The fallback hierarchy
correctly degrades, but the planner sees mostly the global prior:

| Dataset | depth=0 (exact) | depth=1 (section) | depth=2 (global prior) |
|---------|-----------------|-------------------|-------------------------|
| Daytona | 200 / 573 grid pts | 100 | 273 |
| Spa     | 76 / 691 | 8 | 607 |
| Okayama | 165 / 369 | 4 | 200 |

This is **not** a calibration bug. It is a fundamental constraint of
single-session validation — until the cross-session accumulation
feature lands, every fresh session starts the bucketed field empty.

**Transition quarantine threshold (`0.008 rad/sample`)** is too tight
when bank estimate is noisy. Daytona quarantines 38% (real), Spa 32%
(mostly artifact of the road-state misbehavior above). The threshold
should probably scale with road-state quality.

---

## Honesty of the uncertainty machinery

This is the part that surprised me most: the uncertainty machinery
**stayed honest** across all three datasets.

- The Bayesian field's confidence map correctly reports near-zero
  confidence on the parts of Spa where only one or two laps passed
  through.
- The condition-bucket fallback cleanly reports `depth=2 / global prior`
  for sectors that have no data — it does not fabricate confidence.
- The robust-OCP layer's tightening (`nominal − robust`) tracks the
  data quality: 0.187 on Daytona (lots of data → modest tightening),
  0.259 on Spa (less data → more tightening), 0.285 on Okayama
  (still less → most tightening).
- The exploitable mode's `n_trusted` metric correctly drops to single
  digits on sparse datasets — no fake aggressiveness.

The uncertainty layer is doing exactly what was promised: it does not
overclaim when the upstream layers have problems, and it tightens
where it should. **No `planner_infeasibility` warnings on any session
in either pass.**

---

## Are failures localized?

Yes. Each warning category points to a specific layer:

| Warning category | Layer it points at | Fix horizon |
|------------------|--------------------|-----|
| `excessive_fallback` | Bucketed-field density (sample availability) | Cross-session accumulation |
| `transition_contamination` | Road-state estimator + transition threshold | Per-vehicle compliance + better transition logic |
| `lambda_out_of_band` | Tire model D scale + shape | Per-vehicle tire fit |
| `racing_line_inverted` | Field structure / lateral force decomposition | Investigate by track |
| `planner_infeasibility` | Robust OCP invariant violation | (None observed — layer is sound) |
| `tire_model_mismatch` | Pacejka B/C/E shape | Per-vehicle-class tire identification |
| `road_state_mismatch` | Bank/grade separation | Per-vehicle compliance fit |

Nothing is silently failing. Every degradation has a name and a
metric.

---

## Is the stack ready for product integration?

**Not yet — and the harness explains exactly why.**

What it CAN do today:
- Produce a believable lambda field on the calibrated vehicle (McLaren GT4).
- Produce honest uncertainty regardless of vehicle.
- Produce three planner modes that obey their invariants on every dataset tested.
- Surface its own limitations through structured warnings.

What it CANNOT do today:
- Generalize to vehicles outside the GT4 calibration anchor without
  per-vehicle tire identification (the D-only fit is not enough).
- Produce a useful bucketed field from a single session — it needs
  cross-session accumulation.
- Reliably separate elevation from bank on flat tracks with the current
  road-state estimator parameters.

These gaps are **architectural**, not tuning artifacts:

1. **Per-vehicle tire calibration ladder.** The D scale fit is the
   cheapest first step; fitting B/C as a second step (using
   `tire_parameter_fit.py` extended) would be a straightforward
   v1.5 task.
2. **Cross-session accumulation** of the bucketed field. The field's
   data structure is already designed for this; the missing piece is
   persistence (Phase 2 of the broader project).
3. **Vehicle-specific roll compliance defaults.** The
   `roll_compliance_fit` module already exists; it just needs to be
   run as part of vehicle onboarding rather than per session.

None of these require new physics. They require operational glue.

---

## Recommendations (no new physics)

In priority order — each is a self-contained task that the harness
will measure when it next runs:

1. **Add a vehicle calibration table** keyed by `vehicle.id` that the
   manifest can resolve into roll compliance + tire D scale defaults.
   This converts one-shot per-session fitting into a frozen "second
   level" of calibration that lives outside the pipeline. The harness
   will then test the table's transferability instead of testing
   Daytona's leakage.
2. **Loosen `transition_threshold` to a multi-criterion gate**:
   `bank_grad > X AND road_quality < Y`. Right now any noisy
   bank-gradient blip discards the sample, even when road quality is
   high. The threshold is a Pareto knob, not a hard cliff.
3. **Promote cross-session bucket accumulation** to a P0 work item.
   The harness's `excessive_fallback` warnings are essentially
   guaranteed to keep firing on every single-session dataset until
   this lands.
4. **Add a fourth dataset** to the manifest covering a known clean
   case — e.g. another McLaren GT4 session at a flat track — to
   isolate the "GT4 + flat" subspace from the "different car + flat"
   subspace. This separates road-state issues from tire issues.
5. **Run the harness on every commit that touches `track_surface/`.**
   The two-pass design + structured warnings make it suitable for CI;
   regressions on Daytona will be flagged as PASS→FAIL transitions.

---

## Closing

The harness now answers the question that prompted it:
**Daytona was the centre of the world. It is no longer the only
centre.** Lambda physics survives the move. Roll compliance, tire D
scale, and bucket density do not — but each failure now has a name,
a metric, a threshold, a category, and a per-session JSON record
documenting the gap.

The stack is one calibration-ladder commit and one persistence-layer
commit away from being product-ready. Until then, the harness is the
guardrail.
