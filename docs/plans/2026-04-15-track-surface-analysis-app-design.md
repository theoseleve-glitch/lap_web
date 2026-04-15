# Track-Surface Analysis Application Layer — Design

**Date**: 2026-04-15
**Status**: Design — awaiting approval
**Owner**: backend / platform
**Branch**: `feat/track-surface-app` (to be created from `feat/logger-download-sync` or `main`)

---

## 1. Context

The validated track-surface physics stack (under `telemetry_tool/track_surface/`) is now
release-gated and stable. Upstream consumers — the Next.js web app and the desktop
client — cannot consume it directly because:

1. `validation.harness.run_pipeline()` returns a `PipelineResult` dataclass with 40+
   fields (internal diagnostics, numpy arrays, evidence counts). This is a research
   artifact, not a product contract.
2. There is no concept of **user-facing support tier** in the core. Fallback depth,
   confidence, and release-gate verdicts are all present, but no layer combines them
   into a single gating decision the frontend can render against.
3. Outputs are not persisted in any frontend-queryable form. Each run is recomputed.
4. Unsupported (sim, vehicle, track) combinations silently return low-confidence
   results instead of refusing advanced features.

This design introduces a **thin application layer** that wraps the frozen core, adds
support-tier gating, persists per-session analysis runs, and exposes a stable REST
contract. **No physics logic changes.**

## 2. Goals

- A frontend can request an analysis through a stable API and receive typed summaries,
  artifacts, and a support tier.
- Advanced planner outputs (robust / exploitable modes) are never served without
  support-tier metadata.
- Unsupported sessions fail explicitly with a reason code, not silently.
- Artifacts are persisted per-run and fetchable without re-running the pipeline.
- UI can pre-query `/support/resolve` to know which controls to enable before the user
  even uploads a session.

## 3. Non-goals

- No new physics or numerical methods.
- No changes to the research-layer modules (`track_surface/*`) beyond one unavoidable
  import.
- No replacement for the existing 14-stage pipeline in `sessions_v2.py`. This layer
  runs **alongside** it, triggered separately.
- No cross-workspace features in v1 (each `analysis_runs` row is workspace-scoped via
  RLS).

## 4. Architecture

```
                              ┌────────────────────────────────────────┐
HTTP                          │  NEW: telemetry_tool/track_surface_app │
─────►  routes/track_surface_analysis.py   (wraps, does not re-run)    │
        │                     │                                        │
        │  POST /run          │   AnalysisOrchestrator                 │
        │  GET  /summary etc. │     │                                  │
        │                     │     ▼                                  │
        │                     │   Celery task (queue="pipeline")       │
        │                     │     │                                  │
        │                     │     ▼                                  │
        │                     │   validation.harness.run_pipeline()   ─┼──► FROZEN CORE
        │                     │     │                                  │    (track_surface/*)
        │                     │     ▼                                  │
        │                     │   validation.release_gate.evaluate()  ─┤
        │                     │     │                                  │
        │                     │     ▼                                  │
        │                     │   SupportTierResolver                  │
        │                     │     │                                  │
        │                     │     ▼                                  │
        │                     │   OutputGate  ──►  ArtifactWriter      │
        │                     │     │                                  │
        │                     │     ▼                                  │
        │                     │   AnalysisRunRepository  ──►  DB + FS  │
        │                     └────────────────────────────────────────┘
        ▼
   JSON response (support-tier-gated, persisted artifacts linkable)
```

### 4.1 Bounded contexts

- **Core (frozen)** `telemetry_tool/track_surface/` — physics, validation,
  release gate. Internal data structures (`PipelineResult`, `ReleaseSessionResult`,
  `BucketQueryResult`, `GripPolicyPoint`, etc.) live here.
- **Application (new)** `telemetry_tool/track_surface_app/` — orchestration, gating,
  DTO translation, persistence. This package is the only place that imports from
  `track_surface.validation`.
- **Adapter (new)** `telemetry_tool/web/routes/track_surface_analysis.py` — Flask
  blueprint, purely HTTP concerns. Does not know about `PipelineResult`.
- **Contracts (new)** `telemetry_tool/web/schemas/track_surface.py` — Pydantic v2
  request/response DTOs. The only types crossing the HTTP boundary.

### 4.2 Module layout

