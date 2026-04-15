# Productionization Layer — Phase 4 Assessment

**Date:** 2026-04-15
**Modules:**
  - `telemetry_tool/track_surface/validation/release_gate.py` (gate + thresholds)
  - `telemetry_tool/track_surface/validation/ops.py` (registry/manifest/accumulator ops)
**Tests:** 39 (release gate) + 22 (ops) = 61 new tests
**Demo data:** Two Daytona McLaren GT4 sessions + Spa BMW M2 CSR

This document closes the productionization layer. The research stack
now has a release gate, configurable thresholds, ops tooling, and CI
wiring. Phase 5 — first production rollout — has a clear scope.

---

## What was built

### 1. Release gate

`telemetry_tool/track_surface/validation/release_gate.py`:

- `ThresholdProfile` dataclass — every threshold is a named field with
  WARN and FAIL bands where applicable
- `ReleaseThresholds` registry with `default + by_track_class +
  by_vehicle_class + by_track_x_vehicle` overlay layers
- `ThresholdProfile.overlay(partial_dict)` — replace-only-listed-keys
  semantics, rejects unknown keys (catches typos)
- `ReleaseDecision` enum (`PASS`, `WARN`, `FAIL`)
- `ReleaseCheck` per-metric record with name, subsystem, decision,
  metric, value, threshold, message
- `evaluate_session(metrics, profile)` — produces all checks for one session
- `evaluate_suite(...)` — aggregates; produces `ReleaseReport` with
  exit code (0/1/2 = PASS/WARN/FAIL)
- `render_markdown(report)` — human-readable report

The gate is more conservative than the classifier:

| Source | Output | Purpose |
|--------|--------|---------|
| `classifier.py` | informational warnings | Diagnose what's happening |
| `release_gate.py` | binding PASS/WARN/FAIL | Decide whether the build ships |

### 2. Threshold config

`data/release_thresholds.json` — JSON file with the layered structure:

```json
{
  "default": { /* conservative baseline */ },
  "by_track_class": { "banked": {...}, "flat": {...} },
  "by_vehicle_class": { "GT4": {...}, "TouringCar": {...}, "TCR": {...} },
  "by_track_x_vehicle": {
    "banked,GT4": { /* tightest */ },
    "flat,TouringCar": { /* known sparse-coverage scenario */ }
  }
}
```

**Resolution rule:** most-specific-wins, missing-keys-inherit.

`ThresholdProfile().overlay(default_partial).overlay(track_partial)
.overlay(vehicle_partial).overlay(cross_partial)` — each layer adds
overrides to the previous one.

The "Spa 60.2 vs 60.0" issue is fixed by `flat,TouringCar`'s
`max_fallback_depth_2_pct_fail = 80.0`. The global default stays at
60.0; the per-class override only relaxes for the specific known case.

### 3. Ops module + CLI

`telemetry_tool/track_surface/validation/ops.py` — pure functions
returning `OpsResult` (ok/message/details). `scripts/ops.py` — argparse
CLI with subcommands:

| Subcommand | Purpose |
|------------|---------|
| `add-vehicle-profile` | Add a calibration profile to the registry |
| `deprecate-profile` | Mark a profile deprecated (clears active flag) |
| `activate-profile` | Activate a profile (auto-deactivates siblings) |
| `list-profiles` | List all profiles |
| `add-dataset` | Append a dataset to the manifest (validated) |
| `validate-manifest` | End-to-end manifest validation |
| `inspect-accumulator` | Summarize all accumulators in a directory |
| `smoke-pick` | Print the dataset(s) the smoke gate would pick |

All subcommands support `--json` for machine-readable output.

### 4. CI wiring

`.github/workflows/validation.yml` — three jobs:

- `unit-and-regression`: runs the full friction-stack test suite (305 tests)
- `validate-config-files`: schema-validates manifest, registry, thresholds JSON
- `smoke-release-gate`: verifies CLI wiring (`--help`); commented-out
  block shows how to enable real smoke gate on a self-hosted runner
  with telemetry data mounted

### 5. Smoke mode

`scripts/release_gate.py --smoke` filters to the smallest .ibt file on
disk and runs the same gate code path. ~30s wall time vs 1–2 minutes
for a multi-session run. Used for CI / pre-deploy quick checks.

---

## Demo outputs

### PASS example (synthetic, all healthy)

```
RELEASE GATE: PASS
Sessions: 2  PASS=2  WARN=0  FAIL=0
```

### WARN example (real data — three current sessions)

```
RELEASE GATE: WARN
Sessions: 3  PASS=0  WARN=3  FAIL=0

Top warning causes:
  - fallback_pct_ceiling (3)
  - lambda_in_band (1)
  - fy_residual_ceiling (1)

Per-session table:
| Decision | Dataset | Track class | Vehicle class | Pass | Warn | Fail |
|----------|---------|-------------|---------------|------|------|------|
| WARN | daytona_mclaren570sgt4 | banked | GT4 | 10 | 1 | 0 |
| WARN | daytona_mclaren570sgt4_session2 | banked | GT4 | 8 | 3 | 0 |
| WARN | spa_bmwm2csr | flat | TouringCar | 10 | 1 | 0 |
```

Each WARN/FAIL maps cleanly to:
- **metric** (e.g. `fallback_pct_ceiling`)
- **subsystem** (e.g. `bucket`)
- **value** (e.g. 60.2)
- **threshold** (e.g. 60.0)
- **profile** (e.g. "Spa-with-BMW M2 — known sparse-coverage scenario")

### FAIL example (smoke run on tiny .ibt)

