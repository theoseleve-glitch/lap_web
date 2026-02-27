# Free Report Funnel — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a zero-friction free report funnel — homepage CTA → register (auto-login) → upload CSV → limited report with upgrade CTAs.

**Architecture:** Isolated `(free-report)` Next.js route group with its own minimal layout (no sidebar/navbar). Reuses existing chart components and API client. Auto-login after registration via query param redirect. Locked sections use blur + overlay pattern.

**Tech Stack:** Next.js 14 App Router, React, TypeScript, TanStack React Query, Tailwind CSS

---

### Task 1: LockedSection Component

**Files:**
- Create: `src/components/app/LockedSection.tsx`
- Modify: `src/components/app/index.ts:5` (add export)

**Step 1: Create the LockedSection component**

```tsx
// src/components/app/LockedSection.tsx
import Link from 'next/link';

interface LockedSectionProps {
  title: string;
  description: string;
  children: React.ReactNode;
}

export function LockedSection({ title, description, children }: LockedSectionProps) {
  return (
    <div className="relative rounded-lg overflow-hidden">
      {/* Blurred content */}
      <div className="blur-sm opacity-30 pointer-events-none select-none" aria-hidden="true">
        {children}
      </div>

      {/* Overlay */}
      <div className="absolute inset-0 flex flex-col items-center justify-center bg-asphalt/60 backdrop-blur-[1px]">
        <div className="w-12 h-12 rounded-full bg-steel/20 flex items-center justify-center mb-3">
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none" className="text-steel">
            <rect x="3" y="9" width="14" height="9" rx="2" stroke="currentColor" strokeWidth="1.5" />
            <path d="M6 9V6a4 4 0 1 1 8 0v3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        </div>
        <p className="font-monument text-lg text-chalk mb-1">{title}</p>
        <p className="text-steel font-body text-sm mb-4 text-center max-w-xs">{description}</p>
        <Link
          href="/pricing"
          className="px-5 py-2 bg-pit-orange text-asphalt font-monument text-sm tracking-wider rounded hover:brightness-110 transition-all"
        >
          Unlock with Performance
        </Link>
      </div>
    </div>
  );
}
```

**Step 2: Add export to barrel file**

Add to `src/components/app/index.ts`:
```ts
export { LockedSection } from './LockedSection';
```

**Step 3: Commit**

```bash
git add src/components/app/LockedSection.tsx src/components/app/index.ts
git commit -m "feat(free-report): add LockedSection component with blur + upgrade overlay"
```

---

### Task 2: UpgradeBanner Component

**Files:**
- Create: `src/components/app/UpgradeBanner.tsx`
- Modify: `src/components/app/index.ts` (add export)

**Step 1: Create the UpgradeBanner component**

```tsx
// src/components/app/UpgradeBanner.tsx
import Link from 'next/link';

export function UpgradeBanner() {
  return (
    <div className="bg-pit-orange/10 border border-pit-orange/30 rounded-lg px-6 py-4 flex items-center justify-between mb-6">
      <div>
        <p className="font-monument text-sm text-pit-orange tracking-wider">FREE REPORT</p>
        <p className="text-chalk font-body text-sm mt-0.5">
          You&apos;re viewing a free report. Upgrade to Performance for the full analysis.
        </p>
      </div>
      <Link
        href="/pricing"
        className="shrink-0 px-5 py-2.5 bg-pit-orange text-asphalt font-monument text-sm tracking-wider rounded hover:brightness-110 transition-all"
      >
        Upgrade Now
      </Link>
    </div>
  );
}
```

**Step 2: Add export to barrel file**

Add to `src/components/app/index.ts`:
```ts
export { UpgradeBanner } from './UpgradeBanner';
```

**Step 3: Commit**

```bash
git add src/components/app/UpgradeBanner.tsx src/components/app/index.ts
git commit -m "feat(free-report): add UpgradeBanner component"
```

---

### Task 3: Free Report Layout

**Files:**
- Create: `src/app/(free-report)/layout.tsx`