```
telemetry_tool/track_surface_app/
├── __init__.py
├── domain.py              # Enums + domain dataclasses (SupportTier, ...)
├── orchestrator.py        # AnalysisOrchestrator.enqueue(session_id, options)
├── support.py             # SupportTierResolver.resolve(...)
├── gating.py              # OutputGate — filters advanced outputs by tier
├── artifacts.py           # ArtifactWriter — PipelineResult → DTO JSON files
├── persistence.py         # AnalysisRunRepository — DB CRUD
└── support_matrix.py      # Static (sim, vehicle, track) → supported tier lookup

telemetry_tool/tasks/track_surface_tasks.py    # Celery task entry point

telemetry_tool/web/routes/track_surface_analysis.py  # Blueprint (9 endpoints)
telemetry_tool/web/schemas/track_surface.py          # Pydantic v2 DTOs

telemetry_tool/alembic/versions/056_analysis_runs.py   # Migration

telemetry_tool/tests/test_track_surface_app/
├── conftest.py            # Fake PipelineResult / ReleaseDecision fixtures
├── test_support_resolver.py
├── test_output_gate.py
├── test_artifact_writer.py
├── test_persistence.py
├── test_orchestrator.py
├── test_support_matrix.py
└── test_routes.py
```

## 5. Domain model

### 5.1 `SupportTier` (enum)

The user-facing abstraction. This is the single concept the frontend gates UX on.

| Value | Meaning | Planner modes exposed |
|-------|---------|------------------------|
| `A` | Fully supported. Release gate PASS, validated profiles, low fallback. | nominal + robust + **exploitable** |
| `B` | Partially supported. Release gate WARN, or moderate fallback depth. | nominal + robust only |
| `C` | Descriptive only. Release gate FAIL, or heavy fallback, or missing calibration but has GPS+speed. | none — only lap-trace analytics |
| `D` | Unsupported. Cannot run analysis at all. | none |

### 5.2 `ConfidenceLevel` (enum)

Derived from mean `field_confidence` across accepted points.

| Value | Condition |
|-------|-----------|
| `HIGH` | mean confidence ≥ 0.80 |
| `MEDIUM` | 0.50 ≤ mean confidence < 0.80 |
| `LOW` | mean confidence < 0.50 |
| `UNKNOWN` | no confidence data (e.g. tier D) |

### 5.3 `AnalysisRunStatus` (enum)

`queued` → `running` → `succeeded` / `failed` (terminal).

### 5.4 `SupportReason` (string codes)

Machine-readable codes for why a tier was assigned. Closed set:

- `all_checks_passed`
- `release_gate_warn`
- `release_gate_fail`
- `high_global_fallback`
- `vehicle_profile_not_validated`
- `track_profile_not_validated`
- `track_geometry_missing`
- `calibration_missing`
- `insufficient_channels`
- `gps_speed_only_available`

### 5.5 `PlannerModeAvailability`

```python
@dataclass(frozen=True)
class PlannerModeAvailability:
    nominal: bool
    robust: bool
    exploitable: bool
```

### 5.6 `AnalysisRun` (internal aggregate, not HTTP)

```python
@dataclass
class AnalysisRun:
    run_id: str                          # UUID
    session_id: int
    workspace_id: int
    status: AnalysisRunStatus
    support_tier: SupportTier | None     # None while queued/running
    support_reason: str | None
    confidence_level: ConfidenceLevel | None
    fallback_depth_distribution: dict[int, float] | None  # {0: 0.72, 1: 0.20, 2: 0.08}
    validated_vehicle_profile: str | None
    validated_track_profile: str | None
    planner_mode_availability: PlannerModeAvailability | None
    warnings: list[str]
    artifacts_index: dict[str, str]      # {"surface_field": "path/to.json", ...}
    release_decision: str | None         # "pass" | "warn" | "fail"
    pipeline_summary: dict | None        # sanitized PipelineResult subset
    error_code: str | None
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None
```

## 6. Schemas (HTTP contracts)

All schemas use Pydantic v2 `BaseModel` with `ConfigDict(extra="forbid")` on requests
and `extra="ignore"` on responses. Follow the `StrictSchema` / `LenientSchema` pattern
already in `schemas/common.py`.

### 6.1 Requests

```python
class RunAnalysisRequest(StrictSchema):
    # Optional overrides — omit to use session defaults
    vehicle_profile_override: str | None = None
    planner_modes: list[Literal["nominal", "robust", "exploitable"]] | None = None
    force_rerun: bool = False

class ResolveSupportParams(StrictSchema):
    sim: str                 # e.g. "iracing", "ac"
    vehicle: str             # e.g. "mx5"
    track: str               # e.g. "daytona_rc"
```

