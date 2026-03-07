'use client';

import { useState, useRef, useCallback, useEffect } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { PageHeader } from '@/components/app';
import { BACKEND_URL, ApiError } from '@/lib/api-client';
import { getAccessToken, getWorkspaceId, getUserProfile } from '@/lib/auth-store';
import { CornerPicker, type TrackLayout } from '@/components/app/CornerPicker';
import { logger } from '@/lib/logger';

/* ── Types ──────────────────────────────────────────── */

interface UploadResponse {
  job_id: string;
  status: string;
}

type PageState =
  | 'idle'
  | 'uploading'
  | 'tracking'
  | 'awaiting_corners'
  | 'resuming'
  | 'completed'
  | 'error';

interface SSEEvent {
  status: string;
  stage_name: string | null;
  progress_pct: number;
  error_message: string | null;
  session_id?: string;
}

const SESSION_TYPES = [
  { value: 'practice', label: 'Practice' },
  { value: 'qualifying', label: 'Qualifying' },
  { value: 'race', label: 'Race' },
  { value: 'heat', label: 'Heat' },
  { value: 'final', label: 'Final' },
  { value: 'endurance', label: 'Endurance' },
];

const TRACK_STATES = [
  { value: 'dry', label: 'Dry' },
  { value: 'wet', label: 'Wet' },
  { value: 'damp', label: 'Damp' },
  { value: 'green', label: 'Green' },
  { value: 'rubbered', label: 'Rubbered' },
  { value: 'dusty', label: 'Dusty' },
];

const ACCEPTED_EXTENSIONS = '.csv,.txt';

/** Human-readable stage names for the progress bar. */
const STAGE_LABELS: Record<string, string> = {
  ingest: 'Reading CSV',
  csv_read: 'Reading CSV',
  gps_filter: 'GPS Filtering',
  derived_channels: 'Computing Channels',
  session_trim: 'Trimming Session',
  analyze: 'Analyzing',
  track_detect: 'Detecting Track',
  corner_detect: 'Detecting Corners',
  resample: 'Resampling Laps',
  features: 'Computing Features',
  finalize: 'Finalizing',
  reference_line: 'Reference Line',
  physics_models: 'Physics Models',
  theoretical_lap: 'Theoretical Lap',
  ml_anomaly: 'ML Analysis',
  scoring: 'Scoring Session',
  reports: 'Generating Reports',
  cleanup: 'Cleaning Up',
};

/* ── API helpers ──────────────────────────────────────── */

function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  const token = getAccessToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const wsId = getWorkspaceId();
  if (wsId !== null) headers['X-Workspace-Id'] = String(wsId);
  return headers;
}

async function uploadSession(file: File, metadata: {
  driver_name: string;
  session_type: string;
  track_state: string;
  lap_range?: string;
  exclude_laps?: string;
  kart_id?: string;
  session_date?: string;
}): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('driver_name', metadata.driver_name);
  formData.append('session_type', metadata.session_type);
  formData.append('track_state', metadata.track_state);
  if (metadata.lap_range) formData.append('lap_range', metadata.lap_range);
  if (metadata.exclude_laps) formData.append('exclude_laps', metadata.exclude_laps);
  if (metadata.kart_id) formData.append('kart_id', metadata.kart_id);
  if (metadata.session_date) formData.append('session_date', metadata.session_date);

  const res = await fetch(`${BACKEND_URL}/api/v1/sessions/upload`, {
    method: 'POST',
    headers: authHeaders(),
    body: formData,
    credentials: 'include',
  });

  const contentType = res.headers.get('content-type') || '';
  if (!contentType.includes('application/json')) {
    throw new Error(`Server returned non-JSON response (${res.status})`);
  }

  const envelope = await res.json();
  if (envelope.ok && envelope.data) return envelope.data as UploadResponse;

  throw new ApiError(
    envelope.error?.code ?? 'UPLOAD_FAILED',
    envelope.error?.message ?? `Upload failed (${res.status})`,
    res.status,
    envelope.error?.details,
  );
}

