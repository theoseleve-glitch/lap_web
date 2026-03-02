'use client';

import { useState, useRef, useCallback, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { PageHeader } from '@/components/app';
import { BACKEND_URL, ApiError } from '@/lib/api-client';
import { getAccessToken, getWorkspaceId } from '@/lib/auth-store';

/* ── Types ──────────────────────────────────────────── */

interface UploadResponse {
  job_id: string;
  status: string;
}

type UploadStatus = 'idle' | 'uploading' | 'success' | 'error';

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

/* ── Upload function (multipart/form-data) ──────────── */

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

  const headers: Record<string, string> = {};
  const token = getAccessToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const wsId = getWorkspaceId();
  if (wsId !== null) headers['X-Workspace-Id'] = String(wsId);

  // Do NOT set Content-Type -- let the browser set it with the multipart boundary.
  const res = await fetch(`${BACKEND_URL}/api/v1/sessions/upload`, {
    method: 'POST',
    headers,
    body: formData,
    credentials: 'include',
  });

  const contentType = res.headers.get('content-type') || '';
  if (!contentType.includes('application/json')) {
    throw new Error(`Server returned non-JSON response (${res.status})`);
  }

  const envelope = await res.json();

  if (envelope.ok && envelope.data) {
    return envelope.data as UploadResponse;
  }

  throw new ApiError(
    envelope.error?.code ?? 'UPLOAD_FAILED',
    envelope.error?.message ?? `Upload failed (${res.status})`,
    res.status,
    envelope.error?.details,
  );
}

/* ── Component ──────────────────────────────────────── */