The `(free-report)` route group uses a parenthesized folder name so it doesn't affect the URL path. The layout provides minimal chrome — LAP logo, step indicator, and no sidebar.

**Step 1: Create the layout**

```tsx
// src/app/(free-report)/layout.tsx
'use client';

import type { ReactNode } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { QueryProvider } from '@/providers/query-provider';

const steps = [
  { label: 'Upload', path: '/free-report/analyze' },
  { label: 'Results', path: '/free-report/report' },
] as const;

export default function FreeReportLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  const currentStepIndex = steps.findIndex((s) => pathname.startsWith(s.path));

  return (
    <div className="min-h-screen bg-asphalt flex flex-col">
      {/* Minimal header */}
      <header className="border-b border-steel/20 bg-concrete">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between">
          {/* Logo */}
          <Link href="/" className="font-monument text-2xl text-chalk tracking-tight">
            LAP
          </Link>

          {/* Step indicator */}
          <div className="flex items-center gap-3">
            {steps.map((step, i) => {
              const isActive = i === currentStepIndex;
              const isComplete = i < currentStepIndex;
              return (
                <div key={step.label} className="flex items-center gap-3">
                  {i > 0 && (
                    <div className={`w-8 h-0.5 ${isComplete ? 'bg-acid-green' : 'bg-steel/30'}`} />
                  )}
                  <div className="flex items-center gap-2">
                    <div
                      className={`w-6 h-6 rounded-full flex items-center justify-center font-telemetry text-xs ${
                        isActive
                          ? 'bg-acid-green text-asphalt'
                          : isComplete
                            ? 'bg-acid-green/20 text-acid-green'
                            : 'bg-concrete text-steel border border-steel/30'
                      }`}
                    >
                      {isComplete ? '✓' : i + 1}
                    </div>
                    <span className={`font-body text-sm ${isActive ? 'text-chalk' : 'text-steel'}`}>
                      {step.label}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Spacer to balance logo */}
          <div className="w-12" />
        </div>
      </header>

      {/* Content */}
      <QueryProvider>
        <main className="flex-1">
          <div className="max-w-5xl mx-auto px-6 py-8">
            {children}
          </div>
        </main>
      </QueryProvider>
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add "src/app/(free-report)/layout.tsx"
git commit -m "feat(free-report): add minimal layout with step indicator"
```

---

### Task 4: Free Report Analyze Page

**Files:**
- Create: `src/app/(free-report)/free-report/analyze/page.tsx`

This is a simplified version of `src/app/app/analyze/page.tsx`. Key differences:
- Upload only (no file browser of existing files)
- Text inputs for driver/track (not dropdowns from DB)
- No kart field
- Redirects to `/free-report/report/[id]` on completion
- Checks localStorage for `free_report_used` flag

**Step 1: Create the page**

