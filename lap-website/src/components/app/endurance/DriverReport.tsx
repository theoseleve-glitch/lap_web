'use client';

import Link from 'next/link';
import { StatCard } from '@/components/app';
import type { DriverReport as DriverReportType, Stint } from './types';

interface DriverReportProps {
  report: DriverReportType;
  onSelectStint: (stintNumber: number) => void;
  onBack: () => void;
}

function formatTime(s: number | null | undefined): string {
  if (s == null) return '--';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}

const conditionBadge: Record<string, string> = {
  dry: 'bg-acid-green/10 text-acid-green border-acid-green/20',
  damp: 'bg-cyan-400/10 text-cyan-400 border-cyan-400/20',
  wet: 'bg-blue-400/10 text-blue-400 border-blue-400/20',
  mixed: 'bg-marshal-yellow/10 text-marshal-yellow border-marshal-yellow/20',
};

export function DriverReport({ report, onSelectStint, onBack }: DriverReportProps) {
  return (
    <div className="space-y-6">
      {/* Back + Header */}
      <div>
        <button
          type="button"
          onClick={onBack}
          className="text-steel text-xs font-body hover:text-chalk mb-2 transition-colors"
        >
          &larr; Back to Team Report
        </button>
        <h2 className="text-xl font-monument text-chalk">{report.driver_name}</h2>
        <p className="text-steel text-xs font-body">
          {report.total_stints} stints &middot; {report.total_laps} laps
        </p>
      </div>

      {/* Driver Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard label="Best Lap" value={formatTime(report.best_lap_s)} accent="text-acid-green" />
        <StatCard label="Mean Pace" value={formatTime(report.mean_lap_s)} />
        <StatCard label="Inter-Stint CV" value={`${report.consistency_cv_pct?.toFixed(1) ?? '--'}%`} />
        <StatCard label="Total Laps" value={String(report.total_laps)} />
      </div>

      {/* Best Lap Progression */}
      {report.best_per_stint.length > 1 && (
        <div className="bg-concrete rounded-xl border border-steel/10 p-4">
          <h4 className="text-sm font-monument text-chalk mb-3">Best Lap Progression</h4>
          <div className="flex items-end gap-1 h-24">
            {report.best_per_stint.map((bp, i) => {
              const times = report.best_per_stint.map((b) => b.best_lap_s);
              const min = Math.min(...times);
              const max = Math.max(...times);
              const range = max - min || 1;
              const height = 20 + ((max - bp.best_lap_s) / range) * 60;
              return (
                <div key={bp.stint_number} className="flex-1 flex flex-col items-center gap-1">
                  <span className="text-[9px] font-telemetry text-acid-green">{formatTime(bp.best_lap_s)}</span>
                  <div
                    className="w-full bg-acid-green/30 rounded-t"
                    style={{ height: `${height}%` }}
                  />
                  <span className="text-[9px] font-telemetry text-steel">S{bp.stint_number}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Stint Cards */}
      <div className="bg-concrete rounded-xl border border-steel/10 p-6">
        <h3 className="text-lg font-monument text-chalk mb-4">Stints</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {report.stints.map((stint: Stint) => {
            const stintSessionId = (stint as any).session_id;
            const Wrapper = stintSessionId
              ? ({ children, ...props }: any) => <Link href={`/app/sessions/${stintSessionId}`} {...props}>{children}</Link>
              : ({ children, ...props }: any) => <button type="button" onClick={() => onSelectStint(stint.stint_number)} {...props}>{children}</button>;
            return (
            <Wrapper
              key={stint.stint_number}
              className="text-left bg-asphalt/50 rounded-lg border border-steel/10 p-4 hover:border-steel/30 transition-colors block"
            >
              <div className="flex items-center justify-between mb-2">
                <span className="font-telemetry text-chalk text-sm">Stint {stint.stint_number}</span>
                {stint.condition && (
                  <span className={`text-[10px] font-telemetry px-2 py-0.5 rounded border ${conditionBadge[stint.condition] || conditionBadge.dry}`}>
                    {stint.condition}
                  </span>
                )}
              </div>
              <div className="space-y-1 text-xs font-body">
                <div className="flex justify-between">
                  <span className="text-steel">Best</span>
                  <span className="text-acid-green font-telemetry">{formatTime(stint.best_lap_s)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-steel">Mean</span>
                  <span className="text-chalk font-telemetry">{formatTime(stint.mean_lap_s)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-steel">Laps</span>
                  <span className="text-chalk font-telemetry">{stint.lap_count} (L{stint.start_lap}–{stint.end_lap})</span>
                </div>
                {stint.consistency_cv_pct != null && (
                  <div className="flex justify-between">
                    <span className="text-steel">CV%</span>
                    <span className="text-chalk font-telemetry">{stint.consistency_cv_pct.toFixed(1)}%</span>
                  </div>
                )}
                {(stint as any).traffic_count > 0 && (
                  <div className="flex justify-between">
                    <span className="text-safety-red">Time Lost</span>
                    <span className="text-safety-red font-telemetry">{((stint as any).traffic_total_s || 0).toFixed(1)}s ({(stint as any).traffic_count} inc.)</span>
                  </div>
                )}
              </div>
            </Wrapper>
            );
          })}
        </div>
        <p className="text-steel/40 text-xs font-body mt-2">Click a stint for detailed lap-by-lap analysis</p>
      </div>

      {/* Driver Scores */}
      <div className="bg-concrete rounded-xl border border-steel/10 p-6">
        <h3 className="text-lg font-monument text-chalk mb-4">Driver Score</h3>
        <div className="space-y-3">
          {(['pace', 'consistency', 'robustness'] as const).map((key) => {
            const score = report.scores[key];
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
    </div>
  );
}
