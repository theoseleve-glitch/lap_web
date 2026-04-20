---
title: Unified Telemetry Coaching & Optimization — Technical Architecture & Work Breakdown
date: 2026-04-19
status: draft
owner: product
scope: Backend + Frontend + Data + ML
---

# Unified Telemetry Coaching & Optimization

A single-upload product surface that serves both real-life on-track sessions (GPS+IMU from RaceChrono/RaceBox) and simracing sessions (iRacing, Assetto Corsa, future sims). Internally, two distinct engine families analyze the data; externally, users see one history, one session view, one coach. Depth of coaching and optimization scales automatically with data richness.

## 1. Vision

- **One upload**: any supported file type, one dropzone.
- **One history**: all sessions in the same list, source-agnostic.
- **One session view**: panels conditionally render based on data available — no visible "this is the sim page".
- **Two engine families**:
  - Real-life coach & optimizer use only the output of the car (GPS + accelerations + speeds). Over/understeer is *inferred*, driver inputs are *reconstructed*.
  - Simracing coach & optimizer get direct driver inputs + full vehicle state + precise track data. They provide deeper coaching and higher-fidelity optimization.
- **Per-game specialization**: one real-life coach, one sim coach per game (iRacing, AC, ACC, LMU, F1…). All consume the same shared coaching library; each declares the detectors it enables.

## 2. Target Architecture

```
┌─ Unified upload endpoint ─────────────────────────────────────┐
│                                                                │
│   ┌──────────────────────┐                                     │
│   │ Data Profile Detector│  classify file + detect channels    │
│   └──────────┬───────────┘                                     │
│              │                                                  │
│   ┌──────────▼──────────┐                                      │
│   │   Ingest Router      │  select pipeline                    │
│   └────┬──────┬──────┬──┘                                      │
│        │      │      │                                          │
│        ▼      ▼      ▼                                          │
│   ┌────────┐ ┌─────────┐ ┌─────────┐                           │
│   │Real-life│ │iRacing  │ │AC       │  …future sims            │
│   │pipeline │ │pipeline │ │pipeline │                          │
│   └────┬───┘ └─────┬───┘ └────┬────┘                           │
│        │           │          │                                 │
│        └───────────┴──────────┘                                 │
│                    │                                            │
│                    ▼                                            │
│        ┌────────────────────────┐                              │
│        │  Unified Contracts     │                              │
│        │  · SessionContract     │                              │
│        │  · CoachingContract    │                              │
│        │  · OptimizerContract   │                              │
│        └──────────┬─────────────┘                              │
│                   │                                             │
│   ┌───────────────┴────────────────┐                           │
│   ▼                                ▼                            │
│ ┌─────────────────────┐  ┌───────────────────────┐              │
│ │  Coach Dispatcher   │  │ Optimizer Dispatcher  │              │
│ │                     │  │                       │              │
│ │  selects coach:     │  │  selects engine:      │              │
│ │  · RealLifeCoach    │  │  · TrajectoryOnlyOpt  │              │
│ │  · IRacingCoach     │  │  · FullFidelityOpt    │              │
│ │  · ACCoach          │  │  (based on caps)      │              │
│ │  · …                │  │                       │              │
│ │                     │  │                       │              │
│ │  Each uses shared   │  │  Each emits           │              │
│ │  detector registry  │  │  OptimizerContract    │              │
│ │  filtered by        │  │                       │              │
│ │  capabilities.      │  │                       │              │
│ └─────────────────────┘  └───────────────────────┘              │
│                                                                 │
└────────────────────┬────────────────────────────────────────────┘
                     │  one unified contract
                     ▼
             ┌───────────────┐
             │  Frontend     │  history list + session page
             │               │  panels render per capabilities
             └───────────────┘
```

**Key principle — capability-tagged detectors**: each detector in the coaching library declares the channels it needs (`needs={"gps","lat_g"}` or `needs={"throttle","brake","steer"}`). At runtime, a coach only activates the detectors whose needs are satisfied by the session's data profile. This is how depth scales automatically — no if/else on data source.

## 3. Scope

