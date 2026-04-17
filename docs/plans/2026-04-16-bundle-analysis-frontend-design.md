# Bundle Analysis Frontend — Design

**Date**: 2026-04-16
**Status**: Design — ready to implement
**Companion**: `2026-04-15-bundle-intake-design.md` (backend), `2026-04-15-track-surface-analysis-app-design.md` (analysis layer)

---

## Section 1 — Product Flow

### 1.1 User journey (linear, no forks)

```
┌─────────────────┐    ┌────────────────────────┐
│ Bundles list     │ ←──│ /app/bundles            │  "Your Sessions" tab
│ (empty | rows)   │    └────────────────────────┘
└────────┬────────┘
         │ "Upload Session" CTA
         ▼
┌─────────────────┐    ┌────────────────────────┐
│ Upload panel     │ ←──│ /app/bundles/upload     │  drag-drop + progress
└────────┬────────┘    └────────────────────────┘
         │ upload completes
         ▼
┌─────────────────┐
│ Intake result    │    navigates to /app/bundles/<id>
│ ├── accepted ✓   │    → shows readiness + "Analyze" CTA
│ ├── degraded ⚠   │    → shows what's missing + why analysis blocked
│ └── rejected ✗   │    → error toast, stays on upload page
└────────┬────────┘
         │ user clicks "Analyze"
         ▼
┌─────────────────┐
│ Analysis running │    polled every 3s while queued/running
│   ⟳ queued       │
│   ⟳ running      │
│   ✓ succeeded    │    → support tier revealed, artifacts unlocked
│   ✗ failed       │    → error message displayed, "Retry" CTA
└────────┬────────┘
         │ succeeded
         ▼
┌─────────────────┐
│ Results panel    │    support level + planner modes + artifacts
│ ├── surface      │
│ ├── planner      │    gated by tier (A/B visible, C/D locked)
│ ├── artifacts    │    download links, tier-filtered
│ └── diagnostics  │
└─────────────────┘
```

### 1.2 Polling strategy

| Phase | Interval | Stop condition |
|-------|----------|----------------|
| Upload progress | `xhr.upload.onprogress` (real-time) | upload completes / fails |
| Analysis run | React Query `refetchInterval: 3000` | `status ∈ {succeeded, failed}` |
| Bundle detail (idle) | `staleTime: 60_000` (lazy refetch) | — |

### 1.3 Degraded / refused states (user always knows *why*)

| Backend state | What the user sees |
|---------------|-------------------|
| `status=degraded` | "Incomplete Session Data" card: checked/unchecked items, orange badge |
| `readiness.is_ready=false` | "Analyze" button disabled, tooltip: "Missing: [list]" |
| `support_tier=D` | "Not Supported" panel: "This sim/vehicle/track combination isn't supported yet. [Learn more]" |
| `support_tier=C` | "Basic Analysis" — lap data visible, planner locked |
| Analysis `status=failed` | "Analysis Error" card with error message + "Retry Analysis" button |
| Duplicate upload | Toast: "This session was already uploaded. [View existing →]" |

---

## Section 2 — Frontend Architecture

### 2.1 Route structure

```
src/app/app/bundles/
├── layout.tsx                    ← metadata: "Session Analysis"
├── page.tsx                      ← bundle list (GET /bundles)
├── upload/
│   └── page.tsx                  ← upload flow
└── [id]/
    ├── page.tsx                  ← bundle detail + runs + artifacts
    └── layout.tsx                ← optional: shared heading/tabs
```

### 2.2 Components (all in `src/components/app/bundles/`)

```
src/components/app/bundles/
├── BundleUploadPanel.tsx         ← drag-drop, progress, checksum
├── IntakeResultCard.tsx          ← status badge + readiness + CTA
├── ReadinessChecklist.tsx        ← per-field pass/fail list
├── AnalysisRunCard.tsx           ← run lifecycle with polling
├── SupportLevelBadge.tsx         ← A/B/C/D colored pill
├── PlannerAvailabilityPanel.tsx  ← which strategy modes are unlocked
├── ArtifactsIndex.tsx            ← download links, tier-filtered
├── DegradedPanel.tsx             ← what's missing + why
├── RefusedPanel.tsx              ← tier D / analysis blocked
├── BundleListRow.tsx             ← one row in the list table
└── EmptyBundleState.tsx          ← "Upload your first session"
```

