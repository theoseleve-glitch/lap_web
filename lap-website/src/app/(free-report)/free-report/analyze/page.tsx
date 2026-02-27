'use client';

import { useState, useRef, useCallback, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
// api-client no longer used here — direct fetch to backend
import { FormField } from '@/components/app';
import Link from 'next/link';
import { useTranslation } from '@/i18n';
import { getAccessToken } from '@/lib/auth-store';

type Step = 1 | 2 | 3;

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:5000';

async function authenticatedFetch(path: string, init?: RequestInit): Promise<Response> {
  const headers = new Headers(init?.headers);

  if (typeof window !== 'undefined') {
    const token = getAccessToken();
    if (token) {
      headers.set('Authorization', `Bearer ${token}`);
    }
  }

  return fetch(`${BACKEND_URL}${path}`, {
    ...init,
    headers,
    credentials: 'include',
  });
}

interface AnalysisJob {
  job_id: string;
  status: 'pending' | 'processing' | 'complete' | 'failed';
  progress: number;
  message: string;
  session_id?: string;
}

export default function FreeReportAnalyzePage() {
  const router = useRouter();
  const { t } = useTranslation();
  const [step, setStep] = useState<Step>(1);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Step 2
  const [driverName, setDriverName] = useState('');
  const [trackName, setTrackName] = useState('');
  const [sessionType, setSessionType] = useState<string>('Practice');

  // Step 3
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<AnalysisJob | null>(null);

  // One-report limit
  const [alreadyUsed, setAlreadyUsed] = useState(false);
  const [existingSessionId, setExistingSessionId] = useState<string | null>(null);

  const sessionTypeKeys: { key: string; value: string }[] = [
    { key: 'freeReport.sessionPractice', value: 'Practice' },
    { key: 'freeReport.sessionQualifying', value: 'Qualifying' },
    { key: 'freeReport.sessionRace', value: 'Race' },
    { key: 'freeReport.sessionTest', value: 'Test' },
  ];

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

  // Poll job status (Flask serves at /analyze/api/status/:id)
  useQuery({
    queryKey: ['analysis-job', jobId],
    queryFn: async () => {
      const res = await authenticatedFetch(`/analyze/api/status/${jobId}`);
      return res.json() as Promise<AnalysisJob>;
    },
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
      const result = await authenticatedFetch('/api/files/upload', {
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
      // Flask serves ingest start at /analyze/api/start (form data)
      const form = new FormData();
      form.append('csv_file', selectedFile);
      if (driverName) form.append('driver_name', driverName);
      if (trackName) form.append('track_name', trackName);
      form.append('session_type', sessionType);
      const res = await authenticatedFetch('/analyze/api/start', { method: 'POST', body: form });
      const result = await res.json();
      if (!res.ok) throw new Error(result.error || 'Failed');
      setJobId(result.job_id);
      setJobStatus({ job_id: result.job_id, status: 'pending', progress: 0, message: t('freeReport.startingAnalysis') });
    } catch {
      setJobStatus({ job_id: '', status: 'failed', progress: 0, message: t('freeReport.failedToStart') });
    }
  };

  // Already used — show redirect
  if (alreadyUsed) {
    return (
      <div className="bg-concrete rounded-lg border border-steel/20 p-8 text-center">
        <div className="w-16 h-16 rounded-full bg-pit-orange/20 flex items-center justify-center mx-auto mb-4">
          <span className="text-pit-orange font-monument text-2xl">1</span>
        </div>
        <h2 className="font-monument text-xl text-chalk mb-2">{t('freeReport.alreadyUsedTitle')}</h2>
        <p className="text-steel font-body mb-6 max-w-md mx-auto">
          {t('freeReport.alreadyUsedDesc')}
        </p>
        <div className="flex gap-3 justify-center">
          {existingSessionId && (
            <Link
              href={`/free-report/report/${existingSessionId}`}
              className="px-5 py-2.5 bg-concrete border border-steel/30 text-chalk font-telemetry text-sm rounded hover:bg-asphalt/50 transition-colors"
            >
              {t('freeReport.viewReport')}
            </Link>
          )}
          <Link
            href="/pricing"
            className="px-5 py-2.5 bg-pit-orange text-asphalt font-monument text-sm tracking-wider rounded hover:brightness-110 transition-all"
          >
            {t('freeReport.upgradeNow')}
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="text-center mb-8">
        <h1 className="font-monument text-3xl text-chalk tracking-tight mb-2">{t('freeReport.heading')}</h1>
        <p className="text-steel font-body">{t('freeReport.subheading')}</p>
      </div>

      {/* Step 1: Upload */}
      {step === 1 && (
        <div className="bg-concrete rounded-lg border border-steel/20 p-6 max-w-2xl mx-auto">
          <h2 className="font-body text-chalk text-lg mb-4">{t('freeReport.step1Title')}</h2>

          <div
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            className={`border-2 border-dashed rounded-lg p-12 text-center transition-colors ${
              dragOver ? 'border-acid-green bg-acid-green/5' : 'border-steel/30'
            }`}
          >
            <p className="text-steel font-body mb-2">{t('freeReport.dropHint')}</p>
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="px-5 py-2.5 bg-pit-orange text-asphalt font-monument text-sm tracking-wider rounded hover:brightness-110 transition-all"
            >
              {t('freeReport.chooseFile')}
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
              <span className="text-steel font-telemetry text-xs mt-1">{t('freeReport.uploading')}</span>
            </div>
          )}

          {selectedFile && (
            <div className="mt-4 p-3 bg-acid-green/5 border border-acid-green/20 rounded text-acid-green font-telemetry text-sm">
              {t('freeReport.selected')} {selectedFile}
            </div>
          )}

          <div className="flex justify-end mt-6">
            <button
              type="button"
              disabled={!selectedFile}
              onClick={() => setStep(2)}
              className="px-6 py-2.5 bg-acid-green text-asphalt font-telemetry text-sm rounded disabled:opacity-30 disabled:cursor-not-allowed hover:bg-acid-green/80 transition-colors"
            >
              {t('freeReport.nextConfigure')}
            </button>
          </div>
        </div>
      )}

      {/* Step 2: Configure */}
      {step === 2 && (
        <div className="bg-concrete rounded-lg border border-steel/20 p-6 max-w-2xl mx-auto">
          <h2 className="font-body text-chalk text-lg mb-4">{t('freeReport.step2Title')}</h2>

          <div className="mb-3 p-3 bg-asphalt/50 rounded border border-steel/20 flex items-center gap-2">
            <span className="text-steel">{t('freeReport.fileLabel')}</span>
            <span className="text-acid-green font-telemetry text-sm">{selectedFile}</span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-steel font-telemetry text-xs uppercase tracking-wider mb-1.5">
                {t('freeReport.sessionType')}
              </label>
              <select
                value={sessionType}
                onChange={(e) => setSessionType(e.target.value)}
                className="w-full bg-asphalt border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm focus:outline-none focus:border-pit-orange"
              >
                {sessionTypeKeys.map((st) => (
                  <option key={st.value} value={st.value}>{t(st.key)}</option>
                ))}
              </select>
            </div>

            <FormField
              label={t('freeReport.driverName')}
              type="text"
              placeholder={t('freeReport.driverPlaceholder')}
              value={driverName}
              onChange={(e) => setDriverName(e.target.value)}
            />

            <FormField
              label={t('freeReport.trackName')}
              type="text"
              placeholder={t('freeReport.trackPlaceholder')}
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
              {t('freeReport.back')}
            </button>
            <button
              type="button"
              onClick={handleSubmit}
              className="px-6 py-2.5 bg-acid-green text-asphalt font-monument text-sm tracking-wider rounded hover:bg-acid-green/80 transition-colors"
            >
              {t('freeReport.startAnalysis')}
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
                <p className="text-chalk font-body text-lg mb-2">{t('freeReport.analysisComplete')}</p>
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
                  {t('freeReport.viewReport')}
                </button>
              </>
            ) : jobStatus?.status === 'failed' ? (
              <>
                <div className="w-16 h-16 rounded-full bg-safety-red/20 flex items-center justify-center mb-4">
                  <span className="text-safety-red text-3xl">✗</span>
                </div>
                <p className="text-chalk font-body text-lg mb-2">{t('freeReport.analysisFailed')}</p>
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
                  {t('freeReport.tryAgain')}
                </button>
              </>
            ) : (
              <>
                <div className="w-12 h-12 border-3 border-steel/30 border-t-acid-green rounded-full animate-spin mb-4" />
                <p className="text-chalk font-body mb-2">
                  {jobStatus?.message ?? t('freeReport.startingAnalysis')}
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