### In scope (this program)
- Unified upload endpoint accepting real-life CSV (RaceChrono / RaceBox) and iRacing IBT
- AC telemetry flows in through our own `lap_oracle` data logger (internal ingestion path — not a user upload surface)
- Data-profile detector + ingest router
- Three contracts: Session, Coaching, Optimizer
- Per-engine pipeline adapters (real-life, iRacing, AC)
- Capability-tagged coaching library with shared detector registry
- Per-game coach identity (`RealLifeCoach`, `IRacingCoach`, `ACCoach`) sharing the detector registry
- Optimizer dispatcher with trajectory-only + full-fidelity engines
- Unified frontend: single upload surface, single session view, small source tag in history list (see §10 decision 4), conditional panels
- Storage layout for mixed sources (raw sidecars + metadata) with tiered retention (§10 decision 3)

### Explicitly out of scope
- User-uploaded AC CSV or ACC log files (AC data is captured by our own `lap_oracle` automation; other sims are not in first pass)
- Scoring system overhaul (stays as-is; wrapped by contract adapter)
- Auth, workspace, RBAC, billing (unchanged)
- Track surface analysis changes (Side A feature, no dispatch needed)
- Endurance race strategy (Side A feature, unchanged)
- New sim sources beyond iRacing + AC in first pass (extensibility preserved)

## 4. Workstream Catalog

| ID | Name | Size | Depends on | Parallel after |
|----|------|------|------------|----------------|
| W1 | Unified Session / Coaching / Optimizer Contracts | L | — | — foundational |
| W2 | Data Profile + Ingest Router | M | W1 | W1 |
| W3 | Real-life Pipeline → Contracts Adapter | M | W1 | W1 |
| W4a | iRacing Pipeline → Contracts Adapter | M | W1, W5 | W1 + W5.T5.1 |
| W4b | AC Pipeline → Contracts Adapter | M | W1, W5 | W1 + W5.T5.1 |
| W5 | Shared Kernels (geometry, physics, coaching taxonomy) | L | — | can start parallel to W1 |
| W6 | Capability-Tagged Coaching Registry + Coaches | L | W1, W5 | W1 + W5 |
| W7 | Optimizer Dispatcher (trajectory-only + full-fidelity) | M | W1, W5 | W1 + W5 |
| W8 | Frontend Unification (upload, history, session view) | XL | W1 | W1 (mockable earlier) |
| W9 | Multi-source Storage Layout + Migration | M | W1 | W1 |
| W10 | Integration & E2E Tests | L | every WS incrementally | wraps all |

**Size legend**: S = 1–2 days · M = 3–5 days · L = 1–2 weeks · XL = 2+ weeks

## 5. Detailed Workstream Breakdown

### W1 — Unified Contracts

**Why**: The contract is the linchpin. Without it, every engine needs its own frontend and every new sim forces UI changes. With it, new sims only need an adapter — UI, history, coaching stay untouched.

**Tech stack**
- Pydantic v2 models in `telemetry_tool/web/schemas/contracts/`
- JSON Schema export
- TypeScript types generated into `lap-website/src/types/contracts.ts`
- Alembic migration for `sessions` table

**Tasks**
| Task | Description | Est | Blocks |
|------|-------------|-----|--------|
| T1.1 | Define `SessionContract` schema (metadata, laps, trajectory, events, scores, capabilities flags) | 1d | W2, W3, W4, W8, W9 |
| T1.2 | Define `CoachingContract` schema (harmonize with existing prescriptive output) | 1d | W6, W8 |
| T1.3 | Define `OptimizerContract` schema (theoretical_lap, delta_trace, corner_deltas, reconstructed_inputs) | 1d | W7, W8 |
| T1.4 | Emit JSON schemas + generate TypeScript types | 0.5d | W8 |
| T1.5 | Alembic migration: `sessions` adds `source TEXT`, `data_profile JSONB`, `capabilities JSONB` | 0.5d | W9 |
| T1.6 | Contract validation tests + backward-compat for existing session data | 1d | W10 |

**Done when**: Contracts importable, validation tests pass, TS types regenerate, migration applies cleanly.

---

### W2 — Data Profile + Ingest Router

**Why**: Every upload must be classified (what kind?) and routed (which pipeline?) transparently.

