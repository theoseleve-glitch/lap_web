'use client';

import Link from 'next/link';
import { StatCard } from '@/components/app';
import type { Stint } from './types';

interface StintReportProps {
  sessionId: string;
  stint: Stint;
  onBack: () => void;
  trackName?: string | null;
  kartName?: string | null;
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

export function StintReport({ stint, onBack, trackName, kartName }: StintReportProps) {
  const trafficLosses = (stint as any).traffic_losses || [];
  const trafficTotal = (stint as any).traffic_total_s || 0;
  const trafficCount = (stint as any).traffic_count || 0;

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
        <div className="flex items-center gap-3 flex-wrap">
          <p className="text-steel text-xs font-body">
            Laps {stint.start_lap}–{stint.end_lap} ({stint.lap_count} laps)
          </p>
          {trackName && <span className="text-steel/60 text-xs font-body">{trackName}</span>}
          {kartName && <span className="text-steel/60 text-xs font-body">{kartName}</span>}
          {(stint as any).session_id && (
            <Link
              href={`/app/sessions/${(stint as any).session_id}`}
              className="text-[10px] font-telemetry text-acid-green/70 hover:text-acid-green border border-acid-green/20 px-2 py-0.5 rounded transition-colors"
            >
              View Charts &rarr;
            </Link>
          )}
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard label="Best Lap" value={formatTime(stint.best_lap_s)} accent="text-acid-green" />
        <StatCard label="Mean Pace" value={formatTime(stint.mean_lap_s)} />
        <StatCard label="CV%" value={stint.consistency_cv_pct != null ? `${stint.consistency_cv_pct.toFixed(1)}%` : '--'} />
        <StatCard label="Pace Fade" value={(stint as any).pace_fade_pct != null ? `${(stint as any).pace_fade_pct.toFixed(1)}%` : '--'} />
      </div>

      {/* Traffic Time Loss Events */}
      {trafficCount > 0 && (
        <div className="bg-concrete rounded-xl border border-safety-red/20 p-6">
          <h3 className="text-lg font-monument text-chalk mb-2">Traffic / Incidents</h3>
          <div className="grid grid-cols-2 gap-4 mb-4">
            <div className="text-center">
              <p className="text-2xl font-monument text-safety-red">{trafficCount}</p>
              <p className="text-xs font-body text-steel">Incidents</p>
            </div>
            <div className="text-center">
              <p className="text-2xl font-monument text-safety-red">{trafficTotal.toFixed(1)}s</p>
              <p className="text-xs font-body text-steel">Total Time Lost</p>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs font-body">
              <thead>
                <tr className="text-steel border-b border-steel/10">
                  <th className="py-2 text-left">#</th>
                  <th className="py-2 text-right">Lap Time</th>
                  <th className="py-2 text-right">Neighbor Avg</th>
                  <th className="py-2 text-right">Time Lost</th>
                </tr>
              </thead>
              <tbody>
                {trafficLosses.map((tl: any, i: number) => (
                  <tr key={i} className="border-b border-steel/5 text-chalk">
                    <td className="py-2 font-telemetry text-safety-red">{i + 1}</td>
                    <td className="py-2 text-right font-telemetry">{formatTime(tl.lap_time_s)}</td>
                    <td className="py-2 text-right font-telemetry text-steel">{formatTime(tl.neighbor_mean_s)}</td>
                    <td className="py-2 text-right font-telemetry text-safety-red">+{tl.time_lost_s?.toFixed(1)}s</td>
                  </tr>
                ))}
              </tbody>
            </table>
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
    </div>
  );
}