```tsx
// src/app/(free-report)/free-report/analyze/page.tsx
'use client';

import { useState, useRef, useCallback, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api-client';
import { FormField } from '@/components/app';
import Link from 'next/link';

type Step = 1 | 2 | 3;

const SESSION_TYPES = ['Practice', 'Qualifying', 'Race', 'Test'] as const;

interface AnalysisJob {
  job_id: string;
  status: 'pending' | 'processing' | 'complete' | 'failed';
  progress: number;
  message: string;
  session_id?: string;
}

export default function FreeReportAnalyzePage() {
  const router = useRouter();
  const [step, setStep] = useState<Step>(1);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Step 2
  const [driverName, setDriverName] = useState('');
  const [trackName, setTrackName] = useState('');
  const [sessionType, setSessionType] = useState<string>(SESSION_TYPES[0]);

  // Step 3
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<AnalysisJob | null>(null);

  // One-report limit check
  const [alreadyUsed, setAlreadyUsed] = useState(false);
  const [existingSessionId, setExistingSessionId] = useState<string | null>(null);

  useEffect(() => {
    const stored = localStorage.getItem('lap_free_report');
    if (stored) {
      try {
        const parsed = JSON.parse(stored);
        if (parsed.used) {
          setAlreadyUsed(true);
          setExistingSessionId(parsed.session_id ?? null);
        }
      } catch {
        // ignore
      }
    }
  }, []);

  // Poll job status
  useQuery({
    queryKey: ['analysis-job', jobId],
    queryFn: () => api.get<AnalysisJob>(`/ingest/status/${jobId}`),
    enabled: step === 3 && !!jobId && jobStatus?.status !== 'complete' && jobStatus?.status !== 'failed',
    refetchInterval: 2000,
    select: (data) => {
      setJobStatus(data);
      if (data.status === 'complete' && data.session_id) {
        // Save one-report flag
        localStorage.setItem(
          'lap_free_report',
          JSON.stringify({ used: true, session_id: data.session_id }),
        );
      }
      return data;
    },
  });

  const handleUpload = useCallback(async (file: File) => {
    setUploading(true);
    setUploadProgress(0);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const result = await fetch('/api/v1/files/upload', {
        method: 'POST',
        body: formData,
      });
      if (!result.ok) throw new Error('Upload failed');
      const data = await result.json();
      setSelectedFile(data.data?.filename ?? file.name);
      setUploadProgress(100);
    } catch {
      setUploadProgress(0);
    } finally {
      setUploading(false);
    }
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const file = e.dataTransfer.files[0];
      if (file?.name.endsWith('.csv')) {
        handleUpload(file);
      }
    },
    [handleUpload],
  );

  const handleSubmit = async () => {
    if (!selectedFile) return;
    setStep(3);
    try {
      const result = await api.post<{ job_id: string }>('/ingest/start', {
        csv_file: selectedFile,
        driver_name: driverName || null,
        track_name: trackName || null,
        session_type: sessionType,
      });
      setJobId(result.job_id);
      setJobStatus({ job_id: result.job_id, status: 'pending', progress: 0, message: 'Starting analysis...' });
    } catch {
      setJobStatus({ job_id: '', status: 'failed', progress: 0, message: 'Failed to start analysis' });
    }
  };

  // Already used — show redirect
  if (alreadyUsed) {
    return (
      <div className="bg-concrete rounded-lg border border-steel/20 p-8 text-center">
        <div className="w-16 h-16 rounded-full bg-pit-orange/20 flex items-center justify-center mx-auto mb-4">
          <span className="text-pit-orange text-2xl">1</span>
        </div>
        <h2 className="font-monument text-xl text-chalk mb-2">Free Report Already Used</h2>
        <p className="text-steel font-body mb-6 max-w-md mx-auto">
          You&apos;ve already generated your free report. Upgrade to Performance to analyze unlimited sessions.
        </p>
        <div className="flex gap-3 justify-center">
          {existingSessionId && (
            <Link
              href={`/free-report/report/${existingSessionId}`}
              className="px-5 py-2.5 bg-concrete border border-steel/30 text-chalk font-telemetry text-sm rounded hover:bg-asphalt/50 transition-colors"
            >
              View Your Report
            </Link>
          )}
          <Link
            href="/pricing"
            className="px-5 py-2.5 bg-pit-orange text-asphalt font-monument text-sm tracking-wider rounded hover:brightness-110 transition-all"
          >
            Upgrade Now
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="text-center mb-8">
        <h1 className="font-monument text-3xl text-chalk tracking-tight mb-2">YOUR FREE REPORT</h1>
        <p className="text-steel font-body">Upload your telemetry CSV and get instant analysis</p>
      </div>

      {/* Step 1: Upload */}
      {step === 1 && (
        <div className="bg-concrete rounded-lg border border-steel/20 p-6 max-w-2xl mx-auto">
          <h2 className="font-body text-chalk text-lg mb-4">Upload Your Data</h2>

          <div
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            className={`border-2 border-dashed rounded-lg p-12 text-center transition-colors ${
              dragOver ? 'border-acid-green bg-acid-green/5' : 'border-steel/30'
            }`}
          >
            <p className="text-steel font-body mb-2">Drop your RaceChrono or RaceBox CSV here</p>
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="px-5 py-2.5 bg-pit-orange text-asphalt font-monument text-sm tracking-wider rounded hover:brightness-110 transition-all"
            >
              Choose File
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) handleUpload(file);
              }}
            />
          </div>

          {uploading && (
            <div className="mt-4">
              <div className="w-full bg-steel/20 rounded-full h-2">
                <div
                  className="bg-acid-green h-2 rounded-full transition-all"
                  style={{ width: `${uploadProgress}%` }}
                />
              </div>
              <span className="text-steel font-telemetry text-xs mt-1">Uploading...</span>
            </div>
          )}

          {selectedFile && (
            <div className="mt-4 p-3 bg-acid-green/5 border border-acid-green/20 rounded text-acid-green font-telemetry text-sm">
              Selected: {selectedFile}
            </div>
          )}

          <div className="flex justify-end mt-6">
            <button
              type="button"
              disabled={!selectedFile}
              onClick={() => setStep(2)}
              className="px-6 py-2.5 bg-acid-green text-asphalt font-telemetry text-sm rounded disabled:opacity-30 disabled:cursor-not-allowed hover:bg-acid-green/80 transition-colors"
            >
              Next: Configure
            </button>
          </div>
        </div>
      )}

      {/* Step 2: Configure */}
      {step === 2 && (
        <div className="bg-concrete rounded-lg border border-steel/20 p-6 max-w-2xl mx-auto">
          <h2 className="font-body text-chalk text-lg mb-4">Session Details</h2>

          <div className="mb-3 p-3 bg-asphalt/50 rounded border border-steel/20 flex items-center gap-2">
            <span className="text-steel">File:</span>
            <span className="text-acid-green font-telemetry text-sm">{selectedFile}</span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-steel font-telemetry text-xs uppercase mb-1">
                Session Type
              </label>
              <select
                value={sessionType}
                onChange={(e) => setSessionType(e.target.value)}
                className="w-full bg-asphalt border border-steel/30 rounded px-3 py-2 text-chalk font-body text-sm focus:outline-none focus:border-pit-orange"
              >
                {SESSION_TYPES.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </div>

            <FormField
              label="Driver Name"
              type="text"
              placeholder="Your name (optional)"
              value={driverName}
              onChange={(e) => setDriverName(e.target.value)}
            />

            <FormField
              label="Track / Circuit"
              type="text"
              placeholder="Auto-detected if possible"
              value={trackName}
              onChange={(e) => setTrackName(e.target.value)}
            />
          </div>

          <div className="flex justify-between mt-6">
            <button
              type="button"
              onClick={() => setStep(1)}
              className="px-4 py-2 text-steel font-telemetry text-sm hover:text-chalk transition-colors"
            >
              Back
            </button>
            <button
              type="button"
              onClick={handleSubmit}
              className="px-6 py-2.5 bg-acid-green text-asphalt font-monument text-sm tracking-wider rounded hover:bg-acid-green/80 transition-colors"
            >
              Start Analysis
            </button>
          </div>
        </div>
      )}

      {/* Step 3: Progress */}
      {step === 3 && (
        <div className="bg-concrete rounded-lg border border-steel/20 p-6 max-w-2xl mx-auto">
          <div className="flex flex-col items-center py-8">
            {jobStatus?.status === 'complete' ? (
              <>
                <div className="w-16 h-16 rounded-full bg-acid-green/20 flex items-center justify-center mb-4">
                  <span className="text-acid-green text-3xl">✓</span>
                </div>
                <p className="text-chalk font-body text-lg mb-2">Analysis Complete</p>
                <p className="text-steel font-body text-sm mb-6">{jobStatus.message}</p>
                <button
                  type="button"
                  onClick={() =>
                    router.push(
                      jobStatus.session_id
                        ? `/free-report/report/${jobStatus.session_id}`
                        : '/free-report/analyze',
                    )
                  }
                  className="px-6 py-2.5 bg-acid-green text-asphalt font-monument text-sm tracking-wider rounded hover:bg-acid-green/80 transition-colors"
                >
                  View Your Report
                </button>
              </>
            ) : jobStatus?.status === 'failed' ? (
              <>
                <div className="w-16 h-16 rounded-full bg-safety-red/20 flex items-center justify-center mb-4">
                  <span className="text-safety-red text-3xl">✗</span>
                </div>
                <p className="text-chalk font-body text-lg mb-2">Analysis Failed</p>
                <p className="text-safety-red font-body text-sm mb-6">{jobStatus.message}</p>
                <button
                  type="button"
                  onClick={() => {
                    setStep(1);
                    setJobId(null);
                    setJobStatus(null);
                  }}
                  className="px-4 py-2 text-steel font-telemetry text-sm hover:text-chalk transition-colors"
                >
                  Try Again
                </button>
              </>
            ) : (
              <>
                <div className="w-12 h-12 border-3 border-steel/30 border-t-acid-green rounded-full animate-spin mb-4" />
                <p className="text-chalk font-body mb-2">
                  {jobStatus?.message ?? 'Starting analysis...'}
                </p>
                <div className="w-full max-w-md">
                  <div className="w-full bg-steel/20 rounded-full h-2 mb-1">
                    <div
                      className="bg-acid-green h-2 rounded-full transition-all duration-500"
                      style={{ width: `${jobStatus?.progress ?? 0}%` }}
                    />
                  </div>
                  <div className="text-right">
                    <span className="font-telemetry text-xs text-steel">
                      {jobStatus?.progress ?? 0}%
                    </span>
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add "src/app/(free-report)/free-report/analyze/page.tsx"
git commit -m "feat(free-report): add upload + configure + process wizard page"
```

