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

  // One-report limit
  const [alreadyUsed, setAlreadyUsed] = useState(false);
  const [existingSessionId, setExistingSessionId] = useState<string | null>(null);

  useEffect(() => {
    try {
      const stored = localStorage.getItem('lap_free_report');
      if (stored) {
        const parsed = JSON.parse(stored);
        if (parsed.used) {
          setAlreadyUsed(true);
          setExistingSessionId(parsed.session_id ?? null);
        }
      }
    } catch {
      // ignore malformed data
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
          <span className="text-pit-orange font-monument text-2xl">1</span>
        </div>
        <h2 className="font-monument text-xl text-chalk mb-2">FREE REPORT ALREADY USED</h2>
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
              <label className="block text-steel font-telemetry text-xs uppercase tracking-wider mb-1.5">
                Session Type
              </label>
              <select
                value={sessionType}
                onChange={(e) => setSessionType(e.target.value)}
                className="w-full bg-asphalt border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm focus:outline-none focus:border-pit-orange"
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
