# Track Surface Friction Stack — v1

Measures per-`(s, n)` friction coefficient on a track from telemetry,
accumulates evidence across sessions, and feeds three planner modes
(nominal / robust / exploitable) with honest uncertainty.

**Validated narrow-scope production candidate:**
McLaren GT4 on Daytona Road Course, frozen-parameter transfer plus
cross-session accumulation. Other (vehicle × track) combinations ship
as WARN — the release gate surfaces the exact gap.

---

## Module map

### Physics (frozen — do not modify without a research budget)

| File | Role |
|------|------|
| `wheel_kinematics/` | slip-angle geometry per wheel |
| `beta_estimator.py` | sideslip / lateral-velocity estimator |
| `tire_model.py` | Pacejka-style tire force prediction |
| `tire_parameter_fit.py` | one-axis lateral D-scale fit on curated samples |
| `road_state_estimator.py` | bank / grade / tire-only `a_lat` / `a_long` |
| `roll_compliance_fit.py` | one-parameter chassis roll compliance fit |
| `surface_inverse_solver.py` | excitation-gated λ recovery (F_obs / F_pred) |
| `condition_bucketing.py` | regime × stint-phase bucket manager |
| `surface_field.py` | 2D Bayesian λ field (per-cell Kalman + smoothing) |
| `robust_ocp.py` | nominal / robust / exploitable grip policy |

### Infrastructure (this milestone)

| File | Role |
|------|------|
| `multi_criterion_transition_gate.py` | 7-criterion hysteresis-aware quarantine with reason codes |
| `vehicle_calibration_registry.py` | per-vehicle fitted-parameter store (JSON, versioned, active/deprecated) |
| `cross_session_accumulator.py` | per-`(track, profile)` persistent evidence merger + layered query |
| `validation/manifest.py` | dataset manifest schema + loader |
| `validation/harness.py` | end-to-end pipeline runner (one session → structured result) |
| `validation/metrics.py` | `SessionMetrics` computed from `PipelineResult` |
| `validation/classifier.py` | informational warning categorization |
| `validation/suite.py` | multi-session orchestrator (frozen + optional adaptive pass) |
| `validation/reporter.py` | JSON + markdown artifacts |
| `validation/release_gate.py` | binding PASS/WARN/FAIL decision with per-class thresholds |
| `validation/ops.py` | procedural tools for registry / manifest / accumulator |

---

## Data flow

```
.ibt
 │
 ├─► extract_channels ─► road_state ─► roll/pitch compliance
 │                         │
 │                         ├─► transition_gate ─┐
 │                         │   (7 criteria +    │
 │                         │    hysteresis +    │
 │                         │    reason codes)   │
 │                         │                    ▼
 │                         ▼              accept_mask
 │                   tire_model ── solve_lambda ──► λ per sample
 │                                                  │
 │                                                  ▼
 │                                        bucketed surface field
 │                                                  │
 │                                                  ├──► accumulator (persist)
 │                                                  │      ↑
 │              calibration_registry ───► resolve ──┘      │
 │                                                  │     merge guards
 │                                                  ▼      │
 │                                        layered_query ◄──┘
 │                                                  │
 │                                                  ▼
 │                                        robust_ocp (nominal/robust/exploitable)
 │                                                  │
 │                                                  ▼
 │                                        validation metrics
 │                                                  │
 │                                                  ▼
 └─► release_gate ─► thresholds (per track × vehicle class) ─► PASS/WARN/FAIL
```

---

## Operator quickstart

Four files are your surface area. Everything else is internals.

| You touch | What it controls |
|-----------|------------------|
| `data/cross_track_manifest.json` | Which sessions the harness runs |
| `data/vehicle_calibrations.json` | Per-vehicle fitted parameters |
| `data/release_thresholds.json` | Per-class PASS/WARN/FAIL bands |
| `accumulators/*` | Persistent evidence (managed by the harness) |

Three commands cover the common ops loop:

```bash
# Validate config files
python scripts/ops.py validate-manifest --manifest data/cross_track_manifest.json
python scripts/ops.py list-profiles --registry data/vehicle_calibrations.json

# Smoke check (runs smallest dataset, ~30s)
python scripts/release_gate.py --smoke \
    --manifest data/cross_track_manifest.json \
    --thresholds data/release_thresholds.json \
    --registry data/vehicle_calibrations.json \
    --accumulator-dir accumulators \
    --out release_artifacts/

# Full release check
python scripts/release_gate.py \
    --manifest data/cross_track_manifest.json \
    --thresholds data/release_thresholds.json \
    --registry data/vehicle_calibrations.json \
    --accumulator-dir accumulators \
    --out release_artifacts/
```

Exit codes: `0=PASS`, `1=WARN`, `2=FAIL`. Artifacts: `release.json` +
`release.md` + per-session drill-downs under `validation_run/`.

### Adding a new vehicle profile

