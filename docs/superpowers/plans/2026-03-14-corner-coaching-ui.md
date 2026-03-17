# Corner Coaching UI — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the Corners & Coaching tab with a track map entry point and full-takeover corner detail view showing coaching + theoretical engine data.

**Architecture:** Two-screen SPA within the CornersTab: Screen 1 (track map with color-coded corner dots) → Screen 2 (corner detail with verdict, speed bars, and 4 accordion panels). All data fetched on tab mount via 6 parallel React Query calls, filtered client-side per corner.

**Tech Stack:** Next.js 14, TypeScript, Tailwind CSS, TanStack React Query 5, HTML5 Canvas (track map + theoretical chart)

**Spec:** `docs/superpowers/specs/2026-03-14-corner-coaching-ui-design.md`

---

## Chunk 1: Foundation + Data Layer

### Task 1: Types and Data Hook

**Files:**
- Create: `lap-website/src/components/app/corners/useCornerData.ts`
- Modify: `lap-website/src/components/app/corners/CornersTab.tsx` (replace placeholder)
- Modify: `lap-website/src/components/app/corners/index.ts`

- [ ] **Step 1: Create `useCornerData.ts` with all types and 6 React Query calls**

```typescript
// lap-website/src/components/app/corners/useCornerData.ts
'use client';

import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';

/* ── Types ──────────────────────────────────────────────── */

export interface CornerData {
  corner_id: number;
  s_start: number;
  s_end: number;
  s_apex?: number;
  direction?: 'L' | 'R';
  available: boolean;
  entry_speed_actual?: number | null;
  entry_speed_theory?: number | null;
  apex_speed_actual?: number | null;
  apex_speed_theory?: number | null;
  exit_speed_actual?: number | null;
  exit_speed_theory?: number | null;
  time_loss_total_s?: number | null;
  grip_utilisation_pct?: number | null;
  primary_cause?: string | null;
  coaching_hint?: string | null;
  corner_type?: string | null;
  section_type?: string | null;
  exit_importance?: number | null;
  is_user_defined?: boolean | null;
  handling_events?: HandlingEvent[] | null;
  brake_release?: Record<string, unknown> | null;
}

export interface HandlingEvent {
  event_type: 'understeer' | 'oversteer';
  severity: 'mild' | 'moderate' | 'severe';
  cause: string;
  cause_detail: string;
  corner_phase: 'entry' | 'mid' | 'exit';
  magnitude: number;
  time_cost_s?: number | null;
}

export interface CornerPosition {
  corner_id: number;
  lat: number;
  lon: number;
  s_apex: number;
}

export interface GpsTrace {
  latitudes: number[];
  longitudes: number[];
  speeds: number[];
  distances: number[];
}

export interface CornerMetricRow {
  session_id: string;
  lap_number: number;
  corner_id: number;
  brake_point_m: number | null;
  apex_speed_mps: number | null;
  exit_speed_mps: number | null;
  time_loss_ms: number | null;
}

export interface TheoreticalData {
  available: boolean;
  reason_code?: string | null;
  theoretical_time_s: number | null;
  actual_best_time_s: number | null;
  gap_pct: number | null;
  simulation_method: string | null;
  speeds: number[];
  distances: number[];
  corner_coaching: TheoCorner[];
  delta_map_summary?: unknown[];
  session_scalars?: Record<string, unknown>;
}

export interface TheoCorner {
  corner_id: number;
  theoretical_apex_speed_mps?: number | null;
  theoretical_entry_speed_mps?: number | null;
  theoretical_exit_speed_mps?: number | null;
  time_loss_s?: number | null;
  primary_cause?: string | null;
  coaching_hint?: string | null;
}

export interface CoachingData {
  focus_areas: FocusArea[];
  drills: unknown[];
  next_session_goals: string[];
  confidence: number;
}

export interface FocusArea {
  rank: number;
  category: string;
  time_loss_s: number;
  corner_ids: number[];
  summary: string;
  advice: string;
}

/* ── Hook ───────────────────────────────────────────────── */

const STALE = 5 * 60 * 1000;

export function useCornerData(sessionId: string) {
  const corners = useQuery({
    queryKey: ['corners', sessionId],
    queryFn: () => api.get<{ corners: CornerData[] }>(`/sessions/${sessionId}/corners`),
    staleTime: STALE,
    enabled: !!sessionId,
  });

  const positions = useQuery({
    queryKey: ['corner-positions', sessionId],
    queryFn: () => api.get<{ corners: CornerPosition[] }>(`/sessions/${sessionId}/corner-positions`),
    staleTime: STALE,
    enabled: !!sessionId,
  });

  const gpsTrace = useQuery({
    queryKey: ['gps-trace-corners', sessionId],
    queryFn: () => api.get<GpsTrace>(`/sessions/${sessionId}/gps-trace`),
    staleTime: STALE,
    enabled: !!sessionId,
  });

  const metrics = useQuery({
    queryKey: ['corner-metrics', sessionId],
    queryFn: () => api.get<{ corners: CornerMetricRow[]; available: boolean }>(`/sessions/${sessionId}/corner-metrics`),
    staleTime: STALE,
    enabled: !!sessionId,
  });

  const theoretical = useQuery({
    queryKey: ['theoretical', sessionId],
    queryFn: () => api.get<TheoreticalData>(`/sessions/${sessionId}/theoretical`),
    staleTime: STALE,
    enabled: !!sessionId,
  });

  const coaching = useQuery({
    queryKey: ['coaching', sessionId],
    queryFn: () => api.get<CoachingData>(`/sessions/${sessionId}/coaching`),
    staleTime: STALE,
    enabled: !!sessionId,
  });

  const isLoading = corners.isLoading || positions.isLoading || gpsTrace.isLoading;
  const isError = corners.isError || positions.isError || gpsTrace.isError;

  function refetchAll() {
    corners.refetch();
    positions.refetch();
    gpsTrace.refetch();
    metrics.refetch();
    theoretical.refetch();
    coaching.refetch();
  }

  return {
    corners: corners.data?.corners ?? [],
    positions: positions.data?.corners ?? [],
    gpsTrace: gpsTrace.data ?? null,
    metrics: metrics.data?.corners ?? [],
    theoretical: theoretical.data ?? null,
    coaching: coaching.data ?? null,
    isLoading,
    isError,
    refetchAll,
  };
}
```

