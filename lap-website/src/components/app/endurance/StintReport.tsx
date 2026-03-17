'use client';

import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import { StatCard, QueryError, SkeletonCardGrid } from '@/components/app';
import type { Stint } from './types';

interface StintReportProps {
  sessionId: string;
  stint: Stint;
  onBack: () => void;
}

interface LapRow {
  lap_number: number;
  lap_time_s: number | null;
  speed_mean_mps: number | null;
  speed_max_mps: number | null;
  is_valid: boolean;
  is_best: boolean;
  invalid_reason: string | null;
}

function formatTime(s: number | null | undefined): string {
  if (s == null) return '--';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}

function mpsToKmh(mps: number): string {
  return (mps * 3.6).toFixed(1);
}

const conditionBadge: Record<string, string> = {
  dry: 'bg-acid-green/10 text-acid-green border-acid-green/20',
  damp: 'bg-cyan-400/10 text-cyan-400 border-cyan-400/20',
  wet: 'bg-blue-400/10 text-blue-400 border-blue-400/20',
  mixed: 'bg-marshal-yellow/10 text-marshal-yellow border-marshal-yellow/20',
};

export function StintReport({ sessionId, stint, onBack }: StintReportProps) {
  const { data: lapsRes, isLoading, error } = useQuery({
    queryKey: ['laps', sessionId],
    queryFn: () => api.get<{ laps: LapRow[] }>(`/sessions/${sessionId}/laps`),
  });

  const allLaps = lapsRes?.laps || [];
  const stintLaps = allLaps.filter(
    (l) => l.lap_number >= stint.start_lap && l.lap_number <= stint.end_lap
  );
  const validLaps = stintLaps.filter((l) => l.is_valid && l.lap_time_s && l.lap_time_s > 0);
  const bestTime = validLaps.length > 0 ? Math.min(...validLaps.map((l) => l.lap_time_s!)) : null;

  return (
    <div className="space-y-6">
      {/* Back + Header */}
      <div>
        <button
          type="button"
          onClick={onBack}
          className="text-steel text-xs font-body hover:text-chalk mb-2 transition-colors"
        >
          &larr; Back to Driver Report
        </button>
        <div className="flex items-center gap-3">
          <h2 className="text-xl font-monument text-chalk">Stint {stint.stint_number}</h2>
          {stint.condition && (
            <span className={`text-xs font-telemetry px-2 py-0.5 rounded border ${conditionBadge[stint.condition] || conditionBadge.dry}`}>
              {stint.condition}
            </span>
          )}
          {stint.driver_name && (
            <span className="text-steel text-xs font-body">{stint.driver_name}</span>
          )}
        </div>
        <p className="text-steel text-xs font-body">
          Laps {stint.start_lap}–{stint.end_lap} ({stint.lap_count} laps)
        </p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard label="Best Lap" value={formatTime(stint.best_lap_s)} accent="text-acid-green" />
        <StatCard label="Mean Pace" value={formatTime(stint.mean_lap_s)} />
        <StatCard label="CV%" value={stint.consistency_cv_pct != null ? `${stint.consistency_cv_pct.toFixed(1)}%` : '--'} />
        <StatCard label="Pace Fade" value={stint.pace_fade_pct != null ? `${stint.pace_fade_pct.toFixed(1)}%` : '--'} />
      </div>

      {/* Traffic Time Loss */}
      {((stint as any).traffic_count > 0) && (
        <div className="bg-concrete rounded-xl border border-safety-red/20 p-4">
          <div className="flex items-center gap-3">
            <span className="text-safety-red font-monument text-lg">{(stint as any).traffic_count}</span>
            <span className="text-steel text-xs font-body">traffic incidents</span>
            <span className="text-safety-red font-telemetry text-sm ml-auto">{((stint as any).traffic_total_s || 0).toFixed(1)}s lost</span>
          </div>
        </div>
      )}

      {/* Score bars */}
      {stint.scores && (
        <div className="bg-concrete rounded-xl border border-steel/10 p-6">
          <h3 className="text-lg font-monument text-chalk mb-4">Stint Score</h3>
          <div className="space-y-3">
            {(['pace', 'consistency', 'robustness'] as const).map((key) => {
              const score = stint.scores![key];
              const max = 25;
              const pct = (score / max) * 100;
              const colors = { pace: '#B6FF2E', consistency: '#00d4ff', robustness: '#FF6A00' };
              return (
                <div key={key} className="flex items-center gap-3">
                  <span className="text-xs font-body text-steel w-24 capitalize">{key}</span>
                  <div className="flex-1 h-2 bg-asphalt rounded-full overflow-hidden">
                    <div className="h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: colors[key] }} />
                  </div>
                  <span className="text-xs font-telemetry text-chalk w-12 text-right">{score.toFixed(1)}/{max}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Lap Table */}
      <div className="bg-concrete rounded-xl border border-steel/10 p-6">
        <h3 className="text-lg font-monument text-chalk mb-4">Lap Data</h3>
        {isLoading ? (
          <SkeletonCardGrid count={3} />
        ) : error ? (
          <QueryError message="Failed to load laps" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs font-body">
              <thead>
                <tr className="text-steel border-b border-steel/10">
                  <th className="py-2 text-left">Lap</th>
                  <th className="py-2 text-right">Time</th>
                  <th className="py-2 text-right">Delta</th>
                  <th className="py-2 text-right">Avg Speed</th>
                  <th className="py-2 text-right">Max Speed</th>
                  <th className="py-2 text-left">Status</th>
                </tr>
              </thead>
              <tbody>
                {stintLaps.map((lap) => {
                  const isBest = lap.lap_time_s === bestTime && lap.is_valid;
                  const delta = bestTime && lap.lap_time_s && lap.is_valid
                    ? lap.lap_time_s - bestTime
                    : null;
                  return (
                    <tr
                      key={lap.lap_number}
                      className={`border-b border-steel/5 ${
                        isBest ? 'text-acid-green' : lap.is_valid ? 'text-chalk' : 'text-steel/40'
                      }`}
                    >
                      <td className="py-2 font-telemetry">
                        {lap.lap_number}
                        {isBest && <span className="ml-1 text-[9px] bg-acid-green/20 px-1 rounded">Best</span>}
                      </td>
                      <td className="py-2 text-right font-telemetry">{formatTime(lap.lap_time_s)}</td>
                      <td className="py-2 text-right font-telemetry">
                        {delta != null && delta > 0 ? `+${delta.toFixed(3)}` : delta === 0 ? '—' : ''}
                      </td>
                      <td className="py-2 text-right font-telemetry">
                        {lap.speed_mean_mps != null ? `${mpsToKmh(lap.speed_mean_mps)} km/h` : '--'}
                      </td>
                      <td className="py-2 text-right font-telemetry">
                        {lap.speed_max_mps != null ? `${mpsToKmh(lap.speed_max_mps)} km/h` : '--'}
                      </td>
                      <td className="py-2">
                        {lap.is_valid ? (
                          <span className="text-acid-green/60">Valid</span>
                        ) : (
                          <span className="text-safety-red/60">{lap.invalid_reason || 'Invalid'}</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
