# Bundle Intake Bounded Context — Design

**Date**: 2026-04-15
**Status**: Design — awaiting approval, ready to implement
**Companions**: `2026-04-15-track-surface-analysis-app-design.md` (downstream consumer)

---

## 1. Architecture

### 1.1 Responsibility

Accept a **canonical logger bundle v2** from the desktop/logger app, validate it as a
product contract, persist the raw artifact immutably, extract normalized metadata,
assess analysis readiness, and hand off to the existing `track_surface_app` for
analysis. This is the **one and only** boundary where outside-world telemetry
becomes a first-class object in our system.

### 1.2 Boundaries

```
┌──────────────┐       multipart/form-data        ┌─────────────────────────────┐
│  Logger /    │    POST /api/v1/bundles ───────► │   BUNDLE INTAKE (new)       │
│  Desktop app │                                  │                             │
└──────────────┘                                  │  ┌──────────────────────┐   │
                                                  │  │  IntakeService       │   │
┌──────────────┐       GET /bundles/<id>          │  │   ├─ Validator       │   │
│  Web app /   │◄──────────────────────────────── │  │   ├─ ImmutableStore  │   │
│  desktop UI  │       POST /bundles/<id>/analyze │  │   ├─ BundleRepo      │   │
└──────────────┘                                  │  │   └─ Readiness       │   │
                                                  │  └──────────┬───────────┘   │
                                                  └─────────────┼───────────────┘
                                                                │ enqueue
                                                                ▼
                                                  ┌─────────────────────────────┐
                                                  │ track_surface_app (existing)│
                                                  │  AnalysisOrchestrator       │
                                                  │  SupportTier, Artifacts     │
                                                  └─────────────────────────────┘
```

The intake context owns: **bundle identity**, **provenance**, **immutable raw
storage**, **canonical metadata extraction**, **analysis readiness assessment**.

It does NOT own: tier decisions (track_surface_app), physics (frozen core),
artifact serialization for frontend (track_surface_app handles that downstream).

### 1.3 Invariants (enforced by code, never by convention)

1. **Bundles are immutable.** Once a bundle row is written, its `raw_path` and
   `checksum_sha256` are never modified. Re-uploads create new rows.
2. **Checksum is authoritative.** The uploader must declare a SHA-256; the
   server recomputes; mismatch = reject.
3. **Content-addressed storage.** Raw bundle lands at
   `BUNDLES_DIR/<checksum[:2]>/<checksum>.zip`. Same checksum = same file.
4. **Schema versioning is mandatory.** The bundle's `manifest.json` must declare
   an integer `schema_version`. This subsystem only accepts v2.
5. **Append-only run history.** Re-analyzing a bundle creates a new
   `analysis_runs` row; old runs are preserved (track_surface_app already does
   this).
6. **Read models are derivable.** Anything in an indexed table could be
   rebuilt from the raw bundle — so rebuild paths are first-class.
7. **Workspace isolation via RLS.** Bundles are workspace-scoped; cross-workspace
   reads are impossible.

### 1.4 Failure modes (all surface as machine-readable error codes)

| Mode | Outcome | HTTP |
|------|---------|------|
| File missing / empty upload | Reject | 400 |
| Not a ZIP archive | Reject | 415 |
| Bundle too large (> `MAX_BUNDLE_BYTES`) | Reject | 413 |
| Checksum mismatch | Reject (raw discarded) | 422 |
| Duplicate (same checksum in same workspace) | Reject with pointer | 409 |
| Manifest missing / unparseable | Reject (raw kept for debug) | 422 |
| Schema version unsupported | Reject | 422 |
| Schema valid but semantic fields missing | Accept **degraded** | 202 |
| Unknown sim / vehicle / track | Accept **degraded** | 202 |
| Valid + complete | Accept **ready** | 201 |

"Degraded" = bundle is stored, queryable, not analyzable. `/analyze` on a
degraded bundle returns `READINESS_NOT_MET` with the exact reasons — no silent
fallback, no inferred values.

### 1.5 Observability

Every intake produces a structured log line:

```
intake_result={accepted|degraded|rejected}
  bundle_id=<id> checksum=<sha256[:12]>
  schema_version=<n> sim=<str|null>
  reasons=["..."] workspace_id=<id> elapsed_ms=<n>
```

and metrics: `intake.bundles.{accepted,degraded,rejected}.total`.

---

## 2. Domain Model

All types are in `telemetry_tool/bundle_intake/domain.py`. Enums are `str` enums
so values round-trip through JSON cleanly.

### 2.1 Enums

