# Bundle Integration Validation — v1 Simracing

**Date**: 2026-04-16
**Status**: Audit complete. Actionable delta identified.

---

## A. Current State (plain English)

**The desktop app does not produce bundles.** The ManifestV2 zip format we built
the intake system around is aspirational infrastructure — no desktop code path
currently writes a `manifest.json` or zips anything.

What the desktop actually exports:

| Mode | Output | Format |
|------|--------|--------|
| **iRacing replay capture** (`batch_replay_capture.py`) | `.ibt` files + `capture_meta.json` in a flat folder | No zip, no manifest |
| **RaceChrono/CSV** (existing sessions_v2 upload) | Raw `.csv` file + form metadata | Multipart upload, pipeline runs server-side |
| **AC autopilot** (`lap_oracle/`) | JSON files in a SQLite-managed data lake | No bundling |

The track-surface research stack (`validation/harness.py:run_pipeline`) only accepts
**iRacing `.ibt` files** via a `DatasetEntry`. CSV sessions feed the existing 14-stage
pipeline via `sessions_v2.py` — a completely separate code path.

**Bottom line:** The bundle intake system is fully implemented and tested, but has
zero real-world callers. The gap is a thin bridge between the desktop's
`ibt + capture_meta.json` output and the webapp's ManifestV2 intake.

---

## B. Contract Mismatches

| # | Expected by webapp (ManifestV2) | Produced by desktop | Gap | Severity |
|---|------|------|-----|----------|
| 1 | `.zip` archive with `manifest.json` at root | Flat folder with `.ibt` + `capture_meta.json` | **No zip, no manifest** | Blocking — nothing to upload |
| 2 | `manifest.identity.sim` | `capture_meta.source == "replay_ibt_capture"` | Implicit; must be derived → `"iracing"` | Trivial mapping |
| 3 | `manifest.identity.vehicle_key` | `capture_meta.car_name` | Present but different field name | Trivial mapping |
| 4 | `manifest.identity.track_key` | `capture_meta.track_name` | Present but different field name | Trivial mapping |
| 5 | `manifest.identity.session_type` | Not in capture_meta | Missing; default to `"practice"` | Non-blocking (default OK) |
| 6 | `manifest.identity.started_at` | `capture_meta.collected_at` | Present, different name | Trivial mapping |
| 7 | `manifest.source.logger_version` | Not in capture_meta | Missing | Need to add at bundle-build time |
| 8 | `manifest.source.capture_method` | `capture_meta.source` value | Present | Direct map |
| 9 | `manifest.metadata.vehicle_spec` (14 fields) | **Not produced by desktop** | **Missing entirely** | High — causes every bundle to be DEGRADED |
| 10 | `manifest.metadata.track_spec.regime` | Not in capture_meta | Missing | Medium — defaults to "flat" which is often wrong |
| 11 | `manifest.metadata.track_spec.name` | `capture_meta.track_name` | Present, different field name | Trivial |
| 12 | `manifest.metadata.channels_present` | Not in capture_meta | Missing but derivable from IBT header | Low |
| 13 | `manifest.metadata.lap_count` | Not in capture_meta | Missing but derivable from IBT | Low |
| 14 | `manifest.metadata.duration_s` | Not in capture_meta | Missing but derivable from IBT | Low |
| 15 | `manifest.files[*].sha256` | Not computed by desktop | Missing | Must compute at bundle-build time |
| 16 | `manifest.files[*].size` | Not recorded by desktop | Missing | Must compute at bundle-build time |
| 17 | `ReadinessEvaluator` gates on vehicle_spec completeness | VehicleSpec is never available at upload time | **Every real bundle → DEGRADED** | Blocking — makes the feature useless |

**Critical insight for #17:** VehicleSpec (mass_kg, wheelbase_m, etc.) is NOT user
data — it's sim-specific vehicle engineering data. The desktop user should never
have to provide it. It lives in the **CalibrationProfile registry** on the server.
The readiness evaluator was designed as if the logger would embed this data, but in
practice only the server has it.

---

## C. Canonical v1 Bundle Contract