### 6.2 Responses (all wrapped in `{ok, data, error, meta}` envelope)

```python
class AnalysisRunSummary(LenientSchema):
    run_id: str
    session_id: int
    status: Literal["queued", "running", "succeeded", "failed"]
    support_tier: Literal["A", "B", "C", "D"] | None
    support_reason: str | None
    confidence_level: Literal["high", "medium", "low", "unknown"] | None
    fallback_depth_pct: dict[str, float] | None        # {"0": 72.0, "1": 20.0, "2": 8.0}
    validated_vehicle_profile: str | None
    validated_track_profile: str | None
    planner_mode_availability: PlannerModeAvailabilityDTO | None
    warnings: list[str]
    artifacts_available: list[str]                     # ["summary", "surface", ...]
    release_decision: Literal["pass", "warn", "fail"] | None
    error_code: str | None
    error_message: str | None
    created_at: str                                    # ISO 8601
    completed_at: str | None

class SessionSummary(LenientSchema):
    run_id: str
    session_id: int
    n_laps_analyzed: int
    n_samples_accepted: int
    n_samples_rejected: int
    lap_time_median_s: float | None
    lap_time_best_s: float | None
    warnings: list[str]
    # Always present — never gated. Same info appears on tier C/D.

class TrackSurfaceSummary(LenientSchema):
    run_id: str
    coverage_pct: float
    mean_confidence: float
    confidence_level: Literal["high", "medium", "low"]
    fallback_depth_pct: dict[str, float]
    lambda_in_band_pct: float
    bucket_active_count: int
    bucket_sparse_count: int

class PlannerSummary(LenientSchema):
    run_id: str
    support_tier: Literal["A", "B", "C", "D"]
    available_modes: list[str]                         # filtered by tier
    nominal: PlannerModeResult | None
    robust: PlannerModeResult | None
    exploitable: PlannerModeResult | None              # only tier A
    unavailable_reason: str | None                     # non-None when no modes available

class PlannerModeResult(LenientSchema):
    mode: Literal["nominal", "robust", "exploitable"]
    mu_eff_median: float
    mu_eff_min: float
    mu_eff_max: float
    boundary_scale_median: float
    trusted_point_count: int
    total_point_count: int

class UncertaintySummary(LenientSchema):
    run_id: str
    confidence_histogram: list[tuple[float, float, int]]  # [(low, high, count)]
    std_p50: float
    std_p95: float
    evidence_count_total: int

class SupportSummary(LenientSchema):
    run_id: str | None
    sim: str | None
    vehicle: str | None
    track: str | None
    support_tier: Literal["A", "B", "C", "D"]
    support_reason: str
    validated_vehicle_profile: str | None
    validated_track_profile: str | None
    planner_mode_availability: PlannerModeAvailabilityDTO
    warnings: list[str]

class SupportMatrixEntry(LenientSchema):
    sim: str
    vehicle: str
    track: str
    max_support_tier: Literal["A", "B", "C", "D"]
    validated_vehicle_profile: str | None
    validated_track_profile: str | None

class SupportMatrixResponse(LenientSchema):
    entries: list[SupportMatrixEntry]
    last_updated: str                                  # ISO 8601

class ArtifactsIndex(LenientSchema):
    run_id: str
    artifacts: list[ArtifactRef]

class ArtifactRef(LenientSchema):
    kind: str                    # "summary", "surface_field", ...
    download_url: str            # "/api/v1/track-surface/sessions/<sid>/artifacts/<kind>"
    size_bytes: int
    version: str                 # hash or pipeline version

class PlannerModeAvailabilityDTO(LenientSchema):
    nominal: bool
    robust: bool
    exploitable: bool
```

## 7. Endpoints

All endpoints are prefixed `/api/v1/track-surface`. All require authenticated workspace
context (same middleware stack as `sessions_v2`).