```python
class BundleStatus(str, Enum):
    ACCEPTED = "accepted"          # stored, analyzable
    DEGRADED = "degraded"          # stored, not analyzable (see readiness reasons)
    REJECTED = "rejected"          # never persisted
    # there is NO "pending" — intake is synchronous

class BundleSchemaVersion(int, Enum):
    V2 = 2                          # only supported version in this subsystem

class SimKey(str, Enum):
    IRACING   = "iracing"
    AC        = "ac"
    ACC       = "acc"
    RF2       = "rf2"
    LMU       = "lmu"
    F1        = "f1"
    UNKNOWN   = "unknown"           # present = intake degraded

class TrackRegime(str, Enum):
    FLAT   = "flat"
    BANKED = "banked"
    MIXED  = "mixed"
    UNKNOWN = "unknown"
```

### 2.2 Core aggregates

```python
@dataclass(frozen=True)
class SourceProvenance:
    """Where the bundle came from. Immutable once set."""
    logger_version: str                 # semver from manifest, e.g. "2.3.0"
    logger_build: str | None            # git sha if present
    capture_method: str                 # "iracing_ibt" | "ac_autopilot" | ...
    captured_by_user_id: int | None     # logger-side user id if provided
    captured_at: datetime               # session start time, UTC
    uploaded_by_user_id: int            # server-side user id from auth
    uploaded_at: datetime               # server-side receipt time, UTC
    client_hostname: str | None         # free-form diagnostic
    client_os: str | None

@dataclass(frozen=True)
class SessionIdentity:
    """The dedup key. SHA-256 hex over canonicalized components."""
    sim: SimKey
    vehicle_key: str                    # e.g. "iracing_mx5_2024"
    track_key: str                      # e.g. "daytona_rc_v5"
    session_type: str                   # "practice" | "race" | "hotlap" | ...
    started_at: datetime

    def fingerprint(self) -> str:
        payload = "|".join([
            self.sim.value,
            self.vehicle_key,
            self.track_key,
            self.session_type,
            self.started_at.isoformat(timespec="seconds"),
        ])
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

@dataclass(frozen=True)
class CanonicalSessionMetadata:
    """What the logger tells us about the session.

    All fields are EXTRACTED from manifest.json — never inferred.
    Missing critical fields → degraded readiness.
    """
    identity: SessionIdentity
    vehicle_spec: dict[str, Any]        # matches track_surface VehicleSpec shape
    track_spec: dict[str, Any]          # matches track_surface TrackSpec shape
    session_info: dict[str, Any]        # type, kappa_available, ...
    channels_present: list[str]         # channel names the bundle ships with
    lap_count: int
    duration_s: float
    extra: dict[str, Any] = field(default_factory=dict)  # forward-compat

@dataclass(frozen=True)
class ArtifactManifest:
    """The bundle's internal file list. One entry per file in the zip."""
    files: list["ArtifactManifestEntry"]

@dataclass(frozen=True)
class ArtifactManifestEntry:
    path: str                           # relative to bundle root
    size_bytes: int
    checksum_sha256: str
    role: str                           # "telemetry" | "analysis_json" | "manifest" | "aux"

@dataclass(frozen=True)
class AnalysisReadiness:
    """Can this bundle feed the analysis pipeline?"""
    is_ready: bool
    reasons: list[str]                  # machine-readable reason codes
    degraded_fields: list[str]          # CanonicalSessionMetadata field names missing/invalid

@dataclass
class UploadedBundle:
    """Aggregate root. Persisted as one row in `uploaded_bundles` + side rows."""
    bundle_id: str                      # UUID hex
    workspace_id: int
    identity_fingerprint: str           # SessionIdentity.fingerprint()
    status: BundleStatus
    schema_version: BundleSchemaVersion
    checksum_sha256: str                # of the raw archive
    size_bytes: int
    raw_path: str                       # server-side absolute path
    canonical: CanonicalSessionMetadata | None
    provenance: SourceProvenance
    readiness: AnalysisReadiness
    artifact_manifest: ArtifactManifest
    intake_reasons: list[str]           # empty on clean accept
```

### 2.3 Linked from track_surface_app (unchanged)

`AnalysisRun`, `SupportTier`, `ReleaseDecision`, `PlannerModeAvailability` are
reused as-is from `telemetry_tool/track_surface_app/domain.py`. This context
adds a **foreign key** from `analysis_runs.bundle_id → uploaded_bundles.bundle_id`
(nullable, to preserve backward compat with the CSV-upload path).

---

## 3. Intake Flow

### 3.1 Step-by-step