### 2.3 Hooks / services

```
src/hooks/
├── useUploadBundle.ts            ← XHR upload + progress + intake result
├── useBundleDetail.ts            ← GET /bundles/<id> + overview
├── useBundleRun.ts               ← GET /bundles/<id>/runs/latest + auto-poll
├── useTriggerAnalysis.ts         ← POST /bundles/<id>/analyze
└── useBundleArtifacts.ts         ← GET /bundles/<id>/artifacts
```

No Zustand store needed — React Query is the cache. Each hook is a thin wrapper
around `useQuery` / `useMutation` with typed generics.

### 2.4 Types (`src/types/bundles.ts`)

```typescript
// ── Backend envelope shapes ──────────────────────────────

interface ReadinessSummary {
  is_ready: boolean;
  reasons: string[];
  degraded_fields: string[];
}

interface IntakeResult {
  bundle_id: string;
  status: 'accepted' | 'degraded' | 'rejected';
  schema_version: number;
  checksum_sha256: string;
  size_bytes: number;
  identity_fingerprint: string;
  readiness: ReadinessSummary;
  intake_reasons: string[];
  self_url: string;
  analyze_url: string | null;
  duplicate_of: string | null;
}

interface BundleOverview {
  bundle_id: string;
  sim: string;
  vehicle_name: string;
  vehicle_key: string;
  track_name: string;
  track_key: string;
  track_regime: string;
  session_type: string;
  started_at: string;
  lap_count: number;
  duration_s: number;
  status: 'accepted' | 'degraded';
  readiness: ReadinessSummary;
  latest_run_id: string | null;
  uploaded_at: string;
}

interface BundleArtifactRef {
  role: string;
  path: string;
  size_bytes: number;
  checksum_sha256: string;
  download_url: string;
}

interface AnalysisRunSummary {
  run_id: string;
  bundle_id: string;
  status: 'queued' | 'running' | 'succeeded' | 'failed';
  support_tier: 'A' | 'B' | 'C' | 'D' | null;
  support_reason: string | null;
  confidence_level: 'high' | 'medium' | 'low' | 'unknown' | null;
  release_decision: 'pass' | 'warn' | 'fail' | null;
  created_at: string;
  completed_at: string | null;
}

// ── Frontend-enriched types ──────────────────────────────

type UploadPhase = 'idle' | 'uploading' | 'processing' | 'done' | 'error';

interface SupportLevel {
  tier: 'A' | 'B' | 'C' | 'D';
  label: string;           // "Full Analysis", "Standard", "Basic", "Not Supported"
  color: string;           // Tailwind class: "acid-green", "gold", "marshal-yellow", "safety-red"
  plannerModes: string[];  // human-readable mode names available
  description: string;     // one-liner for tooltips
}
```

### 2.5 Query cache strategy

| Hook | Query key | `staleTime` | `refetchInterval` |
|------|-----------|-------------|-------------------|
| `useBundleDetail(id)` | `['bundle', id]` | 60s | — |
| `useBundleRun(id)` | `['bundle-run', id]` | 0 (always fresh) | 3s while non-terminal, off otherwise |
| `useBundleArtifacts(id)` | `['bundle-artifacts', id]` | 60s | — |
| `useTriggerAnalysis` | mutation, no cache | — | — |
| bundle list | `['bundles']` | 30s | — |

### 2.6 Error boundary

Each page wraps its query-dependent content in an `<ErrorBoundary>` that:
- Shows the API error code + message in a `bg-safety-red/10 border-safety-red/30` card
- Includes the `meta.request_id` for support escalation
- Has a "Try Again" button that calls `queryClient.invalidateQueries()`
- Never shows raw stack traces

---

## Section 3 — Component List

### 3.1 Screens