**Tech stack**
- New: `telemetry_tool/ingest/profiler.py`, `telemetry_tool/ingest/router.py`
- Modified: `telemetry_tool/web/routes/sessions_v2.py`
- Celery queue split (new `sim` queue in `telemetry_tool/tasks/`)

**Tasks**
| Task | Description | Est |
|------|-------------|-----|
| T2.1 | Profiler: detect file type by magic bytes + header heuristics. User-uploadable sources in first pass: RC CSV, IBT. Internal source routed separately: AC (via lap_oracle). Profiler should include enum scaffolding for future LMU / ACC / F1 24 without wiring them yet. | 1d |
| T2.2 | Profiler output: `DataProfile { source, channels_available, suggested_engine, confidence }` | 0.5d |
| T2.3 | Router: `route(profile) -> EngineHandler` | 0.5d |
| T2.4 | Modify `POST /api/v1/sessions/upload` to accept RC CSV + iRacing IBT, delegate to profiler + router. Reject AC/ACC/LMU/F1 uploads with a 415 + message steering users to the logger. | 1d |
| T2.5 | Celery queue split: `pipeline` (real-life), `sim` (sim engines — currently iRacing user uploads + AC internal flow) | 0.5d |
| T2.6 | Integration test: upload 2 sample user files (RC CSV + IBT) + separately invoke the AC internal path, verify correct routing | 0.5d |

**Done when**: Single user-facing upload endpoint accepts RC CSV + IBT; AC sessions arrive via internal lap_oracle flow; all three paths route correctly; contracts returned.

---

### W3 — Real-life Pipeline Adapter

**Why**: The existing 14-stage pipeline already works — it just needs to emit the new contracts.

**Tech stack**
- New: `telemetry_tool/pipeline/contract_adapter.py`
- Minor hooks in `telemetry_tool/pipeline/orchestrator.py`

**Tasks**
| Task | Description | Est |
|------|-------------|-----|
| T3.1 | Map stage outputs → `SessionContract` fields | 1d |
| T3.2 | Map prescriptive + corner coaching output → `CoachingContract` | 1d |
| T3.3 | Map theoretical output (stub) → `OptimizerContract` | 0.5d |
| T3.4 | Declare real-life capabilities: `{has_gps, has_imu, has_throttle=false, has_brake=false, has_steer=false, ...}` | 0.5d |
| T3.5 | Snapshot regression tests: existing outputs match new contract emission | 1d |

**Done when**: Existing real-life CSVs produce valid contracts; no regression in stored session data.

---

### W4 — Simracing Pipeline Adapters

#### W4a — iRacing

**Tech stack**
- New: `telemetry_tool/sim_optimizer/contract_adapter.py`
- Minor hooks in `telemetry_tool/sim_optimizer/pipeline.py`
- Productize `pipeline_tasks.py:504` existing IBT loader

**Tasks**
| Task | Description | Est |
|------|-------------|-----|
| T4a.1 | Map sim_optimizer output → SessionContract + OptimizerContract | 1d |
| T4a.2 | Declare iRacing capabilities (throttle, brake, steer, yaw_rate, wheel_spd, shock_defl, tire_temps, ...) | 0.5d |
| T4a.3 | Productize IBT raw Parquet sidecar storage (finish what `pipeline_tasks.py:504` started) | 1.5d |
| T4a.4 | Integration test: upload IBT → full contracts | 0.5d |

#### W4b — AC

**Tech stack**
- New: `telemetry_tool/lap_oracle/ac_contract_adapter.py`
- Reuse: `telemetry_tool/lap_oracle/extractors/ac_files.py`
- Decide: does AC go through `sim_optimizer` or a lightweight AC-specific path?

**Source flow**: AC data arrives only from our own `lap_oracle` automation (§10 decision 1). There is no user upload path for AC — T4b therefore focuses on the internal ingestion boundary (lap_oracle output → SessionContract), not on the upload endpoint.

**Tasks**
| Task | Description | Est |
|------|-------------|-----|
| T4b.1 | Map AC telemetry (lap_oracle output) → SessionContract | 1d |
| T4b.2 | Declare AC capabilities (likely similar to iRacing with some deltas — wheel_spd present, shock_defl may be absent depending on car) | 0.5d |
| T4b.3 | Decide + implement: AC → sim_optimizer or dedicated AC path | 1.5d |
| T4b.4 | Integration test — invoke internal AC ingestion (no HTTP upload), assert SessionContract produced | 0.5d |