```
POST /api/v1/bundles  (multipart/form-data)
  │
  ▼
┌─ Step 1: Request-level validation ─────────────────────────────┐
│  - workspace context present (g.workspace_id)                   │
│  - multipart part "bundle" present                              │
│  - Content-Length ≤ MAX_BUNDLE_BYTES (500MB default)            │
│  - optional header: X-Bundle-Sha256 (uploader's declared hash)  │
└──────────────────────────────────────────────────────────────────┘
  │  fail → 400 / 413 BUNDLE_FILE_MISSING | BUNDLE_SIZE_EXCEEDED
  ▼
┌─ Step 2: Stream to temp + checksum ────────────────────────────┐
│  - write to $TMP/intake_<uuid>.zip                              │
│  - compute SHA-256 while streaming                              │
│  - if X-Bundle-Sha256 provided and mismatch → reject            │
└──────────────────────────────────────────────────────────────────┘
  │  fail → 422 BUNDLE_CHECKSUM_MISMATCH (temp file deleted)
  ▼
┌─ Step 3: Archive structural validation ────────────────────────┐
│  - zipfile.ZipFile(...).testzip() returns None                  │
│  - manifest.json present in archive root                        │
│  - manifest.json parses as JSON object                          │
└──────────────────────────────────────────────────────────────────┘
  │  fail → 415 BUNDLE_CONTENT_INVALID | 422 BUNDLE_MANIFEST_MISSING
  ▼
┌─ Step 4: Schema version check ─────────────────────────────────┐
│  - manifest["schema_version"] is int                            │
│  - value ∈ {SupportedBundleSchemaVersion.V2}                    │
└──────────────────────────────────────────────────────────────────┘
  │  fail → 422 BUNDLE_SCHEMA_VERSION_UNSUPPORTED
  ▼
┌─ Step 5: Manifest semantic validation ─────────────────────────┐
│  - required top-level keys: identity, source, files, metadata   │
│  - identity.sim, vehicle_key, track_key, session_type, started  │
│  - files[*] each have path, size, sha256, role                  │
│  - Pydantic ManifestV2 model passes                             │
└──────────────────────────────────────────────────────────────────┘
  │  fail → 422 BUNDLE_MANIFEST_INVALID (details = Pydantic errors)
  ▼
┌─ Step 6: Inner-file checksum verification ─────────────────────┐
│  - for each entry in manifest.files:                            │
│      * archive has that path                                    │
│      * size matches                                             │
│      * SHA-256 of extracted bytes matches                       │
└──────────────────────────────────────────────────────────────────┘
  │  fail → 422 BUNDLE_INNER_CHECKSUM_MISMATCH
  ▼
┌─ Step 7: Dedup by (workspace_id, checksum_sha256) ─────────────┐
│  - if exists → 409 BUNDLE_DUPLICATE {data: {existing_bundle_id}}│
└──────────────────────────────────────────────────────────────────┘
  ▼
┌─ Step 8: Promote raw to ImmutableBundleStore ──────────────────┐
│  - move temp → $BUNDLES_DIR/<ck[:2]>/<ck>.zip                   │
│  - chmod 0440 (read-only)                                       │
│  - if destination already exists (race), fsync + delete temp    │
└──────────────────────────────────────────────────────────────────┘
  ▼
┌─ Step 9: Extract CanonicalSessionMetadata from manifest ───────┐
│  - build SessionIdentity (+ fingerprint)                        │
│  - build CanonicalSessionMetadata (no inference)                │
└──────────────────────────────────────────────────────────────────┘
  ▼
┌─ Step 10: AnalysisReadinessEvaluator ──────────────────────────┐
│  ready iff:                                                     │
│    - sim != UNKNOWN                                             │
│    - vehicle_spec has all 14 required fields                    │
│    - track_spec has name + regime                               │
│    - an .ibt or .csv telemetry file is referenced (role=telem)  │
│  degraded otherwise, with reason codes                          │
└──────────────────────────────────────────────────────────────────┘
  ▼
┌─ Step 11: Persist UploadedBundle (atomic INSERT) ──────────────┐
│  - uploaded_bundles                                             │
│  - session_metadata (1-to-1)                                    │
│  - bundle_artifacts (1-to-many, one per manifest.files entry)   │
└──────────────────────────────────────────────────────────────────┘
  ▼
201 / 202  { ok: true, data: IntakeResult }
```

### 3.2 What "degraded" looks like to the caller

```json
{
  "ok": true,
  "data": {
    "bundle_id": "4b9d...",
    "status": "degraded",
    "schema_version": 2,
    "readiness": {
      "is_ready": false,
      "reasons": ["vehicle_spec_incomplete", "unknown_sim"],
      "degraded_fields": ["vehicle_spec.aero_cla", "vehicle_spec.cg_height_m", "identity.sim"]
    },
    "analyze_url": null,   // explicitly null when not ready
    "self_url": "/api/v1/bundles/4b9d..."
  },
  "meta": { "request_id": "...", "version": "v1" }
}
```

HTTP **202** (not 201) — the resource exists but the obvious next action is
unavailable.

---

## 4. API Contract

### 4.1 Endpoints