| # | Component / Page | Where | Backend endpoint | Notes |
|---|-----------------|-------|------------------|-------|
| 1 | **BundleListPage** | `app/bundles/page.tsx` | `GET /bundles` | Table: vehicle, track, date, status badge, latest run status. "Upload" CTA top-right. |
| 2 | **BundleUploadPage** | `app/bundles/upload/page.tsx` | `POST /bundles` | Drag-drop zone, progress bar, intake result toast/redirect. |
| 3 | **BundleDetailPage** | `app/bundles/[id]/page.tsx` | `GET /bundles/<id>`, `GET /bundles/<id>/runs/latest`, `GET /bundles/<id>/artifacts` | Two columns: left=overview+readiness+CTA, right=run+artifacts+planner. |

### 3.2 Components (10 total)

| # | Component | Props | Key behavior |
|---|-----------|-------|-------------|
| 1 | `BundleUploadPanel` | `onSuccess(result: IntakeResult)`, `onError(err)` | Drag-drop zone → XHR with progress → intake result. Handles: duplicate (toast + link), rejected (error card), degraded (warning card), accepted (redirect). |
| 2 | `IntakeResultCard` | `bundle: BundleOverview` | Status pill (accepted/degraded), vehicle+track+sim, started_at, lap count. "Analyze" CTA when ready, disabled with tooltip when degraded. |
| 3 | `ReadinessChecklist` | `readiness: ReadinessSummary` | Green ✓ / red ✗ per prerequisite. Human-readable field labels. |
| 4 | `AnalysisRunCard` | `run: AnalysisRunSummary \| null` | States: no-run (empty), queued (spinner), running (spinner + "Analyzing..."), succeeded (support badge + tier summary), failed (error + retry). |
| 5 | `SupportLevelBadge` | `tier: 'A'\|'B'\|'C'\|'D'` | Colored pill: A=acid-green "Full Analysis", B=gold "Standard Analysis", C=marshal-yellow "Basic Analysis", D=safety-red "Not Supported". |
| 6 | `PlannerAvailabilityPanel` | `tier: string, modes: {nominal, robust, exploitable}` | Three rows: Standard Strategy ✓/✗, Safe Strategy ✓/✗, Race Strategy ✓/✗. Locked items show "Upgrade to [tier]" hint. |
| 7 | `ArtifactsIndex` | `artifacts: BundleArtifactRef[], tier: string` | Download links. Locked artifacts show "Requires [tier] analysis" instead of link. |
| 8 | `DegradedPanel` | `readiness: ReadinessSummary` | "Incomplete Session Data" heading. Per-field explanation. "Re-upload with complete metadata" CTA. |
| 9 | `RefusedPanel` | `reason: string` | "Analysis Not Available" heading. Translates reason code to user sentence. |
| 10 | `EmptyBundleState` | — | "No sessions yet. Upload your first session bundle to start." + upload CTA. |

---

## Section 4 — API Consumption Plan

### 4.1 Per-component mapping

| Component | Endpoint | Loading state | Empty state | Retry | Stale handling |
|-----------|----------|---------------|-------------|-------|----------------|
| `BundleListPage` | `GET /bundles` | Skeleton rows (3) | `EmptyBundleState` | Button + pull-to-refresh | `staleTime: 30s` |
| `BundleUploadPanel` | `POST /bundles` (XHR) | Progress bar (0-100%) | Drag-drop zone | "Try Again" resets to idle | N/A (mutation) |
| `IntakeResultCard` | cached from list or `GET /bundles/<id>` | Skeleton card | — | — | `staleTime: 60s` |
| `AnalysisRunCard` | `GET /bundles/<id>/runs/latest` | Spinner inside card | "No analysis yet" + "Analyze" CTA | Auto-retry 3s while queued/running | `refetchInterval: 3000` until terminal |
| `PlannerAvailabilityPanel` | derived from `AnalysisRunSummary.support_tier` | — | "Run analysis first" | — | — |
| `ArtifactsIndex` | `GET /bundles/<id>/artifacts` | Skeleton list | "No artifacts yet" | — | `staleTime: 60s` |
| trigger analyze | `POST /bundles/<id>/analyze` | Button shows spinner | — | Show error, re-enable button | N/A (mutation) |

### 4.2 Error code handling

