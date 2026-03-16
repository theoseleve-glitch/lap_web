'use client';

import { useState, useRef, useCallback, useEffect, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { PageIntro } from '@/components/ui/PageIntro';
import { BACKEND_URL, ApiError, api } from '@/lib/api-client';
import { getAccessToken, getWorkspaceId, getUserProfile } from '@/lib/auth-store';
import { CornerEditor, type TrackLayout } from '@/components/app/CornerEditor';
import { logger } from '@/lib/logger';
import { StintConfigFlow } from '@/components/app/endurance/StintConfigFlow';
import { StintProcessingProgress } from '@/components/app/endurance/StintProcessingProgress';

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
  | 'error'
  | 'endurance_detecting'
  | 'endurance_config'
  | 'endurance_processing';

interface SSEEvent {
  status: string;
  stage_name: string | null;
  progress_pct: number;
  error_message: string | null;
  session_id?: string;
  /** Milestone data — key facts from completed stages */
  milestones?: Record<string, string>;
}

const SESSION_TYPES = [
  { value: 'practice', label: 'Practice' },
  { value: 'qualifying', label: 'Qualifying' },
  { value: 'race', label: 'Race' },
  { value: 'heat', label: 'Heat' },
  { value: 'final', label: 'Final' },
  { value: 'endurance', label: 'Endurance' },
  { value: 'test', label: 'Test' },
];

const TRACK_STATES = [
  { value: 'dry', label: 'Dry' },
  { value: 'wet', label: 'Wet' },
  { value: 'damp', label: 'Damp' },
  { value: 'mixed', label: 'Mixed' },
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
  ocp_solver: 'OCP Solver (min-time lap)',
  finalize_complete: 'Saving Results',
};

/* ── Telemetry Tips ───────────────────────────────────── */

const TELEMETRY_TIPS = [
  { title: 'Trail Braking', text: 'Gradually release brake pressure as you turn in. This keeps weight on the front tyres for maximum grip through corner entry.' },
  { title: 'Consistency Wins', text: 'A driver who laps within 0.3s of their best every lap will beat a faster but inconsistent driver over a race distance.' },
  { title: 'Reading Speed Traces', text: 'Compare your speed trace to the theoretical line — flat spots before corners reveal early braking, while dips mid-corner show hesitation.' },
  { title: 'G-G Diagram', text: 'The G-G plot shows how much of your tyre grip you\'re using. A full "diamond" means you\'re combining braking and cornering efficiently.' },
  { title: 'Corner Exit Speed', text: 'Exit speed matters more than entry speed. A 2 km/h higher exit carries through the entire following straight.' },
  { title: 'Reference Line', text: 'The reference line is computed from your fastest sectors stitched together — it represents your theoretical best lap from this session.' },
  { title: 'Braking Point', text: 'Moving your braking point 2 metres later can save 0.05s per corner. Over 12 corners, that\'s 0.6s per lap.' },
  { title: 'Tyre Temperature', text: 'Kart tyres work best at 50-70C. Your first 2-3 laps are warm-up — exclude them from analysis for cleaner data.' },
  { title: 'Throttle Application', text: 'Smooth, progressive throttle on exit prevents wheelspin. The speed trace will show a smooth curve instead of jagged spikes.' },
  { title: 'What is OCP?', text: 'The Optimal Control Problem solver computes the physically fastest possible lap given your track layout, kart mass, and grip limits.' },
  { title: 'Scoring System', text: 'Your session score (0-100) combines Pace, Consistency, Execution, and Robustness — each worth 25 points.' },
  { title: 'Track Evolution', text: 'Rubber builds up on the racing line throughout a session. Your later laps should naturally be faster as grip improves.' },
  { title: 'Data Quality', text: 'GPS at 10 Hz gives ~3m position accuracy. Higher sample rates improve corner detection and speed trace resolution.' },
  { title: 'Comparing Sessions', text: 'Compare sessions on the same track to see progression. The delta map highlights exactly where you\'re gaining or losing time.' },
];

/** Rotating tips carousel shown during analysis. */
function TelemetryTips() {
  const [index, setIndex] = useState(() => Math.floor(Math.random() * TELEMETRY_TIPS.length));
  const [fade, setFade] = useState(true);

  useEffect(() => {
    const interval = setInterval(() => {
      setFade(false);
      setTimeout(() => {
        setIndex((i) => (i + 1) % TELEMETRY_TIPS.length);
        setFade(true);
      }, 300);
    }, 6000);
    return () => clearInterval(interval);
  }, []);

  const tip = TELEMETRY_TIPS[index];
  return (
    <div className="mt-6 rounded-lg bg-concrete border border-steel/10 p-4 overflow-hidden">
      <div className="flex items-center gap-2 mb-2">
        <div className="w-5 h-5 rounded-full bg-pit-orange/10 flex items-center justify-center flex-shrink-0">
          <svg width="12" height="12" viewBox="0 0 16 16" fill="none" className="text-pit-orange">
            <circle cx="8" cy="8" r="7" stroke="currentColor" strokeWidth="1.5" />
            <path d="M8 5v3m0 2.5v.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        </div>
        <span className="text-xs font-telemetry text-steel uppercase tracking-wider">Did you know?</span>
        <span className="text-[10px] text-steel/30 ml-auto font-telemetry">{index + 1}/{TELEMETRY_TIPS.length}</span>
      </div>
      <div
        className={`transition-opacity duration-300 ${fade ? 'opacity-100' : 'opacity-0'}`}
      >
        <p className="text-sm font-telemetry text-pit-orange mb-1">{tip.title}</p>
        <p className="text-xs font-body text-steel leading-relaxed">{tip.text}</p>
      </div>
    </div>
  );
}

/** Stage milestone insights shown as stages complete. */
function StageInsights({ stageName, milestones }: { stageName: string | null; milestones: Record<string, string> }) {
  const entries = Object.entries(milestones);
  if (entries.length === 0) return null;

  return (
    <div className="mt-4 rounded-lg bg-concrete border border-steel/10 p-4">
      <div className="flex items-center gap-2 mb-3">
        <div className="w-5 h-5 rounded-full bg-acid-green/10 flex items-center justify-center flex-shrink-0">
          <svg width="12" height="12" viewBox="0 0 16 16" fill="none" className="text-acid-green">
            <path d="M3 8h10M8 3v10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        </div>
        <span className="text-xs font-telemetry text-steel uppercase tracking-wider">Analysis Progress</span>
      </div>
      <div className="space-y-1.5">
        {entries.map(([key, value]) => (
          <div key={key} className="flex items-center gap-2 text-xs">
            <svg width="12" height="12" viewBox="0 0 16 16" fill="none" className="text-acid-green flex-shrink-0">
              <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="1.5" />
              <path d="M5 8l2 2 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <span className="text-steel font-body">{value}</span>
          </div>
        ))}
        {stageName && STAGE_LABELS[stageName] && (
          <div className="flex items-center gap-2 text-xs">
            <div className="w-3 h-3 border border-pit-orange/50 border-t-pit-orange rounded-full animate-spin flex-shrink-0" />
            <span className="text-pit-orange font-body">{STAGE_LABELS[stageName]}...</span>
          </div>
        )}
      </div>
    </div>
  );
}

/* ── API helpers ──────────────────────────────────────── */

function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  const token = getAccessToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const wsId = getWorkspaceId();
  if (wsId !== null) headers['X-Workspace-Id'] = String(wsId);
  return headers;
}