**Done when**: iRacing user-uploaded sessions AND internal AC-captured sessions both produce valid SessionContract + downstream contracts.

---

### W5 — Shared Kernels

**Why**: Both sides need geometry, physics primitives, and coaching taxonomy. Today these live inside `kart_envelope/` (Side A). Neutral home prevents future coupling issues.

**Tech stack**
- New package: `telemetry_tool/shared/`
  - `shared/geometry/` — `TrackGeometry`, `FrenetFrame`
  - `shared/physics/` — `FrictionModel`, `VehicleModel` base
  - `shared/coaching_taxonomy/` — pattern ontology (per 2026-04-17 refactor roadmap)

**Tasks**
| Task | Description | Est |
|------|-------------|-----|
| T5.1 | Move `kart_envelope/track/geometry.py::TrackGeometry` → `shared/geometry/track.py` with deprecation shim | 0.5d |
| T5.2 | Identify cross-side physics primitives; move to `shared/physics/` | 1.5d |
| T5.3 | Move coaching taxonomy (`coaching/taxonomy`, `coaching/models.py`, `coaching/templates`) → `shared/coaching_taxonomy/` | 2d |
| T5.4 | Update imports in sim_optimizer + kart_envelope + pipeline to use shared kernels (blocked on W1 capability enum) | 1d |
| T5.5 | Backward-compat re-exports + one-cycle deprecation | 0.5d |

**Done when**: No module outside `shared/` owns a cross-side primitive; all tests pass.

---

### W6 — Capability-Tagged Coaching

**Why**: Depth-scaling with data happens automatically via detector registry. No if/else on source.

**Tech stack**
- New package: `telemetry_tool/coaching_v2/`
  - `registry.py` — detector registry with capability declarations
  - `detectors/` — each detector = class with `NEEDS: set[ChannelTag]`, `detect(session)` method
  - `coaches/real_life.py`, `coaches/iracing.py`, `coaches/ac.py`
  - `coaches/base.py` — shared assembler logic

**Tasks**
| Task | Description | Est |
|------|-------------|-----|
| T6.1 | Define `ChannelTag` enum (GPS, LAT_G, LON_G, YAW_RATE, THROTTLE, BRAKE, STEER, WHEEL_SPD, SHOCK_DEFL, …) | 0.5d |
| T6.2 | `DetectorRegistry` with `register(detector)` + `for_capabilities(caps)` | 1d |
| T6.3 | Migrate existing real-life detectors into registry (handling/, track_surface/prescriptive/) | 2d |
| T6.4 | Add input-based detectors: throttle-lift pattern, trail-brake accuracy, steering smoothness, pedal overlap | 3d |
| T6.5 | Build coach assemblers: RealLifeCoach, IRacingCoach, ACCoach | 1.5d |
| T6.6 | Coach dispatcher: `get_coach(capabilities) -> Coach` | 0.5d |
| T6.7 | Emit CoachingContract | 0.5d |

**Done when**: Real-life session gets N output-based events; iRacing session gets N+M input-aware events from the same registry.

---

### W7 — Optimizer Dispatcher

**Why**: Same principle as coaching — different data depth, different optimizer quality.

**Tech stack**
- New: `telemetry_tool/optimizer_v2/dispatcher.py`
- Reuse: `sim_optimizer/solver/qss_enhanced.py` (full-fidelity, needs inputs + physics)
- Reuse: existing real-life trajectory optimizer (`reference_line.py`, `raceline_optimizer.py`)

**Tasks**
| Task | Description | Est |
|------|-------------|-----|
| T7.1 | Define `OptimizerEngine` interface | 0.5d |
| T7.2 | `TrajectoryOnlyOptimizer` (real-life — GPS+accel only) | 1.5d |
| T7.3 | `FullFidelityOptimizer` wrapper around sim_optimizer | 1d |
| T7.4 | Dispatcher picks engine by capabilities | 0.5d |
| T7.5 | Emit OptimizerContract with confidence/depth metadata | 0.5d |
| T7.6 | Tests: both paths produce valid output; sim path produces deeper insights | 1d |