| API error code | User-facing behavior |
|---|---|
| `BUNDLE_FILE_MISSING` | "No file selected. Drag a bundle or click to browse." |
| `BUNDLE_SIZE_EXCEEDED` | "Bundle exceeds the 500 MB limit." |
| `BUNDLE_CONTENT_INVALID` | "This file isn't a valid session bundle. Expected a .zip archive." |
| `BUNDLE_MANIFEST_MISSING` | "Bundle is missing its manifest file. Re-export from the logger." |
| `BUNDLE_MANIFEST_INVALID` | "Bundle manifest is corrupt. Re-export from the logger." |
| `BUNDLE_SCHEMA_VERSION_UNSUPPORTED` | "This bundle format is outdated. Update your logger to v2+." |
| `BUNDLE_CHECKSUM_MISMATCH` | "Upload integrity check failed. Please try again." |
| `BUNDLE_DUPLICATE` | "This session was already uploaded. [View existing →]" (link to existing bundle) |
| `READINESS_NOT_MET` | renders `DegradedPanel` inline |
| `SUPPORT_TIER_REFUSED` | renders `RefusedPanel` inline |
| `CONFLICT` (in-flight run) | "Analysis is already running. Wait for it to finish or force a re-run." |
| `NOT_FOUND` | "Session not found." + back link to list |

---

## Section 5 — State Model

### 5.1 Upload state machine

```
idle ──(file selected)──► uploading ──(progress 100%)──► processing ──(intake response)──► done
  │                           │                                                            │
  │                           └──(XHR error)──► error                                      ├── accepted → navigate to /bundles/<id>
  │                                                                                        ├── degraded → navigate to /bundles/<id>
  │                                                                                        └── rejected → stay, show error
  └──(drag enter)──► dragover ──(drag leave)──► idle
```

`useUploadBundle` manages this as a discriminated union:

```typescript
type UploadState =
  | { phase: 'idle' }
  | { phase: 'dragover' }
  | { phase: 'uploading'; progress: number }
  | { phase: 'processing' }
  | { phase: 'done'; result: IntakeResult }
  | { phase: 'error'; message: string; code?: string; existingBundleId?: string };
```

### 5.2 Run lifecycle state (derived from `useBundleRun`)

```typescript
type RunDisplayState =
  | { phase: 'no-run' }                                    // no analysis triggered yet
  | { phase: 'queued' }                                    // waiting for worker
  | { phase: 'running' }                                   // pipeline executing
  | { phase: 'succeeded'; tier: SupportLevel; run: AnalysisRunSummary }
  | { phase: 'failed'; errorMessage: string; run: AnalysisRunSummary };
```

### 5.3 Support tier → UI mapping (the vocabulary bridge)

```typescript
const SUPPORT_LEVELS: Record<string, SupportLevel> = {
  A: {
    tier: 'A',
    label: 'Full Analysis',
    color: 'acid-green',
    plannerModes: ['Standard Strategy', 'Safe Strategy', 'Race Strategy'],
    description: 'All analysis modes available. Highest confidence.',
  },
  B: {
    tier: 'B',
    label: 'Standard Analysis',
    color: 'gold',
    plannerModes: ['Standard Strategy', 'Safe Strategy'],
    description: 'Core analysis available. Race strategy requires more data.',
  },
  C: {
    tier: 'C',
    label: 'Basic Analysis',
    color: 'marshal-yellow',
    plannerModes: [],
    description: 'Lap data and diagnostics only. Strategy modes require better data quality.',
  },
  D: {
    tier: 'D',
    label: 'Not Supported',
    color: 'safety-red',
    plannerModes: [],
    description: 'This session cannot be analyzed. Check the requirements below.',
  },
};
```

### 5.4 Readiness reason → user text mapping

```typescript
const READINESS_LABELS: Record<string, string> = {
  unknown_sim:              'Simulator not recognized',
  vehicle_spec_incomplete:  'Vehicle data is incomplete',
  vehicle_spec_invalid:     'Vehicle data has invalid values',
  track_spec_incomplete:    'Track information is incomplete',
  track_spec_invalid:       'Track information has invalid values',
  no_telemetry_file:        'No telemetry data file in bundle',
  no_analysis_json:         'No analysis metadata in bundle',
  unsupported_capture_method: 'Capture method not supported',
};
```

---

## Section 6 — Edge Cases