```
POST   /api/v1/bundles                          multipart upload
GET    /api/v1/bundles                          list (cursor paginated)
GET    /api/v1/bundles/<bid>                    intake + readiness
GET    /api/v1/bundles/<bid>/manifest           raw manifest.json
GET    /api/v1/bundles/<bid>/artifacts          internal artifact index
GET    /api/v1/bundles/<bid>/artifacts/<role>   stream one inner file

POST   /api/v1/bundles/<bid>/analyze            trigger AnalysisRun
GET    /api/v1/bundles/<bid>/runs               list runs (newest first)
GET    /api/v1/bundles/<bid>/runs/latest        delegates to track_surface_app
```

Everything below `/runs/...` is a **view** backed by `track_surface_app`. This
subsystem does not duplicate that state.

### 4.2 Request / response schemas (Pydantic v2, same base classes as rest of app)

```python
# POST /bundles — body is multipart; no JSON body schema.
# Headers:
#   Content-Type: multipart/form-data; boundary=...
#   X-Bundle-Sha256: <optional; lowercase hex>   — if present, must match
# Form fields:
#   bundle: <file>                               — the .zip archive

class IntakeResult(LenientSchema):
    bundle_id: str
    status: Literal["accepted", "degraded", "rejected"]
    schema_version: int
    checksum_sha256: str
    size_bytes: int
    identity_fingerprint: str
    readiness: ReadinessSummary
    intake_reasons: list[str]                    # empty on clean accept
    self_url: str
    analyze_url: str | None                      # None when not ready
    duplicate_of: str | None                     # populated on 409 DUPLICATE

class ReadinessSummary(LenientSchema):
    is_ready: bool
    reasons: list[str]
    degraded_fields: list[str]

class SessionOverview(LenientSchema):
    bundle_id: str
    sim: Literal["iracing", "ac", "acc", "rf2", "lmu", "f1", "unknown"]
    vehicle_name: str
    track_name: str
    track_regime: Literal["flat", "banked", "mixed", "unknown"]
    session_type: str
    started_at: str                              # ISO 8601
    lap_count: int
    duration_s: float
    status: Literal["accepted", "degraded"]
    readiness: ReadinessSummary
    latest_run_id: str | None                    # from analysis_runs

class BundleArtifactRef(LenientSchema):
    role: str
    path: str                                    # in-bundle relative
    size_bytes: int
    checksum_sha256: str
    download_url: str                            # tier-gated via track_surface_app if applicable

class BundleArtifactIndex(LenientSchema):
    bundle_id: str
    artifacts: list[BundleArtifactRef]

class AnalyzeRequest(StrictSchema):
    force_rerun: bool = False

class AnalyzeResponse(LenientSchema):
    bundle_id: str
    run_id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    analyze_url: str
```

### 4.3 Example responses

**Clean accept (201)**

```json
// POST /api/v1/bundles   →   201
{
  "ok": true,
  "data": {
    "bundle_id": "4b9d1f8c2e6a43f19b0d5e72c0f8a3b6",
    "status": "accepted",
    "schema_version": 2,
    "checksum_sha256": "7d9f...",
    "size_bytes": 18_432_100,
    "identity_fingerprint": "e14a...",
    "readiness": { "is_ready": true, "reasons": [], "degraded_fields": [] },
    "intake_reasons": [],
    "self_url": "/api/v1/bundles/4b9d1f8c2e6a43f19b0d5e72c0f8a3b6",
    "analyze_url": "/api/v1/bundles/4b9d1f8c2e6a43f19b0d5e72c0f8a3b6/analyze",
    "duplicate_of": null
  }
}
```

**Degraded accept (202)**

```json
{
  "ok": true,
  "data": {
    "bundle_id": "a1c3...",
    "status": "degraded",
    "schema_version": 2,
    "readiness": {
      "is_ready": false,
      "reasons": ["unknown_sim", "vehicle_spec_incomplete"],
      "degraded_fields": ["identity.sim", "vehicle_spec.mass_kg", "vehicle_spec.wheelbase_m"]
    },
    "intake_reasons": ["schema_valid_but_metadata_incomplete"],
    "self_url": "/api/v1/bundles/a1c3...",
    "analyze_url": null,
    "duplicate_of": null
  }
}
```

**Duplicate (409)**

```json
{
  "ok": false,
  "error": {
    "code": "BUNDLE_DUPLICATE",
    "message": "This bundle was already uploaded in this workspace.",
    "details": [{
      "existing_bundle_id": "4b9d1f8c2e6a43f19b0d5e72c0f8a3b6",
      "existing_bundle_status": "accepted",
      "uploaded_at": "2026-04-15T10:17:21Z"
    }]
  }
}
```

**Analyze on degraded bundle (409 READINESS_NOT_MET)**

```json
// POST /api/v1/bundles/a1c3.../analyze
{
  "ok": false,
  "error": {
    "code": "READINESS_NOT_MET",
    "message": "Bundle is not analyzable. Fix these fields and re-upload.",
    "details": [{
      "readiness": { "is_ready": false, "reasons": ["unknown_sim"], "degraded_fields": ["identity.sim"] }
    }]
  }
}
```

