'use client';

import { useState, useEffect, useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import { DRIVER_COLORS } from './types';

interface StintStatus {
  stint_number: number;
  driver_name: string;
  status: 'queued' | 'processing' | 'complete' | 'error';
  best_lap_s?: number;
  lap_count?: number;
  error?: string;
  session_id?: string;
}

interface StintProcessingProgressProps {
  jobId: string;
  stintConfigs: Array<{ stint_number: number; driver_name: string }>;
  drivers: string[];
  onComplete: (jobId: string) => void;
}

function formatTime(s: number | null | undefined): string {
  if (s == null) return '--';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}

export function StintProcessingProgress({
  jobId,
  stintConfigs,
  drivers,
  onComplete,
}: StintProcessingProgressProps) {
  const [stintStatuses, setStintStatuses] = useState<StintStatus[]>(
    stintConfigs.map((c) => ({
      stint_number: c.stint_number,
      driver_name: c.driver_name,
      status: 'queued',
    }))
  );
  const [phase, setPhase] = useState<'stints' | 'drivers' | 'team' | 'done'>('stints');

  // Poll for status updates
  const { data } = useQuery({
    queryKey: ['endurance-status', jobId],
    queryFn: () => api.get<Record<string, any>>(`/endurance/status/${jobId}`),
    refetchInterval: phase !== 'done' ? 2000 : false,
  });

  useEffect(() => {
    if (!data) return;

    const status = data.status;

    if (status === 'stint_complete') {
      setStintStatuses((prev) =>
        prev.map((s) =>
          s.stint_number === data.stint_number
            ? { ...s, status: 'complete', best_lap_s: data.best_lap_s, lap_count: data.lap_count }
            : s
        )
      );
    }

    if (status === 'processing_stint') {
      setStintStatuses((prev) =>
        prev.map((s) =>
          s.stint_number === data.stint_number ? { ...s, status: 'processing' } : s
        )
      );
    }

    if (status === 'stint_error') {
      setStintStatuses((prev) =>
        prev.map((s) =>
          s.stint_number === data.stint_number ? { ...s, status: 'error', error: data.error } : s
        )
      );
    }

    if (status === 'processing_drivers') setPhase('drivers');
    if (status === 'processing_team') setPhase('team');
    if (status === 'completed') {
      setPhase('done');
      onComplete(jobId);
    }
  }, [data, jobId, onComplete]);

  const driverColorMap = Object.fromEntries(
    drivers.map((d, i) => [d, DRIVER_COLORS[i % DRIVER_COLORS.length]])
  );

  const statusIcon = (s: StintStatus['status']) => {
    switch (s) {
      case 'complete': return <span className="text-acid-green">&#10003;</span>;
      case 'processing': return <span className="w-3 h-3 border border-acid-green/50 border-t-acid-green rounded-full animate-spin inline-block" />;
      case 'error': return <span className="text-safety-red">&#10007;</span>;
      default: return <span className="text-steel/30">&#9711;</span>;
    }
  };

  const completedCount = stintStatuses.filter((s) => s.status === 'complete').length;
  const totalCount = stintStatuses.length;
  const overallPct = totalCount > 0
    ? Math.round(((completedCount + (phase === 'drivers' ? 0.2 : phase === 'team' ? 0.5 : phase === 'done' ? 1 : 0)) / (totalCount + 1)) * 100)
    : 0;

  return (
    <div className="space-y-4">
      <div className="bg-concrete rounded-xl border border-steel/10 p-6">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-lg font-monument text-chalk">Processing Stints</h3>
          <span className="text-xs font-telemetry text-steel">{completedCount}/{totalCount} stints</span>
        </div>

        {/* Overall progress bar */}
        <div className="w-full h-2 bg-asphalt rounded-full overflow-hidden mb-1">
          <div
            className="h-full bg-acid-green rounded-full transition-all duration-700 ease-out"
            style={{ width: `${overallPct}%` }}
          />
        </div>
        <p className="text-steel text-xs font-body mb-4">
          {phase === 'done' ? 'Analysis complete!' : phase === 'team' ? 'Computing team report...' : phase === 'drivers' ? 'Aggregating driver reports...' : 'Analyzing stints individually...'}
        </p>

        <div className="space-y-2">
          {stintStatuses.map((stint) => (
            <div
              key={stint.stint_number}
              className={`flex items-center gap-3 px-4 py-3 rounded-lg border transition-colors ${
                stint.status === 'complete'
                  ? 'bg-acid-green/5 border-acid-green/20 cursor-pointer hover:bg-acid-green/10'
                  : stint.status === 'error'
                    ? 'bg-safety-red/5 border-safety-red/20'
                    : stint.status === 'processing'
                      ? 'bg-asphalt border-acid-green/10'
                      : 'bg-asphalt/50 border-steel/10'
              }`}
            >
              <div className="w-5 text-center">{statusIcon(stint.status)}</div>
              <div
                className="w-2.5 h-2.5 rounded-full"
                style={{ backgroundColor: driverColorMap[stint.driver_name] || '#555' }}
              />
              <span className="font-telemetry text-chalk text-sm">Stint {stint.stint_number}</span>
              <span className="text-steel text-xs font-body">{stint.driver_name}</span>
              <div className="ml-auto flex items-center gap-3">
                {stint.lap_count != null && (
                  <span className="text-steel text-xs font-telemetry">{stint.lap_count} laps</span>
                )}
                {stint.best_lap_s != null && (
                  <span className="text-acid-green text-xs font-telemetry">{formatTime(stint.best_lap_s)}</span>
                )}
                {stint.error && (
                  <span className="text-safety-red text-xs font-body truncate max-w-[200px]">{stint.error}</span>
                )}
                {stint.status === 'processing' && (
                  <span className="text-steel/60 text-xs font-body">analyzing...</span>
                )}
              </div>
            </div>
          ))}
        </div>

        {/* Aggregation phases */}
        {phase !== 'stints' && (
          <div className="mt-4 pt-4 border-t border-steel/10 space-y-2">
            <div className="flex items-center gap-3 px-4 py-2">
              <div className="w-5 text-center">
                {phase === 'drivers' ? statusIcon('processing') : statusIcon('complete')}
              </div>
              <span className="text-chalk text-sm font-body">Driver Reports</span>
            </div>
            <div className="flex items-center gap-3 px-4 py-2">
              <div className="w-5 text-center">
                {phase === 'team' ? statusIcon('processing') : phase === 'done' ? statusIcon('complete') : statusIcon('queued')}
              </div>
              <span className="text-chalk text-sm font-body">Team Race Report</span>
            </div>
          </div>
        )}

        {phase === 'done' && (
          <div className="mt-4 p-4 rounded-lg bg-acid-green/5 border border-acid-green/20">
            <p className="text-acid-green font-body text-sm font-medium">
              Endurance analysis complete! View the full report in the Endurance tab.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