| Method | Path | Body / Query | Response | Notes |
|--------|------|-------------|----------|-------|
| POST | `/sessions/<sid>/run` | `RunAnalysisRequest` (optional) | `AnalysisRunSummary`, 202 | Enqueues Celery task. Rate-limited tier `pipeline`. |
| GET | `/sessions/<sid>` | — | `AnalysisRunSummary` (latest run) | 404 if no run exists. |
| GET | `/sessions/<sid>/summary` | — | `SessionSummary` | Always available (any tier). |
| GET | `/sessions/<sid>/surface` | — | `TrackSurfaceSummary` | 451 if tier D. |
| GET | `/sessions/<sid>/planner` | — | `PlannerSummary` | Gated. 451 if tier C/D. |
| GET | `/sessions/<sid>/uncertainty` | — | `UncertaintySummary` | 451 if tier D. |
| GET | `/sessions/<sid>/artifacts` | — | `ArtifactsIndex` | Lists only artifacts the tier allows. |
| GET | `/sessions/<sid>/artifacts/<kind>` | — | file download | Streams from `RESULTS_DIR`. |
| GET | `/support/resolve` | `ResolveSupportParams` | `SupportSummary` | Session-agnostic; pre-upload gating. |
| GET | `/support/matrix` | — | `SupportMatrixResponse` | Static matrix, cached 5 min. |

### 7.1 Error responses

- `404 NOT_FOUND`: session or run not found, OR artifact not permitted for tier.
- `409 CONFLICT`: run already in flight (and `force_rerun=false`).
- `422 VALIDATION_ERROR`: bad request payload.
- `451 SUPPORT_TIER_REFUSED`: custom ErrorCode — tier D sessions attempting planner.
  (Uses existing envelope; `error.code = "SUPPORT_TIER_REFUSED"`, status 451.)

## 8. Orchestration

### 8.1 Flow (POST /run)

1. **Request validation.** Pydantic parses body.
2. **Session lookup.** Verify session belongs to workspace.
3. **Duplicate check.** If an in-flight run exists and `force_rerun=false`, return 409.
4. **Create run row.** `analysis_runs` row inserted with `status='queued'`, `run_id = uuid4().hex`.
5. **Dispatch Celery task.** `track_surface_tasks.run_track_surface_analysis.delay(run_id)`
   on queue `pipeline`.
6. **Return 202** with the queued `AnalysisRunSummary`.

### 8.2 Celery task (`run_track_surface_analysis`)

Follows the same pattern as `ocp_tasks.py`: try-import celery, decorator-if-available,
plain-function fallback for CLI/test environments.

```python
# pseudocode
def run_track_surface_analysis(run_id: str) -> dict:
    repo = AnalysisRunRepository(db)
    run = repo.get(run_id)
    repo.update_status(run_id, RUNNING)
    try:
        session = load_session(run.session_id, run.workspace_id)
        entry = build_dataset_entry(session, run.options)
        calibration = registry.resolve(session.vehicle_key)
        if calibration is None:
            repo.mark_failed(run_id, SupportTier.D, "calibration_missing", ...)
            return {"status": "failed"}

        pipeline_result = harness.run_pipeline(entry)
        release_result = release_gate.evaluate(pipeline_result.session_metrics, ...)
        tier, reason = SupportTierResolver().resolve(
            pipeline_result, release_result, calibration
        )

        gated = OutputGate(tier).apply(pipeline_result)
        artifacts = ArtifactWriter(RESULTS_DIR, run_id).write_all(
            session_id=run.session_id,
            pipeline_result=pipeline_result,
            gated=gated,
        )
        repo.mark_succeeded(
            run_id=run_id,
            tier=tier,
            reason=reason,
            confidence_level=ConfidenceLevel.from_pipeline(pipeline_result),
            fallback_depth_pct=pipeline_result.fallback_depth_pct,
            validated_vehicle_profile=calibration.profile_id,
            validated_track_profile=entry.track_profile_id,
            planner_mode_availability=PlannerModeAvailability.for_tier(tier),
            warnings=pipeline_result.warnings,
            artifacts_index=artifacts,
            release_decision=release_result.decision.value,
            pipeline_summary=pipeline_result.sanitized_dict(),
        )
        return {"status": "succeeded", "run_id": run_id, "tier": tier.value}
    except Exception as exc:
        logger.exception("Analysis run %s failed", run_id)
        repo.mark_failed(run_id, error_code="INTERNAL_ERROR", error_message=str(exc))
        raise
```

**Timeouts**: `soft_time_limit=180` (3 min), `time_limit=240` (4 min). Aligned with
track-surface pipeline worst case observed in validation.

### 8.3 Status transitions

```
queued ──(task picks up)──► running ──(success)──► succeeded
                                   ──(exception)──► failed
                                   ──(timeout)──► failed (soft_time_limit → SoftTimeLimitExceeded)
queued ──(celery rejects)──► failed
```

No cancellation in v1. (Can be added later — out of scope.)