### 4.4 Error codes (additions to `web/api_utils.py::ErrorCode`)

```python
BUNDLE_FILE_MISSING               # 400
BUNDLE_SIZE_EXCEEDED              # 413   (already exists as FILE_TOO_LARGE — reuse)
BUNDLE_CONTENT_INVALID            # 415
BUNDLE_MANIFEST_MISSING           # 422
BUNDLE_MANIFEST_INVALID           # 422
BUNDLE_SCHEMA_VERSION_UNSUPPORTED # 422
BUNDLE_CHECKSUM_MISMATCH          # 422
BUNDLE_INNER_CHECKSUM_MISMATCH    # 422
BUNDLE_DUPLICATE                  # 409
BUNDLE_NOT_FOUND                  # 404   (use existing NOT_FOUND)
READINESS_NOT_MET                 # 409
```

No code path returns a generic 500 unless genuine infrastructure failure (disk
full, DB unreachable). Everything else is a typed refusal.

---

## 5. Persistence

### 5.1 Tables (Alembic 057)

```sql
CREATE TABLE uploaded_bundles (
    bundle_id                TEXT PRIMARY KEY,                    -- uuid4 hex
    workspace_id             INTEGER NOT NULL
                                 REFERENCES workspaces(id) ON DELETE CASCADE
                                 DEFAULT current_setting('app.current_workspace_id')::integer,
    status                   TEXT NOT NULL,                       -- accepted|degraded
    schema_version           SMALLINT NOT NULL,
    checksum_sha256          CHAR(64) NOT NULL,
    size_bytes               BIGINT NOT NULL,
    raw_path                 TEXT NOT NULL,                       -- immutable after insert
    identity_fingerprint     CHAR(64) NOT NULL,
    uploaded_by_user_id      INTEGER,
    uploaded_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    intake_reasons           JSONB NOT NULL DEFAULT '[]'::jsonb,
    UNIQUE (workspace_id, checksum_sha256)                         -- dedup key
);
CREATE INDEX idx_bundles_workspace     ON uploaded_bundles (workspace_id);
CREATE INDEX idx_bundles_fingerprint   ON uploaded_bundles (workspace_id, identity_fingerprint);
CREATE INDEX idx_bundles_uploaded_at   ON uploaded_bundles (workspace_id, uploaded_at DESC);
ALTER TABLE uploaded_bundles ENABLE ROW LEVEL SECURITY;
CREATE POLICY uploaded_bundles_tenant ON uploaded_bundles
    USING (workspace_id = current_setting('app.current_workspace_id')::integer)
    WITH CHECK (workspace_id = current_setting('app.current_workspace_id')::integer);

CREATE TABLE bundle_session_metadata (
    bundle_id                TEXT PRIMARY KEY
                                 REFERENCES uploaded_bundles(bundle_id) ON DELETE CASCADE,
    workspace_id             INTEGER NOT NULL,                     -- denormalized for RLS
    sim                      TEXT NOT NULL,                        -- enum value
    vehicle_key              TEXT NOT NULL,
    track_key                TEXT NOT NULL,
    session_type             TEXT NOT NULL,
    started_at               TIMESTAMPTZ NOT NULL,
    vehicle_spec             JSONB NOT NULL,
    track_spec               JSONB NOT NULL,
    session_info             JSONB NOT NULL,
    channels_present         JSONB NOT NULL DEFAULT '[]'::jsonb,
    lap_count                INTEGER NOT NULL DEFAULT 0,
    duration_s               DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    readiness_is_ready       BOOLEAN NOT NULL,
    readiness_reasons        JSONB NOT NULL DEFAULT '[]'::jsonb,
    readiness_degraded       JSONB NOT NULL DEFAULT '[]'::jsonb,
    extra                    JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX idx_bsm_sim_vehicle_track
    ON bundle_session_metadata (workspace_id, sim, vehicle_key, track_key);
ALTER TABLE bundle_session_metadata ENABLE ROW LEVEL SECURITY;
CREATE POLICY bsm_tenant ON bundle_session_metadata
    USING (workspace_id = current_setting('app.current_workspace_id')::integer)
    WITH CHECK (workspace_id = current_setting('app.current_workspace_id')::integer);

CREATE TABLE bundle_artifacts (
    bundle_id                TEXT NOT NULL
                                 REFERENCES uploaded_bundles(bundle_id) ON DELETE CASCADE,
    workspace_id             INTEGER NOT NULL,
    role                     TEXT NOT NULL,                        -- telemetry|analysis_json|manifest|aux
    path                     TEXT NOT NULL,                        -- in-bundle relative
    size_bytes               BIGINT NOT NULL,
    checksum_sha256          CHAR(64) NOT NULL,
    PRIMARY KEY (bundle_id, path)
);
CREATE INDEX idx_bundle_artifacts_role ON bundle_artifacts (bundle_id, role);
ALTER TABLE bundle_artifacts ENABLE ROW LEVEL SECURITY;
CREATE POLICY ba_tenant ON bundle_artifacts
    USING (workspace_id = current_setting('app.current_workspace_id')::integer)
    WITH CHECK (workspace_id = current_setting('app.current_workspace_id')::integer);

CREATE TABLE bundle_source_provenance (
    bundle_id                TEXT PRIMARY KEY
                                 REFERENCES uploaded_bundles(bundle_id) ON DELETE CASCADE,
    workspace_id             INTEGER NOT NULL,
    logger_version           TEXT NOT NULL,
    logger_build             TEXT,
    capture_method           TEXT NOT NULL,
    captured_by_user_id      INTEGER,
    captured_at              TIMESTAMPTZ NOT NULL,
    uploaded_by_user_id      INTEGER,
    uploaded_at              TIMESTAMPTZ NOT NULL,
    client_hostname          TEXT,
    client_os                TEXT
);
ALTER TABLE bundle_source_provenance ENABLE ROW LEVEL SECURITY;
CREATE POLICY bsp_tenant ON bundle_source_provenance
    USING (workspace_id = current_setting('app.current_workspace_id')::integer);

-- Optional link back from analysis_runs → bundle
ALTER TABLE analysis_runs
    ADD COLUMN bundle_id TEXT REFERENCES uploaded_bundles(bundle_id) ON DELETE SET NULL;
CREATE INDEX idx_analysis_runs_bundle ON analysis_runs (bundle_id);
```