### C.1 What the logger produces (v1 minimum)

```
my_session.zip
├── manifest.json          (schema_version: 2, see below)
├── telemetry.ibt          (raw iRacing IBT file, unchanged)
└── capture_meta.json      (optional, preserved for provenance)
```

### C.2 Manifest v2 — v1 field requirements

| Field | Required | Source | Notes |
|-------|----------|--------|-------|
| `schema_version` | **yes** | hardcoded `2` | |
| `identity.sim` | **yes** | `"iracing"` (derived from capture_meta.source or hardcoded by builder) | |
| `identity.vehicle_key` | **yes** | `capture_meta.car_name`, normalized (lowercase, underscores) | |
| `identity.track_key` | **yes** | `capture_meta.track_name`, normalized | |
| `identity.session_type` | **yes** | `"practice"` default, user-overridable | |
| `identity.started_at` | **yes** | `capture_meta.collected_at` or IBT header timestamp | |
| `source.logger_version` | **yes** | package version of the desktop tool at build time | |
| `source.capture_method` | **yes** | `capture_meta.source` or `"iracing_ibt"` | |
| `source.captured_at` | **yes** | same as `identity.started_at` | |
| `source.logger_build` | optional | git SHA if available | |
| `source.captured_by_user_id` | optional | null in v1 (no desktop auth yet) | |
| `source.client_hostname` | optional | hostname from platform | |
| `source.client_os` | optional | platform info | |
| `files[0].path` | **yes** | `"telemetry.ibt"` | |
| `files[0].size` | **yes** | actual file size in bytes | |
| `files[0].sha256` | **yes** | computed SHA-256 hex | |
| `files[0].role` | **yes** | `"telemetry"` | |
| `metadata.vehicle_spec` | **empty dict `{}`** | NOT populated by logger in v1 | Resolved server-side from calibration registry |
| `metadata.track_spec` | **partial** | `{"name": "<track_name>"}` | `regime` resolved server-side or defaults to `"flat"` |
| `metadata.session_info` | optional | `{"type": "practice"}` | |
| `metadata.channels_present` | optional | `[]` in v1 | Could be derived from IBT header |
| `metadata.lap_count` | optional | `0` in v1 | Could be derived from IBT |
| `metadata.duration_s` | optional | `0` in v1 | Could be derived from IBT |

### C.3 v1 supported scope by sim

| Sim | Tier | Rationale |
|-----|------|-----------|
| **iRacing** | First-class (A/B/C depending on vehicle+track calibration) | IBT format supported, validation datasets exist, calibration profiles available |
| **AC** (via lap_oracle) | Basic/deferred | JSON-based data lake, no IBT, separate pipeline needed |
| **ACC, rF2, LMU, F1** | Refused (D) | No parser, no validation, no calibration |
| **RaceChrono CSV** | Legacy path only | Stays on `sessions_v2.py`; NOT routed through bundle intake |

---

## D. Minimum Change Set

### D.1 Desktop side — new bundle builder (1 new file)

**`scripts/build_bundle.py`** — CLI tool that wraps a capture folder into a
ManifestV2-compliant zip.

```
python scripts/build_bundle.py \
  --capture-dir output/daytona__MX5/ \
  --output my_session.zip
```

Reads `capture_meta.json` from the folder, finds `.ibt` files, computes checksums,
writes `manifest.json`, zips everything. ~120 lines.

### D.2 Backend — relax readiness evaluator (1 file modify)

**`telemetry_tool/bundle_intake/readiness.py`** — change the readiness gate:

**Before (blocks on vehicle_spec completeness):**
```python
vehicle_missing = _missing_vehicle_fields(metadata.vehicle_spec)
if vehicle_missing:
    reasons.append("vehicle_spec_incomplete")
```

**After (vehicle_spec resolved at analysis time, not intake time):**
```python
# Vehicle spec completeness is NOT a readiness gate in v1.
# The calibration registry resolves it at analysis time.
# Readiness only checks: sim known + vehicle_key present + track_key present + telemetry file.
if not metadata.identity.vehicle_key:
    reasons.append("vehicle_key_missing")
```