## 9. Gating rules (precise)

### 9.1 Tier resolution (pseudo-Python)

```python
def resolve(
    pipeline_result: PipelineResult,
    release_result: ReleaseSessionResult | None,
    calibration: CalibrationProfile | FallbackDefault | None,
) -> tuple[SupportTier, str]:
    # Tier D preconditions are evaluated BEFORE the pipeline ran successfully enough
    # to produce release_result. The resolver itself only sees tier D when
    # pipeline_result is a minimal shell (e.g., produced by the calibration-missing
    # short-circuit in the orchestrator).
    if calibration is None or isinstance(calibration, FallbackDefault):
        return SupportTier.D, "vehicle_profile_not_validated"
    if pipeline_result is None or not _has_track_geometry(pipeline_result):
        return SupportTier.D, "track_geometry_missing"
    if _has_insufficient_channels(pipeline_result):
        return SupportTier.D, "insufficient_channels"

    # Tier C: ran but advanced outputs not trustworthy
    assert release_result is not None, "release_result required once D screens passed"
    if release_result.decision == ReleaseDecision.FAIL:
        return SupportTier.C, "release_gate_fail"
    fb2 = _fallback_depth_2_pct(pipeline_result)
    if fb2 >= 30.0:
        return SupportTier.C, "high_global_fallback"

    # Tier B: partial
    if release_result.decision == ReleaseDecision.WARN:
        return SupportTier.B, "release_gate_warn"
    if fb2 >= 10.0:
        return SupportTier.B, "moderate_fallback"

    # Tier A: full
    return SupportTier.A, "all_checks_passed"
```

**Predicate helpers** (computed inside `support.py` — no `PipelineResult` field
additions):

- `_has_track_geometry(pr)` — `pr.track_geometry_nodes` (or equivalent field observed
  on `PipelineResult`) is non-empty AND `pr.n_samples_accepted > 0`.
- `_has_insufficient_channels(pr)` — `pr.missing_channels` (or `pr.warnings` containing
  `"channel_missing:*"`) non-empty for a critical channel set (speed, yaw_rate,
  a_lat, a_long).
- `_fallback_depth_2_pct(pr)` — from `pr.bucket_fallback_distribution` where key
  `2` gives the fraction of queried points resolved by the global fallback; `* 100`.

The exact `PipelineResult` attribute names are verified during implementation (§5 of
the implementation plan). If the validation harness uses different names, the
resolver adapts without any core change.

### 9.2 Output gate (controls what each tier can fetch)

| Endpoint | Tier A | Tier B | Tier C | Tier D |
|----------|:------:|:------:|:------:|:------:|
| `/summary` | ✓ | ✓ | ✓ | ✓ |
| `/surface` | ✓ | ✓ | ✓ | ✗ (451) |
| `/planner` | ✓ (all 3 modes) | ✓ (nominal, robust) | ✗ (451) | ✗ (451) |
| `/uncertainty` | ✓ | ✓ | ✓ | ✗ (451) |
| `/artifacts` | all kinds | nominal, robust; no exploitable | summary, diagnostics only | summary, diagnostics only |

`✗ (451)` returns HTTP 451 with `SUPPORT_TIER_REFUSED` envelope (see §13.6). `✗` in
`/artifacts` means the requested kind is filtered out of the index; direct
`/artifacts/<kind>` fetch for a filtered kind returns 451 as well.

### 9.3 `PlannerModeAvailability.for_tier(tier)`

| Tier | nominal | robust | exploitable |
|------|:-------:|:------:|:-----------:|
| A | ✓ | ✓ | ✓ |
| B | ✓ | ✓ | ✗ |
| C | ✗ | ✗ | ✗ |
| D | ✗ | ✗ | ✗ |

## 10. Artifacts

### 10.1 Locations

- Base dir: `app.config["RESULTS_DIR"] / "track_surface" / <session_id> / <run_id>`.
- Each artifact is a single JSON file (gzipped optional — out of scope for v1).

### 10.2 Artifact kinds