---

### Task 5: Free Report Page (Limited Report)

**Files:**
- Create: `src/app/(free-report)/free-report/report/[id]/page.tsx`

This page shows the limited report: score cards, Track Map, Speed Trace, top-1 corner, and locked sections for everything else.

**Step 1: Create the report page**

```tsx
// src/app/(free-report)/free-report/report/[id]/page.tsx
'use client';

import { useQuery } from '@tanstack/react-query';
import { useParams } from 'next/navigation';
import { api } from '@/lib/api-client';
import { StatCard, DataTable, LockedSection, UpgradeBanner } from '@/components/app';
import { SpeedTrace, TrackMap, GGDiagram, DrivingStyle } from '@/components/app/charts';
import { CornerReplay } from '@/components/app/corner-replay';

interface SessionDetail {
  id: string;
  date: string;
  track_name: string;
  driver_name: string;
  laps: number;
  best_time: number | null;
  score: number | null;
  grade: string | null;
  consistency_score: number | null;
  pace_score: number | null;
  execution_score: number | null;
  robustness_score: number | null;
}

interface LapRow {
  lap_number: number;
  time: number;
  speed_avg: number | null;
  valid: boolean;
}

interface CornerSummary {
  corner_id: number;
  corner_name: string;
  time_loss: number;
}

function formatTime(s: number | null): string {
  if (s == null) return '--';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}

export default function FreeReportPage() {
  const { id } = useParams<{ id: string }>();

  const { data: session, isLoading } = useQuery({
    queryKey: ['session', id],
    queryFn: () => api.get<SessionDetail>(`/sessions/${id}/details`),
  });

  const { data: lapsData } = useQuery({
    queryKey: ['session', id, 'laps'],
    queryFn: () => api.get<{ laps: LapRow[] }>(`/sessions/${id}/laps`),
  });

  const { data: cornersData } = useQuery({
    queryKey: ['session', id, 'corners'],
    queryFn: () => api.get<{ corners: CornerSummary[] }>(`/sessions/${id}/corners`),
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-48">
        <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
      </div>
    );
  }

  if (!session) {
    return <div className="text-steel font-body">Session not found</div>;
  }

  const laps = lapsData?.laps ?? [];
  const corners = cornersData?.corners ?? [];
  // Sort by time_loss descending to find worst corner
  const worstCorner = [...corners].sort((a, b) => b.time_loss - a.time_loss)[0];

  const previewLaps = laps.slice(0, 3);

  const lapColumns = [
    { key: 'lap_number', header: 'Lap', sortable: true, className: 'font-telemetry w-16' },
    {
      key: 'time',
      header: 'Time',
      sortable: true,
      className: 'font-telemetry',
      render: (row: LapRow) => <span className="text-acid-green">{formatTime(row.time)}</span>,
    },
    {
      key: 'speed_avg',
      header: 'Avg Speed',
      className: 'font-telemetry',
      render: (row: LapRow) => (
        <span>{row.speed_avg != null ? `${row.speed_avg.toFixed(1)} km/h` : '--'}</span>
      ),
    },
    {
      key: 'valid',
      header: 'Valid',
      className: 'font-telemetry',
      render: (row: LapRow) => (
        <span className={row.valid ? 'text-acid-green' : 'text-safety-red'}>
          {row.valid ? 'Y' : 'N'}
        </span>
      ),
    },
  ];

  return (
    <div>
      {/* Header */}
      <div className="mb-6">
        <h1 className="font-monument text-3xl text-chalk tracking-tight">
          {session.track_name}
        </h1>
        <p className="text-steel font-body mt-1">
          {session.driver_name} -- {session.date} -- {session.laps} laps
        </p>
      </div>

      {/* Upgrade banner */}
      <UpgradeBanner />

      {/* Primary score cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
        <StatCard label="Best Time" value={formatTime(session.best_time)} trend="neutral" />
        <StatCard label="Total Laps" value={session.laps} />
        <StatCard
          label="Score"
          value={session.score?.toFixed(1) ?? '--'}
          unit="/100"
          trend={session.score != null && session.score >= 75 ? 'up' : 'neutral'}
        />
        <StatCard label="Grade" value={session.grade ?? '--'} />
      </div>

      {/* Score breakdown */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <StatCard label="Pace" value={session.pace_score?.toFixed(1) ?? '--'} unit="/25" />
        <StatCard label="Consistency" value={session.consistency_score?.toFixed(1) ?? '--'} unit="/25" />
        <StatCard label="Execution" value={session.execution_score?.toFixed(1) ?? '--'} unit="/25" />
        <StatCard label="Robustness" value={session.robustness_score?.toFixed(1) ?? '--'} unit="/25" />
      </div>

      {/* FREE: Track Map + Speed Trace */}
      <div className="mb-6">
        <h2 className="font-monument text-lg text-chalk tracking-tight mb-4">ANALYSIS</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <TrackMap sessionId={id} />
          <SpeedTrace sessionId={id} />
        </div>
      </div>

      {/* LOCKED: Full Overview (GG Diagram + Driving Style) */}
      <div className="mb-6">
        <LockedSection title="Full Overview" description="GG diagram, driving style analysis, and more">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <GGDiagram sessionId={id} />
            <DrivingStyle sessionId={id} />
          </div>
        </LockedSection>
      </div>

      {/* FREE: Top 1 Corner Coaching */}
      {worstCorner && (
        <div className="mb-6">
          <h2 className="font-monument text-lg text-chalk tracking-tight mb-4">KEY CORNER</h2>
          <p className="text-steel font-body text-sm mb-3">
            Your biggest time loss: {worstCorner.corner_name} ({worstCorner.time_loss.toFixed(3)}s)
          </p>
          <div className="h-[400px] bg-concrete rounded-lg border border-steel/20 overflow-hidden">
            <CornerReplay sessionId={id} cornerId={worstCorner.corner_id} />
          </div>
        </div>
      )}

      {/* LOCKED: Remaining Corners */}
      {corners.length > 1 && (
        <div className="mb-6">
          <LockedSection
            title={`All ${corners.length} Corners`}
            description="See detailed coaching for every corner on the circuit"
          >
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 p-4">
              {corners.slice(1, 4).map((c) => (
                <div key={c.corner_id} className="bg-asphalt rounded-lg p-4 border border-steel/20">
                  <p className="font-monument text-sm text-chalk">{c.corner_name}</p>
                  <p className="text-steel font-telemetry text-xs mt-1">
                    Time loss: {c.time_loss.toFixed(3)}s
                  </p>
                </div>
              ))}
            </div>
          </LockedSection>
        </div>
      )}

      {/* LOCKED: Pace Analysis */}
      <div className="mb-6">
        <LockedSection title="Pace Analysis" description="Lap-by-lap progression, sector times, and distribution">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 h-48">
            <div className="bg-asphalt rounded-lg border border-steel/10 p-4" />
            <div className="bg-asphalt rounded-lg border border-steel/10 p-4" />
          </div>
        </LockedSection>
      </div>

      {/* LOCKED: Style Analysis */}
      <div className="mb-6">
        <LockedSection title="Style Analysis" description="Fingerprint, consistency heatmap, and brake analysis">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 h-48">
            <div className="bg-asphalt rounded-lg border border-steel/10 p-4" />
            <div className="bg-asphalt rounded-lg border border-steel/10 p-4" />
          </div>
        </LockedSection>
      </div>

      {/* LOCKED: Physics Analysis */}
      <div className="mb-6">
        <LockedSection title="Physics Analysis" description="Energy balance, fatigue, speed profile, and throttle map">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 h-48">
            <div className="bg-asphalt rounded-lg border border-steel/10 p-4" />
            <div className="bg-asphalt rounded-lg border border-steel/10 p-4" />
          </div>
        </LockedSection>
      </div>

      {/* Lap Data: first 3 visible, rest locked */}
      {laps.length > 0 && (
        <div className="mb-6">
          <h2 className="font-monument text-lg text-chalk tracking-tight mb-3">LAP TIMES</h2>
          <DataTable columns={lapColumns} data={previewLaps} keyField="lap_number" />

          {laps.length > 3 && (
            <div className="mt-2">
              <LockedSection
                title="Full Lap Data"
                description={`See all ${laps.length} laps with detailed timing`}
              >
                <div className="h-24 bg-asphalt rounded-lg border border-steel/10" />
              </LockedSection>
            </div>
          )}
        </div>
      )}

      {/* Bottom upgrade CTA */}
      <div className="text-center py-8 border-t border-steel/20 mt-8">
        <p className="font-monument text-xl text-chalk mb-2">WANT THE FULL PICTURE?</p>
        <p className="text-steel font-body mb-6">
          Upgrade to Performance for unlimited sessions, all corners, and every analysis tab.
        </p>
        <a
          href="/pricing"
          className="inline-block px-8 py-3 bg-pit-orange text-asphalt font-monument text-lg tracking-wider rounded hover:brightness-110 transition-all"
        >
          Upgrade to Performance — €8.99/mo
        </a>
      </div>
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add "src/app/(free-report)/free-report/report/[id]/page.tsx"
git commit -m "feat(free-report): add limited report page with locked sections + upgrade CTAs"
```