export default function UploadPage() {
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);

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

  // UI state
  const [status, setStatus] = useState<UploadStatus>('idle');
  const [errorMessage, setErrorMessage] = useState('');
  const [isDragOver, setIsDragOver] = useState(false);

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
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  }, []);

  // Submit handler
  const handleSubmit = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();

    if (!file) {
      setErrorMessage('Please select a CSV file to upload.');
      return;
    }
    if (!driverName.trim()) {
      setErrorMessage('Driver name is required.');
      return;
    }

    setStatus('uploading');
    setErrorMessage('');

    try {
      await uploadSession(file, {
        driver_name: driverName.trim(),
        session_type: sessionType,
        track_state: trackState,
        lap_range: lapRange.trim() || undefined,
        exclude_laps: excludeLaps.trim() || undefined,
        kart_id: kartId || undefined,
        session_date: sessionDate || undefined,
      });

      setStatus('success');

      // Redirect to the job monitor immediately
      router.push('/app/jobs');
    } catch (err) {
      setStatus('error');
      if (err instanceof ApiError) {
        setErrorMessage(err.message);
      } else if (err instanceof Error) {
        setErrorMessage(err.message);
      } else {
        setErrorMessage('An unexpected error occurred. Please try again.');
      }
    }
  }, [file, driverName, sessionType, trackState, lapRange, excludeLaps, kartId, sessionDate, router]);

  const isDisabled = status === 'uploading' || status === 'success';

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
            onClick={() => !isDisabled && fileInputRef.current?.click()}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                if (!isDisabled) fileInputRef.current?.click();
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
              ${isDisabled ? 'opacity-60 cursor-not-allowed' : ''}
            `}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept={ACCEPTED_EXTENSIONS}
              onChange={handleFileChange}
              disabled={isDisabled}
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
                {!isDisabled && (
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); handleRemoveFile(); }}
                    className="ml-4 text-steel hover:text-safety-red transition-colors text-sm"
                    aria-label="Remove file"
                  >
                    Remove
                  </button>
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
          {/* Driver Name */}
          <div>
            <label htmlFor="driver-name" className="block text-sm font-telemetry text-steel mb-1.5 uppercase tracking-wider">
              Driver Name <span className="text-safety-red">*</span>
            </label>
            <input
              id="driver-name"
              type="text"
              value={driverName}
              onChange={(e) => setDriverName(e.target.value)}
              disabled={isDisabled}
              required
              placeholder="e.g. Alex Rossi"
              className="w-full bg-concrete border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
                placeholder:text-steel/40 focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50
                disabled:opacity-50 disabled:cursor-not-allowed"
            />
          </div>

          {/* Session Type */}
          <div>
            <label htmlFor="session-type" className="block text-sm font-telemetry text-steel mb-1.5 uppercase tracking-wider">
              Session Type
            </label>
            <select
              id="session-type"
              value={sessionType}
              onChange={(e) => setSessionType(e.target.value)}
              disabled={isDisabled}
              className="w-full bg-concrete border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
                focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50
                disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {SESSION_TYPES.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </div>

          {/* Track State */}
          <div>
            <label htmlFor="track-state" className="block text-sm font-telemetry text-steel mb-1.5 uppercase tracking-wider">
              Track Condition
            </label>
            <select
              id="track-state"
              value={trackState}
              onChange={(e) => setTrackState(e.target.value)}
              disabled={isDisabled}
              className="w-full bg-concrete border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
                focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50
                disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {TRACK_STATES.map((s) => (
                <option key={s.value} value={s.value}>{s.label}</option>
              ))}
            </select>
          </div>

          {/* Kart (optional) */}
          {karts.length > 0 && (
            <div>
              <label htmlFor="kart-id" className="block text-sm font-telemetry text-steel mb-1.5 uppercase tracking-wider">
                Kart <span className="text-steel/40 text-xs normal-case">(optional)</span>
              </label>
              <select
                id="kart-id"
                value={kartId}
                onChange={(e) => setKartId(e.target.value)}
                disabled={isDisabled}
                className="w-full bg-concrete border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
                  focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50
                  disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <option value="">None</option>
                {karts.map((k) => (
                  <option key={k.kart_id} value={String(k.kart_id)}>{k.kart_name}</option>
                ))}
              </select>
            </div>
          )}

          {/* Session Date (optional) */}
          <div>
            <label htmlFor="session-date" className="block text-sm font-telemetry text-steel mb-1.5 uppercase tracking-wider">
              Session Date <span className="text-steel/40 text-xs normal-case">(optional — auto-detected from CSV)</span>
            </label>
            <input
              id="session-date"
              type="date"
              value={sessionDate}
              onChange={(e) => setSessionDate(e.target.value)}
              disabled={isDisabled}
              className="w-full bg-concrete border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
                focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50
                disabled:opacity-50 disabled:cursor-not-allowed"
            />
          </div>

          {/* Lap Range */}
          <div>
            <label htmlFor="lap-range" className="block text-sm font-telemetry text-steel mb-1.5 uppercase tracking-wider">
              Lap Range <span className="text-steel/40 text-xs normal-case">(optional)</span>
            </label>
            <input
              id="lap-range"
              type="text"
              value={lapRange}
              onChange={(e) => setLapRange(e.target.value)}
              disabled={isDisabled}
              placeholder="e.g. 3-15"
              className="w-full bg-concrete border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
                placeholder:text-steel/40 focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50
                disabled:opacity-50 disabled:cursor-not-allowed"
            />
          </div>

          {/* Exclude Laps */}
          <div className="sm:col-span-2">
            <label htmlFor="exclude-laps" className="block text-sm font-telemetry text-steel mb-1.5 uppercase tracking-wider">
              Exclude Laps <span className="text-steel/40 text-xs normal-case">(optional)</span>
            </label>
            <input
              id="exclude-laps"
              type="text"
              value={excludeLaps}
              onChange={(e) => setExcludeLaps(e.target.value)}
              disabled={isDisabled}
              placeholder="e.g. 1,2,16"
              className="w-full bg-concrete border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
                placeholder:text-steel/40 focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50
                disabled:opacity-50 disabled:cursor-not-allowed"
            />
          </div>
        </div>

        {/* ── Error Message ──────────────────────────── */}
        {errorMessage && status !== 'uploading' && (
          <div
            className="mb-4 p-3 rounded-lg bg-safety-red/10 border border-safety-red/20 text-safety-red text-sm font-body"
            role="alert"
          >
            {errorMessage}
          </div>
        )}

        {/* ── Loading State ──────────────────────────── */}
        {status === 'uploading' && (
          <div className="mb-4 p-4 rounded-lg bg-pit-orange/5 border border-pit-orange/20" role="status">
            <div className="flex items-center gap-3">
              <div className="w-5 h-5 border-2 border-pit-orange/30 border-t-pit-orange rounded-full animate-spin" />
              <div>
                <p className="text-chalk font-body text-sm">
                  Processing telemetry data...
                </p>
                <p className="text-steel text-xs font-body mt-0.5">
                  This may take a few minutes depending on file size.
                </p>
              </div>
            </div>
          </div>
        )}

        {/* ── Success State ──────────────────────────── */}
        {status === 'success' && (
          <div className="mb-4 p-4 rounded-lg bg-acid-green/5 border border-acid-green/20" role="status">
            <div className="flex items-center gap-3">
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none" className="text-acid-green" aria-hidden="true">
                <circle cx="10" cy="10" r="9" stroke="currentColor" strokeWidth="1.5" />
                <path d="M6 10l3 3 5-6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <p className="text-acid-green font-body text-sm">
                Upload accepted. Redirecting to job monitor...
              </p>
            </div>
          </div>
        )}

        {/* ── Submit Button ──────────────────────────── */}
        <div className="flex items-center gap-4">
          <button
            type="submit"
            disabled={isDisabled || !file || !driverName.trim()}
            className="px-6 py-3 bg-acid-green text-carbon font-monument text-sm rounded-lg
              hover:bg-acid-green/90 transition-colors
              disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-acid-green"
          >
            {status === 'uploading' ? 'Processing...' : 'Upload & Analyze'}
          </button>

          <Link
            href="/app/sessions"
            className="px-4 py-2.5 text-steel hover:text-chalk transition-colors font-body text-sm"
          >
            Cancel
          </Link>
        </div>
      </form>
    </div>
  );
}