| Kind | Source | Size (typical) | Gated by tier |
|------|--------|---------------|---------------|
| `summary` | sanitized PipelineResult subset | <10KB | all |
| `surface_field` | downsampled `SurfaceField.query_batch` over a grid | 50–200KB | C+ |
| `confidence_heatmap` | `(s, n, confidence)` triples from field | 20–80KB | C+ |
| `planner_nominal` | `build_grip_map_for_ocp(mode=NOMINAL)` results | 20–60KB | A/B |
| `planner_robust` | `build_grip_map_for_ocp(mode=ROBUST)` results | 20–60KB | A/B |
| `planner_exploitable` | `build_grip_map_for_ocp(mode=EXPLOITABLE)` results | 20–60KB | A only |
| `racing_line_deltas` | per-lap line-delta from reference | 10–40KB | A/B |
| `diagnostics` | bucket diagnostics, transition gate reasons | 20–80KB | all |

### 10.3 Artifact DTO shape (`surface_field` example)

```json
{
  "run_id": "...",
  "session_id": 123,
  "generated_at": "2026-04-15T10:23:44Z",
  "grid": {
    "s": [0, 10, 20, ...],              // metres along centerline
    "n": [-4, -2, 0, 2, 4]              // metres lateral
  },
  "cells": [
    {"s": 0, "n": -4, "mu_mean": 1.12, "mu_std": 0.08, "confidence": 0.82, "fallback_depth": 0},
    ...
  ],
  "stats": {"coverage_pct": 87.4, "mean_confidence": 0.78}
}
```

**No numpy arrays leak into JSON.** All arrays serialized as lists of primitives.

## 11. Persistence

### 11.1 Table `analysis_runs` (Alembic 056)

```sql
CREATE TABLE analysis_runs (
    run_id                      TEXT PRIMARY KEY,               -- uuid4 hex
    session_id                  INTEGER NOT NULL
                                    REFERENCES sessions(session_id) ON DELETE CASCADE,
    workspace_id                INTEGER NOT NULL
                                    REFERENCES workspaces(id) ON DELETE CASCADE
                                    DEFAULT current_setting('app.current_workspace_id')::integer,
    status                      TEXT NOT NULL DEFAULT 'queued', -- queued | running | succeeded | failed
    support_tier                TEXT,                           -- A | B | C | D
    support_reason              TEXT,
    confidence_level            TEXT,                           -- high | medium | low | unknown
    fallback_depth_distribution JSONB,                          -- {"0": 0.72, "1": 0.20, "2": 0.08}
    validated_vehicle_profile   TEXT,
    validated_track_profile     TEXT,
    planner_mode_availability   JSONB,                          -- {"nominal": true, "robust": true, ...}
    warnings                    JSONB NOT NULL DEFAULT '[]'::jsonb,
    artifacts_index             JSONB NOT NULL DEFAULT '{}'::jsonb,  -- {"summary": "path.json", ...}
    release_decision            TEXT,                           -- pass | warn | fail
    pipeline_summary            JSONB,                          -- sanitized subset
    error_code                  TEXT,
    error_message               TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at                TIMESTAMPTZ
);

CREATE INDEX idx_analysis_runs_session     ON analysis_runs (session_id);
CREATE INDEX idx_analysis_runs_workspace   ON analysis_runs (workspace_id);
CREATE INDEX idx_analysis_runs_status      ON analysis_runs (status)
    WHERE status IN ('queued', 'running');

ALTER TABLE analysis_runs ENABLE ROW LEVEL SECURITY;
CREATE POLICY analysis_runs_tenant ON analysis_runs
    USING (workspace_id = current_setting('app.current_workspace_id')::integer)
    WITH CHECK (workspace_id = current_setting('app.current_workspace_id')::integer);
```

### 11.2 Repository (`persistence.py`)

```python
class AnalysisRunRepository:
    def __init__(self, conn): ...
    def insert_queued(self, *, run_id, session_id, workspace_id) -> None: ...
    def update_status(self, run_id, status) -> None: ...
    def mark_succeeded(self, run_id, **fields) -> None: ...
    def mark_failed(self, run_id, *, error_code, error_message,
                    support_tier=None, support_reason=None) -> None: ...
    def get(self, run_id) -> AnalysisRun | None: ...
    def get_latest_for_session(self, session_id) -> AnalysisRun | None: ...
    def has_in_flight(self, session_id) -> bool: ...
```

SQL uses `db/sql_compat.py` translator; named params (`:name`) so it works on both
SQLite dev and PG prod.

## 12. Testing strategy

### 12.1 Unit tests