```bash
python scripts/ops.py add-vehicle-profile \
    --registry data/vehicle_calibrations.json \
    --profile-id audirs3lms_v1 --vehicle-key audirs3lms \
    --vehicle-class TCR \
    --tire-d1-lat 2.4 --tire-d1-long 2.3 \
    --roll-compliance 0.004 \
    --fit-method manual --notes "Initial seed values"
```

### Adding a new dataset

```bash
python scripts/ops.py add-dataset \
    --manifest data/cross_track_manifest.json \
    --entry-file new_dataset.json
```

---

## Key invariants

- **Planner:** `robust_mean_μ ≤ nominal_mean_μ` AND
  `exploitable_mean_μ ≤ nominal_mean_μ` — asserted per session;
  hard FAIL (no threshold override).
- **Accumulator:** sessions with different `(track_fingerprint,
  calibration_profile_id)` never merge. Per-bucket divergence rejection
  prevents one-bad-session contamination.
- **Transition:** `TRANSITION_BUCKET` never accumulates. The gate's
  reject-mask feeds bucketing *and* accumulator input-filtering.
- **Layered query:** current-session evidence wins when strong
  (confidence ≥ 0.20); accumulator fills the gaps otherwise. Layered
  query NEVER returns deeper fallback than a direct current-only query
  — accumulation *augments*, never *erases*.
- **Registry:** single-active-profile-per-vehicle invariant enforced
  by `upsert`. Default fallback is explicit (`resolve().source` tells
  you what was used).

---

## Tests

305 tests in `telemetry_tool/tests/test_*.py`:

| File | Count | Covers |
|------|-------|--------|
| `test_release_gate.py` | 39 | threshold overlay, class resolution, per-session evaluation, suite aggregation, markdown, JSON round-trip |
| `test_ops.py` | 22 | registry add / deprecate / activate / list, manifest validation + add-dataset, accumulator inspection, smoke-pick |
| `test_transition_gate.py` | 28 | features, scoring, hysteresis (entry/exit/dwell/padding), regime labels, E2E, noise robustness, config knobs |
| `test_persistence_layer.py` | 45 | registry lookup + persistence, accumulator merge guards + divergence + provenance + layered query |
| `test_cross_track_validation.py` | 46 | manifest loading, metrics, classifier, reporter, suite orchestrator, reproducibility, spec validation |
| `test_robust_ocp.py` | 21 | planner invariants across modes |
| `test_condition_bucketing.py` | 22 | regime classification, fallback hierarchy, no-contamination |
| `test_surface_field.py` + other physics | ~82 | research-layer regression |

Run everything:

```bash
python -m pytest \
    telemetry_tool/tests/test_release_gate.py \
    telemetry_tool/tests/test_ops.py \
    telemetry_tool/tests/test_transition_gate.py \
    telemetry_tool/tests/test_persistence_layer.py \
    telemetry_tool/tests/test_cross_track_validation.py \
    telemetry_tool/tests/test_robust_ocp.py \
    telemetry_tool/tests/test_condition_bucketing.py \
    telemetry_tool/tests/test_surface_field.py \
    telemetry_tool/tests/test_surface_inverse.py \
    telemetry_tool/tests/test_tire_model.py \
    telemetry_tool/tests/test_tire_parameter_fit.py \
    telemetry_tool/tests/test_roll_compliance_fit.py \
    -q
```

CI: `.github/workflows/validation.yml` runs unit + regression on PR.

---

## Reference docs

Narrative deep-dives (chronological):

- `docs/cross_track_validation_assessment.md` — Phase 1: honest cross-track transfer measurement; what generalizes vs what's track/car specific
- `docs/persistence_layer_assessment.md` — Phase 2: calibration registry + cross-session accumulator + layered query
- `docs/transition_gate_assessment.md` — Phase 3: multi-criterion transition gate with hysteresis, before/after A/B on real data
- `docs/productionization_assessment.md` — Phase 4: release gate, per-class thresholds, ops CLI, CI wiring, first-rollout scope

---

## What is NOT in v1

Hard-deferred. Each requires a research budget, not ops work:

- **Per-vehicle tire shape** (Pacejka B/C/E fits). The registry schema
  stores D-scale only. Adapting D alone is known insufficient for
  non-GT4 cars (e.g. Spa BMW M2 Fy residual *increased* after D-only
  adaptation in Phase-1 validation).
- **Road-state estimator for elevated flat tracks.** Reports false
  ±36° banking on Spa. The transition gate catches the noise; fixing
  the estimator itself is physics work.
- **kappa / wheel-speed ingestion.** Longitudinal λ is uninformed
  without slip ratio. The system correctly reports this as a WARN,
  not a FAIL.
- **Cross-vehicle accumulator coexistence** verified in tests but not
  stressed on real data. Accumulator key includes `calibration_profile_id`
  so vehicles are isolated by construction.