function uploadSession(
  file: File,
  metadata: {
    driver_name: string;
    session_type: string;
    track_state: string;
    lap_range?: string;
    exclude_laps?: string;
    kart_name?: string;
    track_name?: string;
    session_date?: string;
    joker_enabled?: boolean;
    joker_lap?: string;
    endurance_drivers?: string[];
  },
  onProgress?: (pct: number) => void,
  signal?: AbortSignal,
): Promise<UploadResponse> {
  return new Promise((resolve, reject) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('driver_name', metadata.driver_name);
    formData.append('session_type', metadata.session_type);
    formData.append('track_state', metadata.track_state);
    if (metadata.lap_range) formData.append('lap_range', metadata.lap_range);
    if (metadata.exclude_laps) formData.append('exclude_laps', metadata.exclude_laps);
    if (metadata.kart_name) formData.append('kart_name', metadata.kart_name);
    if (metadata.track_name) formData.append('track_name', metadata.track_name);
    if (metadata.session_date) formData.append('session_date', metadata.session_date);
    if (metadata.endurance_drivers && metadata.endurance_drivers.length > 0) {
      formData.append('endurance_drivers', JSON.stringify(metadata.endurance_drivers));
    }
    if (metadata.joker_enabled) {
      formData.append('joker_enabled', '1');
      if (metadata.joker_lap) formData.append('joker_lap', metadata.joker_lap);
    }

    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${BACKEND_URL}/api/v1/sessions/upload`);
    xhr.withCredentials = true;

    const hdrs = authHeaders();
    for (const [k, v] of Object.entries(hdrs)) xhr.setRequestHeader(k, v);

    if (signal) {
      signal.addEventListener('abort', () => {
        xhr.abort();
        reject(new Error('Upload cancelled'));
      });
    }

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) {
        onProgress(Math.round((e.loaded / e.total) * 100));
      }
    };

    xhr.onload = () => {
      const contentType = xhr.getResponseHeader('content-type') || '';
      if (!contentType.includes('application/json')) {
        reject(new Error(`Server returned non-JSON response (${xhr.status})`));
        return;
      }
      let envelope;
      try {
        envelope = JSON.parse(xhr.responseText);
      } catch {
        reject(new Error(`Invalid JSON in server response (${xhr.status})`));
        return;
      }
      if (envelope.ok && envelope.data) {
        resolve(envelope.data as UploadResponse);
      } else {
        reject(new ApiError(
          envelope.error?.code ?? 'UPLOAD_FAILED',
          envelope.error?.message ?? `Upload failed (${xhr.status})`,
          xhr.status,
          envelope.error?.details,
        ));
      }
    };

    xhr.onerror = () => reject(new Error('Network error during upload'));
    xhr.onabort = () => reject(new Error('Upload cancelled'));
    xhr.send(formData);
  });
}

async function fetchTrackLayout(jobId: string): Promise<TrackLayout> {
  const d = await api.get<Record<string, unknown>>(`/jobs/${jobId}/track-layout`);
  // Normalize key names — backend may return short keys (lat/lon/distance_m)
  return {
    latitudes: (d.latitudes ?? d.lat ?? []) as number[],
    longitudes: (d.longitudes ?? d.lon ?? []) as number[],
    distances: (d.distances ?? d.distance_m ?? []) as number[],
    speeds: (d.speeds ?? []) as number[],
    corners: (d.corners ?? []) as TrackLayout['corners'],
    track_id: d.track_id as string | undefined,
  };
}

async function resumeWithCorners(
  jobId: string,
  corners: { s_start: number; s_apex: number; s_end: number }[],
): Promise<void> {
  await api.post(`/jobs/${jobId}/resume`, { corners });
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

export default function UploadPageWrapper() {
  return (
    <Suspense fallback={<div className="py-12 text-center text-steel text-sm">Loading...</div>}>
      <UploadPage />
    </Suspense>
  );
}

function UploadPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const sseRef = useRef<EventSource | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const sseAbortRef = useRef<AbortController | null>(null);

  // Resume support: ?resume=<jobId>
  const resumeJobId = searchParams.get('resume');

  // Form state
  const [file, setFile] = useState<File | null>(null);
  const [fileQueue, setFileQueue] = useState<File[]>([]);
  const [driverName, setDriverName] = useState('');
  const [sessionType, setSessionType] = useState('practice');
  const [enduranceDrivers, setEnduranceDrivers] = useState<string[]>([]);
  const [newEnduranceDriver, setNewEnduranceDriver] = useState('');
  const [pitThreshold, setPitThreshold] = useState(120);
  const [trackState, setTrackState] = useState('dry');
  const [lapRange, setLapRange] = useState('');
  const [excludeLaps, setExcludeLaps] = useState('');
  const [kartName, setKartName] = useState('');
  const [trackName, setTrackName] = useState('');
  const [sessionDate, setSessionDate] = useState('');
  const [jokerEnabled, setJokerEnabled] = useState(false);
  const [jokerLap, setJokerLap] = useState('');
  const [kartNames, setKartNames] = useState<string[]>([]);
  const [trackNames, setTrackNames] = useState<string[]>([]);
  const [driverNames, setDriverNames] = useState<string[]>([]);

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
  const [uploadPct, setUploadPct] = useState(0);
  const [milestones, setMilestones] = useState<Record<string, string>>({});

  // Batch upload tracking
  const [batchResults, setBatchResults] = useState<{ name: string; sessionId: string | null; error: string | null }[]>([]);
  const [batchTotal, setBatchTotal] = useState(0);
  const batchQueueRef = useRef<File[]>([]);
  const connectSSERef = useRef<(jId: string) => void>(() => {});
  const trackNameRef = useRef('');
  const cornerResumedRef = useRef(false);

  // Endurance flow state
  const [enduranceJobId, setEnduranceJobId] = useState<string | null>(null);
  const [enduranceLaps, setEnduranceLaps] = useState<any[]>([]);
  const [enduranceAutoStints, setEnduranceAutoStints] = useState<any[]>([]);
  const [enduranceMedian, setEnduranceMedian] = useState(0);
  const [enduranceStintConfigs, setEnduranceStintConfigs] = useState<any[]>([]);

  // Pre-fill driver name from user profile
  useEffect(() => {
    const profile = getUserProfile();
    if (profile?.display_name) {
      setDriverName(profile.display_name);
    }
  }, []);

  // Fetch entity lists for combobox suggestions
  useEffect(() => {
    api.get<Array<{ id: number; name: string }>>('/karts')
      .then((data) => { if (Array.isArray(data)) setKartNames(data.map((k) => k.name).filter(Boolean)); })
      .catch(() => {});
    api.get<Array<{ id: number; name: string }>>('/tracks')
      .then((data) => { if (Array.isArray(data)) setTrackNames(data.map((t) => t.name).filter(Boolean)); })
      .catch(() => {});
    api.get<Array<{ id: number; name: string }>>('/drivers')
      .then((data) => { if (Array.isArray(data)) setDriverNames(data.map((d) => d.name).filter(Boolean)); })
      .catch(() => {});
  }, []);

  // Keep ref in sync for SSE callback access
  useEffect(() => { trackNameRef.current = trackName; }, [trackName]);

  // Upload next file in batch queue (called after a file completes)
  const uploadNextInBatch = useCallback(async () => {
    const nextFile = batchQueueRef.current.shift();
    if (!nextFile) return false; // No more files

    setFile(nextFile);
    setFileQueue([...batchQueueRef.current]);
    setPageState('uploading');
    setUploadPct(0);
    setProgressPct(0);
    setStageName(null);
    setSseStatus('');
    setErrorMessage('');
    setMilestones({});

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const result = await uploadSession(nextFile, {
        driver_name: driverName.trim(),
        session_type: sessionType,
        track_state: trackState,
        lap_range: lapRange.trim() || undefined,
        exclude_laps: excludeLaps.trim() || undefined,
        kart_name: kartName.trim() || undefined,
        track_name: trackName.trim() || undefined,
        session_date: sessionDate || undefined,
        joker_enabled: jokerEnabled || undefined,
        joker_lap: jokerEnabled && jokerLap.trim() ? jokerLap.trim() : undefined,
        endurance_drivers: sessionType === 'endurance' ? enduranceDrivers : undefined,
      }, setUploadPct, controller.signal);

      setJobId(result.job_id);
      setPageState('tracking');
      connectSSERef.current(result.job_id);
    } catch (err) {
      if (err instanceof Error && err.message === 'Upload cancelled') return true;
      // Record failure for this file, continue with next
      setBatchResults((prev) => [...prev, { name: nextFile.name, sessionId: null, error: err instanceof Error ? err.message : 'Upload failed' }]);
      // Try next file
      const hasMore = batchQueueRef.current.length > 0;
      if (hasMore) {
        await uploadNextInBatch();
      } else {
        setPageState('completed');
      }
    }
    return true;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [driverName, sessionType, trackState, lapRange, excludeLaps, kartName, trackName, sessionDate]);

  // ── SSE connection ──────────────────────────────────
  const connectSSE = useCallback((jId: string) => {
    if (sseRef.current) {
      sseRef.current.close();
      sseRef.current = null;
    }
    // Abort any previous SSE fetch
    if (sseAbortRef.current) {
      sseAbortRef.current.abort();
    }
    const sseController = new AbortController();
    sseAbortRef.current = sseController;

    const hdrs = authHeaders();
    const url = new URL(`${BACKEND_URL}/api/v1/jobs/${jId}/stream`);
    // SSE doesn't support custom headers; we pass auth as query params
    // Actually, we'll use fetch-based SSE polling instead
    const pollSSE = async () => {
      try {
        const res = await fetch(url.toString(), {
          headers: hdrs,
          credentials: 'include',
          signal: sseController.signal,
        });
        if (!res.ok || !res.body) {
          setErrorMessage(`Pipeline tracking failed (HTTP ${res.status})`);
          setPageState('error');
          return;
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        const closeStream = () => {
          reader.cancel().catch(() => {});
          sseController.abort();
        };

        try {
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

              // Accumulate milestones from backend or derive from stage transitions
              if (event.milestones) {
                setMilestones((prev) => ({ ...prev, ...event.milestones }));
              }
              // Generate frontend-side milestones from completed stages
              if (event.stage_name) {
                const stageMap: Record<string, string> = {
                  gps_filter: 'GPS data validated',
                  track_detect: 'Track identified',
                  corner_detect: 'Corners detected',
                  resample: 'Laps resampled',
                  features: 'Telemetry features computed',
                  reference_line: 'Reference line built',
                  physics_models: 'Physics model fitted',
                  theoretical_lap: 'Theoretical lap calculated',
                  scoring: 'Performance scored',
                  ocp_solver: 'Computing optimal lap (this may take a few minutes)',
                };
                // Mark all stages BEFORE current as complete
                const stageOrder = ['gps_filter', 'track_detect', 'corner_detect', 'resample', 'features', 'reference_line', 'physics_models', 'theoretical_lap', 'scoring', 'ocp_solver'];
                const currentIdx = stageOrder.indexOf(event.stage_name);
                if (currentIdx > 0) {
                  setMilestones((prev) => {
                    const next = { ...prev };
                    for (let i = 0; i < currentIdx; i++) {
                      const key = stageOrder[i];
                      if (stageMap[key] && !next[key]) next[key] = stageMap[key];
                    }
                    return next;
                  });
                }
              }

              if (event.status === 'awaiting_corner_selection') {
                // V1: skip corner editor — auto-accept detected corners (once)
                if (!cornerResumedRef.current) {
                  cornerResumedRef.current = true;
                  api.post(`/jobs/${jId}/resume`, { selected_corner_ids: [] }).catch(() => {});
                }
                continue;
              }

              if (event.status === 'completed') {
                const sid = event.session_id || jId;
                // Apply user-specified track name (pipeline auto-detects, this overrides)
                const tn = trackNameRef.current?.trim();
                if (tn && sid) {
                  api.patch(`/sessions/${sid}`, { track_name: tn }).catch(() => {});
                }
                // Record batch result
                if (batchTotal > 1) {
                  setBatchResults((prev) => [...prev, { name: file?.name ?? 'Unknown', sessionId: sid, error: null }]);
                }
                closeStream();
                // If more files in queue, upload next
                if (batchQueueRef.current.length > 0) {
                  uploadNextInBatch();
                  return;
                }
                setPageState('completed');
                // Single file → redirect immediately; batch → show summary
                if (batchTotal <= 1) {
                  setTimeout(() => router.push(`/app/sessions/${sid}`), 1500);
                }
                return;
              }

              if (event.status === 'failed' || event.status === 'stale'
                  || event.status === 'timeout' || event.status === 'not_found'
                  || event.status === 'error') {
                const defaultMsgs: Record<string, string> = {
                  failed: 'Pipeline failed',
                  stale: 'Processing appears stuck — please retry',
                  timeout: 'Processing timed out — please retry',
                  not_found: 'Job not found',
                  error: 'An error occurred during processing',
                };
                const errMsg = event.error_message || defaultMsgs[event.status] || 'Processing failed';
                closeStream();
                // In batch mode, record failure and continue
                if (batchTotal > 1) {
                  setBatchResults((prev) => [...prev, { name: file?.name ?? 'Unknown', sessionId: null, error: errMsg }]);
                  if (batchQueueRef.current.length > 0) {
                    uploadNextInBatch();
                    return;
                  }
                  setPageState('completed');
                  return;
                }
                setErrorMessage(errMsg);
                setPageState('error');
                return;
              }
            } catch {
              // Ignore parse errors
            }
          }
        }
        } finally {
          closeStream();
        }
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        if (err instanceof TypeError && /network/i.test(err.message)) return;
        logger.error('SSE connection error:', err);
      }
    };

    pollSSE();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router, uploadNextInBatch, batchTotal]);

  // Keep ref in sync so uploadNextInBatch can call connectSSE without circular deps
  connectSSERef.current = connectSSE;

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

  // Cleanup on unmount — abort any in-flight SSE or upload fetches
  useEffect(() => {
    return () => {
      if (sseAbortRef.current) sseAbortRef.current.abort();
      if (abortRef.current) abortRef.current.abort();
      if (sseRef.current) sseRef.current.close();
    };
  }, []);

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

    const droppedFiles = Array.from(e.dataTransfer.files);
    const validFiles = droppedFiles.filter((f) => {
      const ext = f.name.split('.').pop()?.toLowerCase();
      return ext === 'csv' || ext === 'txt';
    });
    if (validFiles.length === 0) {
      setErrorMessage('Only .csv and .txt files are accepted.');
      return;
    }
    setFile(validFiles[0]);
    if (validFiles.length > 1) {
      setFileQueue(validFiles.slice(1));
    }
    setErrorMessage('');
  }, []);

  const handleFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      const allFiles = Array.from(files);
      setFile(allFiles[0]);
      if (allFiles.length > 1) {
        setFileQueue(allFiles.slice(1));
      }
      setErrorMessage('');
    }
  }, []);

  const handleRemoveFile = useCallback(() => {
    setFile(null);
    setFileQueue([]);
    if (fileInputRef.current) fileInputRef.current.value = '';
  }, []);

  // Submit handler
  const handleSubmit = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();

    if (!file) { setErrorMessage('Please select a CSV file to upload.'); return; }

    // ── Endurance flow: quick detect instead of full upload ──
    if (sessionType === 'endurance') {
      if (enduranceDrivers.length < 1) { setErrorMessage('Add at least one driver.'); return; }
      setPageState('endurance_detecting');
      setErrorMessage('');
      try {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('pit_threshold_s', String(pitThreshold));
        formData.append('drivers', JSON.stringify(enduranceDrivers));
        formData.append('track_state', trackState);
        if (kartName.trim()) formData.append('kart_name', kartName.trim());
        if (trackName.trim()) formData.append('track_name', trackName.trim());
        if (sessionDate) formData.append('session_date', sessionDate);

        const token = getAccessToken();
        const wsId = getWorkspaceId();
        const resp = await fetch(`${BACKEND_URL}/api/v1/endurance/detect`, {
          method: 'POST',
          headers: {
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
            ...(wsId ? { 'X-Workspace-Id': String(wsId) } : {}),
          },
          body: formData,
        });
        const json = await resp.json();
        if (!json.ok) throw new Error(json.error?.message || 'Detection failed');
        setEnduranceJobId(json.data.job_id);
        setEnduranceLaps(json.data.laps || []);
        setEnduranceAutoStints(json.data.auto_stints || []);
        setEnduranceMedian(json.data.median_lap_time_s || 0);
        setPageState('endurance_config');
      } catch (err: any) {
        setErrorMessage(err.message || 'Endurance detection failed');
        setPageState('error');
      }
      return;
    }

    if (!driverName.trim()) { setErrorMessage('Driver name is required.'); return; }

    setPageState('uploading');
    setErrorMessage('');
    setUploadPct(0);
    setMilestones({});

    // Initialize batch tracking
    const totalFiles = 1 + fileQueue.length;
    setBatchTotal(totalFiles);
    setBatchResults([]);
    batchQueueRef.current = [...fileQueue];

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const result = await uploadSession(file, {
        driver_name: driverName.trim(),
        session_type: sessionType,
        track_state: trackState,
        lap_range: lapRange.trim() || undefined,
        exclude_laps: excludeLaps.trim() || undefined,
        kart_name: kartName.trim() || undefined,
        track_name: trackName.trim() || undefined,
        session_date: sessionDate || undefined,
        joker_enabled: jokerEnabled || undefined,
        joker_lap: jokerEnabled && jokerLap.trim() ? jokerLap.trim() : undefined,
        endurance_drivers: sessionType === 'endurance' ? enduranceDrivers : undefined,
      }, setUploadPct, controller.signal);

      setJobId(result.job_id);
      setPageState('tracking');
      connectSSE(result.job_id);
    } catch (err) {
      // Don't show error if user cancelled
      if (err instanceof Error && err.message === 'Upload cancelled') return;
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
  }, [file, driverName, sessionType, trackState, lapRange, excludeLaps, kartName, trackName, sessionDate, jokerEnabled, jokerLap, connectSSE, enduranceDrivers, pitThreshold]);

  // Corner editor submit (custom geometry)
  const handleCornerSubmit = useCallback(async (
    corners: { s_start: number; s_apex: number; s_end: number }[],
  ) => {
    if (!jobId) return;
    if (!corners || corners.length === 0) {
      setErrorMessage('Please define at least one corner before submitting.');
      return;
    }
    setIsSubmittingCorners(true);
    try {
      await resumeWithCorners(jobId, corners);
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

  const handleCancel = useCallback(() => {
    // Abort in-flight upload
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    // Close SSE stream
    if (sseAbortRef.current) {
      sseAbortRef.current.abort();
      sseAbortRef.current = null;
    }
    if (sseRef.current) {
      sseRef.current.close();
      sseRef.current = null;
    }
    setPageState('idle');
    setProgressPct(0);
    setUploadPct(0);
    setStageName(null);
    setSseStatus('');
    setJobId(null);
    setErrorMessage('');
  }, []);

  const isFormDisabled = pageState !== 'idle' && pageState !== 'error';
  const showForm = pageState === 'idle' || pageState === 'error';
  const showProgress = pageState === 'uploading' || pageState === 'tracking' || pageState === 'resuming';
  const showCornerPicker = pageState === 'awaiting_corners' && trackLayout;
  const showCompleted = pageState === 'completed';
  const showEnduranceDetecting = pageState === 'endurance_detecting';
  const showEnduranceConfig = pageState === 'endurance_config';
  const showEnduranceProcessing = pageState === 'endurance_processing';

  return (
    <div>
      <PageIntro
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
                multiple
                onChange={handleFileChange}
                disabled={isFormDisabled}
                className="sr-only"
                aria-label="Choose telemetry files"
              />

              {file ? (
                <div className="w-full">
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
                        {fileQueue.length > 0 && (
                          <span className="ml-2 text-pit-orange">
                            +{fileQueue.length} more file{fileQueue.length !== 1 ? 's' : ''} queued
                          </span>
                        )}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); handleRemoveFile(); }}
                      className="ml-4 text-steel hover:text-safety-red transition-colors text-sm"
                      aria-label="Remove all files"
                    >
                      Remove
                    </button>
                  </div>
                  {fileQueue.length > 0 && (
                    <div className="mt-3 pl-[52px] space-y-1">
                      {fileQueue.map((qf, idx) => (
                        <div key={`${qf.name}-${idx}`} className="flex items-center gap-2 text-xs">
                          <span className="text-steel/50 font-telemetry w-4 text-right">{idx + 2}.</span>
                          <span className="text-steel font-body truncate">{qf.name}</span>
                          <span className="text-steel/40 font-body">({(qf.size / 1024).toFixed(1)} KB)</span>
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              setFileQueue((prev) => prev.filter((_, i) => i !== idx));
                            }}
                            className="text-steel/40 hover:text-safety-red transition-colors"
                            aria-label={`Remove ${qf.name}`}
                          >
                            x
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
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
                    Drag and drop your CSV files here
                  </p>
                  <p className="font-body text-steel text-xs">
                    or click to browse. Accepts .csv and .txt files. Multiple files supported.
                  </p>
                </>
              )}
            </div>
          </div>

          {/* ── Metadata Form ──────────────────────────── */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-6">
            {sessionType !== 'endurance' && (
            <div>
              <label htmlFor="driver-name" className="block text-sm font-telemetry text-steel mb-1.5 uppercase tracking-wider">
                Driver Name <span className="text-safety-red">*</span>
              </label>
              <input id="driver-name" type="text" list="dl-drivers" value={driverName} onChange={(e) => setDriverName(e.target.value)}
                disabled={isFormDisabled} required placeholder="e.g. Alex Rossi"
                className="w-full bg-concrete border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
                  placeholder:text-steel/60 focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50
                  disabled:opacity-50 disabled:cursor-not-allowed" />
              <datalist id="dl-drivers">
                {driverNames.map((d) => (<option key={d} value={d} />))}
              </datalist>
            </div>
            )}
            <div>
              <label htmlFor="session-type" className="block text-sm font-telemetry text-steel mb-1.5 uppercase tracking-wider">Session Type</label>
              <select id="session-type" value={sessionType} onChange={(e) => setSessionType(e.target.value)} disabled={isFormDisabled}
                className="w-full bg-concrete border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
                  focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50 disabled:opacity-50 disabled:cursor-not-allowed">
                {SESSION_TYPES.map((t) => (<option key={t.value} value={t.value}>{t.label}</option>))}
              </select>
            </div>
            {/* Endurance Drivers */}
            {sessionType === 'endurance' && (
              <div className="col-span-full bg-asphalt/30 rounded-lg border border-pit-orange/20 p-4">
                <label className="block text-sm font-telemetry text-pit-orange mb-2 uppercase tracking-wider">
                  Endurance Drivers
                </label>
                <p className="text-steel text-xs font-body mb-3">
                  Add all drivers participating. You&apos;ll assign stints after processing.
                </p>
                <div className="flex items-center gap-2 mb-3">
                  <input
                    type="text"
                    value={newEnduranceDriver}
                    onChange={(e) => setNewEnduranceDriver(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault();
                        const name = newEnduranceDriver.trim();
                        if (name && !enduranceDrivers.includes(name)) {
                          setEnduranceDrivers((prev) => [...prev, name]);
                          setNewEnduranceDriver('');
                        }
                      }
                    }}
                    disabled={isFormDisabled}
                    placeholder="Driver name"
                    className="flex-1 max-w-xs bg-concrete border border-steel/30 rounded px-3 py-2 text-chalk font-body text-sm
                      placeholder:text-steel/60 focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50
                      disabled:opacity-50 disabled:cursor-not-allowed"
                  />
                  <button
                    type="button"
                    disabled={isFormDisabled || !newEnduranceDriver.trim()}
                    onClick={() => {
                      const name = newEnduranceDriver.trim();
                      if (name && !enduranceDrivers.includes(name)) {
                        setEnduranceDrivers((prev) => [...prev, name]);
                        setNewEnduranceDriver('');
                      }
                    }}
                    className="px-3 py-2 bg-pit-orange/10 border border-pit-orange/30 rounded text-pit-orange text-sm font-body
                      hover:bg-pit-orange/20 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                  >
                    + Add
                  </button>
                </div>
                {enduranceDrivers.length > 0 && (
                  <div className="flex flex-wrap gap-2">
                    {enduranceDrivers.map((d) => (
                      <span key={d} className="inline-flex items-center gap-1.5 px-3 py-1 bg-concrete border border-steel/20 rounded-full text-chalk text-xs font-body">
                        {d}
                        <button
                          type="button"
                          onClick={() => setEnduranceDrivers((prev) => prev.filter((n) => n !== d))}
                          className="text-steel/40 hover:text-safety-red transition-colors"
                        >
                          &times;
                        </button>
                      </span>
                    ))}
                  </div>
                )}
                <div className="mt-3">
                  <label className="block text-xs font-telemetry text-steel mb-1 uppercase tracking-wider">
                    Pit Stop Duration (seconds)
                  </label>
                  <input
                    type="number"
                    value={pitThreshold}
                    onChange={(e) => setPitThreshold(Number(e.target.value))}
                    disabled={isFormDisabled}
                    min={20}
                    max={600}
                    className="w-32 bg-concrete border border-steel/30 rounded px-3 py-2 text-chalk font-body text-sm
                      focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50
                      disabled:opacity-50 disabled:cursor-not-allowed"
                  />
                  <p className="text-steel/50 text-[10px] font-body mt-1">Laps longer than this will be detected as pit stops</p>
                </div>
              </div>
            )}
            <div>
              <label htmlFor="track-name" className="block text-sm font-telemetry text-steel mb-1.5 uppercase tracking-wider">
                Track <span className="text-steel/60 text-xs normal-case">(optional — auto-detected from GPS)</span>
              </label>
              <input id="track-name" type="text" list="dl-tracks" value={trackName} onChange={(e) => setTrackName(e.target.value)}
                disabled={isFormDisabled} placeholder="Type or select track"
                className="w-full bg-concrete border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
                  placeholder:text-steel/60 focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50
                  disabled:opacity-50 disabled:cursor-not-allowed" />
              <datalist id="dl-tracks">
                {trackNames.map((t) => (<option key={t} value={t} />))}
              </datalist>
            </div>
            <div>
              <label htmlFor="track-state" className="block text-sm font-telemetry text-steel mb-1.5 uppercase tracking-wider">Track Condition</label>
              <select id="track-state" value={trackState} onChange={(e) => setTrackState(e.target.value)} disabled={isFormDisabled}
                className="w-full bg-concrete border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
                  focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50 disabled:opacity-50 disabled:cursor-not-allowed">
                {TRACK_STATES.map((s) => (<option key={s.value} value={s.value}>{s.label}</option>))}
              </select>
            </div>
            <div>
              <label htmlFor="kart-name" className="block text-sm font-telemetry text-steel mb-1.5 uppercase tracking-wider">
                Kart <span className="text-steel/60 text-xs normal-case">(optional — type to create new)</span>
              </label>
              <input id="kart-name" type="text" list="dl-karts" value={kartName} onChange={(e) => setKartName(e.target.value)}
                disabled={isFormDisabled} placeholder="Type or select kart"
                className="w-full bg-concrete border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
                  placeholder:text-steel/60 focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50
                  disabled:opacity-50 disabled:cursor-not-allowed" />
              <datalist id="dl-karts">
                {kartNames.map((k) => (<option key={k} value={k} />))}
              </datalist>
            </div>
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

            {/* ── Joker Lap ──────────────────────────────── */}
            <div className="sm:col-span-2">
              <div className="flex items-center gap-3">
                <label className="relative inline-flex items-center cursor-pointer">
                  <input
                    type="checkbox"
                    checked={jokerEnabled}
                    onChange={(e) => {
                      setJokerEnabled(e.target.checked);
                      if (!e.target.checked) setJokerLap('');
                    }}
                    disabled={isFormDisabled}
                    className="sr-only peer"
                  />
                  <div className="w-9 h-5 bg-steel/30 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full
                    after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-chalk after:rounded-full after:h-4 after:w-4
                    after:transition-all peer-checked:bg-pit-orange disabled:opacity-50" />
                </label>
                <span className="text-sm font-telemetry text-steel uppercase tracking-wider">
                  Joker Lap
                </span>
                {jokerEnabled && (
                  <input
                    id="joker-lap"
                    type="number"
                    min="1"
                    value={jokerLap}
                    onChange={(e) => setJokerLap(e.target.value)}
                    disabled={isFormDisabled}
                    placeholder="Lap #"
                    className="w-24 bg-concrete border border-steel/30 rounded px-3 py-1.5 text-chalk font-body text-sm
                      placeholder:text-steel/60 focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50
                      disabled:opacity-50 disabled:cursor-not-allowed"
                  />
                )}
              </div>
              <p className="text-steel/60 text-xs font-body mt-1.5 ml-12">
                Mark a specific lap as a joker lap (excluded from stats, flagged in reports)
              </p>
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
            <button type="submit" disabled={isFormDisabled || !file || (sessionType !== 'endurance' && !driverName.trim()) || (sessionType === 'endurance' && enduranceDrivers.length < 1)}
              className="px-6 py-3 bg-gold text-carbon font-monument text-sm rounded-lg
                hover:bg-gold/90 transition-colors
                disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-gold">
              {sessionType === 'endurance' ? 'Upload & Detect Stints' : fileQueue.length > 0 ? `Upload ${fileQueue.length + 1} Files` : 'Upload & Analyze'}
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
          {batchTotal > 1 && (
            <div className="mb-3 flex items-center gap-2 text-xs font-telemetry text-steel">
              <span>File {batchResults.length + 1} of {batchTotal}</span>
              <span className="text-steel/30">|</span>
              <span className="truncate">{file?.name}</span>
            </div>
          )}
          {pageState === 'uploading' && (
            <div className="mb-4">
              <div className="rounded-lg bg-concrete border border-steel/20 p-4 mb-4">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <div className="w-4 h-4 border-2 border-pit-orange/30 border-t-pit-orange rounded-full animate-spin" />
                    <span className="font-telemetry text-chalk text-sm">Uploading file...</span>
                  </div>
                  <span className="font-telemetry text-steel text-xs">{uploadPct}%</span>
                </div>
                <div className="h-2 rounded-full bg-steel/10 overflow-hidden">
                  <div
                    className="h-full rounded-full bg-pit-orange transition-all duration-300 ease-out"
                    style={{ width: `${uploadPct}%` }}
                  />
                </div>
              </div>
            </div>
          )}
          {(pageState === 'tracking' || pageState === 'resuming') && (
            <>
              <PipelineProgress pct={progressPct} stageName={stageName} status={sseStatus} />
              <StageInsights stageName={stageName} milestones={milestones} />
            </>
          )}
          <button
            type="button"
            onClick={handleCancel}
            className="mt-4 px-4 py-2 text-sm font-body text-steel hover:text-safety-red border border-steel/20 hover:border-safety-red/30 rounded-lg transition-colors"
          >
            Cancel
          </button>
        </div>
      )}

      {/* ── Endurance: Detecting ──────────────────────── */}
      {showEnduranceDetecting && (
        <div className="max-w-2xl flex items-center justify-center py-20">
          <div className="w-8 h-8 border-2 border-steel/30 border-t-pit-orange rounded-full animate-spin" />
          <span className="ml-3 text-steel text-sm font-body">Detecting laps and pit stops...</span>
        </div>
      )}

      {/* ── Endurance: Stint Config ──────────────────── */}
      {showEnduranceConfig && (
        <div className="max-w-3xl">
          <StintConfigFlow
            laps={enduranceLaps}
            autoStints={enduranceAutoStints}
            drivers={enduranceDrivers}
            medianLapTime={enduranceMedian}
            pitThreshold={pitThreshold}
            isProcessing={false}
            onProcess={(configs) => {
              setEnduranceStintConfigs(configs);
              setPageState('endurance_processing');
              // Dispatch processing
              api.post('/endurance/process', {
                job_id: enduranceJobId,
                stints: configs,
              }).catch((err: any) => {
                setErrorMessage(err.message || 'Failed to start processing');
                setPageState('error');
              });
            }}
          />
        </div>
      )}

      {/* ── Endurance: Processing Progress ───────────── */}
      {showEnduranceProcessing && enduranceJobId && (
        <div className="max-w-3xl">
          <StintProcessingProgress
            jobId={enduranceJobId}
            stintConfigs={enduranceStintConfigs}
            drivers={enduranceDrivers}
            onComplete={(jobId) => {
              setPageState('completed');
              // Navigate to sessions list after brief delay
              setTimeout(() => router.push('/app/sessions'), 2000);
            }}
          />
        </div>
      )}

      {/* ── Corner Picker ──────────────────────────────── */}
      {showCornerPicker && (
        <div className="max-w-3xl">
          <div className="mb-4 p-4 rounded-lg bg-pit-orange/5 border border-pit-orange/20">
            <p className="text-chalk font-body text-sm mb-1">
              Define corners for detailed analysis
            </p>
            <p className="text-steel text-xs font-body">
              Click on the track to place corners. Drag entry/exit handles to adjust zones.
              Auto-detected corners will be used if you don&apos;t interact within 15 seconds.
            </p>
          </div>
          <CornerEditor
            trackLayout={trackLayout}
            onSubmit={handleCornerSubmit}
            isSubmitting={isSubmittingCorners}
          />
        </div>
      )}

      {/* ── Completed State ──────────────────────────── */}
      {showCompleted && (
        <div className="max-w-2xl">
          {batchTotal > 1 ? (
            /* Batch summary */
            <div className="space-y-3">
              <div className="p-4 rounded-lg bg-acid-green/5 border border-acid-green/20" role="status">
                <p className="text-acid-green font-body text-sm font-medium mb-1">
                  Batch upload complete
                </p>
                <p className="text-steel text-xs font-body">
                  {batchResults.filter((r) => r.sessionId).length} of {batchTotal} files processed successfully
                </p>
              </div>
              <div className="space-y-1.5">
                {batchResults.map((r, i) => (
                  <div key={i} className={`flex items-center gap-2 p-2.5 rounded-lg border text-sm font-body ${
                    r.error ? 'bg-safety-red/5 border-safety-red/20 text-safety-red' : 'bg-concrete border-steel/20 text-chalk'
                  }`}>
                    {r.error ? (
                      <span className="text-safety-red flex-shrink-0" aria-hidden="true">x</span>
                    ) : (
                      <svg width="14" height="14" viewBox="0 0 20 20" fill="none" className="text-acid-green flex-shrink-0" aria-hidden="true">
                        <circle cx="10" cy="10" r="9" stroke="currentColor" strokeWidth="1.5" />
                        <path d="M6 10l3 3 5-6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    )}
                    <span className="truncate flex-1">{r.name}</span>
                    {r.error && <span className="text-xs text-safety-red/70 truncate max-w-[200px]">{r.error}</span>}
                    {r.sessionId && (
                      <Link href={`/app/sessions/${r.sessionId}`} className="text-xs text-pit-orange hover:text-chalk transition-colors flex-shrink-0">
                        View
                      </Link>
                    )}
                  </div>
                ))}
              </div>
              <Link
                href="/app/sessions"
                className="inline-block mt-2 px-4 py-2 text-sm font-telemetry text-chalk bg-concrete border border-steel/20 rounded-lg hover:border-steel/40 transition-colors"
              >
                Back to Sessions
              </Link>
            </div>
          ) : (
            /* Single file completion */
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
          )}
        </div>
      )}
    </div>
  );
}