Fields that become **analysis-time checks** (not readiness gates):
- `vehicle_spec.*` (14 fields) — resolved from CalibrationProfile registry
- `track_spec.regime` — defaults to "flat" if absent

Fields that remain **readiness gates**:
- `identity.sim` must not be `UNKNOWN`
- `identity.vehicle_key` must be non-empty
- `identity.track_key` must be non-empty
- At least one file with `role=telemetry`

### D.3 Backend — session_loader falls back to calibration registry (1 file modify)

**`telemetry_tool/track_surface_app/session_loader.py:load_from_bundle()`** — when
`vehicle_spec` from `bundle_session_metadata` is empty/partial, attempt to resolve
from the CalibrationProfile registry before failing.

```python
# In load_from_bundle():
vehicle_spec = _load_json(_row_get(row, "vehicle_spec")) or {}
if not _has_required_vehicle_fields(vehicle_spec):
    # Try calibration registry fallback
    vehicle_spec = _resolve_vehicle_spec_from_registry(
        vehicle_key=..., vehicle_class=...
    )
    if vehicle_spec is None:
        return LoadResult(reason=NOT_SUPPORTED_VEHICLE_SPEC_MISSING, ...)
```

This is a thin lookup — the registry already has `VehicleSpec`-equivalent data
for calibrated vehicles.

### D.4 Backend — support_matrix.json seed data update (1 file modify)

**`telemetry_tool/track_surface_app/data/support_matrix.json`** — add entries for
every calibrated (sim, vehicle, track) combo that has a validated CalibrationProfile.
Currently only 2 entries (iracing/mx5/daytona, iracing/mx5/spa). Need to sync
with whatever the calibration registry contains.

### D.5 Readiness test updates (1 file modify)

**`telemetry_tool/tests/test_bundle_intake/test_readiness.py`** — update expectations:
- `test_vehicle_spec_missing_fields` → now passes readiness (not a gate)
- Add `test_vehicle_key_missing_is_degraded`
- Add `test_track_key_missing_is_degraded`

### D.6 Fixture updates (1 file modify)

**`telemetry_tool/tests/test_bundle_intake/fixtures/build_fixtures.py`** — update
`build_good_bundle()` to match the v1 contract (empty vehicle_spec, partial
track_spec).

### D.7 Frontend — no changes needed

The vocabulary already handles all states. `ReadinessChecklist` renders pass/fail
based on whatever reason codes the backend returns. `SupportLevelBadge` handles
all tiers. No frontend changes.

### File summary

| File | Action | Lines |
|------|--------|-------|
| `scripts/build_bundle.py` | **create** | ~120 |
| `bundle_intake/readiness.py` | **modify** | ~15 lines changed |
| `track_surface_app/session_loader.py` | **modify** | ~20 lines added (registry fallback) |
| `track_surface_app/data/support_matrix.json` | **modify** | sync with registry |
| `tests/test_bundle_intake/test_readiness.py` | **modify** | ~20 lines (update expectations) |
| `tests/test_bundle_intake/fixtures/build_fixtures.py` | **modify** | ~10 lines |
| `tests/test_bundle_intake/test_intake_service.py` | **modify** | ~5 lines (update happy-path assertions) |

**Total: 1 new file, 6 modified. ~190 lines of delta.**

---

## E. Real-Bundle Test Plan

### E.1 Happy path — supported iRacing bundle

**Setup:** Run `batch_replay_capture.py` against an iRacing MX-5 session at Daytona
(vehicle in calibration registry). Run `build_bundle.py` to produce the zip.

**Test:**
```
POST /api/v1/bundles  (multipart: bundle.zip)
  → 201 accepted, readiness.is_ready=true

POST /api/v1/bundles/<id>/analyze
  → 202 queued

GET /api/v1/bundles/<id>/runs/latest  (poll until succeeded)
  → support_tier in {A, B, C}
  → artifacts_available includes summary + diagnostics

GET /api/v1/bundles/<id>/artifacts
  → at least summary.json downloadable
```

### E.2 Degraded — unknown vehicle