### 5.2 Filesystem layout (content-addressed)

```
$BUNDLES_DIR/
├── 7d/
│   └── 7d9f3b4c...e8.zip         # raw, read-only after promote
└── 4b/
    └── 4b9d1f8c...b6.zip
```

- Two-level sharding prevents >10k-file directories.
- Mode `0440` — no accidental mutation.
- Same checksum under different workspaces is *physically* stored once but
  the DB still has two bundle rows (cross-workspace data isolation preserved,
  storage deduped).

### 5.3 What is stored where

| Data | Raw file | DB | Derivable? |
|------|----------|----|----|
| Bundle bytes | ✓ (`raw_path`) | — | no (source of truth) |
| Checksum | — | ✓ | yes (recompute) |
| Schema version | — | ✓ | yes (re-read manifest) |
| Session identity | — | ✓ (denormalized for indexing) | yes |
| Vehicle / track spec | — | ✓ (JSONB) | yes |
| Readiness | — | ✓ | yes (rebuild via ReadinessEvaluator) |
| Manifest inner file list | — | ✓ (`bundle_artifacts`) | yes |
| Provenance | — | ✓ | partly (uploaded_at/by is intake-side only) |

A rebuild script (`scripts/rebuild_bundle_derived.py`) can repopulate every
indexed row from raw bundles alone — no data loss risk.

### 5.4 Immutability contract

- `uploaded_bundles.raw_path`, `checksum_sha256`, `size_bytes`, `schema_version`
  are set at INSERT and never updated. Updates are blocked by a Postgres trigger:

  ```sql
  CREATE OR REPLACE FUNCTION _uploaded_bundles_immutable() RETURNS trigger AS $$
  BEGIN
    IF NEW.raw_path IS DISTINCT FROM OLD.raw_path
       OR NEW.checksum_sha256 IS DISTINCT FROM OLD.checksum_sha256
       OR NEW.size_bytes IS DISTINCT FROM OLD.size_bytes
       OR NEW.schema_version IS DISTINCT FROM OLD.schema_version THEN
      RAISE EXCEPTION 'uploaded_bundles core columns are immutable';
    END IF;
    RETURN NEW;
  END;
  $$ LANGUAGE plpgsql;

  CREATE TRIGGER trg_uploaded_bundles_immutable
    BEFORE UPDATE ON uploaded_bundles
    FOR EACH ROW EXECUTE FUNCTION _uploaded_bundles_immutable();
  ```

- `bundle_artifacts` rows are never updated — only INSERT and (cascade-driven) DELETE.

---

## 6. Testing

### 6.1 Test layout

```
telemetry_tool/tests/test_bundle_intake/
├── conftest.py                       # sqlite + tmp bundle fixtures
├── fixtures/
│   ├── bundle_v2_good.zip            # checked-in minimal valid bundle
│   ├── bundle_v2_degraded.zip        # valid schema, missing vehicle_spec fields
│   ├── bundle_v2_bad_checksum.zip    # inner checksum wrong
│   ├── bundle_v1_legacy.zip          # schema_version=1 (rejected)
│   └── build_fixtures.py             # reproducible synth script
├── test_domain.py
├── test_validator.py                 # unit — each validator rule
├── test_immutable_store.py           # filesystem contract
├── test_persistence.py               # repo CRUD + RLS
├── test_readiness.py
├── test_intake_service.py            # all step combinations
├── test_routes.py                    # HTTP — happy/degrade/dup/reject
└── test_end_to_end.py                # bundle upload → analyze → /runs/latest
```