| File | What it validates |
|------|-------------------|
| `test_support_resolver.py` | All 4 tiers reachable via synthetic `PipelineResult` + `ReleaseSessionResult` inputs. Boundary conditions (fb2 = 9.9 → A; fb2 = 10.0 → B; fb2 = 29.9 → B; fb2 = 30.0 → C). |
| `test_output_gate.py` | Gating matrix: each (tier × artifact-kind) pair returns permitted / refused correctly. |
| `test_artifact_writer.py` | DTO serialization is stable (no numpy arrays leak). Round-trip: write → read → Pydantic parse OK. |
| `test_persistence.py` | CRUD + status transitions. RLS: two workspaces can't see each other's runs. `has_in_flight` detects queued/running only. |
| `test_support_matrix.py` | Static lookup returns expected tiers for known (sim, vehicle, track) combos. Unknown combos → tier D. |

### 12.2 Integration tests

| File | What it validates |
|------|-------------------|
| `test_orchestrator.py` | End-to-end with mocked `run_pipeline()` — seeded session → enqueue → task picks up → status transitions → row has expected fields. |
| `test_routes.py` | Flask test client: all 9 endpoints, auth enforcement, envelope shape, 404s, 451 for tier-D planner access, idempotency of GETs. |

### 12.3 Fixtures

- `conftest.py` provides:
  - `fake_pipeline_result(tier_target)` — builds a `PipelineResult`-shaped object whose
    fields lead `SupportTierResolver` to the requested tier.
  - `fake_release_result(decision)` — wraps a `ReleaseDecision`.
  - `fake_calibration(validated=True)` — returns a minimal `CalibrationProfile`.

No test touches real physics code. All validation wiring is mocked at the
`track_surface_app` seam.

## 13. Example responses

### 13.1 Tier A (full)

```json
// GET /api/v1/track-surface/sessions/123
{
  "ok": true,
  "data": {
    "run_id": "a8c94b3e9d2f4c17b5a0e61fd7c4d8b2",
    "session_id": 123,
    "status": "succeeded",
    "support_tier": "A",
    "support_reason": "all_checks_passed",
    "confidence_level": "high",
    "fallback_depth_pct": {"0": 82.4, "1": 14.1, "2": 3.5},
    "validated_vehicle_profile": "iracing_mx5_2024",
    "validated_track_profile": "daytona_rc_v5",
    "planner_mode_availability": {"nominal": true, "robust": true, "exploitable": true},
    "warnings": [],
    "artifacts_available": [
      "summary", "surface_field", "confidence_heatmap",
      "planner_nominal", "planner_robust", "planner_exploitable",
      "racing_line_deltas", "diagnostics"
    ],
    "release_decision": "pass",
    "error_code": null,
    "error_message": null,
    "created_at": "2026-04-15T10:20:00Z",
    "completed_at": "2026-04-15T10:22:14Z"
  },
  "meta": {"request_id": "...", "version": "v1"}
}
```

### 13.2 Tier B (partial)

```json
{
  "ok": true,
  "data": {
    "run_id": "...",
    "session_id": 124,
    "status": "succeeded",
    "support_tier": "B",
    "support_reason": "moderate_fallback",
    "confidence_level": "medium",
    "fallback_depth_pct": {"0": 52.1, "1": 29.7, "2": 18.2},
    "validated_vehicle_profile": "iracing_mx5_2024",
    "validated_track_profile": "daytona_rc_v5",
    "planner_mode_availability": {"nominal": true, "robust": true, "exploitable": false},
    "warnings": ["exploitable_mode_suppressed_due_to_fallback"],
    "artifacts_available": [
      "summary", "surface_field", "confidence_heatmap",
      "planner_nominal", "planner_robust",
      "racing_line_deltas", "diagnostics"
    ],
    "release_decision": "pass",
    "error_code": null,
    "error_message": null,
    "created_at": "2026-04-15T10:25:00Z",
    "completed_at": "2026-04-15T10:27:05Z"
  }
}
```

### 13.3 Tier C (descriptive only)

```json
{
  "ok": true,
  "data": {
    "run_id": "...",
    "session_id": 125,
    "status": "succeeded",
    "support_tier": "C",
    "support_reason": "release_gate_fail",
    "confidence_level": "low",
    "fallback_depth_pct": {"0": 18.2, "1": 29.4, "2": 52.4},
    "validated_vehicle_profile": "iracing_mx5_2024",
    "validated_track_profile": "unknown_layout",
    "planner_mode_availability": {"nominal": false, "robust": false, "exploitable": false},
    "warnings": [
      "release_gate_failed:racing_line_lift_below_threshold",
      "planner_suppressed"
    ],
    "artifacts_available": ["summary", "diagnostics"],
    "release_decision": "fail",
    "error_code": null,
    "error_message": null,
    "created_at": "2026-04-15T10:30:00Z",
    "completed_at": "2026-04-15T10:32:44Z"
  }
}
```

