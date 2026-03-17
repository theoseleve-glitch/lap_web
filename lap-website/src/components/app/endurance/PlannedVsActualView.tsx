'use client';

import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import { QueryError, SkeletonCardGrid } from '@/components/app';
import type { PlannedVsActualReport } from './types';

interface PlannedVsActualViewProps {
  raceId: number;
}

function formatDuration(s: number): string {
  const abs = Math.abs(s);
  const h = Math.floor(abs / 3600);
  const m = Math.floor((abs % 3600) / 60);
  const sec = Math.floor(abs % 60);
  if (h > 0) return `${h}:${m.toString().padStart(2, '0')}:${sec.toString().padStart(2, '0')}`;
  return `${m}:${sec.toString().padStart(2, '0')}`;
}

function formatLapTime(s: number | null | undefined): string {
  if (s == null) return '\u2014';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}

function formatDelta(seconds: number): string {
  const abs = Math.abs(seconds);
  const sign = seconds >= 0 ? '+' : '-';
  const h = Math.floor(abs / 3600);
  const m = Math.floor((abs % 3600) / 60);
  const s = Math.floor(abs % 60);

  if (h > 0) return `${sign}${h}h ${m.toString().padStart(2, '0')}m ${s.toString().padStart(2, '0')}s`;
  if (m > 0) return `${sign}${m}m ${s.toString().padStart(2, '0')}s`;
  return `${sign}${s}s`;
}

export function PlannedVsActualView({ raceId }: PlannedVsActualViewProps) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['race-strategy', raceId, 'planned-vs-actual'],
    queryFn: () => api.get<PlannedVsActualReport>(`/race-strategy/${raceId}/planned-vs-actual`),
  });

  if (isLoading) return <SkeletonCardGrid count={4} />;
  if (error || !data) return <QueryError message="Failed to load planned vs actual comparison." />;

  const { stints, summary } = data;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-concrete rounded-lg border border-steel/20 px-4 py-3">
        <h3 className="font-telemetry text-xs text-steel uppercase tracking-wider">
          Planned vs Actual Comparison
        </h3>
      </div>

      {/* Stint Comparison Table */}
      <div className="bg-concrete rounded-lg border border-steel/20 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-steel/20">
                <th scope="col" className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Stint</th>
                <th scope="col" className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Driver</th>
                <th scope="col" className="text-right px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Planned</th>
                <th scope="col" className="text-right px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Actual</th>
                <th scope="col" className="text-right px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Delta</th>
                <th scope="col" className="text-right px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Best Lap</th>
                <th scope="col" className="text-right px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Mean Lap</th>
                <th scope="col" className="text-right px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">CV%</th>
              </tr>
            </thead>
            <tbody>
              {stints.map((s) => {
                const delta = s.delta_duration_s ?? 0;
                const isUnder = delta < 0;
                const isOver = delta > 0;
                return (
                  <tr key={s.stint_order} className="border-b border-steel/10">
                    <td className="px-4 py-3 text-chalk font-telemetry text-sm">{s.stint_order}</td>
                    <td className="px-4 py-3 text-chalk font-body text-sm">{s.driver_name}</td>
                    <td className="px-4 py-3 text-chalk font-telemetry text-sm text-right">{formatDuration(s.planned.duration_s)}</td>
                    <td className="px-4 py-3 text-chalk font-telemetry text-sm text-right">{formatDuration(s.actual.duration_s ?? 0)}</td>
                    <td className="px-4 py-3 text-right">
                      <span
                        className={`inline-flex px-2 py-0.5 rounded text-xs font-telemetry ${
                          isUnder
                            ? 'text-green-400 bg-green-500/10'
                            : isOver
                              ? 'text-red-400 bg-red-500/10'
                              : 'text-steel'
                        }`}
                      >
                        {s.delta_duration_s != null ? formatDelta(s.delta_duration_s) : '\u2014'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right font-telemetry text-sm text-acid-green">{formatLapTime(s.actual.best_lap_s)}</td>
                    <td className="px-4 py-3 text-right font-telemetry text-sm text-chalk">{formatLapTime(s.actual.mean_lap_s)}</td>
                    <td className="px-4 py-3 text-right font-telemetry text-sm text-chalk">
                      {s.actual.consistency_cv_pct != null ? `${s.actual.consistency_cv_pct.toFixed(1)}%` : '\u2014'}
                    </td>
                  </tr>
                );
              })}

              {/* Summary row */}
              <tr className="border-t-2 border-steel/30 bg-asphalt/30">
                <td className="px-4 py-3 text-chalk font-telemetry text-sm font-medium" colSpan={2}>Total</td>
                <td className="px-4 py-3 text-chalk font-telemetry text-sm text-right font-medium">{formatDuration(summary.total_planned_s)}</td>
                <td className="px-4 py-3 text-chalk font-telemetry text-sm text-right font-medium">{formatDuration(summary.total_actual_s)}</td>
                <td className="px-4 py-3 text-right">
                  <span
                    className={`inline-flex px-2 py-0.5 rounded text-xs font-telemetry font-medium ${
                      (summary.delta_s ?? 0) < 0
                        ? 'text-green-400 bg-green-500/10'
                        : (summary.delta_s ?? 0) > 0
                          ? 'text-red-400 bg-red-500/10'
                          : 'text-steel'
                    }`}
                  >
                    {summary.delta_s != null ? formatDelta(summary.delta_s) : '\u2014'}
                  </span>
                </td>
                <td colSpan={3} />
              </tr>

              {stints.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-4 py-6 text-center text-steel font-body text-sm">
                    No stint comparison data available.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Driver Breakdown */}
      {Object.keys(summary.driver_deltas).length > 0 && (
        <div className="bg-concrete rounded-lg border border-steel/20 overflow-hidden">
          <div className="px-4 py-3 border-b border-steel/20">
            <h3 className="font-telemetry text-xs text-steel uppercase tracking-wider">Driver Breakdown</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-steel/20">
                  <th scope="col" className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Driver</th>
                  <th scope="col" className="text-right px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Planned</th>
                  <th scope="col" className="text-right px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Actual</th>
                  <th scope="col" className="text-right px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Delta</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(summary.driver_deltas).map(([driver, d]) => {
                  const isUnder = d.delta_s < 0;
                  const isOver = d.delta_s > 0;
                  return (
                    <tr key={driver} className="border-b border-steel/10">
                      <td className="px-4 py-3 text-chalk font-body text-sm">{driver}</td>
                      <td className="px-4 py-3 text-chalk font-telemetry text-sm text-right">{formatDuration(d.planned_s)}</td>
                      <td className="px-4 py-3 text-chalk font-telemetry text-sm text-right">{formatDuration(d.actual_s)}</td>
                      <td className="px-4 py-3 text-right">
                        <span
                          className={`inline-flex px-2 py-0.5 rounded text-xs font-telemetry ${
                            isUnder
                              ? 'text-green-400 bg-green-500/10'
                              : isOver
                                ? 'text-red-400 bg-red-500/10'
                                : 'text-steel'
                          }`}
                        >
                          {formatDelta(d.delta_s)}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