| Case | Detection | UI behavior |
|------|-----------|------------|
| **Duplicate upload** | `BUNDLE_DUPLICATE` with `existing_bundle_id` in details | Toast: "Already uploaded", link to existing. Upload panel resets. |
| **Unsupported bundle version** | `BUNDLE_SCHEMA_VERSION_UNSUPPORTED` | Error card: "Update your logger" + download link. |
| **Missing metadata (degraded)** | `intake.status === 'degraded'` | `DegradedPanel` with per-field checklist. "Analyze" button disabled. |
| **Tier D run** | `run.support_tier === 'D'` | `RefusedPanel`. No artifacts section. "Not supported" badge. |
| **Tier C — no planner** | `run.support_tier === 'C'` | Planner section shows all modes locked. Surface + diagnostics visible. |
| **Analysis failed** | `run.status === 'failed'` | Error card with `run.error_message`. "Retry Analysis" button. |
| **Latest run absent** | `GET /runs/latest` returns 404 | `AnalysisRunCard` shows "No analysis yet" + "Analyze" CTA. |
| **Artifact blocked by tier** | artifact `role` not in tier's allowed set | Download button replaced with "Requires Full Analysis" text. |
| **Upload interrupted** | XHR `onerror` / `ontimeout` | Error state with "Connection lost. Try again." + retry button. |
| **Checksum mismatch** | `BUNDLE_CHECKSUM_MISMATCH` | "Upload verification failed. File may have been corrupted during transfer. Try again." |
| **Bundle file is not a ZIP** | `BUNDLE_CONTENT_INVALID` | "This file isn't a valid session bundle. Session bundles are .zip files exported from the Lap logger." |
| **Race: user clicks Analyze twice** | Second POST returns 409 CONFLICT | Button enters loading state on first click; 409 is ignored (run already started). |
| **Run succeeds with warnings** | `release_decision === 'warn'` | Orange "Verified with Warnings" badge alongside the tier badge. |

---

## Section 7 — Implementation Steps

### 7.1 Files to create

```
lap-website/src/types/bundles.ts                          # TS interfaces
lap-website/src/lib/bundle-vocabulary.ts                   # tier/readiness label maps
lap-website/src/hooks/useUploadBundle.ts                   # XHR + progress
lap-website/src/hooks/useBundleDetail.ts                   # GET /bundles/<id>
lap-website/src/hooks/useBundleRun.ts                      # GET /bundles/<id>/runs/latest + poll
lap-website/src/hooks/useTriggerAnalysis.ts                # POST /bundles/<id>/analyze
lap-website/src/hooks/useBundleArtifacts.ts                # GET /bundles/<id>/artifacts
lap-website/src/components/app/bundles/SupportLevelBadge.tsx
lap-website/src/components/app/bundles/ReadinessChecklist.tsx
lap-website/src/components/app/bundles/DegradedPanel.tsx
lap-website/src/components/app/bundles/RefusedPanel.tsx
lap-website/src/components/app/bundles/AnalysisRunCard.tsx
lap-website/src/components/app/bundles/PlannerAvailabilityPanel.tsx
lap-website/src/components/app/bundles/ArtifactsIndex.tsx
lap-website/src/components/app/bundles/BundleUploadPanel.tsx
lap-website/src/components/app/bundles/IntakeResultCard.tsx
lap-website/src/components/app/bundles/BundleListRow.tsx
lap-website/src/components/app/bundles/EmptyBundleState.tsx
lap-website/src/app/app/bundles/layout.tsx
lap-website/src/app/app/bundles/page.tsx
lap-website/src/app/app/bundles/upload/page.tsx
lap-website/src/app/app/bundles/[id]/page.tsx
```

### 7.2 Files to modify

- `lap-website/src/data/navigation.ts` — add "Analysis" nav item linking to `/app/bundles`
- `lap-website/src/lib/api-client.ts` — no changes needed (existing `api.post` handles FormData? → verify; may need XHR wrapper)

### 7.3 Build order (component-first, bottom-up)