---

### Task 6: Auto-Login on Registration

**Files:**
- Modify: `src/app/(auth)/register/page.tsx:18-38`
- Modify: `src/lib/auth.ts` (add `storeTokens` helper)

The register page currently calls `register()` then redirects to `/login`. We need it to also call `login()` and store tokens, then redirect to the `?redirect=` query param.

**Step 1: Add token storage helper to auth.ts**

Add at the bottom of `src/lib/auth.ts`:
```ts
/** Store auth tokens in localStorage */
export function storeTokens(accessToken: string, refreshToken: string) {
  localStorage.setItem('lap_access_token', accessToken);
  localStorage.setItem('lap_refresh_token', refreshToken);
}

/** Clear stored auth tokens */
export function clearTokens() {
  localStorage.removeItem('lap_access_token');
  localStorage.removeItem('lap_refresh_token');
}
```

**Step 2: Update register page to auto-login + redirect**

Replace `handleSubmit` in `src/app/(auth)/register/page.tsx` (lines 18-38). The key changes are:
1. Import `login`, `storeTokens` from auth
2. Import `useSearchParams` from next/navigation
3. After `register()`, call `login()` with same credentials
4. Store tokens
5. Redirect to `searchParams.get('redirect')` or fallback to `/login?registered=true`

Replace the imports section (lines 1-7):
```tsx
'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { FormField } from '@/components/app/FormField';
import { register, login, storeTokens } from '@/lib/auth';
```

