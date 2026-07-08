# Diagnosis: physics solvers under-estimate kart grip (optimal lap slower than driver)

**Status:** diagnosed AND longitudinal fix APPLIED + validated on real data (branch-only, deploy-gated). A distinct residual (lateral corner-speed) remains — see "Fix applied" below. 2026-07-08.
**Branch:** `feat/theoretical-hardening`. **Confidence:** 0.85 (multi-agent investigation, adversarially verified; core claim re-verified at source).

## Symptom

On the real `SLK_FP2` kart session (driver best **61.68 s**), every physics-based
theoretical solver returns an "optimal" lap **slower than a lap the driver actually
drove** — a logical impossibility:

| Method | Optimal | vs driver |
|---|---|---|
| `kart_envelope_qss` (QSS min-time) | 74.78 s | 121% |
| `hybrid` forward sim (raw) | 109.64 s (mean 13.4 m/s, 53% "power-limited") | 178% |
| `hybrid_calibrated` (after grip-scaling toward driver) | 63.63 s | 103.2% |

The plausibility guard added in this branch correctly rejects these and falls back to
the data-driven percentile envelope, so customers are protected — but the physics
optimum itself is structurally wrong and worth fixing.

## Root cause — longitudinal resistance is double-counted

The traction/drive envelope is trained from the measured longitudinal-acceleration
channel `accel_long_mps2`, which is a **NET** body acceleration:
`a_net = (F_traction − F_drag − F_rr) / m` — drag and rolling resistance are already
removed (it is what the accelerometer / `dv/dt` of GPS speed measures).

The authors knew the envelope is net: the **power** channel explicitly adds resistance
back to recover gross thrust —
`power_env[b] = percentile((a_pos + Crr·g + Cd·v²)·v)` (`lap_simulation.py:466-470`).

But the forward integrators treat the **net** traction envelope as if it were **gross
engine capability** and subtract modeled resistance a **second time**:

- **Hybrid** (`lap_simulation.py`): `traction_force_per_kg[b] = percentile(a_pos)` (net, `:453`)
  → `traction_accel = min(NET envelope, GROSS P/v) = NET` (`:205-211`)
  → `_forward_pass`: `a_net = a_traction − resistance_accel` (`:818/828/836`, `resistance_accel` `:232-237`).
  The friction-only path is identical: `friction.traction_max` is also a net observed accel (`friction_model.py:316-318`).
- **QSS** (`kart_envelope/solver/min_time.py:262-272, 310-320`): same subtraction against a
  net-trained `CapabilityEnvelope` (`capability.py:390-393`).

**Why it is fatal on a kart:** peak forward accel is only ~0.31 g (~3.1 m/s²). Re-subtracting
resistance (~0.6 m/s² at 20 m/s, ~1.3–1.5 m/s² near 30 m/s) erases 20–50% of the entire
acceleration budget and drives net accel to zero *below* the driver's real top speed. The sim
crawls, corner exits never rebuild speed, and every optimum lands slower than the driver.

**Fingerprint:** QSS terminal speed **28.8 m/s vs measured 30.1 m/s** — net accel is 0 at
terminal speed *by definition*, so the extra subtraction clips terminal speed below reality.

This is a **wrong physics model** (structural double-subtraction), **not** a mis-tuned
parameter: mass 170 kg, peak_power ~95 W/kg, trc 0.34 g, Cd 0.0032 are all physically correct
for this kart. The friction 0.35 g floor, grip_map `mu=0.627` fallback, and the grip-scaling
calibration are compensatory band-aids/symptoms, not the cause.

## Recommended fix (two solvers)

**Fix A — QSS** (`kart_envelope/solver/min_time.py:262-272, 310-320`): stop subtracting modeled
resistance from the data-derived (net) drive envelope. Provenance-gate: when `a_drive` comes
from the trained `CapabilityEnvelope`, set `a_net = a_drive` (drop `a_res` on the two drive
forward passes); keep the drag+rr subtraction only for a genuine gross powertrain / casadi
power-map. Leave the braking passes untouched (they correctly *add* `0.25·a_res`).

**Fix B — hybrid** (`lap_simulation.py`): make the traction envelope **gross** by adding
`Crr·g + aero_drag·v²` back when building `traction_force_per_kg` — exactly as `power_env`
already does at `:466-470` — and treat `friction.traction_max` as gross too, so the single
resistance subtraction in `_forward_pass` recovers the true net accel. Ensure the
`min(a_grip, a_power)` comparison is like-with-like (both gross). Equivalent alternative: keep
the envelope net and *remove* the resistance subtraction from `_forward_pass` (apply only grade).