async function fetchTrackLayout(jobId: string): Promise<TrackLayout> {
  const res = await fetch(`${BACKEND_URL}/api/v1/jobs/${jobId}/track-layout`, {
    headers: { ...authHeaders(), 'Content-Type': 'application/json' },
    credentials: 'include',
  });
  const envelope = await res.json();
  if (envelope.ok && envelope.data) return envelope.data as TrackLayout;
  throw new Error(envelope.error?.message ?? 'Failed to load track layout');
}

async function resumeWithCorners(jobId: string, selectedIds: number[]): Promise<void> {
  const res = await fetch(`${BACKEND_URL}/api/v1/jobs/${jobId}/resume`, {
    method: 'POST',
    headers: { ...authHeaders(), 'Content-Type': 'application/json' },
    body: JSON.stringify({ selected_corner_ids: selectedIds }),
    credentials: 'include',
  });
  const envelope = await res.json();
  if (!envelope.ok) throw new Error(envelope.error?.message ?? 'Resume failed');
}

/* ── Progress Bar ──────────────────────────────────────── */

function PipelineProgress({
  pct,
  stageName,
  status,
}: {
  pct: number;
  stageName: string | null;
  status: string;
}) {
  const label = stageName ? (STAGE_LABELS[stageName] ?? stageName) : 'Processing...';
  const isResuming = status === 'processing' || status === 'running';

  return (
    <div className="rounded-lg bg-concrete border border-steel/20 p-4 mb-4">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          {isResuming && (
            <div className="w-4 h-4 border-2 border-acid-green/30 border-t-acid-green rounded-full animate-spin" />
          )}
          <span className="font-telemetry text-chalk text-sm">{label}</span>
        </div>
        <span className="font-telemetry text-steel text-xs">{Math.round(pct)}%</span>
      </div>
      <div className="h-2 rounded-full bg-steel/10 overflow-hidden">
        <div
          className="h-full rounded-full bg-acid-green transition-all duration-700 ease-out"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

/* ── Component ──────────────────────────────────────── */

export default function UploadPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const sseRef = useRef<EventSource | null>(null);

  // Resume support: ?resume=<jobId>
  const resumeJobId = searchParams.get('resume');

  // Form state
  const [file, setFile] = useState<File | null>(null);
  const [driverName, setDriverName] = useState('');
  const [sessionType, setSessionType] = useState('practice');
  const [trackState, setTrackState] = useState('dry');
  const [lapRange, setLapRange] = useState('');
  const [excludeLaps, setExcludeLaps] = useState('');
  const [kartId, setKartId] = useState('');
  const [sessionDate, setSessionDate] = useState('');
  const [karts, setKarts] = useState<{ kart_id: number; kart_name: string }[]>([]);

  // Page state machine
  const [pageState, setPageState] = useState<PageState>(resumeJobId ? 'awaiting_corners' : 'idle');
  const [jobId, setJobId] = useState<string | null>(resumeJobId);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [progressPct, setProgressPct] = useState(0);
  const [stageName, setStageName] = useState<string | null>(null);
  const [sseStatus, setSseStatus] = useState('');
  const [errorMessage, setErrorMessage] = useState('');
  const [errorRequestId, setErrorRequestId] = useState<string | null>(null);
  const [trackLayout, setTrackLayout] = useState<TrackLayout | null>(null);
  const [isSubmittingCorners, setIsSubmittingCorners] = useState(false);
  const [isDragOver, setIsDragOver] = useState(false);

  // Pre-fill driver name from user profile
  useEffect(() => {
    const profile = getUserProfile();
    if (profile?.display_name) {
      setDriverName(profile.display_name);
    }
  }, []);

  // Fetch karts for dropdown
  useEffect(() => {
    const token = getAccessToken();
    fetch(`${BACKEND_URL}/api/v1/karts`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then((r) => r.ok ? r.json() : null)
      .then((data) => { if (data?.karts) setKarts(data.karts); })
      .catch(() => {});
  }, []);

  // ── SSE connection ──────────────────────────────────
  const connectSSE = useCallback((jId: string) => {
    if (sseRef.current) {
      sseRef.current.close();
      sseRef.current = null;
    }

    const hdrs = authHeaders();
    const url = new URL(`${BACKEND_URL}/api/v1/jobs/${jId}/stream`);
    // SSE doesn't support custom headers; we pass auth as query params
    // Actually, we'll use fetch-based SSE polling instead
    const pollSSE = async () => {
      try {
        const res = await fetch(url.toString(), {
          headers: hdrs,
          credentials: 'include',
        });
        if (!res.ok || !res.body) return;

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            try {
              const event: SSEEvent = JSON.parse(line.slice(6));
              setProgressPct(event.progress_pct);
              setStageName(event.stage_name);
              setSseStatus(event.status);
              if (event.session_id) setSessionId(event.session_id);

              if (event.status === 'awaiting_corner_selection') {
                setPageState('awaiting_corners');
                // Fetch track layout
                try {
                  const layout = await fetchTrackLayout(jId);
                  setTrackLayout(layout);
                } catch (err) {
                  logger.error('Failed to fetch track layout:', err);
                  setErrorMessage('Failed to load track layout');
                  setPageState('error');
                }
                return; // Stop reading SSE
              }

              if (event.status === 'completed') {
                setPageState('completed');
                const sid = event.session_id || jId;
                setTimeout(() => router.push(`/app/sessions/${sid}`), 1500);
                return;
              }

              if (event.status === 'failed') {
                setErrorMessage(event.error_message || 'Pipeline failed');
                setPageState('error');
                return;
              }
            } catch {
              // Ignore parse errors
            }
          }
        }
      } catch (err) {
        logger.error('SSE connection error:', err);
      }
    };

    pollSSE();
  }, [router]);

  // Resume: if ?resume=jobId, load track layout immediately
  useEffect(() => {
    if (!resumeJobId) return;
    (async () => {
      try {
        const layout = await fetchTrackLayout(resumeJobId);
        setTrackLayout(layout);
        setPageState('awaiting_corners');
      } catch {
        // If not in awaiting state, try connecting SSE
        setPageState('tracking');
        connectSSE(resumeJobId);
      }
    })();
  }, [resumeJobId, connectSSE]);

  // Drag-and-drop handlers
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);

    const droppedFiles = e.dataTransfer.files;
    if (droppedFiles.length > 0) {
      const f = droppedFiles[0];
      const ext = f.name.split('.').pop()?.toLowerCase();
      if (ext === 'csv' || ext === 'txt') {
        setFile(f);
        setErrorMessage('');
      } else {
        setErrorMessage('Only .csv and .txt files are accepted.');
      }
    }
  }, []);

  const handleFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      setFile(files[0]);
      setErrorMessage('');
    }
  }, []);

  const handleRemoveFile = useCallback(() => {
    setFile(null);
    if (fileInputRef.current) fileInputRef.current.value = '';
  }, []);

  // Submit handler
  const handleSubmit = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();

    if (!file) { setErrorMessage('Please select a CSV file to upload.'); return; }
    if (!driverName.trim()) { setErrorMessage('Driver name is required.'); return; }

    setPageState('uploading');
    setErrorMessage('');

    try {
      const result = await uploadSession(file, {
        driver_name: driverName.trim(),
        session_type: sessionType,
        track_state: trackState,
        lap_range: lapRange.trim() || undefined,
        exclude_laps: excludeLaps.trim() || undefined,
        kart_id: kartId || undefined,
        session_date: sessionDate || undefined,
      });

      setJobId(result.job_id);
      setPageState('tracking');
      connectSSE(result.job_id);
    } catch (err) {
      setPageState('error');
      if (err instanceof ApiError) {
        setErrorMessage(err.message);
        setErrorRequestId(err.requestId ?? null);
      } else if (err instanceof Error) {
        setErrorMessage(err.message);
        setErrorRequestId(null);
      } else {
        setErrorMessage('An unexpected error occurred.');
        setErrorRequestId(null);
      }
    }
  }, [file, driverName, sessionType, trackState, lapRange, excludeLaps, kartId, sessionDate, connectSSE]);

  // Corner selection submit
  const handleCornerSubmit = useCallback(async (selectedIds: number[]) => {
    if (!jobId) return;
    setIsSubmittingCorners(true);
    try {
      await resumeWithCorners(jobId, selectedIds);
      setPageState('tracking');
      setProgressPct(47); // ~7/15 stages
      connectSSE(jobId);
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : 'Resume failed');
      setPageState('error');
    } finally {
      setIsSubmittingCorners(false);
    }
  }, [jobId, connectSSE]);

  const isFormDisabled = pageState !== 'idle' && pageState !== 'error';
  const showForm = pageState === 'idle' || pageState === 'error';
  const showProgress = pageState === 'uploading' || pageState === 'tracking' || pageState === 'resuming';
  const showCornerPicker = pageState === 'awaiting_corners' && trackLayout;
  const showCompleted = pageState === 'completed';

  return (
    <div>
      <PageHeader
        title="Upload Session"
        subtitle="Upload a RaceChrono or RaceBox CSV file for analysis"
        actions={
          <Link
            href="/app/sessions"
            className="px-4 py-2 text-sm font-telemetry text-steel hover:text-chalk transition-colors"
          >
            Back to Sessions
          </Link>
        }
      />

      {/* ── Upload Form (shown in idle/error states) ── */}
      {showForm && (
        <form onSubmit={handleSubmit} className="max-w-2xl">
          {/* ── File Drop Zone ─────────────────────────── */}
          <div className="mb-6">
            <label className="block text-sm font-telemetry text-steel mb-2 uppercase tracking-wider">
              Telemetry File
            </label>
            <div
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              onClick={() => !isFormDisabled && fileInputRef.current?.click()}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  if (!isFormDisabled) fileInputRef.current?.click();
                }
              }}
              className={`
                relative flex flex-col items-center justify-center p-8 rounded-lg border-2 border-dashed cursor-pointer transition-all duration-200
                ${isDragOver
                  ? 'border-acid-green bg-acid-green/5 scale-[1.01]'
                  : file
                    ? 'border-acid-green/40 bg-acid-green/5'
                    : 'border-steel/30 bg-concrete hover:border-steel/50 hover:bg-asphalt/50'
                }
                ${isFormDisabled ? 'opacity-60 cursor-not-allowed' : ''}
              `}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept={ACCEPTED_EXTENSIONS}
                onChange={handleFileChange}
                disabled={isFormDisabled}
                className="sr-only"
                aria-label="Choose telemetry file"
              />

              {file ? (
                <div className="flex items-center gap-3">
                  <div className="flex items-center justify-center w-10 h-10 rounded-lg bg-acid-green/10">
                    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" className="text-acid-green" aria-hidden="true">
                      <path d="M4 4h8l4 4v8a2 2 0 01-2 2H4a2 2 0 01-2-2V6a2 2 0 012-2z" stroke="currentColor" strokeWidth="1.5" />
                      <path d="M12 4v4h4" stroke="currentColor" strokeWidth="1.5" />
                    </svg>
                  </div>
                  <div>
                    <p className="font-telemetry text-chalk text-sm">{file.name}</p>
                    <p className="text-steel text-xs font-body">
                      {(file.size / 1024).toFixed(1)} KB
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); handleRemoveFile(); }}
                    className="ml-4 text-steel hover:text-safety-red transition-colors text-sm"
                    aria-label="Remove file"
                  >
                    Remove
                  </button>
                </div>
              ) : (
                <>
                  <div className="flex items-center justify-center w-12 h-12 rounded-full bg-steel/10 mb-3">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" className="text-steel" aria-hidden="true">
                      <path d="M12 16V8m0 0l-3 3m3-3l3 3" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                      <path d="M20 16.7V19a2 2 0 01-2 2H6a2 2 0 01-2-2v-2.3" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                    </svg>
                  </div>
                  <p className="font-body text-chalk text-sm mb-1">
                    Drag and drop your CSV file here
                  </p>
                  <p className="font-body text-steel text-xs">
                    or click to browse. Accepts .csv and .txt files.
                  </p>
                </>
              )}
            </div>
          </div>

          {/* ── Metadata Form ──────────────────────────── */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-6">
            <div>
              <label htmlFor="driver-name" className="block text-sm font-telemetry text-steel mb-1.5 uppercase tracking-wider">
                Driver Name <span className="text-safety-red">*</span>
              </label>
              <input id="driver-name" type="text" value={driverName} onChange={(e) => setDriverName(e.target.value)}
                disabled={isFormDisabled} required placeholder="e.g. Alex Rossi"
                className="w-full bg-concrete border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
                  placeholder:text-steel/60 focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50
                  disabled:opacity-50 disabled:cursor-not-allowed" />
            </div>
            <div>
              <label htmlFor="session-type" className="block text-sm font-telemetry text-steel mb-1.5 uppercase tracking-wider">Session Type</label>
              <select id="session-type" value={sessionType} onChange={(e) => setSessionType(e.target.value)} disabled={isFormDisabled}
                className="w-full bg-concrete border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
                  focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50 disabled:opacity-50 disabled:cursor-not-allowed">
                {SESSION_TYPES.map((t) => (<option key={t.value} value={t.value}>{t.label}</option>))}
              </select>
            </div>
            <div>
              <label htmlFor="track-state" className="block text-sm font-telemetry text-steel mb-1.5 uppercase tracking-wider">Track Condition</label>
              <select id="track-state" value={trackState} onChange={(e) => setTrackState(e.target.value)} disabled={isFormDisabled}
                className="w-full bg-concrete border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
                  focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50 disabled:opacity-50 disabled:cursor-not-allowed">
                {TRACK_STATES.map((s) => (<option key={s.value} value={s.value}>{s.label}</option>))}
              </select>
            </div>
            {karts.length > 0 && (
              <div>
                <label htmlFor="kart-id" className="block text-sm font-telemetry text-steel mb-1.5 uppercase tracking-wider">
                  Kart <span className="text-steel/60 text-xs normal-case">(optional)</span>
                </label>
                <select id="kart-id" value={kartId} onChange={(e) => setKartId(e.target.value)} disabled={isFormDisabled}
                  className="w-full bg-concrete border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
                    focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50 disabled:opacity-50 disabled:cursor-not-allowed">
                  <option value="">None</option>
                  {karts.map((k) => (<option key={k.kart_id} value={String(k.kart_id)}>{k.kart_name}</option>))}
                </select>
              </div>
            )}
            <div>
              <label htmlFor="session-date" className="block text-sm font-telemetry text-steel mb-1.5 uppercase tracking-wider">
                Session Date <span className="text-steel/60 text-xs normal-case">(optional — auto-detected from CSV)</span>
              </label>
              <input id="session-date" type="date" value={sessionDate} onChange={(e) => setSessionDate(e.target.value)} disabled={isFormDisabled}
                className="w-full bg-concrete border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
                  focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50 disabled:opacity-50 disabled:cursor-not-allowed" />
            </div>
            <div>
              <label htmlFor="lap-range" className="block text-sm font-telemetry text-steel mb-1.5 uppercase tracking-wider">
                Lap Range <span className="text-steel/60 text-xs normal-case">(optional)</span>
              </label>
              <input id="lap-range" type="text" value={lapRange} onChange={(e) => setLapRange(e.target.value)} disabled={isFormDisabled}
                placeholder="e.g. 3-15"
                className="w-full bg-concrete border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
                  placeholder:text-steel/60 focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50
                  disabled:opacity-50 disabled:cursor-not-allowed" />
            </div>
            <div className="sm:col-span-2">
              <label htmlFor="exclude-laps" className="block text-sm font-telemetry text-steel mb-1.5 uppercase tracking-wider">
                Exclude Laps <span className="text-steel/60 text-xs normal-case">(optional)</span>
              </label>
              <input id="exclude-laps" type="text" value={excludeLaps} onChange={(e) => setExcludeLaps(e.target.value)} disabled={isFormDisabled}
                placeholder="e.g. 1,2,16"
                className="w-full bg-concrete border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
                  placeholder:text-steel/60 focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50
                  disabled:opacity-50 disabled:cursor-not-allowed" />
            </div>
          </div>

          {/* ── Error Message ──────────────────────────── */}
          {errorMessage && (
            <div className="mb-4 p-3 rounded-lg bg-safety-red/10 border border-safety-red/20 text-safety-red text-sm font-body" role="alert">
              {errorMessage}
              {errorRequestId && (
                <p className="mt-1 text-steel/50 text-[10px] tracking-wider font-telemetry">
                  Ref: {errorRequestId}
                </p>
              )}
            </div>
          )}

          {/* ── Submit Button ──────────────────────────── */}
          <div className="flex items-center gap-4">
            <button type="submit" disabled={isFormDisabled || !file || !driverName.trim()}
              className="px-6 py-3 bg-gold text-carbon font-monument text-sm rounded-lg
                hover:bg-gold/90 transition-colors
                disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-gold">
              Upload &amp; Analyze
            </button>
            <Link href="/app/sessions"
              className="px-4 py-2.5 text-steel hover:text-chalk transition-colors font-body text-sm">
              Cancel
            </Link>
          </div>
        </form>
      )}

      {/* ── Progress Section ──────────────────────────── */}
      {showProgress && (
        <div className="max-w-2xl">
          {pageState === 'uploading' && (
            <div className="mb-4 p-4 rounded-lg bg-pit-orange/5 border border-pit-orange/20" role="status">
              <div className="flex items-center gap-3">
                <div className="w-5 h-5 border-2 border-pit-orange/30 border-t-pit-orange rounded-full animate-spin" />
                <div>
                  <p className="text-chalk font-body text-sm">Uploading telemetry file...</p>
                  <p className="text-steel text-xs font-body mt-0.5">Starting analysis pipeline.</p>
                </div>
              </div>
            </div>
          )}
          {(pageState === 'tracking' || pageState === 'resuming') && (
            <PipelineProgress pct={progressPct} stageName={stageName} status={sseStatus} />
          )}
        </div>
      )}

      {/* ── Corner Picker ──────────────────────────────── */}
      {showCornerPicker && (
        <div className="max-w-3xl">
          <div className="mb-4 p-4 rounded-lg bg-pit-orange/5 border border-pit-orange/20">
            <p className="text-chalk font-body text-sm mb-1">
              Select corners for detailed analysis
            </p>
            <p className="text-steel text-xs font-body">
              Click corners on the map or use the chips below to choose which turns get full coaching analysis.
              All corners are selected by default.
            </p>
          </div>
          <CornerPicker
            trackLayout={trackLayout}
            onSubmit={handleCornerSubmit}
            isSubmitting={isSubmittingCorners}
          />
        </div>
      )}

      {/* ── Completed State ──────────────────────────── */}
      {showCompleted && (
        <div className="max-w-2xl">
          <div className="mb-4 p-4 rounded-lg bg-acid-green/5 border border-acid-green/20" role="status">
            <div className="flex items-center gap-3">
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none" className="text-acid-green" aria-hidden="true">
                <circle cx="10" cy="10" r="9" stroke="currentColor" strokeWidth="1.5" />
                <path d="M6 10l3 3 5-6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <p className="text-acid-green font-body text-sm">
                Analysis complete. Redirecting to session...
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