- [ ] **Step 2: Update `CornersTab.tsx` to use the hook and manage view state**

Replace the current placeholder with:

```typescript
// lap-website/src/components/app/corners/CornersTab.tsx
'use client';

import { useState, useCallback } from 'react';
import { useCornerData, type CornerData } from './useCornerData';
import { TrackMapView } from './TrackMapView';
import { CornerDetailView } from './CornerDetailView';

export type { CornerData };

interface CornersTabProps {
  corners: CornerData[];
  sessionId: string;
}

export function CornersTab({ sessionId }: CornersTabProps) {
  const data = useCornerData(sessionId);
  const [selectedCornerId, setSelectedCornerId] = useState<number | null>(null);

  const handleSelectCorner = useCallback((id: number) => setSelectedCornerId(id), []);
  const handleBack = useCallback(() => setSelectedCornerId(null), []);

  if (data.isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
        <span className="ml-3 text-steel text-sm font-body">Loading corner data...</span>
      </div>
    );
  }

  if (data.isError) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-3">
        <p className="text-steel font-body text-sm">Failed to load corner data</p>
        <button
          onClick={data.refetchAll}
          className="px-4 py-2 bg-concrete text-chalk text-sm font-monument rounded border border-steel/20 hover:border-acid-green/50 transition-colors"
        >
          Try again
        </button>
      </div>
    );
  }

  if (data.corners.length === 0) {
    return (
      <div className="py-16 text-center">
        <p className="font-monument text-lg text-chalk mb-2">No corners detected</p>
        <p className="text-steel font-body text-sm max-w-md mx-auto">
          Corner detection requires sufficient GPS data with clear curvature changes.
        </p>
      </div>
    );
  }

  if (selectedCornerId !== null) {
    return (
      <CornerDetailView
        cornerId={selectedCornerId}
        data={data}
        onBack={handleBack}
        onNavigate={handleSelectCorner}
      />
    );
  }

  return (
    <TrackMapView
      corners={data.corners}
      positions={data.positions}
      gpsTrace={data.gpsTrace}
      onSelectCorner={handleSelectCorner}
    />
  );
}
```

- [ ] **Step 3: Update `index.ts` barrel exports**

```typescript
// lap-website/src/components/app/corners/index.ts
export { CornersTab } from './CornersTab';
export type { CornerData } from './useCornerData';
```

- [ ] **Step 4: Verify build passes**

Run: `cd lap-website && npm run build 2>&1 | tail -5`

Expected: Build will fail because `TrackMapView` and `CornerDetailView` don't exist yet. That's fine — create stub files.

- [ ] **Step 5: Create stub files for `TrackMapView` and `CornerDetailView`**

```typescript
// lap-website/src/components/app/corners/TrackMapView.tsx
'use client';

import type { CornerData, CornerPosition, GpsTrace } from './useCornerData';

interface TrackMapViewProps {
  corners: CornerData[];
  positions: CornerPosition[];
  gpsTrace: GpsTrace | null;
  onSelectCorner: (id: number) => void;
}

export function TrackMapView({ corners, onSelectCorner }: TrackMapViewProps) {
  return (
    <div className="py-8">
      <p className="text-steel text-sm text-center mb-4 font-body">Click a corner to view coaching</p>
      <div className="flex flex-wrap gap-2 justify-center">
        {corners.map((c) => (
          <button
            key={c.corner_id}
            onClick={() => onSelectCorner(c.corner_id)}
            className="px-3 py-2 bg-concrete rounded border border-steel/20 text-chalk text-sm font-telemetry hover:border-acid-green/50 transition-colors"
          >
            C{c.corner_id} {c.direction ?? ''} {c.time_loss_total_s != null ? `(${(c.time_loss_total_s * 1000).toFixed(0)}ms)` : ''}
          </button>
        ))}
      </div>
    </div>
  );
}
```