### 13.4 Tier D (unsupported)

```json
{
  "ok": true,
  "data": {
    "run_id": "...",
    "session_id": 126,
    "status": "failed",
    "support_tier": "D",
    "support_reason": "vehicle_profile_not_validated",
    "confidence_level": "unknown",
    "fallback_depth_pct": null,
    "validated_vehicle_profile": null,
    "validated_track_profile": null,
    "planner_mode_availability": {"nominal": false, "robust": false, "exploitable": false},
    "warnings": ["vehicle_not_in_registry", "no_analysis_performed"],
    "artifacts_available": ["summary"],
    "release_decision": null,
    "error_code": "CALIBRATION_MISSING",
    "error_message": "No validated calibration profile found for vehicle 'unknown_hotrod'",
    "created_at": "2026-04-15T10:34:00Z",
    "completed_at": "2026-04-15T10:34:01Z"
  }
}
```

### 13.5 `/support/resolve` pre-upload check

```json
// GET /api/v1/track-surface/support/resolve?sim=iracing&vehicle=mx5&track=daytona_rc
{
  "ok": true,
  "data": {
    "run_id": null,
    "sim": "iracing",
    "vehicle": "mx5",
    "track": "daytona_rc",
    "support_tier": "A",
    "support_reason": "all_checks_passed",
    "validated_vehicle_profile": "iracing_mx5_2024",
    "validated_track_profile": "daytona_rc_v5",
    "planner_mode_availability": {"nominal": true, "robust": true, "exploitable": true},
    "warnings": []
  }
}
```

### 13.6 `/planner` on tier C (refused)

```json
// GET /api/v1/track-surface/sessions/125/planner
{
  "ok": false,
  "error": {
    "code": "SUPPORT_TIER_REFUSED",
    "message": "Planner outputs unavailable at support tier C.",
    "details": {
      "support_tier": "C",
      "support_reason": "release_gate_fail",
      "planner_mode_availability": {"nominal": false, "robust": false, "exploitable": false}
    }
  },
  "meta": {"request_id": "...", "version": "v1"}
}
```
(HTTP status 451.)

## 14. Operational considerations

- **Queue**: Celery `pipeline` queue (concurrency=2 per CLAUDE.md). No new worker needed.
- **Rate limit**: POST `/run` uses rate-limit tier `upload` (existing). Idempotency via
  in-flight detection in step 3 of §8.1.
- **Observability**: Log structured `{run_id, session_id, tier, reason}` at task
  entry / exit. `analysis_runs` status is the source of truth for dashboards.
- **Cleanup**: `RESULTS_DIR/track_surface/` has no retention policy in v1. (TODO
  future: prune runs > 90 days old. Out of scope here.)

## 15. Security & multi-tenancy

- `workspace_id` defaults via `SET LOCAL app.current_workspace_id` already set by
  `tenant_middleware`. RLS policy on `analysis_runs` enforces isolation.
- Artifact downloads verify `run.workspace_id == g.workspace_id` before streaming
  (defence-in-depth; RLS is primary).
- No PII in `pipeline_summary` (only aggregate stats).

## 16. Rollout

1. Deploy migration 056.
2. Deploy backend (new blueprint + Celery task registration).
3. Frontend consumes new endpoints behind a feature flag (`features.track_surface_app`).
   Flag flip is a separate change.
4. No rollback complexity — new tables, new endpoints; nothing existing is modified.

## 17. Out of scope (v1)

- Run cancellation.
- Re-running only a subset of the pipeline (partial runs).
- Compressed / binary artifact formats (gzipped JSON, Arrow, etc.).
- Cross-session comparison endpoints.
- Artifact retention / cleanup.
- Websocket push of status transitions (polling is sufficient).
- Webhook callbacks on completion.

---

## Approval checklist

- [ ] SupportTier mapping (§5.1, §9.1) matches intended product gating
- [ ] Endpoint set (§7) covers all required frontend use cases
- [ ] Table shape (§11.1) fits existing RLS / Alembic conventions
- [ ] Error model (§7.1) including `SUPPORT_TIER_REFUSED` / 451 is acceptable
- [ ] Example responses (§13) match what the frontend expects
- [ ] Module layout (§4.2) respects boundary: no physics changes