**Setup:** Build a bundle with `vehicle_key: "unknown_custom_car"` (not in
calibration registry).

**Test:**
```
POST /api/v1/bundles
  → 201 accepted, readiness.is_ready=true  (vehicle_key is present, sim is known)

POST /api/v1/bundles/<id>/analyze
  → 202 queued → runs → succeeded with tier D

GET /api/v1/bundles/<id>/runs/latest
  → support_tier=D, support_reason="vehicle_profile_not_validated"
```

Note: This is "degraded at analysis time" not "degraded at intake time" — the
readiness gate passes because the bundle has sim + vehicle_key + telemetry. The
tier D comes from the SupportTierResolver when the calibration registry can't
resolve the vehicle.

### E.3 Refused — non-iRacing sim

**Setup:** Build a bundle with `identity.sim: "rf2"` (not first-class).

**Test:**
```
POST /api/v1/bundles
  → 202 degraded, readiness.is_ready=false, reasons=["unknown_sim"]
  → analyze_url=null

POST /api/v1/bundles/<id>/analyze
  → 409 READINESS_NOT_MET
```

### E.4 Duplicate upload

**Setup:** Upload the same zip twice.

**Test:**
```
POST /api/v1/bundles  (first time)
  → 201 accepted

POST /api/v1/bundles  (same bytes again)
  → 409 BUNDLE_DUPLICATE, details.existing_bundle_id present
```

### E.5 Corrupted archive

**Setup:** Truncate a valid zip at 50% of its bytes.

**Test:**
```
POST /api/v1/bundles
  → 415 BUNDLE_CONTENT_INVALID
```

### E.6 Automated test (pytest)

Add `telemetry_tool/tests/test_bundle_intake/test_real_bundle_flow.py` that:
1. Calls `build_bundle.py` programmatically on a synthetic capture folder
2. Uploads the result to a Flask test client
3. Verifies the full happy-path flow (201 → analyze → tier result)
4. Repeats with degraded and refused variants

---

## F. Go / No-Go Criteria

The feature is ready for production beta when ALL of these are true:

| # | Criterion | How to verify |
|---|-----------|---------------|
| 1 | `build_bundle.py` produces a valid ManifestV2 zip from a real iRacing capture folder | Run against a real `batch_replay_capture.py` output; upload to staging |
| 2 | A real iRacing MX-5 Daytona bundle uploads → 201 accepted → `readiness.is_ready=true` | Staging test with real IBT |
| 3 | Analyze on that bundle produces a non-D tier | Staging test; `support_tier in {A, B, C}` |
| 4 | Artifacts are downloadable via `/artifacts/<role>` | Staging test; `summary.json` returns 200 |
| 5 | An unknown-vehicle bundle uploads → accepted → analyze → tier D with clear reason | Staging test |
| 6 | A non-iRacing bundle uploads → 202 degraded, analyze blocked | Staging test |
| 7 | Duplicate upload returns 409 with existing_bundle_id | Staging test |
| 8 | Frontend shows correct state for each path (ready, degraded, D, failed) | Manual QA on staging |
| 9 | All backend tests pass (bundle_intake + track_surface_app) | CI green |
| 10 | No research-layer code was modified | `git diff` on `track_surface/` shows zero changes |

**Not required for beta (deferred to v1.1):**
- AC autopilot bundles
- CSV→bundle migration
- Track regime auto-detection (defaults to "flat")
- Channel inventory from IBT header
- Lap count / duration extraction from IBT
- Desktop GUI bundle export (CLI-only in beta)

---

## Summary of the delta

The entire gap is **one script + two backend relaxations**. The bundle intake
system, track-surface app layer, analysis orchestrator, and frontend are already
correct — they were designed for a contract the desktop doesn't produce YET. The
fix is to:

1. **Teach the desktop to produce ManifestV2 zips** (`build_bundle.py`)
2. **Stop gating readiness on vehicle_spec** (the server resolves it from the
   calibration registry at analysis time, not at upload time)
3. **Fall back to the calibration registry** in the session loader when the bundle
   doesn't carry a full VehicleSpec

Everything else is already wired, tested, and build-verified.
