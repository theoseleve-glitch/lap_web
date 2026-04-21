# W7 — Optimizer Dispatcher (trajectory-only + full-fidelity) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship an `optimizer_v2/` package that exposes a capability-driven `OptimizerDispatcher` which selects between `TrajectoryOnlyOptimizer` (real-life — GPS + accel only) and `FullFidelityOptimizer` (sim — wraps `sim_optimizer/solver/qss_enhanced.py`) and emits a uniform `OptimizerContract` with `depth`, `confidence`, and `method_notes` metadata. Existing solvers and optimizers are **wrapped, never modified**.

**Architecture:**
- Three user-facing types: `OptimizerEngine` (Protocol), `OptimizerDispatcher` (selects engine by `SessionCapabilities`), and `OptimizerContract` (from W1).
- Two concrete engines, each a thin wrapper (<100 LOC of non-translation logic — see §Wrapping-thickness rule):
  - `TrajectoryOnlyOptimizer` wraps `telemetry_tool/reference_line.py` + `telemetry_tool/raceline_optimizer.py` + `telemetry_tool/theoretical_adapter.py::compute_theoretical_via_envelope` (the existing real-life theoretical-lap path, itself ultimately backed by `kart_envelope/solver/min_time.py`).
  - `FullFidelityOptimizer` wraps `telemetry_tool/sim_optimizer/solver/qss_enhanced.py::compute_sim_theoretical_lap`.
- Dispatcher selects purely on `SessionCapabilities`. **No branching on `session.source`**; a CI check (`tests/test_optimizer_v2/test_no_source_branching.py`) greps `optimizer_v2/` for the forbidden patterns and fails the build if any match.
- Both engines and the dispatcher consume W5's shared primitives: `telemetry_tool.shared.physics.VehicleModel` for typing, `telemetry_tool.shared.physics.FrictionModel` as an optional-use protocol (see §W5 consumption).
- W4's in-pipeline `sim_optimizer/contract_adapter.py` continues to emit `OptimizerContract` directly from the live pipeline. The W7 dispatcher is the authoritative path for "re-optimize from stored session" flows and for the public API (`POST /api/v1/optimizer/run`, added in a later workstream). The two agree on the contract shape; a regression test pins the cross-path equivalence for a sim fixture.

**Tech Stack:** Python 3.x · Pydantic v2 (W1 contracts) · numpy · pandas · pytest · no new runtime deps.

**Spec reference:** `docs/superpowers/specs/2026-04-19-unified-coaching-architecture-design.md` §2, §5 W7 (T7.1–T7.6), §10 decision 2 (per-engine identity)

**Session prompt:** `c:\Users\Admin\Downloads\07-W7-plan-only.md` (authoritative — the matching `07-W7-optimizer-v2.md` launch prompt is missing from Downloads; this plan uses §5 W7 of the spec as the deep source)

**Branch:** `feat/ws-w7-optimizer-v2` — **NOT YET CREATED.** Created only after W5 merges to main and this plan is `/approve`d.

**Worktree:** `.worktrees/ws-w7-optimizer-v2` (project convention per W2/W4/W5 plans) — **NOT YET CREATED.**

---

## Plan-only session scope

Per `07-W7-plan-only.md` §3 and §Constraints: this session produces **one artifact — this plan doc**. No package directories, no branch, no worktree, no source edits.

**Hold at `/approve` after reporting:**
1. Plan doc path + one-paragraph summary
2. Existing-optimizer inventory → dispatcher-lane mapping
3. Open questions where spec §10 was ambiguous
4. Readiness gate (what must be true on `main` before implementation starts)

Implementation resumes only after both:
- **Readiness**: `[signal:W5-done]` hits `main`, equivalently `python -c "from telemetry_tool.shared.physics import FrictionModel, VehicleModel"` succeeds from a clean main checkout.
- **Human `/approve`** on this plan doc.

---

## Dependency status

| Dep | Status | Evidence |
|-----|--------|----------|
| **W1 contracts** | ✅ **On main** | `git log --oneline main` shows `2d2fea07 Merge W1 — unified Session/Coaching/Optimizer contracts (PR #65)`. `telemetry_tool/web/schemas/contracts/{capabilities.py,optimizer.py,session.py,coaching.py,common.py}` all importable from main. W1 did NOT emit `signal:W1-done` — don't grep for it. |
| **W3 real-life adapter** | ✅ **On main** | `9864e54d Merge W3 …` and `bb3192ed …[signal:W3-done]`. `telemetry_tool/pipeline/contract_adapter/optimizer.py` already emits a `TRAJECTORY_ONLY`-depth contract from the real-life pipeline summary. W7's `TrajectoryOnlyOptimizer` must supersede — not duplicate — this. See §Interaction with W3's optimizer stub. |
| **W5 shared kernels** | ❌ **NOT on main** | `feat/ws-w5-shared-kernels` exists; `[signal:W5.T5.2-done]` is on branch at `93d0833b`. `telemetry_tool/shared/physics/` does not exist on main. **Hard blocker** for Task 2 onward. Task 1 (interface) can technically be drafted without W5 but the plan assumes W5 merged before any implementation work. |
| **W4 sim adapters** | ❌ **NOT on main** | `feat/ws-w4-sim-adapters` exists. W7 does **not** depend on W4 at the type level — the FullFidelityOptimizer wraps the QSS solver directly, not the W4 pipeline-adapter. W4 and W7 can land independently; a cross-agreement test (§Integration tests) asserts they emit structurally equivalent `OptimizerContract` for a shared fixture. |
| **`feat/ocp-solver` branch** | ⚠️ **Unrelated** | Pre-existing OCP work, last commit `85abea98` predating 2026-04-19. Not a dependency. Do not conflate. |

**Readiness-gate command (executing engineer runs before Task 1):**

```bash
git fetch origin main
git log origin/main --grep "signal:W5-done" -1   # must return 1 commit
python -c "from telemetry_tool.shared.physics import FrictionModel, VehicleModel; \
           from telemetry_tool.shared.geometry import TrackGeometry, FrenetFrame; \
           print('W5 on main')"
```

If either fails, **stop and escalate** — do not polyfill missing W5 primitives inside `optimizer_v2/`.

---

## Decisions requiring `/approve` before writing code

Six items fall outside the session prompt's literal text, resolve ambiguities in spec §10, or depend on how W5 lands. Confirm each before Task 1 code starts.

### D1 — Package location: `telemetry_tool/optimizer_v2/`

Spec §5 W7 tech-stack line says `telemetry_tool/optimizer_v2/dispatcher.py`. We create a **sub-package** (not a single file) mirroring W3's `pipeline/contract_adapter/` decomposition:

```
telemetry_tool/optimizer_v2/
├── __init__.py                     # Public: OptimizerDispatcher, OptimizerEngine, dispatch()
├── _types.py                       # Internal Result adapter types
├── engine.py                       # OptimizerEngine Protocol (T7.1)
├── capabilities.py                 # MIN_CAPABILITIES sets + match helpers
├── trajectory_only.py              # TrajectoryOnlyOptimizer (T7.2)
├── full_fidelity.py                # FullFidelityOptimizer (T7.3)
├── dispatcher.py                   # OptimizerDispatcher (T7.4)
├── contract_builder.py             # Shared SimTheoreticalResult / AdapterResult → OptimizerContract helpers (T7.5)
└── errors.py                       # NoMatchingEngineError, OptimizerInputError
```

Rationale: each file < 250 LOC; splits by responsibility; matches W3/W4 pattern; lets future sim extensions (LMU, ACC per spec §10 decision 5) add `full_fidelity_lmu.py` without touching dispatcher.

### D2 — Engine selection tie-break rule

Spec §2: "selects engine based on caps". Spec §5 W7.T7.4: "Dispatcher picks engine by capabilities". Ambiguous for cases where multiple engines match (e.g. a sim session with full channels satisfies both `TrajectoryOnlyOptimizer.MIN_CAPABILITIES = {GPS, LAT_G, LON_G}` AND `FullFidelityOptimizer.MIN_CAPABILITIES = {GPS, LAT_G, LON_G, THROTTLE, BRAKE, STEER}`).

**Proposed rule** (same pattern as W2 HandlerRegistry §1.1.1): (1) filter engines whose `can_handle(caps)` returns True, (2) of those, pick the one with the highest `FIDELITY_RANK` (`FULL_FIDELITY=2`, `TRAJECTORY_ONLY=1`), (3) ties broken deterministically by class name. Raises `NoMatchingEngineError` if no engine matches.

### D3 — `TrajectoryOnlyOptimizer` wraps — which real-life optimizer surface?

The real-life theoretical lap is produced today by `telemetry_tool/theoretical_adapter.py::compute_theoretical_via_envelope(...)` (line 386), which internally calls `kart_envelope/solver/min_time.py::compute_theoretical_lap(geometry, envelope, scalars, config, ...)` and optionally the CasADi OCP backend via `kart_envelope/solver/ocp_casadi.py`. The `raceline_optimizer.py` module (gated by `enable_raceline_optimizer`, default False) produces per-corner line variants.