Replace `handleSubmit` (lines 18-38):
```tsx
  const searchParams = useSearchParams();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (password !== confirmPassword) {
      setError('Passwords do not match');
      return;
    }
    if (password.length < 8) {
      setError('Password must be at least 8 characters');
      return;
    }

    setLoading(true);
    setError(null);
    try {
      await register(email, password, displayName);

      // Auto-login after registration
      const loginResult = await login(email, password);
      storeTokens(loginResult.access_token, loginResult.refresh_token);

      // Redirect to specified destination or default
      const redirect = searchParams.get('redirect');
      router.push(redirect ?? '/login?registered=true');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Registration failed');
    } finally {
      setLoading(false);
    }
  };
```

**Step 3: Commit**

```bash
git add src/lib/auth.ts "src/app/(auth)/register/page.tsx"
git commit -m "feat(auth): auto-login after registration with redirect param support"
```

---

### Task 7: Update Homepage CTAs

**Files:**
- Modify: `src/components/site/SiteHeader.tsx` (update "Start Free Report" link)
- Modify: Podium room component (update CTA link)

The CTA buttons currently link to `/register?source=podium-free-report`. Update them to include the redirect parameter: `/register?source=free-report&redirect=/free-report/analyze`.

**Step 1: Find and update CTA links**