### 6.2 Concrete tests (named)

**Happy path**
- `test_upload_clean_bundle_returns_201_and_accepted`
- `test_intake_result_includes_analyze_url_when_ready`
- `test_list_bundles_returns_newest_first`
- `test_get_bundle_after_upload_returns_full_overview`

**Incomplete bundle**
- `test_missing_manifest_returns_422_bundle_manifest_missing`
- `test_unparseable_manifest_returns_422`
- `test_manifest_missing_required_field_returns_422`
- `test_vehicle_spec_incomplete_returns_202_degraded`

**Unknown sim**
- `test_unknown_sim_accepts_as_degraded_with_reason_codes`
- `test_analyze_on_unknown_sim_returns_409_readiness_not_met`

**Unresolved canonical ids**
- `test_unknown_vehicle_key_still_accepts_but_marks_degraded`
- `test_unknown_track_key_still_accepts_but_marks_degraded`

**Missing analysis_json**
- `test_no_telemetry_role_file_returns_202_degraded`
- `test_only_manifest_present_returns_202_degraded`

**Checksum / provenance**
- `test_outer_checksum_mismatch_returns_422_and_does_not_persist`
- `test_inner_file_checksum_mismatch_returns_422`
- `test_provenance_captured_at_preserved_exactly`

**Duplicate upload**
- `test_same_checksum_same_workspace_returns_409_with_existing_id`
- `test_same_checksum_different_workspaces_both_accepted`
- `test_duplicate_response_includes_uploaded_at_of_original`

**Re-run behavior**
- `test_multiple_analyses_same_bundle_create_separate_runs`
- `test_get_latest_run_returns_most_recent`
- `test_analyze_while_in_flight_returns_409_conflict`   # delegated to track_surface_app
- `test_analyze_with_force_rerun_creates_new_run_even_when_in_flight`

**Persistence + RLS**
- `test_workspace_a_cannot_see_workspace_b_bundles`
- `test_bundle_row_core_columns_are_immutable_after_insert`
- `test_bundle_artifacts_cascade_delete_on_bundle_delete`

**Schema version**
- `test_schema_version_1_rejected`
- `test_schema_version_missing_rejected`
- `test_schema_version_future_rejected_with_clear_message`

### 6.3 Fixture strategy

`build_fixtures.py` synthesizes each `.zip` from source JSON + a 1KB pseudo-telemetry
file. Reproducible, no binary drift in git history. The "telemetry" file is a
byte pattern — NOT a real IBT — since we don't run the physics here.

---

## 7. Implementation Steps

### 7.1 Files to create

```
telemetry_tool/bundle_intake/
├── __init__.py
├── domain.py                         # §2 types
├── manifest_schema.py                # Pydantic ManifestV2 model
├── validator.py                      # Steps 3–6
├── storage.py                        # ImmutableBundleStore (§5.2 layout)
├── persistence.py                    # BundleRepository
├── readiness.py                      # AnalysisReadinessEvaluator (§3.1 Step 10)
├── service.py                        # IntakeService.intake(upload) → UploadedBundle
└── errors.py                         # typed exceptions → ErrorCode map

telemetry_tool/web/routes/bundles.py          # Flask blueprint (§4)
telemetry_tool/web/schemas/bundles.py         # Pydantic response DTOs (§4.2)

telemetry_tool/alembic/versions/057_bundles.py  # migration
telemetry_tool/tests/test_bundle_intake/...     # §6
```

### 7.2 Files to modify

- `telemetry_tool/web/api_utils.py` — add error codes listed in §4.4
- `telemetry_tool/web/app.py` — register `bundles_bp` in `_blueprint_imports`
- `telemetry_tool/track_surface_app/session_loader.py` — new `load_from_bundle(bundle_id)`
  path that reads `bundle_session_metadata` instead of `sessions.analysis_json`
  (keeps the CSV path alive behind a `source` argument)
- `telemetry_tool/track_surface_app/pipeline_adapters.py` — accept a
  `BundleAwareSessionLoader` variant so `run_pipeline_adapter(session_id_or_bundle_id, ...)`
  works for both

### 7.3 Service-layer signatures