**Proposed wrap**: `TrajectoryOnlyOptimizer.optimize()` calls `compute_theoretical_via_envelope` for the lap profile, and OPTIONALLY invokes `raceline_optimizer.optimize_corner_lines` when `config.enable_raceline_optimizer` is True (preserve existing gate). Do not wrap `reference_line.py` — it produces the *input* to the optimizer (reference line + curvature profile) and is already consumed by the real-life pipeline. The optimizer starts from a curvature DataFrame that the caller supplies (either `summary["curvature_profile"]` from the pipeline, or rebuilt from `summary["reference_line"]` via the adapter's existing `_build_geometry_from_curvature` helper).

### D4 — `FullFidelityOptimizer` wraps — solver only, not pipeline

Session prompt: "wraps `sim_optimizer/solver/qss_enhanced.py`; do not modify solver internals".

**Proposed wrap**: `FullFidelityOptimizer.optimize()` calls `sim_optimizer.solver.qss_enhanced.compute_sim_theoretical_lap(geometry, vehicle, fuel_level_l, config)` and converts the returned `SimTheoreticalResult` to `OptimizerContract(depth=FULL_FIDELITY, ...)`. Reconstructed-input traces (`ReconstructedInputs.throttle/brake/steer`) are derived by calling `sim_optimizer.reconstruction.input_trace` when available; if the module is not importable the optimizer raises `OptimizerInputError` (since `FULL_FIDELITY` contract validator requires reconstructed_inputs).

W7 does **not** wrap `sim_optimizer.pipeline.optimize_session` — that is W4's surface. Repeat from §Architecture: W4 emits OptimizerContract from the live-pipeline run; W7 emits OptimizerContract from stored geometry + identified vehicle. Both produce contracts that match the W1 schema; a cross-path equivalence test pins that.

### D5 — W5 `FrictionModel` as an **optional** consumption point

W5 defines `FrictionModel` as a runtime-checkable Protocol with a single method: `mu(slip: np.ndarray, load_n: np.ndarray) -> np.ndarray` (see W5 plan §Task 2). This signature is sim-native — real-life sessions have no slip channel (no wheel speed sensor), so the real-life path cannot meaningfully call `mu()`.

**Proposed approach**:
- `FullFidelityOptimizer` accepts `friction: FrictionModel | None = None`. When provided, a future `full_fidelity.py::_replay_with_friction` hook uses it (not MVP — flagged for a follow-up). MVP just relies on `VehicleModel`'s built-in grip (as `qss_enhanced.py` already does).
- `TrajectoryOnlyOptimizer` does **not** take `FrictionModel`. It consumes `VehicleModel` for mass/wheelbase/cg_height (typing-level only — the kart `CapabilityEnvelope` is still the actual grip surface, passed separately). A docstring explains why: "The shared `FrictionModel` protocol assumes a slip-channel-aware friction model; real-life sessions only observe the grip envelope, not slip."

This makes W5.T5.2 a mandatory dependency (for the `VehicleModel` typing) but keeps the real-life wrapper honest about what it can't use.

### D6 — Method-notes metadata schema

`OptimizerContract.validation: dict[str, Any]` is already free-form. Session prompt §3 asks for `method_notes` inside it. **Proposed schema**:

```python
validation = {
    "method_notes": {
        "engine": "TrajectoryOnlyOptimizer" | "FullFidelityOptimizer",
        "solver_backend": "envelope_qss" | "envelope_casadi_ocp" | "sim_qss",
        "wrapper_version": "0.1.0",
        "w5_vehicle_source": "kart_envelope.CapabilityEnvelope" | "sim_optimizer.param_id.VehicleModel",
        "w5_friction_source": "none" | "sim_optimizer.param_id.Pacejka",
        "fallbacks_triggered": list[str],    # e.g. ["casadi_unavailable", "ocp_failed_fell_back_to_qss"]
    },
    "driver_best_s": float | None,
    "gap_to_theoretical_s": float | None,
    "attributed_loss_s": float,
    "unattributed_loss_s": float | None,
}
```

This keeps W3's existing `validation` shape (already in `pipeline/contract_adapter/optimizer.py`) backward-compatible and adds `method_notes` inside it. W8 can consume `method_notes.engine` to label the optimizer panel.

---

## Wrapping-thickness rule (must-have guardrail)

Per session prompt §3: "wrappers are translation layers; any wrapper > 100 lines of non-translation logic is a scope violation."

**Enforcement**:
- Each of `trajectory_only.py` and `full_fidelity.py` is inspected by `tests/test_optimizer_v2/test_wrapper_thickness.py` using Python's `ast` module.
- "Non-translation logic" = any function body whose AST contains a loop, comprehension, conditional, or arithmetic operation that is not a direct dict/attribute pass-through.
- Translation passes ≤ 100 LOC. Rejected additions must be refactored upstream (e.g. into the wrapped solver) or classed as a new engine.

A wrapper that grows beyond this is a signal that the dispatcher layer is accreting optimizer logic — the correct response is to push the logic into the concrete solver (sim_optimizer or kart_envelope) or spin off a new engine class.

---

## No source-branching guarantee (must-have guardrail)

Per session prompt §3: "plan explicitly says … CI check that greps `optimizer_v2/` for `session.source ==` or `if.*iracing`."

**Enforcement**: new test `telemetry_tool/tests/test_optimizer_v2/test_no_source_branching.py`:

```python
"""Invariant: the optimizer dispatcher must select on capabilities, not source.

If this test fails, a conditional has leaked into optimizer_v2/ that branches
on session.source, session.data_profile['source'], or a literal source string
('iracing', 'ac', 'real_life'). Refactor to use SessionCapabilities instead.
"""
from __future__ import annotations

import pathlib
import re

OPTIMIZER_V2 = pathlib.Path(__file__).resolve().parents[2] / "optimizer_v2"

FORBIDDEN_PATTERNS = [
    re.compile(r"\bsession\.source\s*=="),
    re.compile(r"\bsession\.data_profile\b.*source"),
    re.compile(r"\bprofile\.source\s*=="),
    re.compile(r"[\"']iracing[\"']"),
    re.compile(r"[\"']real_life[\"']"),
    re.compile(r"[\"']ac[\"'](?!=)"),      # exclude e.g. "ac/dc" or test literals — scoped below
    re.compile(r"if\s+.*\.source\s*in\s*\("),
]


def test_no_source_branching_in_optimizer_v2():
    offenders: list[tuple[str, int, str]] = []
    for py in OPTIMIZER_V2.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        for i, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            # Skip docstrings / comments where the literal is descriptive
            stripped = line.lstrip()
            if stripped.startswith("#") or stripped.startswith('"""'):
                continue
            for pat in FORBIDDEN_PATTERNS:
                if pat.search(line):
                    offenders.append((str(py.relative_to(OPTIMIZER_V2)), i, line.strip()))
    assert not offenders, (
        "optimizer_v2/ must select on capabilities, not source. "
        f"Forbidden branches: {offenders}"
    )
```

---

## Do-not-touch list (per session prompt §3)

These files are wrapped and never modified by this workstream. Any diff that touches them fails review.

| Path | Why off-limits |
|------|---------------|
| `telemetry_tool/sim_optimizer/solver/qss_enhanced.py` | Sim solver — wrap via `FullFidelityOptimizer`. |
| `telemetry_tool/raceline_optimizer.py` | Real-life per-corner line optimization — wrap via `TrajectoryOnlyOptimizer`. |
| `telemetry_tool/reference_line.py` | Reference-line computation — consumed as *input*, not wrapped. |
| `kart_envelope/solver/min_time.py` | Kart QSS + CasADi dispatch — reached transitively through `theoretical_adapter.compute_theoretical_via_envelope`. |
| `kart_envelope/solver/ocp_casadi.py` | Kart CasADi OCP backend — transitively reached. |
| `telemetry_tool/theoretical_adapter.py` | Bridge from RC columns → kart geometry; wrap via `TrajectoryOnlyOptimizer`. |

All changes confined to:
- `telemetry_tool/optimizer_v2/**` (new)
- `telemetry_tool/tests/test_optimizer_v2/**` (new)
- `telemetry_tool/web/routes/optimizer_v2.py` **DEFERRED** (see §Deferred to follow-up)

---

## Existing-optimizer inventory

| # | Module | Role | Inputs | Outputs | W5 primitive consumed | Dispatcher lane |
|---|--------|------|--------|---------|----------------------|-----------------|
| 1 | `telemetry_tool/sim_optimizer/solver/qss_enhanced.py` · `compute_sim_theoretical_lap(geometry, vehicle, fuel_level_l, config)` | Sim QSS forward/backward solver | `TrackGeometry`, sim `VehicleModel`, `SimOptimizerConfig` | `SimTheoreticalResult` (speed_profile_mps, distance_m, accel_profile_mps2, lap_time_s, cornering/accel/braking_limited masks, gear_profile) | **`shared.geometry.TrackGeometry`** (via W5.T5.1 relocation); **`shared.physics.VehicleModel`** base (sim's `VehicleModel` in `sim_optimizer/param_id/vehicle_model.py` becomes a subclass under W5.T5.2) | **FullFidelityOptimizer** |
| 2 | `telemetry_tool/sim_optimizer/reconstruction/input_trace.py` | Reconstructs optimal throttle/brake/steer trace from QSS result | `SimTheoreticalResult`, `VehicleModel`, `TrackGeometry` | dict with `throttle, brake, steer` arrays aligned to `distance_m` | Same W5 deps as #1 | **FullFidelityOptimizer** (populates `ReconstructedInputs`) |
| 3 | `telemetry_tool/raceline_optimizer.py` · `optimize_corner_lines(corners, ref_line, boundaries, friction_model, ...)` | Real-life per-corner line variant generator (early/neutral/late apex) + point-mass simulation | corner dicts, reference-line dict, boundary estimates, friction_model dict | `RacelineResult(corner_results, total_delta_s, n_variants_evaluated)` | Optional — uses an inline friction scalar only. No need to consume W5 primitives (friction is a single float here). | **TrajectoryOnlyOptimizer** (optional — gated by `config.enable_raceline_optimizer`, default False) |
| 4 | `telemetry_tool/reference_line.py` · `compute_reference_line`, `compute_curvature_profile`, `compute_track_width_estimate` | Aggregate multiple GPS laps → single reference line + curvature + lateral scatter | dict[lap_id → DataFrame] (resampled laps) | DataFrame with `distance_m`, `x_ref_m`, `y_ref_m`, `curvature_1pm`, `heading_rad`, `lateral_scatter_m` | None — pure numpy/pandas geometry. | **Input** (consumed by TrajectoryOnlyOptimizer, not wrapped by it) |
| 5 | `telemetry_tool/theoretical_adapter.py` · `compute_theoretical_via_envelope(...)` | Bridge RC column names → kart canonical; build `TrackGeometry` from curvature; call kart solver | pipeline DataFrame + curvature profile | `AdapterResult(theoretical_df, theoretical_result, method, corner_coaching, delta_map, session_scalars)` | After W5.T5.1, the internal `TrackGeometry` import shifts to `shared.geometry.track`. | **TrajectoryOnlyOptimizer** (primary wrap target) |
| 6 | `kart_envelope/solver/min_time.py` · `compute_theoretical_lap(geometry, envelope, scalars, config, metadata, acd_engine, ...)` | Dispatch between QSS (default) and CasADi OCP backends; warm-start CasADi from QSS | `TrackGeometry`, `CapabilityEnvelope`, `SessionScalars`, `KartEnvelopeConfig`, powertrain/aero runtimes | `TheoreticalResult` (lap_time_s, speed profile, limit masks, solver_backend, solver_diagnostics) | After W5.T5.1, imports `shared.geometry.TrackGeometry` via the deprecation shim (no code change). | **TrajectoryOnlyOptimizer** (reached via #5) |
| 7 | `kart_envelope/solver/ocp_casadi.py` · `compute_theoretical_lap_casadi(...)` | CasADi direct OCP backend (optional, requires casadi) | Same inputs as #6 plus warm-start | `TheoreticalResult` | Same as #6. | **TrajectoryOnlyOptimizer** (reached via #6) |

**Findings / surprises:**

- `telemetry_tool/reference_line/raceline_optimizer.py` (as named in the session prompt) does not exist; the actual file is `telemetry_tool/raceline_optimizer.py` (top-level module, no sub-package). Plan treats this as a prompt transcription error, not a missing file.
- `raceline_optimizer.py` is already config-gated (`enable_raceline_optimizer`) and currently **off by default**. W7 preserves that gate — it does not silently enable per-corner line optimization in production.
- `theoretical_adapter.py::compute_theoretical_via_envelope` is the real-life path's entry into `kart_envelope/solver/`. The QSS/CasADi backend choice is made inside `kart_envelope/solver/min_time.py`; the W7 wrapper only needs to call the adapter and surface `solver_backend` into `method_notes`.
- The W3 adapter at `telemetry_tool/pipeline/contract_adapter/optimizer.py` **already emits** a `TRAJECTORY_ONLY`-depth contract from `summary["delta_map"]` + `summary["corner_coaching"]`. This is not a surprise — it's the stub W7 is meant to supersede. See §Interaction with W3's optimizer stub.
- No existing file should be **deleted**. Everything is wrapped. W3's stub becomes a fallback path (invoked only when `OPTIMIZER_V2_DISPATCHER` is disabled — see §Feature flag).

---

## Interaction with W3's optimizer stub

W3 shipped `telemetry_tool/pipeline/contract_adapter/optimizer.py::build_optimizer_contract(summary)` which emits `TRAJECTORY_ONLY` depth using fields already present in the pipeline summary. W7's dispatcher is the richer authoritative path once landed.

**Integration plan** (Task 7):
- Add a feature flag `OPTIMIZER_V2_DISPATCHER` (env var, default **OFF** in Phase 1 for safety).
- In `telemetry_tool/pipeline/orchestrator.py::run_full_analysis`, after the existing contract emission, if `OPTIMIZER_V2_DISPATCHER=1` **and** capabilities satisfy `TrajectoryOnlyOptimizer`, replace the W3 stub's `OptimizerContract` with `OptimizerDispatcher.dispatch(session_ctx).optimize()`.
- W3's stub remains on disk, unmodified — it is the fallback when the flag is off or the dispatcher raises.
- Cross-path regression test: for a fixed RC CSV fixture, assert `validation.attributed_loss_s` and `theoretical_lap_time_s` agree within tolerance between the two paths.

**No source-branching**: the flag selects *which adapter emits*; the dispatcher inside still selects on capabilities only.

---

## Feature flag

| Var | Default | Purpose |
|-----|---------|---------|
| `OPTIMIZER_V2_DISPATCHER` | `"0"` | When `"1"`, the pipeline orchestrator routes OptimizerContract emission through `optimizer_v2.OptimizerDispatcher`. Keep off in Phase 1; flip to default-on in a follow-up cycle after the cross-path regression test has run clean across all fixture sessions. |

Documented in project root `CLAUDE.md` under *Environment Variables*.

---

## File manifest

### Created

```
telemetry_tool/optimizer_v2/
├── __init__.py                       # public surface
├── _types.py                         # NamedTuple OptimizerInput, OptimizerRunResult
├── engine.py                         # OptimizerEngine protocol (T7.1)
├── capabilities.py                   # MIN_CAPABILITIES constants + match helpers
├── trajectory_only.py                # TrajectoryOnlyOptimizer (T7.2)
├── full_fidelity.py                  # FullFidelityOptimizer (T7.3)
├── dispatcher.py                     # OptimizerDispatcher (T7.4)
├── contract_builder.py               # Shared result → OptimizerContract helpers (T7.5)
└── errors.py                         # NoMatchingEngineError, OptimizerInputError

telemetry_tool/tests/test_optimizer_v2/
├── __init__.py
├── conftest.py                       # fixtures: real_life_input, sim_input, stub engines
├── fixtures/
│   ├── real_life_input.json          # serialized OptimizerInput for a Monza RC session
│   ├── sim_input.json                # serialized OptimizerInput for an iRacing Monza session
│   └── expected_contracts/
│       ├── real_life.optimizer.json  # golden OptimizerContract
│       └── sim.optimizer.json
├── test_engine_protocol.py           # T7.1 — Protocol conformance
├── test_capabilities.py              # T7.1 — MIN_CAPABILITIES match logic
├── test_trajectory_only.py           # T7.2 — wrap correctness + W5 VehicleModel consumption
├── test_full_fidelity.py             # T7.3 — wrap correctness + reconstructed_inputs present
├── test_dispatcher.py                # T7.4 — tie-break rule, NoMatchingEngineError
├── test_contract_builder.py          # T7.5 — depth/confidence/method_notes emission
├── test_no_source_branching.py       # CI invariant
├── test_wrapper_thickness.py         # CI invariant
├── test_depth_monotonicity.py        # T7.6 — sim strictly more info than real-life on comparable fixture
└── test_w3_fallback_equivalence.py   # T7.6 — dispatcher result vs W3 stub regression
```

### Modified

```
telemetry_tool/pipeline/orchestrator.py    # +~15 lines — feature-flagged dispatcher wiring (Task 7)
```

### Deferred to follow-up

```
telemetry_tool/web/routes/optimizer_v2.py  # POST /api/v1/optimizer/run — re-optimize stored session
telemetry_tool/sim_optimizer/contract_adapter.py  # (W4) — post-W7 refactor to delegate to FullFidelityOptimizer
```

The follow-up refactors happen only after the cross-path regression test is green. Not in W7's scope.

---

## W5 consumption by task

Every W7 task that writes non-translation logic cites which W5 module it consumes. Plan-level summary:

| Task | W5 primitive consumed | How |
|------|----------------------|-----|
| T7.1 (interface) | `telemetry_tool.shared.physics.VehicleModel` | `OptimizerEngine.optimize(input: OptimizerInput) -> OptimizerContract` — `OptimizerInput.vehicle: VehicleModel` annotated with the shared base. |
| T7.1 (interface) | `telemetry_tool.shared.physics.FrictionModel` | `OptimizerInput.friction: FrictionModel \| None = None` — optional; sim path may use, real-life ignores. |
| T7.1 (interface) | `telemetry_tool.shared.geometry.TrackGeometry` | `OptimizerInput.geometry: TrackGeometry`. |
| T7.2 (trajectory-only) | `shared.geometry.TrackGeometry` | Passed to `theoretical_adapter.compute_theoretical_via_envelope`. |
| T7.2 (trajectory-only) | `shared.physics.VehicleModel` | Typing only — the concrete `CapabilityEnvelope` is supplied separately via `OptimizerInput.rl_envelope: CapabilityEnvelope`. |
| T7.3 (full-fidelity) | `shared.geometry.TrackGeometry` | Passed directly to `compute_sim_theoretical_lap(geometry, vehicle, ...)`. |
| T7.3 (full-fidelity) | `shared.physics.VehicleModel` | The sim `VehicleModel` subclass (from W5.T5.2's downstream sim migration) is passed as `OptimizerInput.vehicle`. |
| T7.4 (dispatcher) | `shared.physics.VehicleModel` | Type hint on dispatcher signature only. |
| T7.5 (contract builder) | `shared.coaching_taxonomy.channels.ChannelTag` (moved from W1's `web/schemas/contracts/capabilities.py` in W5.T5.3) | Capability checks use the shared `ChannelTag` symbol. |

---

## Tasks

Six implementation tasks, each ≤ ~½ day of coding once W5 is on main. TDD order: Protocol + match logic (T7.1) → each engine wrap with golden fixtures (T7.2, T7.3) → dispatcher tie-break (T7.4) → contract-builder consolidation (T7.5) → cross-path regression + depth monotonicity (T7.6) → pipeline wiring + feature flag (Task 7 — extra, not in spec but necessary for safe landing).

### Task 0: Worktree + green baseline (prerequisite)

**Files:** _none created_ — environment setup only.

- [ ] **Step 0.1: Confirm W5 is on main**

Run:
```bash
git fetch origin main
git log origin/main --grep "signal:W5-done" -1
python -c "from telemetry_tool.shared.physics import FrictionModel, VehicleModel; \
           from telemetry_tool.shared.geometry import TrackGeometry, FrenetFrame; \
           print('W5 on main')"
```

Expected: the `git log` returns exactly one commit AND the Python import succeeds. If either fails, **stop — escalate**.

- [ ] **Step 0.2: Create worktree from main**

Run:
```bash
git worktree add .worktrees/ws-w7-optimizer-v2 -b feat/ws-w7-optimizer-v2 main
cd .worktrees/ws-w7-optimizer-v2
```

- [ ] **Step 0.3: Verify green baseline**

Run: `pytest telemetry_tool/tests/ kart_envelope/tests/ -x -q`

Expected: PASS. If pre-existing failures, capture and report to user before proceeding.

---

### Task 1: `OptimizerEngine` Protocol + input types (T7.1)

Define the engine interface, the shared input tuple, capability-match helpers, and the errors. No concrete engine yet.

**Files:**
- Create: `telemetry_tool/optimizer_v2/__init__.py`
- Create: `telemetry_tool/optimizer_v2/_types.py`
- Create: `telemetry_tool/optimizer_v2/engine.py`
- Create: `telemetry_tool/optimizer_v2/capabilities.py`
- Create: `telemetry_tool/optimizer_v2/errors.py`
- Create: `telemetry_tool/tests/test_optimizer_v2/__init__.py`
- Create: `telemetry_tool/tests/test_optimizer_v2/test_engine_protocol.py`
- Create: `telemetry_tool/tests/test_optimizer_v2/test_capabilities.py`

- [ ] **Step 1.1: Write failing Protocol test**

```python
# telemetry_tool/tests/test_optimizer_v2/test_engine_protocol.py
"""OptimizerEngine is a runtime-checkable Protocol; stub engines satisfy it."""
from __future__ import annotations

import pytest

from telemetry_tool.optimizer_v2 import OptimizerEngine
from telemetry_tool.optimizer_v2.capabilities import MIN_CAPS_TRAJECTORY_ONLY
from telemetry_tool.web.schemas.contracts.capabilities import (
    ChannelTag,
    SessionCapabilities,
)


class _StubEngine:
    FIDELITY_RANK: int = 1
    MIN_CAPABILITIES = MIN_CAPS_TRAJECTORY_ONLY

    def can_handle(self, caps: SessionCapabilities) -> bool:
        return caps.has_all(self.MIN_CAPABILITIES)

    def optimize(self, inp):  # noqa: ANN001 — stub
        raise NotImplementedError


def test_stub_engine_satisfies_protocol():
    engine: OptimizerEngine = _StubEngine()
    assert isinstance(engine, OptimizerEngine)


def test_stub_engine_can_handle_requires_all_channels():
    engine = _StubEngine()
    full = SessionCapabilities(channels=frozenset({
        ChannelTag.GPS, ChannelTag.LAT_G, ChannelTag.LON_G,
    }))
    partial = SessionCapabilities(channels=frozenset({ChannelTag.GPS}))
    assert engine.can_handle(full)
    assert not engine.can_handle(partial)
```

- [ ] **Step 1.2: Run — expect ImportError**

Run: `pytest telemetry_tool/tests/test_optimizer_v2/test_engine_protocol.py -v`

Expected: `ImportError: cannot import name 'OptimizerEngine' from 'telemetry_tool.optimizer_v2'`.

- [ ] **Step 1.3: Implement Protocol + errors**

```python
# telemetry_tool/optimizer_v2/errors.py
"""Dispatcher + engine errors."""
from __future__ import annotations


class NoMatchingEngineError(RuntimeError):
    """Raised when no registered engine can handle the supplied capabilities."""


class OptimizerInputError(ValueError):
    """Raised when a required input (vehicle, geometry, friction) is missing
    for the engine's fidelity level."""
```

```python
# telemetry_tool/optimizer_v2/_types.py
"""Internal input/output shapes for optimizer_v2 engines."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from telemetry_tool.shared.geometry import TrackGeometry
from telemetry_tool.shared.physics import FrictionModel, VehicleModel
from telemetry_tool.web.schemas.contracts.capabilities import SessionCapabilities


@dataclass(frozen=True)
class OptimizerInput:
    """Bundle of inputs an OptimizerEngine needs to produce a contract.

    Real-life callers fill: geometry, vehicle (shared typing), rl_envelope, session_summary.
    Sim callers fill:     geometry, vehicle (sim subclass), friction (optional), session_summary.
    """
    capabilities: SessionCapabilities
    geometry: TrackGeometry
    vehicle: VehicleModel
    session_summary: dict[str, Any]            # pipeline summary dict (real-life) or sim result dict
    friction: Optional[FrictionModel] = None
    rl_envelope: Any = None                    # CapabilityEnvelope for real-life; None for sim
    config: dict[str, Any] = field(default_factory=dict)
```

```python
# telemetry_tool/optimizer_v2/engine.py
"""OptimizerEngine Protocol — the contract every engine in optimizer_v2 satisfies."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from telemetry_tool.web.schemas.contracts import OptimizerContract
from telemetry_tool.web.schemas.contracts.capabilities import (
    ChannelTag,
    SessionCapabilities,
)

from ._types import OptimizerInput


@runtime_checkable
class OptimizerEngine(Protocol):
    """Capability-driven optimizer engine.

    Each engine declares the minimal channel set it needs via MIN_CAPABILITIES
    and a FIDELITY_RANK used by the dispatcher to break ties (higher wins).
    """

    MIN_CAPABILITIES: frozenset[ChannelTag]
    FIDELITY_RANK: int

    def can_handle(self, caps: SessionCapabilities) -> bool: ...
    def optimize(self, inp: OptimizerInput) -> OptimizerContract: ...
```

```python
# telemetry_tool/optimizer_v2/capabilities.py
"""Minimum-capability sets per engine + match helpers."""
from __future__ import annotations

from telemetry_tool.web.schemas.contracts.capabilities import (
    ChannelTag,
    SessionCapabilities,
)

MIN_CAPS_TRAJECTORY_ONLY: frozenset[ChannelTag] = frozenset({
    ChannelTag.GPS, ChannelTag.LAT_G, ChannelTag.LON_G,
})

MIN_CAPS_FULL_FIDELITY: frozenset[ChannelTag] = frozenset({
    ChannelTag.GPS, ChannelTag.LAT_G, ChannelTag.LON_G,
    ChannelTag.THROTTLE, ChannelTag.BRAKE, ChannelTag.STEER,
})


def matches(required: frozenset[ChannelTag], caps: SessionCapabilities) -> bool:
    """True when every required tag is present in caps."""
    return caps.has_all(required)
```

```python
# telemetry_tool/optimizer_v2/__init__.py
"""Capability-driven optimizer dispatcher.

Public surface:
    - OptimizerEngine       — Protocol implemented by each concrete engine
    - OptimizerInput        — bundle of inputs an engine consumes
    - OptimizerDispatcher   — selects an engine from capabilities
    - NoMatchingEngineError, OptimizerInputError

Concrete engines live in trajectory_only.py and full_fidelity.py and are
registered by the dispatcher at import time.
"""
from __future__ import annotations

from ._types import OptimizerInput
from .engine import OptimizerEngine
from .errors import NoMatchingEngineError, OptimizerInputError

__all__ = [
    "OptimizerEngine",
    "OptimizerInput",
    "NoMatchingEngineError",
    "OptimizerInputError",
]
```

- [ ] **Step 1.4: Write failing capability-match test**

```python
# telemetry_tool/tests/test_optimizer_v2/test_capabilities.py
from __future__ import annotations

from telemetry_tool.optimizer_v2.capabilities import (
    MIN_CAPS_FULL_FIDELITY,
    MIN_CAPS_TRAJECTORY_ONLY,
    matches,
)
from telemetry_tool.web.schemas.contracts.capabilities import (
    ChannelTag,
    SessionCapabilities,
)


def test_trajectory_only_minimum_set():
    assert MIN_CAPS_TRAJECTORY_ONLY == frozenset({
        ChannelTag.GPS, ChannelTag.LAT_G, ChannelTag.LON_G,
    })


def test_full_fidelity_superset_of_trajectory_only():
    assert MIN_CAPS_TRAJECTORY_ONLY < MIN_CAPS_FULL_FIDELITY


def test_matches_returns_true_for_exact_set():
    caps = SessionCapabilities(channels=frozenset(MIN_CAPS_TRAJECTORY_ONLY))
    assert matches(MIN_CAPS_TRAJECTORY_ONLY, caps)


def test_matches_returns_false_missing_lat_g():
    caps = SessionCapabilities(channels=frozenset({ChannelTag.GPS, ChannelTag.LON_G}))
    assert not matches(MIN_CAPS_TRAJECTORY_ONLY, caps)


def test_matches_returns_true_when_superset():
    caps = SessionCapabilities(channels=frozenset(MIN_CAPS_FULL_FIDELITY))
    assert matches(MIN_CAPS_TRAJECTORY_ONLY, caps)
```

- [ ] **Step 1.5: Run — expect PASS**

Run: `pytest telemetry_tool/tests/test_optimizer_v2/ -v`

Expected: PASS (Protocol test + 5 capability tests).

- [ ] **Step 1.6: Commit**

```bash
git add telemetry_tool/optimizer_v2/ telemetry_tool/tests/test_optimizer_v2/
git commit -m "feat(optimizer_v2): engine Protocol + capability match helpers (W7.T7.1)"
```

---

### Task 2: `TrajectoryOnlyOptimizer` (T7.2)

Wrap `theoretical_adapter.compute_theoretical_via_envelope` (+ optional `raceline_optimizer.optimize_corner_lines`). Emit `OptimizerContract(depth=TRAJECTORY_ONLY)` with the deltas, corner losses, and `method_notes` metadata.

**Files:**
- Create: `telemetry_tool/optimizer_v2/trajectory_only.py`
- Create: `telemetry_tool/optimizer_v2/contract_builder.py`
- Create: `telemetry_tool/tests/test_optimizer_v2/test_trajectory_only.py`
- Create: `telemetry_tool/tests/test_optimizer_v2/fixtures/real_life_input.json`

- [ ] **Step 2.1: Capture a real `AdapterResult` fixture**

```bash
python -c "
from telemetry_tool.pipeline.orchestrator import run_full_analysis
import json, pathlib
summary = run_full_analysis('data/fixtures/ouest_karting.csv', metadata={})
# strip numpy arrays for JSON serialization
def _clean(o):
    if hasattr(o, 'tolist'): return o.tolist()
    if isinstance(o, dict): return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, list): return [_clean(v) for v in o]
    return o
out = pathlib.Path('telemetry_tool/tests/test_optimizer_v2/fixtures/real_life_summary.json')
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(_clean(summary), indent=2))
"
```

Use this to build the fixture. Reuse the existing W3 fixture at `telemetry_tool/tests/test_pipeline/test_contract_adapter/fixtures/summary_ouest_karting.json` if present — this avoids re-running the pipeline.

- [ ] **Step 2.2: Write failing test — trajectory-only happy path**

```python
# telemetry_tool/tests/test_optimizer_v2/test_trajectory_only.py
from __future__ import annotations

import json
import pathlib

import pytest

from telemetry_tool.optimizer_v2 import OptimizerInput
from telemetry_tool.optimizer_v2.capabilities import MIN_CAPS_TRAJECTORY_ONLY
from telemetry_tool.optimizer_v2.trajectory_only import TrajectoryOnlyOptimizer
from telemetry_tool.web.schemas.contracts.capabilities import (
    ChannelTag,
    SessionCapabilities,
)
from telemetry_tool.web.schemas.contracts.optimizer import OptimizerDepth

FIX = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def rl_summary():
    shared_fix = pathlib.Path(__file__).resolve().parents[1] / \
        "test_pipeline/test_contract_adapter/fixtures/summary_ouest_karting.json"
    assert shared_fix.exists(), f"missing W3 fixture: {shared_fix}"
    return json.loads(shared_fix.read_text())


def test_trajectory_only_can_handle_minimal_caps(rl_summary):
    engine = TrajectoryOnlyOptimizer()
    caps = SessionCapabilities(channels=frozenset(MIN_CAPS_TRAJECTORY_ONLY))
    assert engine.can_handle(caps)


def test_trajectory_only_rejects_missing_lat_g(rl_summary):
    engine = TrajectoryOnlyOptimizer()
    caps = SessionCapabilities(channels=frozenset({ChannelTag.GPS, ChannelTag.LON_G}))
    assert not engine.can_handle(caps)


def test_trajectory_only_produces_trajectory_only_depth(rl_summary, vehicle_stub, geometry_from_summary, envelope_from_summary):
    engine = TrajectoryOnlyOptimizer()
    caps = SessionCapabilities(channels=frozenset(MIN_CAPS_TRAJECTORY_ONLY))
    inp = OptimizerInput(
        capabilities=caps,
        geometry=geometry_from_summary,
        vehicle=vehicle_stub,
        rl_envelope=envelope_from_summary,
        session_summary=rl_summary,
    )
    result = engine.optimize(inp)
    assert result.depth is OptimizerDepth.TRAJECTORY_ONLY
    assert result.reconstructed_inputs is None
    assert result.theoretical_lap_time_s > 0
    assert 0.0 <= result.confidence <= 1.0
    assert result.validation["method_notes"]["engine"] == "TrajectoryOnlyOptimizer"
    assert result.validation["method_notes"]["solver_backend"] in {"envelope_qss", "envelope_casadi_ocp"}
```

- [ ] **Step 2.3: Implement `TrajectoryOnlyOptimizer` (translation layer only)**

```python
# telemetry_tool/optimizer_v2/trajectory_only.py
"""Trajectory-only optimizer — real-life sessions (GPS + accel)."""
from __future__ import annotations

from telemetry_tool.theoretical_adapter import compute_theoretical_via_envelope
from telemetry_tool.web.schemas.contracts import OptimizerContract
from telemetry_tool.web.schemas.contracts.capabilities import SessionCapabilities
from telemetry_tool.web.schemas.contracts.optimizer import OptimizerDepth

from ._types import OptimizerInput
from .capabilities import MIN_CAPS_TRAJECTORY_ONLY, matches
from .contract_builder import build_trajectory_only_contract
from .errors import OptimizerInputError


class TrajectoryOnlyOptimizer:
    """Wraps telemetry_tool.theoretical_adapter for GPS+accel-only sessions.

    Translation layer only — no optimization logic. Delegates to the existing
    kart_envelope solver (via the adapter) and converts AdapterResult → OptimizerContract.
    """

    MIN_CAPABILITIES = MIN_CAPS_TRAJECTORY_ONLY
    FIDELITY_RANK: int = 1

    def can_handle(self, caps: SessionCapabilities) -> bool:
        return matches(self.MIN_CAPABILITIES, caps)

    def optimize(self, inp: OptimizerInput) -> OptimizerContract:
        if inp.rl_envelope is None:
            raise OptimizerInputError("TrajectoryOnlyOptimizer requires rl_envelope (CapabilityEnvelope)")
        adapter_result = compute_theoretical_via_envelope(
            pipeline_df=inp.session_summary.get("pipeline_df"),
            curvature_profile=inp.session_summary.get("curvature_profile"),
            envelope=inp.rl_envelope,
            session_summary=inp.session_summary,
            config=inp.config,
        )
        return build_trajectory_only_contract(
            adapter_result=adapter_result,
            summary=inp.session_summary,
            depth=OptimizerDepth.TRAJECTORY_ONLY,
        )
```

```python
# telemetry_tool/optimizer_v2/contract_builder.py
"""Result → OptimizerContract builders (shared between engines)."""
from __future__ import annotations

from typing import Any

from telemetry_tool.web.schemas.contracts import OptimizerContract
from telemetry_tool.web.schemas.contracts.optimizer import (
    CornerDelta,
    OptimizerDepth,
    ReconstructedInputs,
    TrajectoryDelta,
)

_WRAPPER_VERSION = "0.1.0"


def _clamp01(x: Any) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(1.0, v))


def _corner_deltas_from_summary(summary: dict[str, Any]) -> list[CornerDelta]:
    rows = summary.get("corner_coaching") or []
    out: list[CornerDelta] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        try:
            out.append(CornerDelta(
                corner_id=str(r.get("corner_id")),
                time_loss_s=float(r.get("time_loss_s") or 0.0),
                root_cause=str(r.get("root_cause") or "unknown"),
                coaching_text=str(r.get("summary") or r.get("coaching_text") or ""),
                phase=(r.get("phase") or None),
            ))
        except Exception:
            continue
    return out


def _trajectory_delta_from_summary(summary: dict[str, Any]) -> TrajectoryDelta | None:
    df = summary.get("delta_map")
    if df is None:
        return None
    try:
        distance = list(df["distance_m"])
        speed = list(df["speed_delta_mps"])
    except Exception:
        return None
    if not distance or len(distance) != len(speed):
        return None
    return TrajectoryDelta(
        distance_m=[float(x) for x in distance],
        speed_delta_ms=[float(x) for x in speed],
    )


def _method_notes(*, engine: str, solver_backend: str, vehicle_source: str,
                  friction_source: str, fallbacks: list[str]) -> dict[str, Any]:
    return {
        "engine": engine,
        "solver_backend": solver_backend,
        "wrapper_version": _WRAPPER_VERSION,
        "w5_vehicle_source": vehicle_source,
        "w5_friction_source": friction_source,
        "fallbacks_triggered": fallbacks,
    }


def build_trajectory_only_contract(
    *,
    adapter_result: Any,
    summary: dict[str, Any],
    depth: OptimizerDepth = OptimizerDepth.TRAJECTORY_ONLY,
) -> OptimizerContract:
    corner_deltas = _corner_deltas_from_summary(summary)
    total_loss = sum(cd.time_loss_s for cd in corner_deltas)
    theo = summary.get("theoretical_metrics") or {}
    lap_times = [
        t for t in (summary.get("lap_times") or [])
        if isinstance(t, (int, float)) and t > 0
    ]
    driver_best = min(lap_times) if lap_times else None
    best_theo = theo.get("best_s") or getattr(adapter_result.theoretical_result, "lap_time_s", 0.0)
    gap = (driver_best - best_theo) if (best_theo and driver_best) else None
    return OptimizerContract(
        depth=depth,
        method=str(adapter_result.method or "envelope_qss"),
        theoretical_lap_time_s=float(best_theo or 0.0),
        confidence=_clamp01(summary.get("theoretical_confidence", 0.5)),
        corner_deltas=corner_deltas,
        total_time_loss_s=total_loss,
        trajectory_delta=_trajectory_delta_from_summary(summary),
        reconstructed_inputs=None,
        vehicle_model={"note": "trajectory-only — envelope-identified"},
        validation={
            "method_notes": _method_notes(
                engine="TrajectoryOnlyOptimizer",
                solver_backend=str(getattr(adapter_result.theoretical_result, "solver_backend", "envelope_qss")),
                vehicle_source="kart_envelope.CapabilityEnvelope",
                friction_source="none",
                fallbacks=list(getattr(adapter_result.theoretical_result, "solver_diagnostics", {}).get("fallbacks", [])),
            ),
            "driver_best_s": driver_best,
            "gap_to_theoretical_s": gap,
            "attributed_loss_s": total_loss,
            "unattributed_loss_s": ((gap - total_loss) if (gap is not None) else None),
        },
    )
```

- [ ] **Step 2.4: Write `conftest.py` with fixtures**

```python
# telemetry_tool/tests/test_optimizer_v2/conftest.py
from __future__ import annotations

import json
import pathlib

import numpy as np
import pytest

from telemetry_tool.shared.geometry import TrackGeometry
from telemetry_tool.shared.physics import VehicleModel


class _StubVehicle(VehicleModel):
    @property
    def mass_kg(self) -> float: return 720.0
    @property
    def wheelbase_m(self) -> float: return 1.05
    @property
    def cg_height_m(self) -> float: return 0.28


@pytest.fixture
def vehicle_stub():
    return _StubVehicle()


@pytest.fixture
def geometry_from_summary(rl_summary):
    """Build TrackGeometry from the fixture summary's curvature profile."""
    curv = rl_summary.get("curvature_profile") or {}
    dist = np.array(curv["distance_m"], dtype=float)
    kappa = np.array(curv["curvature_1pm"], dtype=float)
    heading = np.array(curv.get("heading_rad", np.zeros_like(dist)), dtype=float)
    x = np.array(curv.get("x_ref_m", np.zeros_like(dist)), dtype=float)
    y = np.array(curv.get("y_ref_m", np.zeros_like(dist)), dtype=float)
    return TrackGeometry(
        distance_m=dist, curvature_1pm=kappa, heading_rad=heading,
        x_ref_m=x, y_ref_m=y,
        lap_length_m=float(dist[-1] - dist[0]),
        track_id=str(rl_summary.get("track_id", "")),
    )


@pytest.fixture
def envelope_from_summary(rl_summary):
    """Rehydrate a CapabilityEnvelope from the serialized summary."""
    from kart_envelope.envelope.capability import CapabilityEnvelope
    env_data = rl_summary.get("capability_envelope") or {}
    return CapabilityEnvelope.from_dict(env_data)
```

- [ ] **Step 2.5: Run test — expect PASS**

Run: `pytest telemetry_tool/tests/test_optimizer_v2/test_trajectory_only.py -v`

Expected: all 3 tests PASS.

- [ ] **Step 2.6: Commit**

```bash
git add telemetry_tool/optimizer_v2/trajectory_only.py \
        telemetry_tool/optimizer_v2/contract_builder.py \
        telemetry_tool/tests/test_optimizer_v2/test_trajectory_only.py \
        telemetry_tool/tests/test_optimizer_v2/conftest.py \
        telemetry_tool/tests/test_optimizer_v2/fixtures/
git commit -m "feat(optimizer_v2): TrajectoryOnlyOptimizer wrapping theoretical_adapter (W7.T7.2)"
```

---

### Task 3: `FullFidelityOptimizer` (T7.3)

Wrap `sim_optimizer.solver.qss_enhanced.compute_sim_theoretical_lap`. Emit `OptimizerContract(depth=FULL_FIDELITY)` with reconstructed input traces.

**Files:**
- Create: `telemetry_tool/optimizer_v2/full_fidelity.py`
- Create: `telemetry_tool/tests/test_optimizer_v2/test_full_fidelity.py`
- Create: `telemetry_tool/tests/test_optimizer_v2/fixtures/sim_input.json`
- Modify: `telemetry_tool/optimizer_v2/contract_builder.py` (add `build_full_fidelity_contract`)

- [ ] **Step 3.1: Capture an iRacing fixture (small IBT run)**

Run sim_optimizer on `tests/fixtures/sim/tiny_iracing.ibt` (the W4 fixture — reuse once W4's branch is merged; if W4 is still in flight, prompt user for a tiny IBT + skip this fixture temporarily with `pytest.skip`).

- [ ] **Step 3.2: Write failing test**

```python
# telemetry_tool/tests/test_optimizer_v2/test_full_fidelity.py
from __future__ import annotations

import pytest

from telemetry_tool.optimizer_v2 import OptimizerInput
from telemetry_tool.optimizer_v2.capabilities import MIN_CAPS_FULL_FIDELITY
from telemetry_tool.optimizer_v2.full_fidelity import FullFidelityOptimizer
from telemetry_tool.web.schemas.contracts.capabilities import (
    ChannelTag,
    SessionCapabilities,
)
from telemetry_tool.web.schemas.contracts.optimizer import OptimizerDepth


def test_full_fidelity_requires_driver_inputs():
    engine = FullFidelityOptimizer()
    partial = SessionCapabilities(channels=frozenset({
        ChannelTag.GPS, ChannelTag.LAT_G, ChannelTag.LON_G,
    }))
    assert not engine.can_handle(partial)


def test_full_fidelity_accepts_full_sim_caps():
    engine = FullFidelityOptimizer()
    full = SessionCapabilities(channels=frozenset(MIN_CAPS_FULL_FIDELITY))
    assert engine.can_handle(full)


@pytest.mark.usefixtures("sim_fixture_available")
def test_full_fidelity_produces_reconstructed_inputs(sim_input: OptimizerInput):
    engine = FullFidelityOptimizer()
    result = engine.optimize(sim_input)
    assert result.depth is OptimizerDepth.FULL_FIDELITY
    assert result.reconstructed_inputs is not None
    rc = result.reconstructed_inputs
    n = len(rc.distance_m)
    assert n > 0
    assert len(rc.throttle) == len(rc.brake) == len(rc.steer) == n
    assert result.validation["method_notes"]["engine"] == "FullFidelityOptimizer"
    assert result.validation["method_notes"]["solver_backend"] == "sim_qss"
```

- [ ] **Step 3.3: Implement `FullFidelityOptimizer`**

```python
# telemetry_tool/optimizer_v2/full_fidelity.py
"""Full-fidelity optimizer — sim sessions with driver-input channels."""
from __future__ import annotations

from telemetry_tool.sim_optimizer.solver.qss_enhanced import (
    compute_sim_theoretical_lap,
)
from telemetry_tool.web.schemas.contracts import OptimizerContract
from telemetry_tool.web.schemas.contracts.capabilities import SessionCapabilities
from telemetry_tool.web.schemas.contracts.optimizer import OptimizerDepth

from ._types import OptimizerInput
from .capabilities import MIN_CAPS_FULL_FIDELITY, matches
from .contract_builder import build_full_fidelity_contract
from .errors import OptimizerInputError


class FullFidelityOptimizer:
    """Wraps sim_optimizer.solver.qss_enhanced for sim sessions."""

    MIN_CAPABILITIES = MIN_CAPS_FULL_FIDELITY
    FIDELITY_RANK: int = 2

    def can_handle(self, caps: SessionCapabilities) -> bool:
        return matches(self.MIN_CAPABILITIES, caps)

    def optimize(self, inp: OptimizerInput) -> OptimizerContract:
        if inp.vehicle is None:
            raise OptimizerInputError("FullFidelityOptimizer requires vehicle (VehicleModel)")
        sim_result = compute_sim_theoretical_lap(
            geometry=inp.geometry,
            vehicle=inp.vehicle,
            fuel_level_l=float(inp.config.get("fuel_level_l", 30.0)),
            config=inp.config.get("sim_config"),
        )
        # Reconstructed input traces — lazy import to keep wrapper thin
        from telemetry_tool.sim_optimizer.reconstruction.input_trace import (
            reconstruct_input_trace,
        )
        inputs = reconstruct_input_trace(sim_result, inp.vehicle, inp.geometry)
        return build_full_fidelity_contract(
            sim_result=sim_result,
            reconstructed_inputs=inputs,
            summary=inp.session_summary,
            depth=OptimizerDepth.FULL_FIDELITY,
        )
```

- [ ] **Step 3.4: Add `build_full_fidelity_contract` to contract_builder**

```python
# append to telemetry_tool/optimizer_v2/contract_builder.py

def build_full_fidelity_contract(
    *,
    sim_result: Any,
    reconstructed_inputs: dict[str, Any],
    summary: dict[str, Any],
    depth: OptimizerDepth = OptimizerDepth.FULL_FIDELITY,
) -> OptimizerContract:
    corner_deltas = _corner_deltas_from_summary(summary)
    total_loss = sum(cd.time_loss_s for cd in corner_deltas)
    rc = ReconstructedInputs(
        distance_m=[float(x) for x in reconstructed_inputs["distance_m"]],
        throttle=[float(x) for x in reconstructed_inputs["throttle"]],
        brake=[float(x) for x in reconstructed_inputs["brake"]],
        steer=[float(x) for x in reconstructed_inputs["steer"]],
    )
    lap_times = [
        t for t in (summary.get("lap_times") or [])
        if isinstance(t, (int, float)) and t > 0
    ]
    driver_best = min(lap_times) if lap_times else None
    best_theo = float(sim_result.lap_time_s)
    gap = (driver_best - best_theo) if (best_theo and driver_best) else None
    return OptimizerContract(
        depth=depth,
        method="sim_qss",
        theoretical_lap_time_s=best_theo,
        confidence=_clamp01(summary.get("theoretical_confidence", 0.75)),
        corner_deltas=corner_deltas,
        total_time_loss_s=total_loss,
        trajectory_delta=_trajectory_delta_from_summary(summary),
        reconstructed_inputs=rc,
        vehicle_model=dict(summary.get("vehicle_params") or {}),
        validation={
            "method_notes": _method_notes(
                engine="FullFidelityOptimizer",
                solver_backend="sim_qss",
                vehicle_source="sim_optimizer.param_id.VehicleModel",
                friction_source="sim_optimizer.param_id.Pacejka",
                fallbacks=[],
            ),
            "driver_best_s": driver_best,
            "gap_to_theoretical_s": gap,
            "attributed_loss_s": total_loss,
            "unattributed_loss_s": ((gap - total_loss) if (gap is not None) else None),
        },
    )
```

- [ ] **Step 3.5: Run — expect PASS (or conditional skip if no sim fixture)**

Run: `pytest telemetry_tool/tests/test_optimizer_v2/test_full_fidelity.py -v`

Expected: PASS, or skip with reason "sim fixture unavailable" if the W4 IBT fixture is not yet on main.

- [ ] **Step 3.6: Commit**

```bash
git add telemetry_tool/optimizer_v2/full_fidelity.py \
        telemetry_tool/optimizer_v2/contract_builder.py \
        telemetry_tool/tests/test_optimizer_v2/test_full_fidelity.py
git commit -m "feat(optimizer_v2): FullFidelityOptimizer wrapping sim_optimizer solver (W7.T7.3)"
```

---

### Task 4: `OptimizerDispatcher` + tie-break rule (T7.4)

Register concrete engines; select by `FIDELITY_RANK` then class name; raise `NoMatchingEngineError` when no engine matches.

**Files:**
- Create: `telemetry_tool/optimizer_v2/dispatcher.py`
- Create: `telemetry_tool/tests/test_optimizer_v2/test_dispatcher.py`
- Modify: `telemetry_tool/optimizer_v2/__init__.py` (export `OptimizerDispatcher`, `dispatch`)

- [ ] **Step 4.1: Write failing test — tie-break picks higher fidelity**

```python
# telemetry_tool/tests/test_optimizer_v2/test_dispatcher.py
from __future__ import annotations

import pytest

from telemetry_tool.optimizer_v2 import OptimizerDispatcher, NoMatchingEngineError
from telemetry_tool.optimizer_v2.full_fidelity import FullFidelityOptimizer
from telemetry_tool.optimizer_v2.trajectory_only import TrajectoryOnlyOptimizer
from telemetry_tool.web.schemas.contracts.capabilities import (
    ChannelTag,
    SessionCapabilities,
)


def test_dispatcher_selects_trajectory_only_for_real_life_caps():
    caps = SessionCapabilities(channels=frozenset({
        ChannelTag.GPS, ChannelTag.LAT_G, ChannelTag.LON_G,
    }))
    engine = OptimizerDispatcher().select(caps)
    assert isinstance(engine, TrajectoryOnlyOptimizer)


def test_dispatcher_selects_full_fidelity_for_sim_caps():
    caps = SessionCapabilities(channels=frozenset({
        ChannelTag.GPS, ChannelTag.LAT_G, ChannelTag.LON_G,
        ChannelTag.THROTTLE, ChannelTag.BRAKE, ChannelTag.STEER,
    }))
    engine = OptimizerDispatcher().select(caps)
    assert isinstance(engine, FullFidelityOptimizer)


def test_dispatcher_raises_when_no_engine_matches():
    caps = SessionCapabilities(channels=frozenset({ChannelTag.GPS}))  # missing LAT_G/LON_G
    with pytest.raises(NoMatchingEngineError):
        OptimizerDispatcher().select(caps)


def test_dispatcher_tiebreak_is_fidelity_rank():
    """Registration order does not affect selection — higher FIDELITY_RANK wins."""
    disp = OptimizerDispatcher()
    # Shuffle registration — dispatcher must still pick full-fidelity for sim caps.
    disp._engines = list(reversed(disp._engines))  # noqa: SLF001 — private poke for test
    caps = SessionCapabilities(channels=frozenset({
        ChannelTag.GPS, ChannelTag.LAT_G, ChannelTag.LON_G,
        ChannelTag.THROTTLE, ChannelTag.BRAKE, ChannelTag.STEER,
    }))
    engine = disp.select(caps)
    assert isinstance(engine, FullFidelityOptimizer)
```

- [ ] **Step 4.2: Implement `OptimizerDispatcher`**

```python
# telemetry_tool/optimizer_v2/dispatcher.py
"""Capability-driven optimizer dispatcher.

Selection rule (see plan §D2):
    1. Filter engines where can_handle(caps) is True.
    2. Of those, pick highest FIDELITY_RANK.
    3. Tie-break by class name (deterministic).
    4. Raise NoMatchingEngineError if the filtered set is empty.

Dispatcher does NOT branch on session.source — only SessionCapabilities.
Enforced by tests/test_optimizer_v2/test_no_source_branching.py.
"""
from __future__ import annotations

from typing import Iterable

from telemetry_tool.web.schemas.contracts import OptimizerContract
from telemetry_tool.web.schemas.contracts.capabilities import SessionCapabilities

from ._types import OptimizerInput
from .engine import OptimizerEngine
from .errors import NoMatchingEngineError
from .full_fidelity import FullFidelityOptimizer
from .trajectory_only import TrajectoryOnlyOptimizer


class OptimizerDispatcher:
    """Selects an OptimizerEngine for a given SessionCapabilities."""

    def __init__(self, engines: Iterable[OptimizerEngine] | None = None) -> None:
        self._engines: list[OptimizerEngine] = list(engines) if engines else [
            TrajectoryOnlyOptimizer(),
            FullFidelityOptimizer(),
        ]

    def select(self, caps: SessionCapabilities) -> OptimizerEngine:
        candidates = [e for e in self._engines if e.can_handle(caps)]
        if not candidates:
            raise NoMatchingEngineError(
                f"No OptimizerEngine handles capabilities={sorted(c.value for c in caps.channels)}"
            )
        candidates.sort(key=lambda e: (-e.FIDELITY_RANK, type(e).__name__))
        return candidates[0]

    def dispatch(self, inp: OptimizerInput) -> OptimizerContract:
        """Select an engine and run it. Convenience for the common case."""
        engine = self.select(inp.capabilities)
        return engine.optimize(inp)
```

- [ ] **Step 4.3: Re-export from `__init__.py`**

```python
# telemetry_tool/optimizer_v2/__init__.py  — add to existing file
from .dispatcher import OptimizerDispatcher

__all__ += ["OptimizerDispatcher"]
```

- [ ] **Step 4.4: Run tests — expect PASS**

Run: `pytest telemetry_tool/tests/test_optimizer_v2/test_dispatcher.py -v`

Expected: 4 tests PASS.

- [ ] **Step 4.5: Commit**

```bash
git add telemetry_tool/optimizer_v2/dispatcher.py \
        telemetry_tool/optimizer_v2/__init__.py \
        telemetry_tool/tests/test_optimizer_v2/test_dispatcher.py
git commit -m "feat(optimizer_v2): OptimizerDispatcher with capability-driven tie-break (W7.T7.4)"
```

---

### Task 5: Contract emission — depth / confidence / method_notes (T7.5)

The contract builder is already written in Task 2/3. This task adds the dedicated unit test for the emission schema and verifies `method_notes` presence across both engines.

**Files:**
- Create: `telemetry_tool/tests/test_optimizer_v2/test_contract_builder.py`

- [ ] **Step 5.1: Write failing test — method_notes schema**

```python
# telemetry_tool/tests/test_optimizer_v2/test_contract_builder.py
from __future__ import annotations

from telemetry_tool.optimizer_v2.contract_builder import (
    build_full_fidelity_contract,
    build_trajectory_only_contract,
)
from telemetry_tool.web.schemas.contracts.optimizer import OptimizerDepth


METHOD_NOTES_REQUIRED_KEYS = {
    "engine", "solver_backend", "wrapper_version",
    "w5_vehicle_source", "w5_friction_source", "fallbacks_triggered",
}


def test_trajectory_only_contract_method_notes_has_all_keys(adapter_result_stub, rl_summary):
    c = build_trajectory_only_contract(
        adapter_result=adapter_result_stub,
        summary=rl_summary,
    )
    notes = c.validation["method_notes"]
    assert set(notes.keys()) >= METHOD_NOTES_REQUIRED_KEYS
    assert notes["engine"] == "TrajectoryOnlyOptimizer"
    assert notes["wrapper_version"] == "0.1.0"


def test_full_fidelity_contract_method_notes_has_all_keys(sim_result_stub, reconstructed_inputs_stub, rl_summary):
    c = build_full_fidelity_contract(
        sim_result=sim_result_stub,
        reconstructed_inputs=reconstructed_inputs_stub,
        summary=rl_summary,
    )
    notes = c.validation["method_notes"]
    assert set(notes.keys()) >= METHOD_NOTES_REQUIRED_KEYS
    assert notes["engine"] == "FullFidelityOptimizer"


def test_depth_mirrors_depth_enum(adapter_result_stub, rl_summary):
    c = build_trajectory_only_contract(
        adapter_result=adapter_result_stub, summary=rl_summary,
        depth=OptimizerDepth.TRAJECTORY_ONLY,
    )
    assert c.depth is OptimizerDepth.TRAJECTORY_ONLY
```

- [ ] **Step 5.2: Add `adapter_result_stub`, `sim_result_stub`, `reconstructed_inputs_stub` to conftest**

```python
# append to telemetry_tool/tests/test_optimizer_v2/conftest.py
from types import SimpleNamespace


@pytest.fixture
def adapter_result_stub():
    return SimpleNamespace(
        theoretical_df=None,
        theoretical_result=SimpleNamespace(
            lap_time_s=83.12,
            solver_backend="envelope_qss",
            solver_diagnostics={},
        ),
        method="envelope_qss",
        corner_coaching=[],
        delta_map=None,
        session_scalars=None,
    )


@pytest.fixture
def sim_result_stub():
    return SimpleNamespace(
        lap_time_s=82.44,
        speed_profile_mps=np.array([]),
        distance_m=np.array([]),
        accel_profile_mps2=np.array([]),
        cornering_limited=np.array([]),
        accel_limited=np.array([]),
        braking_limited=np.array([]),
        gear_profile=np.array([]),
        method="sim_qss",
    )


@pytest.fixture
def reconstructed_inputs_stub():
    return {
        "distance_m": [0.0, 10.0, 20.0],
        "throttle":  [1.0, 1.0, 0.7],
        "brake":     [0.0, 0.0, 0.2],
        "steer":     [0.0, 0.0, 0.1],
    }
```

- [ ] **Step 5.3: Run — expect PASS**

Run: `pytest telemetry_tool/tests/test_optimizer_v2/test_contract_builder.py -v`

Expected: 3 tests PASS.

- [ ] **Step 5.4: Commit**

```bash
git add telemetry_tool/tests/test_optimizer_v2/test_contract_builder.py \
        telemetry_tool/tests/test_optimizer_v2/conftest.py
git commit -m "test(optimizer_v2): method_notes schema + depth emission (W7.T7.5)"
```

---

### Task 6: Cross-path equivalence + depth monotonicity tests (T7.6)

Two regression tests: (a) real-life sim-comparable fixture — the full-fidelity optimizer must produce strictly more populated fields than trajectory-only for the same fixture; (b) W3's stub vs W7 dispatcher agree on lap time + attributed loss for the shared real-life fixture.

**Files:**
- Create: `telemetry_tool/tests/test_optimizer_v2/test_depth_monotonicity.py`
- Create: `telemetry_tool/tests/test_optimizer_v2/test_w3_fallback_equivalence.py`
- Create: `telemetry_tool/tests/test_optimizer_v2/test_no_source_branching.py`
- Create: `telemetry_tool/tests/test_optimizer_v2/test_wrapper_thickness.py`

- [ ] **Step 6.1: Write `test_depth_monotonicity.py`**

```python
# telemetry_tool/tests/test_optimizer_v2/test_depth_monotonicity.py
"""Sim path strictly more informative than real-life on a comparable fixture."""
from __future__ import annotations

import pytest

from telemetry_tool.optimizer_v2 import OptimizerDispatcher


@pytest.mark.usefixtures("sim_fixture_available")
def test_full_fidelity_has_reconstructed_inputs(sim_input):
    contract = OptimizerDispatcher().dispatch(sim_input)
    assert contract.reconstructed_inputs is not None
    assert len(contract.reconstructed_inputs.distance_m) > 0


def test_trajectory_only_has_no_reconstructed_inputs(real_life_input):
    contract = OptimizerDispatcher().dispatch(real_life_input)
    assert contract.reconstructed_inputs is None
    assert contract.trajectory_delta is not None   # still has delta trace


@pytest.mark.usefixtures("sim_fixture_available")
def test_full_fidelity_non_empty_where_trajectory_only_empty(sim_input, real_life_input):
    """For fields that only the sim path populates, ensure the trajectory-only path leaves them empty."""
    sim = OptimizerDispatcher().dispatch(sim_input)
    rl = OptimizerDispatcher().dispatch(real_life_input)
    assert sim.reconstructed_inputs is not None and rl.reconstructed_inputs is None
    # vehicle_model has identified params for sim; descriptive-only for real-life
    assert sim.vehicle_model and "note" not in sim.vehicle_model
    assert "note" in rl.vehicle_model
```

- [ ] **Step 6.2: Write `test_w3_fallback_equivalence.py`**

```python
# telemetry_tool/tests/test_optimizer_v2/test_w3_fallback_equivalence.py
"""W7 dispatcher and W3's OptimizerContract stub agree within tolerance on the same fixture."""
from __future__ import annotations

import math

from telemetry_tool.optimizer_v2 import OptimizerDispatcher
from telemetry_tool.pipeline.contract_adapter.optimizer import build_optimizer_contract as w3_build


def test_w3_vs_w7_agree_on_lap_time(real_life_input, rl_summary):
    w7 = OptimizerDispatcher().dispatch(real_life_input)
    w3 = w3_build(rl_summary)
    # Same underlying solver backend — lap times should match to 1 ms.
    assert math.isclose(w7.theoretical_lap_time_s, w3.theoretical_lap_time_s, abs_tol=1e-3)


def test_w3_vs_w7_agree_on_attributed_loss(real_life_input, rl_summary):
    w7 = OptimizerDispatcher().dispatch(real_life_input)
    w3 = w3_build(rl_summary)
    assert math.isclose(
        w7.validation["attributed_loss_s"],
        w3.validation["attributed_loss_s"],
        abs_tol=1e-3,
    )
```

- [ ] **Step 6.3: Write `test_no_source_branching.py`** (full body in §No source-branching guarantee above — copy verbatim)

- [ ] **Step 6.4: Write `test_wrapper_thickness.py`**

```python
# telemetry_tool/tests/test_optimizer_v2/test_wrapper_thickness.py
"""Each engine wrapper stays under 100 LOC of non-translation logic.

"Non-translation logic" = statements with loops, comprehensions, conditionals,
or arithmetic not in a simple dict/attribute pass-through.
"""
from __future__ import annotations

import ast
import pathlib

WRAPPERS = [
    pathlib.Path(__file__).resolve().parents[2] / "optimizer_v2" / "trajectory_only.py",
    pathlib.Path(__file__).resolve().parents[2] / "optimizer_v2" / "full_fidelity.py",
]

_LOGIC_NODES = (ast.For, ast.While, ast.If, ast.comprehension, ast.BinOp, ast.BoolOp)


def _logic_line_count(src: str) -> int:
    tree = ast.parse(src)
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, _LOGIC_NODES) and hasattr(node, "lineno"):
            lines.add(node.lineno)
    return len(lines)


def test_trajectory_only_wrapper_thin():
    n = _logic_line_count(WRAPPERS[0].read_text(encoding="utf-8"))
    assert n <= 100, f"trajectory_only.py has {n} lines of non-translation logic (cap: 100)"


def test_full_fidelity_wrapper_thin():
    n = _logic_line_count(WRAPPERS[1].read_text(encoding="utf-8"))
    assert n <= 100, f"full_fidelity.py has {n} lines of non-translation logic (cap: 100)"
```

- [ ] **Step 6.5: Run all new tests — expect PASS**

Run: `pytest telemetry_tool/tests/test_optimizer_v2/ -v`

Expected: PASS for everything. The sim-dependent tests skip if no IBT fixture.

- [ ] **Step 6.6: Commit with signal**

```bash
git add telemetry_tool/tests/test_optimizer_v2/test_depth_monotonicity.py \
        telemetry_tool/tests/test_optimizer_v2/test_w3_fallback_equivalence.py \
        telemetry_tool/tests/test_optimizer_v2/test_no_source_branching.py \
        telemetry_tool/tests/test_optimizer_v2/test_wrapper_thickness.py
git commit -m "test(optimizer_v2): depth monotonicity + W3 equivalence + CI guards (W7.T7.6) [signal:W7-done]"
```

---

### Task 7: Feature-flagged pipeline wiring (beyond T7.1–T7.6)

Add the `OPTIMIZER_V2_DISPATCHER` flag and route the real-life pipeline through `OptimizerDispatcher` when it is on. W3's stub remains the default.

**Files:**
- Modify: `telemetry_tool/pipeline/orchestrator.py` (after the existing W3 contract emission — ~15 lines)

- [ ] **Step 7.1: Write failing test — flag-gated routing**

```python
# telemetry_tool/tests/test_pipeline/test_contract_adapter/test_optimizer_v2_flag.py
from __future__ import annotations

import os
import pytest
from unittest.mock import patch

from telemetry_tool.pipeline.orchestrator import run_full_analysis


@pytest.fixture
def rl_csv(tmp_path):
    ...  # reuse existing fixture path


def test_flag_off_uses_w3_stub(rl_csv, monkeypatch):
    monkeypatch.delenv("OPTIMIZER_V2_DISPATCHER", raising=False)
    out = run_full_analysis(rl_csv, metadata={})
    assert out["optimizer_contract"].validation["method_notes"] is None or \
           "TrajectoryOnlyOptimizer" not in str(out["optimizer_contract"].validation.get("method_notes", ""))


def test_flag_on_uses_dispatcher(rl_csv, monkeypatch):
    monkeypatch.setenv("OPTIMIZER_V2_DISPATCHER", "1")
    out = run_full_analysis(rl_csv, metadata={})
    assert out["optimizer_contract"].validation["method_notes"]["engine"] == "TrajectoryOnlyOptimizer"
```

- [ ] **Step 7.2: Implement the flag in orchestrator**

```python
# at end of telemetry_tool/pipeline/orchestrator.py::run_full_analysis, after existing contract emission:
import os
if os.environ.get("OPTIMIZER_V2_DISPATCHER", "0") == "1":
    try:
        from telemetry_tool.optimizer_v2 import OptimizerDispatcher, OptimizerInput
        from telemetry_tool.pipeline.contract_adapter.capabilities import build_capabilities
        from telemetry_tool.optimizer_v2._types import OptimizerInput as _OI
        # Build OptimizerInput from summary + ctx
        caps = build_capabilities(summary)
        inp = _OI(
            capabilities=caps,
            geometry=summary.get("track_geometry"),
            vehicle=summary.get("vehicle_surrogate"),
            rl_envelope=summary.get("capability_envelope"),
            session_summary=summary,
            config=config or {},
        )
        optimizer_contract = OptimizerDispatcher().dispatch(inp)
    except Exception as e:
        logger.warning("optimizer_v2 dispatcher failed, falling back to W3 stub: %s", e)
```

- [ ] **Step 7.3: Run — expect PASS**

Run: `pytest telemetry_tool/tests/test_pipeline/test_contract_adapter/test_optimizer_v2_flag.py -v`

Expected: 2 tests PASS.

- [ ] **Step 7.4: Commit**

```bash
git add telemetry_tool/pipeline/orchestrator.py \
        telemetry_tool/tests/test_pipeline/test_contract_adapter/test_optimizer_v2_flag.py
git commit -m "feat(pipeline): route OptimizerContract through optimizer_v2 dispatcher when OPTIMIZER_V2_DISPATCHER=1"
```

---

### Task 8: Plan checklist + merge signal

- [ ] **Step 8.1: Update plan-doc checklist**

In this file, replace each `- [ ]` with `- [x]` as tasks complete. Commit after Task 7.

- [ ] **Step 8.2: Final signal commit**

```bash
git commit --allow-empty -m "docs(plan): W7 optimizer v2 — all tasks complete [signal:W7-done]"
```

- [ ] **Step 8.3: Open PR**

Target: `main`. Title: `Merge W7 — Optimizer Dispatcher (trajectory-only + full-fidelity)`.

PR body sections:
- Summary (architecture diagram from §Architecture)
- Fidelity matrix (which engine emits what)
- CI guards (no-source-branching + wrapper-thickness)
- Cross-path regression result
- Flag status: `OPTIMIZER_V2_DISPATCHER` off by default in Phase 1

---

## Self-review

1. **Spec coverage:**
   - T7.1 `OptimizerEngine` interface → Task 1 ✅
   - T7.2 `TrajectoryOnlyOptimizer` → Task 2 ✅
   - T7.3 `FullFidelityOptimizer` → Task 3 ✅
   - T7.4 `OptimizerDispatcher` → Task 4 ✅
   - T7.5 OptimizerContract emission with metadata → Task 5 ✅ (contract-builder Task 2 body, test Task 5)
   - T7.6 Tests — both paths valid, sim strictly more info → Task 6 ✅
   - Spec §10 decision 2 (per-engine identity) → honored by having two concrete classes, not one adaptive optimizer ✅
   - Session prompt §3 wrapping-thickness rule → explicit in §Wrapping-thickness rule + test ✅
   - Session prompt §3 no-source-branching CI check → explicit in §No source-branching guarantee + test ✅
   - Session prompt §3 do-not-touch list → §Do-not-touch list ✅
   - Session prompt §2 W5 consumption per task → §W5 consumption by task table ✅

2. **Placeholder scan:** No `TBD`, `implement later`, or handwaving. Every step has concrete code or a concrete command.

3. **Type consistency:**
   - `OptimizerInput` shape is identical between Tasks 1, 2, 3, 4 — dataclass fields match across wrappers.
   - `OptimizerEngine.MIN_CAPABILITIES` / `FIDELITY_RANK` / `can_handle` / `optimize` consistently referenced.
   - `OptimizerDepth.TRAJECTORY_ONLY` / `FULL_FIDELITY` — W1 contract values, used verbatim.
   - `build_trajectory_only_contract` / `build_full_fidelity_contract` names match between Task 2, 3, 5.

---

## Open questions

1. **Sim-comparable fixture**: `test_depth_monotonicity.py` and `test_w3_fallback_equivalence.py` assume a tiny IBT fixture is importable. W4 plan names `telemetry_tool/tests/fixtures/sim/tiny_iracing.ibt`; if W4 merges before W7, reuse. If W7 merges first, those tests `pytest.skip` with reason "W4 sim fixture not yet on main" and are re-enabled post-W4-merge via a targeted follow-up commit. Confirm acceptable.

2. **Spec §10 decision 2 — "per-engine identity"**: the spec phrases this for *coaches* (`RealLifeCoach`, `IRacingCoach`, `ACCoach`). For optimizers, §5 W7 shows only two classes (`TrajectoryOnlyOptimizer`, `FullFidelityOptimizer`) rather than per-game (`IRacingOptimizer`, `ACOptimizer`, …). Interpreting this as: optimizers are depth-scoped (2 classes), coaches are game-scoped (N classes). Confirm that's the intended asymmetry — or if each sim should eventually get its own optimizer class too (which would change §D2 tie-break design).

3. **`theoretical_adapter.compute_theoretical_via_envelope` signature**: this plan's Task 2 calls it with `pipeline_df`, `curvature_profile`, `envelope`, `session_summary`, `config`. That signature is *reconstructed* from the file header — the real function is at `theoretical_adapter.py:386`. If the actual signature drifts (e.g. requires `session_scalars` explicitly), Task 2 Step 2.3's wrapper adjusts. Not a blocker, but flagging so engineer doesn't assume the plan is exact on that call.

4. **`sim_optimizer.reconstruction.input_trace`**: the exact function name `reconstruct_input_trace(sim_result, vehicle, geometry)` is inferred from `sim_optimizer/reconstruction/input_trace.py`'s filename — the actual callable may be different. Executing engineer verifies at Task 3 Step 3.3; if the surface is different, `full_fidelity.py` adapts (still translation-only).

5. **Feature-flag default**: proposed `OPTIMIZER_V2_DISPATCHER=0` in Phase 1 for safety. If product prefers default-on, flip the default in Task 7 Step 7.2. No code impact beyond the env var default.

---

## Readiness gate (what must be true on `main` before implementation starts)

All of the following must be true for Task 0 Step 0.1 to pass:

1. `telemetry_tool/shared/physics/friction.py` exists, exports `FrictionModel` (runtime-checkable Protocol with `mu(slip, load_n)` method).
2. `telemetry_tool/shared/physics/vehicle.py` exists, exports `VehicleModel` (ABC with `mass_kg`, `wheelbase_m`, `cg_height_m` abstract properties).
3. `telemetry_tool/shared/geometry/track.py` exists, exports `TrackGeometry`. Deprecation shim at `kart_envelope/track/geometry.py` still importable.
4. `telemetry_tool/shared/geometry/frenet.py` exists, exports `FrenetFrame`.
5. `git log origin/main --grep "signal:W5-done"` returns exactly one commit.
6. `pytest telemetry_tool/tests/ kart_envelope/tests/ -x -q` is green on main.

If any fail: stop, escalate, do not polyfill missing W5 primitives inside `optimizer_v2/`.

---

**Status**: Plan-only. Awaiting `/approve` + W5 merge to main before implementation begins.