**Done when**: Real-life + sim sessions both have optimizer views; sim version includes input traces + delta attribution.

---

### W8 — Frontend Unification

**Why**: The user-facing surface. One upload, one history, one session view rendering whatever the contract contains.

**Tech stack**
- Next.js 14 App Router
- `lap-website/src/app/app/sessions/*` (existing, major refactor)
- `lap-website/src/components/session/*` (new panels)
- TanStack Query for contract fetching
- Generated TS types from W1.T1.4

**Tasks**
| Task | Description | Est |
|------|-------------|-----|
| T8.1 | Refactor upload page: single dropzone, shows detected source post-parse | 2d |
| T8.2 | Session list: add source badge + capability indicators | 1.5d |
| T8.3 | Session detail: panel registry; conditionally render based on contract capabilities | 3d |
| T8.4 | Coaching panel: render from CoachingContract; gracefully show "limited depth" for real-life | 2d |
| T8.5 | Optimizer panel: deeper visuals for sim (input delta trace), simpler for real-life | 2d |
| T8.6 | TS types from JSON schemas; wire into `api-client.ts` | 0.5d |
| T8.7 | Playwright E2E: upload real-life → session page; upload IBT → session with extra panels | 1d |

**Done when**: User cannot tell from UI which pipeline ran; only data-dependent panels differ.

---

### W9 — Multi-source Storage Layout

**Why**: iRacing IBT = 332 channels × 360 Hz = tens of MB per session. Must use parquet sidecars. Session metadata gains source + profile + capabilities.

**Tech stack**
- PostgreSQL 16 (existing schema + new cols from W1.T1.5)
- Parquet sidecars via `parquet_manager.py`
- New: `telemetry_tool/storage/sidecar_store.py`

**Tasks**
| Task | Description | Est |
|------|-------------|-----|
| T9.1 | Migration implemented in W1.T1.5 — verify + integrate | 0.5d |
| T9.2 | `SidecarStore.save(session_id, source, df)` + `.load(session_id)` | 1.5d |
| T9.3 | Tiered retention policy for raw sidecars — paid tiers keep longer; internal retention is long-term because sidecars are training data for ML models (§10 decision 3) | 1d |
| T9.4 | Backfill existing sessions: set `source="real_life"`, default capabilities | 0.5d |
| T9.5 | Rollback plan for migration | 0.5d |

**Done when**: Any session (any source) has durable storage + can be reloaded for re-analysis.

---

### W10 — Integration & E2E Tests

**Tech stack**
- `pytest` (backend), Playwright (frontend)
- Fixtures: 1 RC CSV, 1 iRacing IBT, 1 AC CSV — committed sample files

**Tasks**
| Task | Description | Est |
|------|-------------|-----|
| T10.1 | Backend per-engine smoke: upload → pipeline → contracts produced | 1d |
| T10.2 | Backend contract validity: Pydantic validation across all three paths | 0.5d |
| T10.3 | Frontend E2E per source: upload → history shows → session view renders | 1d |
| T10.4 | Cross-source regression: existing real-life sessions render identically | 0.5d |
| T10.5 | CI gates blocking regressions | 0.5d |

## 6. Dependency Graph

```
                        ┌──────────────────────────────┐
                        │  W1 Unified Contracts         │  ← blocks nearly everything
                        └──────────────────┬────────────┘
                                           │
     ┌──────────┬──────────┬───────────────┼────────────┬────────────┐
     ▼          ▼          ▼               ▼            ▼            ▼
 ┌────────┐ ┌─────────┐ ┌─────────┐ ┌─────────────┐ ┌─────────┐ ┌─────────┐
 │ W2     │ │ W5      │ │ W9      │ │ W10 scaffold│ │ W8      │ │ W3 real │
 │ Router │ │ Shared  │ │ Storage │ │             │ │ FE prep │ │ pipeline│
 └───┬────┘ │ Kernels │ └─────────┘ └─────────────┘ └─────────┘ └─────────┘
     │      └────┬────┘
     │           │
     ▼           ▼
 ┌──────────────────────────────────────────────┐
 │ W4a iRacing adapter                          │
 │ W4b AC adapter                               │
 │ W6 Coach registry + per-game coaches         │
 │ W7 Optimizer dispatcher                      │
 └─────────────────────┬────────────────────────┘
                       │
                       ▼
               ┌────────────────┐
               │ W8 FE (full)   │  panels consume contracts
               │ W10 E2E full   │  cross-path regression
               └────────────────┘
```