```typescript
// lap-website/src/components/app/corners/CornerDetailView.tsx
'use client';

import type { CornerData } from './useCornerData';

interface CornerDetailViewProps {
  cornerId: number;
  data: { corners: CornerData[]; metrics: unknown[]; theoretical: unknown; coaching: unknown; gpsTrace: unknown };
  onBack: () => void;
  onNavigate: (id: number) => void;
}

export function CornerDetailView({ cornerId, onBack }: CornerDetailViewProps) {
  return (
    <div>
      <button onClick={onBack} className="text-steel text-sm mb-4 hover:text-chalk transition-colors font-body">
        ← Back to track
      </button>
      <p className="text-chalk font-monument">Corner {cornerId} — Detail view (building...)</p>
    </div>
  );
}
```

- [ ] **Step 6: Verify build passes**

Run: `cd lap-website && npm run build 2>&1 | tail -5`
Expected: Build succeeds.

- [ ] **Step 7: Commit**

```bash
git add lap-website/src/components/app/corners/
git commit -m "feat(corners): add data hook and CornersTab orchestrator with stubs"
```

---

## Chunk 2: Track Map + Corner Detail Header

### Task 2: Track Map with Canvas Rendering

**Files:**
- Modify: `lap-website/src/components/app/corners/TrackMapView.tsx` (replace stub)

- [ ] **Step 1: Implement full `TrackMapView.tsx`**

Replace the stub with canvas-based track map. Follow the `CornerPicker.tsx` canvas pattern:
- DPR scaling: `canvas.width = w * dpr; ctx.scale(dpr, dpr)`
- Equirectangular projection: normalize lat/lon to bounding box with 10% padding
- Precompute pixel arrays (`pxs[]`, `pys[]`) once per render
- Draw track outline as polyline (white/chalk, 2px)
- Draw corner dots: filled circles, color-coded by time loss severity
  - `< 50ms` → `#C6F135` (acid-green)
  - `50–150ms` → `#F5C518` (marshal-yellow)
  - `150–300ms` → `#FF6B2B` (pit-orange)
  - `> 300ms` → `#FF2A2A` (safety-red)
  - No theoretical → `#888888` (steel)
- Corner labels: number inside or beside each dot
- Hit-testing: on canvas click, find nearest corner dot within 20px radius
- Hover: show tooltip (corner number, direction, time loss) via absolute-positioned div
- ResizeObserver for responsive canvas

Reference existing projection code in `CornerPicker.tsx:87-164` for the buildProjection pattern.

Est. ~280 lines.

- [ ] **Step 2: Verify build passes**

Run: `cd lap-website && npm run build 2>&1 | tail -5`
Expected: Build succeeds.

- [ ] **Step 3: Commit**

```bash
git add lap-website/src/components/app/corners/TrackMapView.tsx
git commit -m "feat(corners): canvas track map with color-coded corner dots"
```

---

### Task 3: Corner Detail Header

**Files:**
- Create: `lap-website/src/components/app/corners/CornerDetailHeader.tsx`

- [ ] **Step 1: Create `CornerDetailHeader.tsx`**