In `SiteHeader.tsx`, find the "Start Free Report" CTA and change its `href` from:
```
/register?source=podium-free-report
```
to:
```
/register?source=free-report&redirect=/free-report/analyze
```

Do the same for the Podium room CTA. Search for all occurrences of `podium-free-report` or `free-report` in the marketing components and update the links.

**Step 2: Commit**

```bash
git add src/components/site/SiteHeader.tsx
git commit -m "feat(marketing): update free report CTAs to redirect through registration to upload wizard"
```

---

### Task 8: Build Verification

**Step 1: Run TypeScript check**

```bash
npx tsc --noEmit
```

Expected: No errors.

**Step 2: Run the dev server**

```bash
npm run dev
```

Verify:
1. Homepage "Start Free Report" → goes to `/register?source=free-report&redirect=/free-report/analyze`
2. Register form → auto-login → redirect to `/free-report/analyze`
3. `/free-report/analyze` shows upload wizard (no sidebar, no navbar)
4. Upload + configure → processing → redirects to `/free-report/report/[id]`
5. Report shows: score cards, track map, speed trace, top corner, locked sections with blur
6. Returning to `/free-report/analyze` shows "already used" message
7. "Upgrade Now" buttons link to `/pricing`

**Step 3: Final commit**

```bash
git add -A
git commit -m "feat(free-report): complete free report funnel — register → upload → limited report"
```

---

## File Summary

| File | Action | Purpose |
|------|--------|---------|
| `src/components/app/LockedSection.tsx` | Create | Blur + lock overlay + upgrade CTA |
| `src/components/app/UpgradeBanner.tsx` | Create | Top banner with upgrade message |
| `src/components/app/index.ts` | Modify | Add exports for new components |
| `src/app/(free-report)/layout.tsx` | Create | Minimal layout (logo + step indicator) |
| `src/app/(free-report)/free-report/analyze/page.tsx` | Create | Upload + configure + process wizard |
| `src/app/(free-report)/free-report/report/[id]/page.tsx` | Create | Limited report + locked sections |
| `src/lib/auth.ts` | Modify | Add `storeTokens`/`clearTokens` helpers |
| `src/app/(auth)/register/page.tsx` | Modify | Auto-login + redirect param support |
| `src/components/site/SiteHeader.tsx` | Modify | Update CTA href |