```python
# bundle_intake/service.py
@dataclass
class IntakeInput:
    stream: BinaryIO
    declared_checksum: str | None
    content_length: int | None
    uploaded_by_user_id: int
    workspace_id: int

class IntakeResult(TypedDict):
    bundle: UploadedBundle | None
    outcome: Literal["accepted", "degraded", "rejected"]
    error_code: str | None
    error_details: list[dict] | None

class IntakeService:
    def __init__(self, *, store, repo, validator, readiness): ...
    def intake(self, inp: IntakeInput) -> IntakeResult: ...
    def get_overview(self, bundle_id, workspace_id) -> SessionOverview | None: ...
    def get_artifact_stream(self, bundle_id, role, workspace_id) -> BinaryIO: ...

# bundle_intake/validator.py
class BundleValidator:
    def validate_archive(self, path: Path) -> ManifestV2: ...
    def validate_inner_checksums(self, path: Path, manifest: ManifestV2) -> None: ...
    # raises typed exceptions from errors.py

# bundle_intake/storage.py
class ImmutableBundleStore:
    def __init__(self, base_dir: Path): ...
    def promote(self, temp_path: Path, checksum: str) -> Path: ...
    def path_for(self, checksum: str) -> Path: ...
    def exists(self, checksum: str) -> bool: ...

# bundle_intake/persistence.py
class BundleRepository:
    def insert_bundle(self, bundle: UploadedBundle) -> None: ...   # atomic across all 4 tables
    def find_by_checksum(self, ws, ck) -> UploadedBundle | None: ...
    def get(self, bundle_id, ws) -> UploadedBundle | None: ...
    def get_overview(self, bundle_id, ws) -> SessionOverview | None: ...
    def list_for_workspace(self, ws, *, limit, cursor) -> list[SessionOverview]: ...
    def link_run(self, bundle_id, run_id) -> None: ...

# bundle_intake/readiness.py
class AnalysisReadinessEvaluator:
    def evaluate(self, metadata: CanonicalSessionMetadata,
                 artifact_manifest: ArtifactManifest) -> AnalysisReadiness: ...
```

### 7.4 Build order (TDD, one commit per step)

1. **Scaffold + domain** — `__init__.py`, `domain.py` + `test_domain.py`.
2. **Errors + ErrorCode additions** — `errors.py`, update `api_utils.py`.
3. **ManifestV2 schema** — `manifest_schema.py` + parse tests.
4. **Validator** — `validator.py` + `test_validator.py` (drives all §3 steps
   3–6 in unit form, before the service layer).
5. **ImmutableBundleStore** — `storage.py` + `test_immutable_store.py` (promote,
   dedup, read-only mode).
6. **ReadinessEvaluator** — `readiness.py` + `test_readiness.py`.
7. **Alembic 057** — tables, RLS policies, immutability trigger.
8. **BundleRepository** — `persistence.py` + `test_persistence.py` (+RLS).
9. **IntakeService** — `service.py` + `test_intake_service.py` wiring 1–11.
10. **Pydantic response DTOs** — `web/schemas/bundles.py`.
11. **Flask blueprint** — `web/routes/bundles.py` + `test_routes.py` for each
    endpoint.
12. **Register blueprint** — one-line edit in `web/app.py`.
13. **Bundle-aware session loader** — `track_surface_app/session_loader.py`:
    new `load_from_bundle(bundle_id)` + `load_from_saas_session(session_id)`
    discriminator.
14. **End-to-end test** — `test_end_to_end.py`: upload clean bundle → trigger
    analyze → fetch `/runs/latest` → assert tier A/B/C.
15. **Fixture builder** — `fixtures/build_fixtures.py` (hermetic regeneration).

### 7.5 Rollout

- Deploy migration 057.
- Deploy backend with new blueprint.
- Logger-side: ship v2 bundle producer behind a logger-side feature flag.
- Webapp frontend: consume new `/bundles` endpoints behind `features.bundle_intake`.
- Legacy CSV `/sessions/upload` path stays operational until logger v2 rollout is
  complete; `analysis_runs.bundle_id` is nullable so old rows remain readable.

### 7.6 Out of scope for v1 (documented, not hidden)

- Bundle garbage collection / retention policy (manual for now).
- Resumable multipart uploads (single-shot only).
- Cross-workspace bundle sharing (always isolated).
- Incremental re-validation when a newer manifest schema is added (v3 would be
  a new subsystem; v2 is frozen).
- Webhooks on intake outcome (polling only).
- Bulk upload (one bundle per request).

---

## Design principles — compliance check

| Principle | How this design upholds it |
|-----------|---------------------------|
| Bundle v2 is a product contract | `ManifestV2` is a Pydantic model, versioned, failing-fast |
| No research-layer leakage to HTTP | `track_surface_app` types still only cross its own boundary; `bundle_intake` emits its own DTOs |
| Tier explainable | `ReadinessSummary.reasons` + `SupportSummary.support_reason` both machine-readable |
| Every degraded case debuggable | Raw bundle immutably kept even on degraded accept; `intake_reasons` persisted |
| Append-only runs | Unchanged: `track_surface_app` already appends |
| Immutable source + derived read models | §5.3 + trigger in §5.4 |
| Production correctness / observability / multi-sim | Structured logging, metrics, SimKey enum with explicit UNKNOWN |