```typescript
// lap-website/src/components/app/corners/CornerDetailHeader.tsx
'use client';

import type { CornerData } from './useCornerData';

interface CornerDetailHeaderProps {
  corner: CornerData;
  cornerIndex: number;
  totalCorners: number;
  onBack: () => void;
  onPrev: () => void;
  onNext: () => void;
}

const TYPE_LABELS: Record<string, string> = {
  hairpin: 'HAIRPIN',
  fast_sweeper: 'FAST SWEEPER',
  simple: 'SIMPLE',
  kink: 'KINK',
  double_apex: 'DOUBLE APEX',
  compound: 'COMPOUND',
  chicane: 'CHICANE',
  decreasing_radius: 'DECREASING R',
  increasing_radius: 'INCREASING R',
};

export function CornerDetailHeader({
  corner,
  cornerIndex,
  totalCorners,
  onBack,
  onPrev,
  onNext,
}: CornerDetailHeaderProps) {
  const typeLabel = corner.corner_type ? (TYPE_LABELS[corner.corner_type] ?? corner.corner_type.toUpperCase()) : null;
  const dirLabel = corner.direction === 'L' ? 'LEFT' : corner.direction === 'R' ? 'RIGHT' : null;
  const badge = [dirLabel, typeLabel].filter(Boolean).join(' ');

  return (
    <div className="flex items-center justify-between py-3 px-1 border-b border-steel/20 mb-4">
      <div className="flex items-center gap-3">
        <button
          onClick={onBack}
          className="text-steel text-sm hover:text-chalk transition-colors font-body"
        >
          ← Back to track
        </button>
        <span className="font-monument text-lg text-chalk tracking-tight">
          CORNER {corner.corner_id}
        </span>
        {badge && (
          <span className="bg-white/10 text-steel text-[11px] font-telemetry px-2 py-0.5 rounded">
            {badge}
          </span>
        )}
      </div>
      <div className="flex gap-2">
        <button
          onClick={onPrev}
          disabled={cornerIndex === 0}
          className="px-3 py-1.5 bg-concrete border border-steel/20 text-steel text-xs font-telemetry rounded disabled:opacity-30 disabled:cursor-not-allowed hover:border-steel/40 transition-colors"
        >
          ← Prev
        </button>
        <button
          onClick={onNext}
          disabled={cornerIndex === totalCorners - 1}
          className="px-3 py-1.5 bg-concrete border border-steel/20 text-steel text-xs font-telemetry rounded disabled:opacity-30 disabled:cursor-not-allowed hover:border-steel/40 transition-colors"
        >
          Next →
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify build**

Run: `cd lap-website && npm run build 2>&1 | tail -5`

- [ ] **Step 3: Commit**

```bash
git add lap-website/src/components/app/corners/CornerDetailHeader.tsx
git commit -m "feat(corners): corner detail header with nav"
```

---

## Chunk 3: Above-the-Fold Sections

### Task 4: Verdict Section

**Files:**
- Create: `lap-website/src/components/app/corners/VerdictSection.tsx`

- [ ] **Step 1: Create `VerdictSection.tsx`**

```typescript
// lap-website/src/components/app/corners/VerdictSection.tsx
'use client';

import type { CornerData } from './useCornerData';

interface VerdictSectionProps {
  corner: CornerData;
}

function deriveLossPhase(c: CornerData): string {
  const deltas = [
    { phase: 'Entry', loss: (c.entry_speed_theory ?? 0) - (c.entry_speed_actual ?? 0) },
    { phase: 'Apex', loss: (c.apex_speed_theory ?? 0) - (c.apex_speed_actual ?? 0) },
    { phase: 'Exit', loss: (c.exit_speed_theory ?? 0) - (c.exit_speed_actual ?? 0) },
  ];
  const worst = deltas.reduce((a, b) => (b.loss > a.loss ? b : a));
  return worst.loss > 0 ? `${worst.phase} phase` : '';
}