| # | Step | Files | Tests |
|---|------|-------|-------|
| 1 | Types + vocabulary | `types/bundles.ts`, `lib/bundle-vocabulary.ts` | — |
| 2 | `SupportLevelBadge` | small, self-contained, no API | `SupportLevelBadge.test.tsx` |
| 3 | `ReadinessChecklist` | | `ReadinessChecklist.test.tsx` |
| 4 | `DegradedPanel` + `RefusedPanel` | uses ReadinessChecklist | |
| 5 | `useBundleDetail` hook | `useQuery` wrapper | `useBundleDetail.test.ts` |
| 6 | `useBundleRun` hook | polling logic | `useBundleRun.test.ts` |
| 7 | `useBundleArtifacts` hook | | |
| 8 | `useTriggerAnalysis` hook | mutation | |
| 9 | `AnalysisRunCard` | uses useBundleRun | `AnalysisRunCard.test.tsx` |
| 10 | `PlannerAvailabilityPanel` | pure from tier | |
| 11 | `ArtifactsIndex` | uses useBundleArtifacts | |
| 12 | `IntakeResultCard` | composes 2-4 | |
| 13 | `useUploadBundle` hook | XHR + state machine | `useUploadBundle.test.ts` |
| 14 | `BundleUploadPanel` | uses useUploadBundle | `BundleUploadPanel.test.tsx` |
| 15 | `BundleListRow` + `EmptyBundleState` | | |
| 16 | Detail page | `[id]/page.tsx` | |
| 17 | Upload page | `upload/page.tsx` | |
| 18 | List page | `page.tsx` | |
| 19 | Navigation | add nav item | |
| 20 | Page-level integration | mock all API scenarios A/B/C/D/degraded/failed | Playwright or Vitest integration |

### 7.4 Testing strategy

**Component tests (Vitest + Testing Library):**
- `SupportLevelBadge` renders correct color/label for each tier
- `ReadinessChecklist` renders ✓/✗ for known reason codes
- `AnalysisRunCard` cycles through no-run → queued → running → succeeded/failed
- `DegradedPanel` renders all degraded fields as human labels
- `RefusedPanel` renders tier D + C messages correctly

**Hook tests (Vitest + msw):**
- `useUploadBundle` state machine transitions
- `useBundleRun` polling starts/stops at correct lifecycle phases
- `useTriggerAnalysis` handles 202, 409 CONFLICT, 409 READINESS_NOT_MET

**Page integration tests (Vitest + Testing Library):**
- Bundle detail page: mock Tier A → verify all sections visible
- Bundle detail page: mock Tier C → verify planner section locked
- Bundle detail page: mock Tier D → verify RefusedPanel shown
- Upload page: mock successful upload → verify redirect
- Upload page: mock duplicate → verify toast + link
- Upload page: mock rejected → verify error card

### 7.5 Out of scope

- Bundle delete / archive UI (backend doesn't support yet)
- Comparison view (compare two bundles)
- Websocket push for run status (polling is sufficient)
- Bulk upload
- Analysis run history table (just latest for now)

---

## Vocabulary cheat-sheet (backend → frontend)

| Backend concept | Frontend label | Where used |
|---|---|---|
| `support_tier: A` | "Full Analysis" | `SupportLevelBadge`, `PlannerAvailabilityPanel` |
| `support_tier: B` | "Standard Analysis" | same |
| `support_tier: C` | "Basic Analysis" | same |
| `support_tier: D` | "Not Supported" | `RefusedPanel` |
| `release_decision: pass` | "Verified" | small check badge |
| `release_decision: warn` | "Verified with Warnings" | orange badge |
| `release_decision: fail` | "Unverified" | red badge |
| `readiness.is_ready` | "Ready for Analysis" | green indicator |
| `readiness.is_ready=false` | "Incomplete Session Data" | orange indicator + checklist |
| `planner...nominal` | "Standard Strategy" | `PlannerAvailabilityPanel` |
| `planner...robust` | "Safe Strategy" | same |
| `planner...exploitable` | "Race Strategy" | same |
| `status=degraded` | "Incomplete" | `IntakeResultCard` badge |
| `status=accepted` | "Ready" | `IntakeResultCard` badge |
| `confidence_level: high` | "High Confidence" | small text under tier badge |
| `confidence_level: medium` | "Moderate Confidence" | same |
| `confidence_level: low` | "Low Confidence" | same |