## 7. Phased Execution Plan

### Phase 0 — Foundation (serial, ~1 week)
- **W1** entire workstream
- **W5.T5.1** (TrackGeometry extraction) can start in parallel if a second dev is free

### Phase 1 — Parallel Build (~2 weeks, wide fan-out)
All concurrent once Phase 0 complete:
- **W2** Router — backend dev
- **W3** Real-life adapter — backend dev (real-life expert)
- **W4a** iRacing adapter — backend dev (sim_optimizer expert)
- **W4b** AC adapter — backend dev (lap_oracle expert)
- **W5.T5.2–T5.5** Shared kernels completion — backend dev
- **W6** Coach registry — backend + domain expert (coaching)
- **W7** Optimizer dispatcher — backend + physics specialist
- **W8** Frontend (upload + history + panel registry) — frontend dev
- **W9** Storage — backend + DBA
- **W10** Test scaffolding — QA

### Phase 2 — Integration (~1 week)
- All engines emit contracts
- Router dispatches end-to-end for all three sources
- Frontend consumes contracts, renders per source
- E2E green for all three paths

### Phase 3 — Launch prep (~3 days)
- Session backfill migration (source/capabilities)
- Performance testing with 10 GB iRacing IBT
- Staging deploy → smoke tests → production

## 8. Parallelism Matrix

Legend: ✅ can run concurrently, ❌ blocked.

| After Phase 0 done | W2 | W3 | W4a | W4b | W5-rest | W6 | W7 | W8 | W9 | W10 |
|--------------------|----|----|-----|-----|---------|----|----|-----|-----|-----|
| **W2**             | —  | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **W3**             | ✅ | —  | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **W4a**            | ✅ | ✅ | — | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **W4b**            | ✅ | ✅ | ✅ | — | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **W5-rest**        | ✅ | ✅ | ✅ | ✅ | — | ❌¹ | ❌¹ | ✅ | ✅ | ✅ |
| **W6**             | ✅ | ✅ | ✅ | ✅ | ❌¹ | — | ✅ | ✅ | ✅ | ✅ |
| **W7**             | ✅ | ✅ | ✅ | ✅ | ❌¹ | ✅ | — | ✅ | ✅ | ✅ |
| **W8**             | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — | ✅ | ✅ |
| **W9**             | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — | ✅ |
| **W10**            | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |

¹ W6 and W7 need W5's coaching taxonomy + physics primitives before starting their main work. W6/W7 *design* tasks (T6.1, T7.1) can start but implementation waits.

**Bottlenecks**: W1 is the single serialization point. Once W1 is done, 8 workstreams can genuinely run in parallel if team capacity allows.

## 9. Role Matrix

| Role | Primary | Secondary |
|------|---------|-----------|
| Backend Lead | W1, W2, W5 | W10 |
| Backend Dev — real-life | W3, W6 (real-life detectors) | W10 |
| Backend Dev — simracing | W4a, W4b, W7 | W6 (sim detectors) |
| ML / Physics Specialist | W6 detector design, W7 optimizer core | W5 physics |
| Frontend Lead | W8 | W1 (TS gen) |
| DBA / Data Eng | W9 | W1 migration |
| QA | W10 | All |

### Minimum viable team (3 people, ~6 weeks)
- 1 backend lead (full-time) — W1, W2, W5, W10
- 1 backend dev (full-time) — W3, W4a, W4b, W6, W7
- 1 frontend dev (part-time Phase 0, full-time Phase 1–2) — W8

### Aggressive parallel team (6–7 people, ~3 weeks after Phase 0)
- 1 backend lead — W1, W2, W5
- 1 backend dev (real-life) — W3, W6-partial
- 1 backend dev (simracing) — W4a, W4b, W7
- 1 ML/physics specialist — W6, W7 detectors
- 1 frontend dev — W8
- 1 DBA/data — W9
- 1 QA — W10