export function VerdictSection({ corner }: VerdictSectionProps) {
  const hasData = corner.available && corner.time_loss_total_s != null;
  const timeLoss = corner.time_loss_total_s ?? 0;
  const isGain = timeLoss < 0;
  const phase = hasData ? deriveLossPhase(corner) : '';

  // Split coaching_hint to highlight the action part (last sentence)
  const hint = corner.coaching_hint ?? '';
  const sentences = hint.split(/(?<=\.)\s+/);
  const actionSentence = sentences.length > 1 ? sentences.pop() : null;
  const diagnosisPart = sentences.join(' ');

  return (
    <div className="flex gap-6 items-start py-5 border-b border-steel/20">
      {/* Time loss badge */}
      <div className="text-center min-w-[100px] shrink-0">
        {hasData ? (
          <>
            <div className={`text-4xl font-bold font-telemetry ${isGain ? 'text-acid-green' : 'text-safety-red'}`}>
              {isGain ? '+' : '-'}{Math.abs(timeLoss).toFixed(3)}s
            </div>
            <div className="text-[10px] text-steel uppercase tracking-widest mt-1 font-telemetry">
              Time {isGain ? 'Gained' : 'Lost'}
            </div>
          </>
        ) : (
          <>
            <div className="text-4xl font-bold font-telemetry text-steel">—</div>
            <div className="text-[10px] text-steel uppercase tracking-widest mt-1 font-telemetry">
              No theoretical data
            </div>
          </>
        )}
      </div>

      {/* Cause + tip */}
      <div className="flex-1 min-w-0">
        {hasData && corner.primary_cause ? (
          <>
            <div className="flex items-center gap-2 mb-2">
              <span className="bg-safety-red/20 text-safety-red text-[11px] font-telemetry font-semibold px-2.5 py-0.5 rounded">
                {corner.primary_cause.replace(/_/g, ' ').toUpperCase()}
              </span>
              {phase && <span className="text-steel text-[11px] font-telemetry">{phase}</span>}
            </div>
            <p className="text-chalk/80 text-sm font-body leading-relaxed">
              {diagnosisPart}
              {actionSentence && (
                <>{' '}<strong className="text-acid-green">{actionSentence}</strong></>
              )}
            </p>
          </>
        ) : (
          <p className="text-steel text-sm font-body">
            No theoretical data available for this corner.
          </p>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify build**

Run: `cd lap-website && npm run build 2>&1 | tail -5`

- [ ] **Step 3: Commit**

```bash
git add lap-website/src/components/app/corners/VerdictSection.tsx
git commit -m "feat(corners): verdict section with time loss and coaching tip"
```

---

### Task 5: Speed Comparison Bars

**Files:**
- Create: `lap-website/src/components/app/corners/SpeedComparisonBars.tsx`

- [ ] **Step 1: Create `SpeedComparisonBars.tsx`**

Three animated horizontal bars comparing actual vs theoretical speeds at entry/apex/exit. Each bar:
- Fills from 0 to actual width on mount (300ms ease-out, staggered 100ms per row)
- Shows dashed line at theoretical position (if available)
- Delta value on the right (red/green)
- Uses `useEffect` + `useState` for mount animation trigger

Key implementation:
- Compute bar width as `(actual / maxSpeed) * 100%` where `maxSpeed = max(actual, theory) * 1.1`
- Theory marker at `(theory / maxSpeed) * 100%`
- Speed display in km/h: `value * 3.6`
- Use `requestAnimationFrame` or CSS transition for smooth width animation

Est. ~120 lines.

- [ ] **Step 2: Verify build**

Run: `cd lap-website && npm run build 2>&1 | tail -5`

- [ ] **Step 3: Commit**

```bash
git add lap-website/src/components/app/corners/SpeedComparisonBars.tsx
git commit -m "feat(corners): animated speed comparison bars"
```

---

## Chunk 4: Accordion + Detail View Wiring

### Task 6: Accordion Panel Wrapper

**Files:**
- Create: `lap-website/src/components/app/corners/AccordionPanel.tsx`

- [ ] **Step 1: Create `AccordionPanel.tsx`**

Follow the `FaqAccordion.tsx` pattern:
- Grid `gridTemplateRows: isOpen ? '1fr' : '0fr'` for height animation
- `overflow-hidden` inner div
- Chevron rotation on open
- `aria-expanded`, `aria-controls`, `role="region"` for accessibility

```typescript
// lap-website/src/components/app/corners/AccordionPanel.tsx
'use client';

import { useState, useId } from 'react';

interface AccordionPanelProps {
  title: string;
  subtitle: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}

export function AccordionPanel({ title, subtitle, children, defaultOpen = false }: AccordionPanelProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen);
  const id = useId();
  const panelId = `${id}-panel`;
  const buttonId = `${id}-btn`;

  return (
    <div className="border-b border-steel/10">
      <button
        type="button"
        id={buttonId}
        onClick={() => setIsOpen((o) => !o)}
        aria-expanded={isOpen}
        aria-controls={panelId}
        className="w-full flex items-center justify-between py-4 px-1 text-left group"
      >
        <div>
          <span className="font-monument text-sm text-chalk tracking-tight">{title}</span>
          <p className="text-[11px] text-steel font-body mt-0.5">{subtitle}</p>
        </div>
        <span
          className="text-steel text-lg transition-transform duration-200 shrink-0 ml-4"
          style={{ transform: isOpen ? 'rotate(90deg)' : 'rotate(0deg)' }}
          aria-hidden="true"
        >
          ▸
        </span>
      </button>
      <div
        id={panelId}
        role="region"
        aria-labelledby={buttonId}
        className="grid transition-all duration-200 ease-out"
        style={{ gridTemplateRows: isOpen ? '1fr' : '0fr' }}
      >
        <div className="overflow-hidden">
          <div className="pb-4 px-1">{children}</div>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify build**

Run: `cd lap-website && npm run build 2>&1 | tail -5`

- [ ] **Step 3: Commit**

```bash
git add lap-website/src/components/app/corners/AccordionPanel.tsx
git commit -m "feat(corners): reusable accordion panel with animation"
```

---

### Task 7: Wire CornerDetailView with Real Components

**Files:**
- Modify: `lap-website/src/components/app/corners/CornerDetailView.tsx` (replace stub)

- [ ] **Step 1: Replace `CornerDetailView.tsx` stub with full orchestrator**

```typescript
// lap-website/src/components/app/corners/CornerDetailView.tsx
'use client';

import { useMemo } from 'react';
import type { CornerData, CornerMetricRow, TheoreticalData, CoachingData, GpsTrace } from './useCornerData';
import { CornerDetailHeader } from './CornerDetailHeader';
import { VerdictSection } from './VerdictSection';
import { SpeedComparisonBars } from './SpeedComparisonBars';
import { AccordionPanel } from './AccordionPanel';
import { LapByLapPanel } from './LapByLapPanel';
import { TheoreticalBestPanel } from './TheoreticalBestPanel';
import { HandlingEventsPanel } from './HandlingEventsPanel';
import { ProgressiveStepsPanel } from './ProgressiveStepsPanel';

interface CornerDetailViewProps {
  cornerId: number;
  data: {
    corners: CornerData[];
    metrics: CornerMetricRow[];
    theoretical: TheoreticalData | null;
    coaching: CoachingData | null;
    gpsTrace: GpsTrace | null;
  };
  onBack: () => void;
  onNavigate: (id: number) => void;
}

export function CornerDetailView({ cornerId, data, onBack, onNavigate }: CornerDetailViewProps) {
  const sortedCorners = useMemo(
    () => [...data.corners].sort((a, b) => a.corner_id - b.corner_id),
    [data.corners],
  );

  const cornerIndex = sortedCorners.findIndex((c) => c.corner_id === cornerId);
  const corner = sortedCorners[cornerIndex];

  const cornerMetrics = useMemo(
    () => data.metrics.filter((m) => m.corner_id === cornerId),
    [data.metrics, cornerId],
  );

  const theoCorner = useMemo(
    () => data.theoretical?.corner_coaching?.find((c) => c.corner_id === cornerId) ?? null,
    [data.theoretical, cornerId],
  );

  const focusArea = useMemo(
    () => data.coaching?.focus_areas?.find((fa) => fa.corner_ids?.includes(cornerId)) ?? null,
    [data.coaching, cornerId],
  );

  if (!corner) {
    return (
      <div className="py-12 text-center">
        <p className="text-steel font-body">Corner not found</p>
        <button onClick={onBack} className="text-acid-green text-sm mt-2 font-body">← Back to track</button>
      </div>
    );
  }

  const handlePrev = () => {
    if (cornerIndex > 0) onNavigate(sortedCorners[cornerIndex - 1].corner_id);
  };
  const handleNext = () => {
    if (cornerIndex < sortedCorners.length - 1) onNavigate(sortedCorners[cornerIndex + 1].corner_id);
  };

  return (
    <div>
      <CornerDetailHeader
        corner={corner}
        cornerIndex={cornerIndex}
        totalCorners={sortedCorners.length}
        onBack={onBack}
        onPrev={handlePrev}
        onNext={handleNext}
      />

      <VerdictSection corner={corner} />

      <SpeedComparisonBars corner={corner} />

      <div className="mt-4">
        <AccordionPanel title="Lap-by-Lap Breakdown" subtitle="Apex speed, brake point, exit speed across all laps">
          <LapByLapPanel metrics={cornerMetrics} />
        </AccordionPanel>

        <AccordionPanel title="Theoretical Best" subtitle="Physics-optimal speed profile vs your best lap">
          <TheoreticalBestPanel
            corner={corner}
            theoCorner={theoCorner}
            theoretical={data.theoretical}
            gpsTrace={data.gpsTrace}
          />
        </AccordionPanel>

        <AccordionPanel title="Handling Events" subtitle="Understeer / oversteer events at this corner">
          <HandlingEventsPanel events={corner.handling_events ?? []} />
        </AccordionPanel>

        <AccordionPanel title="Progressive Steps" subtitle="Step-by-step improvement plan for this corner">
          <ProgressiveStepsPanel
            focusArea={focusArea}
            coachingHint={corner.coaching_hint}
          />
        </AccordionPanel>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Create stub files for the 4 panel components**

Each panel gets a minimal stub that renders its empty state. This allows the build to pass while we implement each one.

```typescript
// LapByLapPanel.tsx
'use client';
import type { CornerMetricRow } from './useCornerData';
interface LapByLapPanelProps { metrics: CornerMetricRow[]; }
export function LapByLapPanel({ metrics }: LapByLapPanelProps) {
  if (metrics.length === 0) return <p className="text-steel text-sm font-body">Lap data not available for this corner</p>;
  return <p className="text-steel text-sm font-body">Lap-by-Lap — implementing...</p>;
}
```

```typescript
// TheoreticalBestPanel.tsx
'use client';
import type { CornerData, TheoCorner, TheoreticalData, GpsTrace } from './useCornerData';
interface TheoreticalBestPanelProps { corner: CornerData; theoCorner: TheoCorner | null; theoretical: TheoreticalData | null; gpsTrace: GpsTrace | null; }
export function TheoreticalBestPanel({ theoretical }: TheoreticalBestPanelProps) {
  if (!theoretical?.available) return <p className="text-steel text-sm font-body">Theoretical lap not available for this session</p>;
  return <p className="text-steel text-sm font-body">Theoretical Best — implementing...</p>;
}
```

```typescript
// HandlingEventsPanel.tsx
'use client';
import type { HandlingEvent } from './useCornerData';
interface HandlingEventsPanelProps { events: HandlingEvent[]; }
export function HandlingEventsPanel({ events }: HandlingEventsPanelProps) {
  if (events.length === 0) return <div className="flex items-center gap-2"><span className="text-acid-green">✓</span><span className="text-steel text-sm font-body">No handling events detected</span></div>;
  return <p className="text-steel text-sm font-body">Handling Events — implementing...</p>;
}
```

```typescript
// ProgressiveStepsPanel.tsx
'use client';
import type { FocusArea } from './useCornerData';
interface ProgressiveStepsPanelProps { focusArea: FocusArea | null; coachingHint: string | null | undefined; }
export function ProgressiveStepsPanel({ focusArea, coachingHint }: ProgressiveStepsPanelProps) {
  if (!focusArea && !coachingHint) return <p className="text-steel text-sm font-body">No coaching available for this corner</p>;
  return <p className="text-steel text-sm font-body">Progressive Steps — implementing...</p>;
}
```

- [ ] **Step 3: Verify build**

Run: `cd lap-website && npm run build 2>&1 | tail -5`
Expected: Build succeeds.

- [ ] **Step 4: Deploy and verify live**

Run: `cd lap-website && npm run cf:deploy 2>&1 | tail -10`
Expected: Deployment succeeds. Visit a session → Corners & Coaching tab → see track map with corner buttons, click one → see verdict + speed bars + accordion panels.

- [ ] **Step 5: Commit**

```bash
git add lap-website/src/components/app/corners/
git commit -m "feat(corners): wire corner detail view with verdict, speed bars, accordion stubs"
```

---

## Chunk 5: Panel Implementations

### Task 8: Lap-by-Lap Panel (Full)

**Files:**
- Modify: `lap-website/src/components/app/corners/LapByLapPanel.tsx` (replace stub)

- [ ] **Step 1: Implement full `LapByLapPanel.tsx`**

Compact table with one row per lap. Columns: Lap #, Brake Point (m), Apex Speed (km/h), Exit Speed (km/h), Time Loss (ms). Best lap row has `acid-green` left border, worst has `safety-red`. Show trend arrow if apex speed improves across laps (compare first half avg vs second half avg).

Est. ~120 lines.

- [ ] **Step 2: Verify build**

Run: `cd lap-website && npm run build 2>&1 | tail -5`

- [ ] **Step 3: Commit**

```bash
git add lap-website/src/components/app/corners/LapByLapPanel.tsx
git commit -m "feat(corners): lap-by-lap panel with best/worst highlights"
```

---

### Task 9: Theoretical Best Panel (Full)

**Files:**
- Modify: `lap-website/src/components/app/corners/TheoreticalBestPanel.tsx` (replace stub)

- [ ] **Step 1: Implement full `TheoreticalBestPanel.tsx`**

Canvas-rendered speed-over-distance chart for the corner zone. Two traces (actual best vs theoretical), delta shading between curves.

Key implementation:
- Slice `gpsTrace.distances[]` / `gpsTrace.speeds[]` to `[s_start, s_end]` range for actual line
- Slice `theoretical.distances[]` / `theoretical.speeds[]` to same range for theory line
- Interpolate both onto a common 200-point distance axis using linear interpolation
- Draw on canvas with DPR scaling (same pattern as TrackMapView)
- Delta shading: fill area between curves — red where actual < theory, green where actual > theory
- Key metrics row below chart: theoretical apex speed, optimal brake point (from `brake_release` if present), optimal exit speed, simulation method label

Est. ~200 lines.

- [ ] **Step 2: Verify build**

Run: `cd lap-website && npm run build 2>&1 | tail -5`

- [ ] **Step 3: Commit**

```bash
git add lap-website/src/components/app/corners/TheoreticalBestPanel.tsx
git commit -m "feat(corners): theoretical best panel with speed-over-distance chart"
```

---

### Task 10: Handling Events Panel (Full)

**Files:**
- Modify: `lap-website/src/components/app/corners/HandlingEventsPanel.tsx` (replace stub)

- [ ] **Step 1: Implement full `HandlingEventsPanel.tsx`**

```typescript
// lap-website/src/components/app/corners/HandlingEventsPanel.tsx
'use client';

import type { HandlingEvent } from './useCornerData';

interface HandlingEventsPanelProps {
  events: HandlingEvent[];
}

const SEVERITY_COLORS: Record<string, string> = {
  mild: 'bg-acid-green/20 text-acid-green',
  moderate: 'bg-marshal-yellow/20 text-marshal-yellow',
  severe: 'bg-safety-red/20 text-safety-red',
};

const TYPE_COLORS: Record<string, string> = {
  understeer: 'bg-blue-500/20 text-blue-400',
  oversteer: 'bg-pit-orange/20 text-pit-orange',
};

export function HandlingEventsPanel({ events }: HandlingEventsPanelProps) {
  if (events.length === 0) {
    return (
      <div className="flex items-center gap-2 py-2">
        <span className="text-acid-green text-lg">✓</span>
        <span className="text-steel text-sm font-body">No handling events detected — clean driving through this corner</span>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {events.map((ev, i) => (
        <div key={i} className="flex items-start gap-3 bg-concrete/50 rounded-lg p-3">
          <div className="flex flex-wrap gap-1.5 shrink-0">
            <span className={`text-[10px] font-telemetry font-semibold px-2 py-0.5 rounded ${TYPE_COLORS[ev.event_type] ?? 'bg-steel/20 text-steel'}`}>
              {ev.event_type.toUpperCase()}
            </span>
            <span className={`text-[10px] font-telemetry px-2 py-0.5 rounded ${SEVERITY_COLORS[ev.severity] ?? 'bg-steel/20 text-steel'}`}>
              {ev.severity}
            </span>
            <span className="text-[10px] font-telemetry px-2 py-0.5 rounded bg-steel/10 text-steel">
              {ev.corner_phase}
            </span>
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-chalk/80 text-sm font-body">{ev.cause_detail || ev.cause}</p>
            {ev.time_cost_s != null && (
              <p className="text-safety-red text-xs font-telemetry mt-1">
                {(ev.time_cost_s * 1000).toFixed(0)}ms cost
              </p>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Verify build**

Run: `cd lap-website && npm run build 2>&1 | tail -5`

- [ ] **Step 3: Commit**

```bash
git add lap-website/src/components/app/corners/HandlingEventsPanel.tsx
git commit -m "feat(corners): handling events panel with type/severity badges"
```

---

### Task 11: Progressive Steps Panel (Full)

**Files:**
- Modify: `lap-website/src/components/app/corners/ProgressiveStepsPanel.tsx` (replace stub)

- [ ] **Step 1: Implement full `ProgressiveStepsPanel.tsx`**

```typescript
// lap-website/src/components/app/corners/ProgressiveStepsPanel.tsx
'use client';

import type { FocusArea } from './useCornerData';

interface ProgressiveStepsPanelProps {
  focusArea: FocusArea | null;
  coachingHint: string | null | undefined;
}

function splitIntoSteps(text: string): string[] {
  // Try numbered items first: "1. Do this 2. Do that"
  const numbered = text.match(/\d+\.\s+[^.]+(?:\.|$)/g);
  if (numbered && numbered.length > 1) return numbered.map((s) => s.replace(/^\d+\.\s*/, '').trim());

  // Try semicolons
  const semicolons = text.split(/;\s*/);
  if (semicolons.length > 1) return semicolons.map((s) => s.trim()).filter(Boolean);

  // Fall back to sentences
  const sentences = text.split(/(?<=\.)\s+/).filter((s) => s.length > 10);
  if (sentences.length > 1) return sentences;

  return [text];
}

export function ProgressiveStepsPanel({ focusArea, coachingHint }: ProgressiveStepsPanelProps) {
  const rawText = focusArea?.advice ?? coachingHint;

  if (!rawText) {
    return <p className="text-steel text-sm font-body">No coaching available for this corner.</p>;
  }

  const steps = splitIntoSteps(rawText);

  return (
    <div className="space-y-3">
      {focusArea && (
        <p className="text-steel text-xs font-telemetry uppercase tracking-wider mb-2">
          {focusArea.category.replace(/_/g, ' ')} — {focusArea.time_loss_s.toFixed(3)}s total loss
        </p>
      )}
      <ol className="space-y-3">
        {steps.map((step, i) => (
          <li key={i} className="flex items-start gap-3">
            <span className="shrink-0 w-6 h-6 rounded-full bg-concrete border border-steel/20 flex items-center justify-center text-xs font-telemetry text-steel">
              {i + 1}
            </span>
            <p className="text-chalk/80 text-sm font-body leading-relaxed pt-0.5">{step}</p>
          </li>
        ))}
      </ol>
    </div>
  );
}
```

- [ ] **Step 2: Verify build**

Run: `cd lap-website && npm run build 2>&1 | tail -5`

- [ ] **Step 3: Commit**

```bash
git add lap-website/src/components/app/corners/ProgressiveStepsPanel.tsx
git commit -m "feat(corners): progressive steps panel with text splitting"
```

---

## Chunk 6: Final Deploy + Verify

### Task 12: Build, Deploy, Verify

- [ ] **Step 1: Full build**

Run: `cd lap-website && npm run build 2>&1 | tail -10`
Expected: Build succeeds with no errors.

- [ ] **Step 2: Deploy to Cloudflare Workers**

Run: `cd lap-website && npm run cf:deploy 2>&1 | tail -10`
Expected: Deployment succeeds.

- [ ] **Step 3: Verify live**

Visit a session with corner data on `lap-coach.racing`:
1. Go to Corners & Coaching tab → see track map (or button list) with corners
2. Click a corner → full detail view takes over
3. See verdict (time loss + cause + tip) and speed bars above fold
4. Expand each accordion panel → content renders
5. Navigate prev/next between corners
6. Click "Back to track" → returns to map

- [ ] **Step 4: Final commit with all files**

```bash
git add lap-website/src/components/app/corners/
git commit -m "feat(corners): complete corner coaching UI rebuild

Track map entry point with color-coded corner dots.
Full-takeover corner detail view with:
- Verdict section (time loss + primary cause + coaching tip)
- Speed comparison bars (entry/apex/exit actual vs theoretical)
- Lap-by-Lap breakdown panel
- Theoretical Best panel (speed-over-distance chart)
- Handling Events panel (understeer/oversteer badges)
- Progressive Steps panel (coaching advice)"
```
