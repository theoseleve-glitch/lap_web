'use client';

import { useState, useRef, useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api-client';
import { PageHeader } from '@/components/app';

type Step = 1 | 2 | 3;

interface FileEntry {
  name: string;
  size: number;
  modified: string;
}

interface Driver {
  driver_id: number;
  driver_name: string;
}

interface Track {
  track_id: number;
  track_name: string;
}

interface Kart {
  id: number;
  name: string;
}

interface AnalysisJob {
  job_id: string;
  status: 'pending' | 'processing' | 'complete' | 'failed';
  progress: number;
  message: string;
  session_id?: string;
}

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:5000';
const SESSION_TYPES = ['Practice', 'Qualifying', 'Race', 'Test'] as const;

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const stepLabels = ['Select Data', 'Configure', 'Analyze'] as const;

export default function AnalyzePage() {
  const router = useRouter();
  const [step, setStep] = useState<Step>(1);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [uploadedFile, setUploadedFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Step 2 form state
  const [driverId, setDriverId] = useState('');
  const [trackId, setTrackId] = useState('');
  const [kartId, setKartId] = useState('');
  const [sessionType, setSessionType] = useState<string>(SESSION_TYPES[0]);

  // Step 3 state
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<AnalysisJob | null>(null);

  // Data fetching
  const { data: filesData } = useQuery({
    queryKey: ['files', 'list'],
    queryFn: () => api.get<{ files: FileEntry[] }>('/files'),
    enabled: step === 1,
  });

  const { data: driversData } = useQuery({
    queryKey: ['drivers', 'list'],
    queryFn: () => api.get<{ drivers: Driver[] }>('/drivers'),
    enabled: step === 2,
  });

  const { data: tracksData } = useQuery({
    queryKey: ['tracks', 'list'],
    queryFn: () => api.get<{ tracks: Track[] }>('/tracks'),
    enabled: step === 2,
  });

  const { data: kartsData } = useQuery({
    queryKey: ['karts', 'list'],
    queryFn: () => api.get<{ karts: Kart[] }>('/karts'),
    enabled: step === 2,
  });

  // Poll job status in step 3 (Flask serves at /api/v1/ingest/status/:id)
  useQuery({
    queryKey: ['analysis-job', jobId],
    queryFn: async () => {
      const res = await fetch(`${BACKEND_URL}/api/v1/ingest/status/${jobId}`);
      return res.json() as Promise<AnalysisJob>;
    },
    enabled: step === 3 && !!jobId && jobStatus?.status !== 'complete' && jobStatus?.status !== 'failed',
    refetchInterval: 2000,
    select: (data) => {
      setJobStatus(data);
      return data;
    },
  });

  const handleUpload = useCallback(async (file: File) => {
    setUploading(true);
    setUploadProgress(0);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const result = await fetch(`${BACKEND_URL}/api/files/upload`, {
        method: 'POST',
        body: formData,
      });
      if (!result.ok) throw new Error('Upload failed');
      const data = await result.json();
      setSelectedFile(data.data?.filename ?? file.name);
      setUploadedFile(file);
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
      // Flask serves ingest start at /api/v1/ingest/start (form data)
      const form = new FormData();
      form.append('csv_file', selectedFile);
      if (driverId) form.append('driver_id', driverId);
      if (trackId) form.append('track_id', trackId);
      if (kartId) form.append('kart_id', kartId);
      form.append('session_type', sessionType);
      const res = await fetch(`${BACKEND_URL}/api/v1/ingest/start`, { method: 'POST', body: form });
      const result = await res.json();
      if (!res.ok) throw new Error(result.error || 'Failed');
      setJobId(result.job_id);
      setJobStatus({ job_id: result.job_id, status: 'pending', progress: 0, message: 'Starting analysis...' });
    } catch {
      setJobStatus({ job_id: '', status: 'failed', progress: 0, message: 'Failed to start analysis' });
    }
  };

  const files = filesData?.files ?? [];
  const drivers = driversData?.drivers ?? [];
  const tracks = tracksData?.tracks ?? [];
  const karts = kartsData?.karts ?? [];

  return (
    <div>
      <PageHeader title="New Analysis" subtitle="Upload and analyze telemetry data" />

      {/* Step indicator */}
      <div className="flex items-center gap-2 mb-8">
        {stepLabels.map((label, i) => {
          const num = (i + 1) as Step;
          const isActive = step === num;
          const isComplete = step > num;
          return (
            <div key={label} className="flex items-center gap-2">
              {i > 0 && (
                <div
                  className={`w-12 h-0.5 ${isComplete ? 'bg-acid-green' : 'bg-steel/30'}`}
                />
              )}
              <div className="flex items-center gap-2">
                <div
                  className={`w-8 h-8 rounded-full flex items-center justify-center font-telemetry text-sm ${
                    isActive
                      ? 'bg-acid-green text-asphalt'
                      : isComplete
                        ? 'bg-acid-green/20 text-acid-green'
                        : 'bg-concrete text-steel border border-steel/30'
                  }`}
                >
                  {isComplete ? '✓' : num}
                </div>
                <span
                  className={`font-body text-sm ${isActive ? 'text-chalk' : 'text-steel'}`}
                >
                  {label}
                </span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Step 1: Select Data */}
      {step === 1 && (
        <div className="bg-concrete rounded-lg border border-steel/20 p-6">
          <h2 className="font-body text-chalk text-lg mb-4">Data Source</h2>

          {/* Drag-drop zone */}
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            className={`border-2 border-dashed rounded-lg p-8 text-center mb-4 transition-colors ${
              dragOver ? 'border-acid-green bg-acid-green/5' : 'border-steel/30'
            }`}
          >
            <p className="text-steel font-body mb-2">Drop CSV files here to upload</p>
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="px-4 py-2 bg-pit-orange text-asphalt font-telemetry text-sm rounded hover:bg-pit-orange/80 transition-colors"
            >
              Upload CSV
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
            <div className="mb-4">
              <div className="w-full bg-steel/20 rounded-full h-2">
                <div
                  className="bg-acid-green h-2 rounded-full transition-all"
                  style={{ width: `${uploadProgress}%` }}
                />
              </div>
              <span className="text-steel font-telemetry text-xs mt-1">Uploading...</span>
            </div>
          )}

          {/* File browser */}
          <div className="border border-steel/20 rounded-lg overflow-hidden">
            <div className="bg-asphalt/50 px-4 py-2 border-b border-steel/20 flex justify-between items-center">
              <span className="font-telemetry text-sm text-steel">data/raw/</span>
              {uploadedFile && (
                <span className="text-acid-green font-telemetry text-xs">
                  Uploaded: {uploadedFile.name}
                </span>
              )}
            </div>
            <div className="max-h-64 overflow-y-auto">
              {files.length === 0 ? (
                <div className="p-4 text-center text-steel font-body text-sm">
                  No files found. Upload a CSV to get started.
                </div>
              ) : (
                files.map((f) => (
                  <button
                    key={f.name}
                    type="button"
                    onClick={() => setSelectedFile(f.name)}
                    className={`w-full text-left px-4 py-2.5 flex justify-between items-center border-b border-steel/10 transition-colors ${
                      selectedFile === f.name
                        ? 'bg-acid-green/10 text-acid-green'
                        : 'text-chalk hover:bg-asphalt/50'
                    }`}
                  >
                    <span className="font-body text-sm">{f.name}</span>
                    <span className="font-telemetry text-xs text-steel">
                      {formatSize(f.size)} · {f.modified}
                    </span>
                  </button>
                ))
              )}
            </div>
          </div>

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
        <div className="bg-concrete rounded-lg border border-steel/20 p-6">
          <h2 className="font-body text-chalk text-lg mb-4">Session Configuration</h2>

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
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-steel font-telemetry text-xs uppercase mb-1">
                Driver
              </label>
              <select
                value={driverId}
                onChange={(e) => setDriverId(e.target.value)}
                className="w-full bg-asphalt border border-steel/30 rounded px-3 py-2 text-chalk font-body text-sm focus:outline-none focus:border-pit-orange"
              >
                <option value="">Auto-detect</option>
                {drivers.map((d) => (
                  <option key={d.driver_id} value={d.driver_id}>
                    {d.driver_name}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-steel font-telemetry text-xs uppercase mb-1">
                Track
              </label>
              <select
                value={trackId}
                onChange={(e) => setTrackId(e.target.value)}
                className="w-full bg-asphalt border border-steel/30 rounded px-3 py-2 text-chalk font-body text-sm focus:outline-none focus:border-pit-orange"
              >
                <option value="">Auto-detect</option>
                {tracks.map((t) => (
                  <option key={t.track_id} value={t.track_id}>
                    {t.track_name}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-steel font-telemetry text-xs uppercase mb-1">
                Kart
              </label>
              <select
                value={kartId}
                onChange={(e) => setKartId(e.target.value)}
                className="w-full bg-asphalt border border-steel/30 rounded px-3 py-2 text-chalk font-body text-sm focus:outline-none focus:border-pit-orange"
              >
                <option value="">None</option>
                {karts.map((k) => (
                  <option key={k.id} value={k.id}>
                    {k.name}
                  </option>
                ))}
              </select>
            </div>
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
              className="px-6 py-2.5 bg-acid-green text-asphalt font-telemetry text-sm rounded hover:bg-acid-green/80 transition-colors"
            >
              Start Analysis
            </button>
          </div>
        </div>
      )}

      {/* Step 3: Progress */}
      {step === 3 && (
        <div className="bg-concrete rounded-lg border border-steel/20 p-6">
          <h2 className="font-body text-chalk text-lg mb-4">Analyzing...</h2>

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
                        ? `/app/sessions/${jobStatus.session_id}`
                        : '/app/sessions',
                    )
                  }
                  className="px-6 py-2.5 bg-acid-green text-asphalt font-telemetry text-sm rounded hover:bg-acid-green/80 transition-colors"
                >
                  View Session
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