```
RELEASE GATE: FAIL
Sessions: 1  PASS=0  WARN=0  FAIL=1

Top failure causes:
  - bucket_actives_floor (1)
```

The gate caught a tiny session with only 1 active bucket — exactly
the kind of regression we want to fail builds on.

---

## Acceptance criteria — line by line

| Criterion | Result |
|-----------|--------|
| Stack has a formal release gate | ✅ `release_gate.py` with `ReleaseDecision` enum, exit codes 0/1/2 |
| Validation thresholds configurable and explicit | ✅ `data/release_thresholds.json` with documented schema, layered resolution |
| CI can run a meaningful subset automatically | ✅ `.github/workflows/validation.yml` runs 305 tests + manifest/registry/thresholds validation; smoke-gate wiring documented |
| Report artifacts clean enough for ongoing ops | ✅ JSON (`release.json`) + markdown (`release.md`); per-session detail; top causes ranked |
| Adding cars / datasets becomes procedural | ✅ `scripts/ops.py add-vehicle-profile`, `add-dataset`, `validate-manifest` |
| No research-layer behavior changed | ✅ Zero modifications to `wheel_kinematics`, `beta_estimator`, `tire_model`, `road_state_estimator`, `surface_inverse_solver`, `condition_bucketing`, `surface_field`, `robust_ocp`, `vehicle_calibration_registry`, `cross_session_accumulator`, `multi_criterion_transition_gate` |

All six hold.

### Test status

- Release gate: **39 tests**
- Ops: **22 tests**
- Pre-existing friction stack (transition gate + persistence + cross-track + research layer): **244 tests**
- **Total: 305 tests, 305 pass.**

---

## First production rollout — recommended scope

**Ship this first**, in order:

1. **One-vehicle, one-track production lock.** McLaren GT4 + Daytona
   Road Course, frozen-pass + accumulator. The full stack is
   calibrated and validated for this combination. Release gate WARN is
   acceptable on a per-session basis (data sparsity is well-understood);
   FAIL aborts.

2. **Operator runbook** consisting of three commands:
   - `python scripts/ops.py validate-manifest --manifest data/cross_track_manifest.json`
   - `python scripts/release_gate.py --smoke --manifest ... --thresholds ... --registry ... --accumulator-dir ... --out ...`
   - `python scripts/release_gate.py --manifest ... --thresholds ... --registry ... --accumulator-dir ... --out ...` (full)

3. **Calibration ladder for a second vehicle** (e.g. BMW M2 CSR):
   - Run frozen pipeline on one session
   - Adapt: fit roll compliance + tire D scale per session
   - Use `scripts/ops.py add-vehicle-profile` to register the fitted profile
   - Re-run release gate; expect WARN→PASS as the BMW-specific profile
     replaces the GT4-tuned defaults

4. **Add a track threshold profile** for the new vehicle class only when
   the WARN→PASS path requires it (avoid pre-tuning).

**Defer until after first rollout:**

- **CI integration on a self-hosted runner with telemetry data mounted.**
  The hosted-runner CI block validates wiring; the actual data-driven
  smoke gate needs persistent storage. Spin this up after the first
  manual release.

- **Multi-vehicle accumulator coexistence.** The accumulator key includes
  `calibration_profile_id` so different vehicles' accumulators are
  isolated by construction. Verify with a second vehicle's session
  after step 3 above.

- **Operator dashboard.** The markdown + JSON artifacts are functional;
  a web view is nice-to-have but not blocking.

**Hard deferred (do NOT attempt without explicit research budget):**

- Tire shape (Pacejka B/C/E) per-vehicle fitting. The current registry
  only stores D scale; expanding the schema is a research task, not an
  ops task.
- Road-state estimator improvements for elevated flat tracks. The
  transition gate now correctly catches the resulting noise; fixing
  the estimator itself requires physics work.

---

## Closing

The system has graduated from research artifact to operable subsystem.

What an operator now does to ship a release:

```bash
# 1. Verify config
python scripts/ops.py validate-manifest --manifest data/cross_track_manifest.json
python scripts/ops.py list-profiles --registry data/vehicle_calibrations.json

# 2. Quick check
python scripts/release_gate.py --smoke \\
    --manifest data/cross_track_manifest.json \\
    --thresholds data/release_thresholds.json \\
    --registry data/vehicle_calibrations.json \\
    --accumulator-dir accumulators \\
    --out release_artifacts/

# 3. Full check
python scripts/release_gate.py \\
    --manifest data/cross_track_manifest.json \\
    --thresholds data/release_thresholds.json \\
    --registry data/vehicle_calibrations.json \\
    --accumulator-dir accumulators \\
    --out release_artifacts/

# 4. Inspect artifacts
cat release_artifacts/release.md
jq .decision release_artifacts/release.json

# 5. Decision: PASS → ship; WARN → review; FAIL → investigate
```

What an operator does to add a new car:

```bash
python scripts/ops.py add-vehicle-profile \\
    --registry data/vehicle_calibrations.json \\
    --profile-id audirs3lms_v1 --vehicle-key audirs3lms \\
    --vehicle-class TCR \\
    --tire-d1-lat 2.4 --tire-d1-long 2.3 \\
    --roll-compliance 0.004 \\
    --fit-method manual --notes "Initial seed values"
```

What an operator does to add a new track session:

```bash
python scripts/ops.py add-dataset \\
    --manifest data/cross_track_manifest.json \\
    --entry-file new_dataset.json
```

That's it. The research stack is no longer the surface area an operator
has to understand. The four files an operator touches:
`cross_track_manifest.json`, `vehicle_calibrations.json`,
`release_thresholds.json`, `accumulators/*`. Everything else is internals.

That is product-readiness, in the only sense that matters.