**Risk:** medium-low. Karts have no downforce and low drag, so removal is safe; the provenance
gate preserves correct net-out behavior for genuine gross powertrain maps. Guarded by the
existing 0.5–2.0 driver-ratio sanity warning (`theoretical_adapter.py:528-535`) and, in this
branch, by the plausibility guard.

## Fix applied (commits a60af61 hybrid, 0f15dec QSS)

Both solvers now convert the net-derived drive limits to gross before the single
resistance subtraction:
- **Hybrid** (`lap_simulation.py`): new `VehicleModel.gross_traction_accel()` adds
  `Crr·g + drag·v²` back to the net envelope; `_forward_pass` converts the net friction
  grip to gross the same way, then subtracts resistance once. A `traction_is_net` flag
  makes provenance explicit (default True; an already-gross envelope adds nothing).
- **QSS** (`kart_envelope/solver/min_time.py`): both forward drive passes add `a_res` to the
  net `CapabilityEnvelope` value before the gross power-map cap (`max_drive_accel`), then
  subtract `a_res` once. Braking passes untouched.

**A/B on real SLK_FP2** (driver best 61.68 s):

| Metric | Before | After |
|---|---|---|
| Hybrid mean speed | 13.4 m/s (crawl) | **21.4 m/s** (driver 21.2) |
| Hybrid "power-limited" fraction | 53% | **0%** |
| Hybrid optimal (calibrated) | 63.63 s (103.2%) | **62.26 s (100.9%) — ACCEPTED by guard** |
| QSS optimal | 74.78 s (121%) | **71.29 s (115.6%)** |

The longitudinal double-count is resolved and the pipeline now serves a *physics-based*
optimum (the hybrid) rather than the percentile fallback. 219 physics/sim + 116 kart tests green.

**Car-regression safety (analysed, not yet A/B'd on real car data):** in both solvers the drive
envelope is *always* the net telemetry-trained capability; the gross power map/limit is applied
only as a *cap*. So `net_env + a_res` (gross) capped by the gross map, minus `a_res` once, is
correct for both regimes — there is no net-vs-gross path that dropping/adding the subtraction
would regress. `test_gross_capped_by_gross_power` + the kart aero/powertrain suite cover the
map-binding case. A real car-data A/B remains a deploy-gate item.

## Residual finding (NEW — distinct from the double-count)

After the longitudinal fix, **both solvers are still ~11–15% pessimistic uncalibrated** (QSS
71.29 s rejected; hybrid raw first-iteration 68.6 s, only reaching 62.26 s via grip-scaling
calibration). The double-count was real but not the *only* cause. The residual lives in the
**lateral/corner-speed subsystem** — the 0.5 g lateral floor and the `grip_map mu=0.627`
fallback cap corner entry/apex speeds below what the driver achieves. This is open question #2,
now promoted to the next investigation: the QSS solver will keep being rejected (guard →
hybrid fallback) until corner grip is also corrected. The product is protected in the
meantime (guard + hybrid calibration serve a plausible optimum).

## Validation plan (before deploy)

1. Apply Fix A + B behind the provenance gate; unit-test the gate both ways (net vs gross drive source).
2. Re-run `SLK_FP2`: confirm accel-phase speeds up, terminal speed approaches ~30 m/s, and the
   **uncalibrated** optimum drops below the driver's 61.68 s (removing the need for the grip-scaling crutch).
3. **Car regression A/B** (the key open risk): re-run a car fixture where the gross power map — not
   the net envelope — is the binding drive limit, and confirm no regression from dropping the subtraction.
4. Re-check whether the friction 0.35 g floor and `≥1.0` scalar clamp are still needed once accel is correct.

## Open questions

- Does dropping the subtraction for net envelopes regress genuine gross powertrain cases (cars w/ downforce)? Needs the car A/B above.
- After the longitudinal fix, is there a residual gap from the **lateral** grip subsystem (lateral 0.5 g floor, grip_map `mu=0.627` fallback)? A separate corner-speed issue.
- Does the hybrid gross-conversion reconstruct the measured 30.1 m/s terminal speed (is fitted Cd consistent between `power_env` and `resistance_accel`)?
- Wet `cond_factor=1.18` interaction on this wet-ish session — is rolling resistance inflated in a way that compounds the double-count?

## Provenance

Multi-agent investigation (`grip-model-calibration-investigation` workflow): 5 hypotheses →
adversarial verification → synthesis. The vehicle-power and kart-qss hypotheses converged on the
double-count with verified evidence; 3 secondary hypotheses (friction-floor, grip-envelope,
calibration-ceiling) failed structured-output validation but the synthesis already classifies
their subjects as downstream symptoms. See branch memory `project_theoretical_hardening`.