## 10. Risks & Open Questions

| Risk | Impact | Mitigation |
|------|--------|------------|
| iRacing IBT size (tens of MB × thousands of sessions) | Storage cost balloons | Parquet compression + retention policy (W9.T9.3) |
| Capability detection false positives | Coach runs wrong detectors | Explicit channel-presence check after parse, not just source tag |
| Frontend contract drift | UI breaks on backend schema change | Generated TS types in CI, contract versioning in W1 |
| Existing sessions backfill | User history mis-renders or disappears | W9.T9.4 migration + rollback plan (T9.5) |
| sim_optimizer requires raw channel pipeline work | W4a blocked | T4a.3 scoped explicitly to productize existing seed |
| `shared/` refactor breaks currently-passing tests | Phase 0 slows | T5.5 backward-compat re-exports kept one release cycle |
| Two Celery queues compete for memory | Workers OOM on IBT + real-life concurrent | Queue-aware memory limits, tested in W9 + W10 |

### Product-owner decisions (resolved 2026-04-20)

1. **AC telemetry source** — **only from our own `lap_oracle` data logger**. No user-uploaded AC CSVs. W4b scope narrows: the AC adapter consumes lap_oracle output internally; the W2 router does NOT accept AC uploads. The user-facing upload surface covers real-life CSV + iRacing IBT only.

2. **Per-game vs capability-only coaches** — **per-game coach identity**. `RealLifeCoach`, `IRacingCoach`, `ACCoach`, plus future `LMUCoach`, `ACCCoach`, `F1Coach`. All share the detector registry from W6; game-specific classes carry game-specific thresholds, templates, and coaching language.

3. **Sidecar retention** — **tiered**. Paid tiers keep raw sidecars longer than free tier. Crucially, raw sidecars are **internally retained long-term for ML model training** — so even after a user-facing retention window expires, the data is preserved on our side for training datasets. W9.T9.3 must design the policy with two axes: user-facing retention (tier-based) vs internal retention (long-term for ML).

4. **Source visibility in UI** — **small source tag, yes**. Philosophy framing: "one big brain computing whatever data you give it" — the user must NEVER feel they're using two different products. But a compact tag (`GPS` / `iRacing` / `AC` / `LMU` …) in the history list is acceptable because it helps users understand why *their own* session has richer vs simpler panels. W8 executes this as a subtle badge, not a first-class filter dimension.

5. **Sim support priority order after iRacing + AC** — **LMU → ACC → F1 24**. This determines W2/W4 extensibility roadmap and which channel profile gets studied next. LMU is third sim source; ACC fourth; F1 24 fifth.

## 11. System-level Acceptance Criteria

**User-uploaded sources** via the single upload endpoint:
1. RaceChrono CSV (GPS+IMU)
2. RaceBox CSV
3. iRacing IBT

**Internal source** (arrives via lap_oracle automation, not exposed as an upload):
4. AC telemetry

For each of the four sources:
- Session appears in unified history with a small source tag (`GPS` / `iRacing` / `AC`)
- Coaching panel populates — depth matches data richness (fewer events for real-life, more for sim)
- Optimizer panel populates — depth matches data richness (trajectory-only vs input+output)
- No visible error for data that's genuinely absent (graceful degradation)
- Session re-analysis possible from stored raw sidecar (tier-gated user retention + internal long-term retention for ML)
- User experience does not reveal that multiple pipelines exist — "one big brain" framing

## 12. What is NOT this spec

This document is architectural + work breakdown. It does NOT specify:
- Exact Pydantic field names (decided in W1 implementation)
- Exact detector thresholds (decided in W6 implementation)
- Exact UI layouts (decided in W8 implementation with designer input)
- Estimate confidence beyond T-shirt sizes (individual task owners size precisely during planning)

Each workstream owner produces their own implementation plan (`docs/superpowers/plans/YYYY-MM-DD-WX-<name>.md`) referencing this spec as the design anchor.

---

**Status**: Draft, awaiting owner review.  
**Next step on approval**: Invoke `writing-plans` skill to decompose highest-priority workstream (recommended: W1) into an implementation plan.
