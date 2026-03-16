'use client';

import { StatCard } from '@/components/app';
import type { TeamReport as TeamReportType, DriverReport } from './types';
import { DRIVER_COLORS } from './types';
import { StrategyTimeline } from './StrategyTimeline';

interface TeamReportProps {
  report: TeamReportType;
  stints: import('./types').Stint[];
  onSelectDriver: (name: string) => void;
}

function formatTime(s: number | null | undefined): string {
  if (s == null) return '--';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}

function formatDuration(s: number | null): string {
  if (s == null) return '--';
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  if (h > 0) return `${h}h ${m}m ${sec}s`;
  return `${m}m ${sec}s`;
}

export function TeamReport({ report, stints, onSelectDriver }: TeamReportProps) {
  const drivers = report.driver_comparison;

  return (
    <div className="space-y-6">
      {/* Race Summary */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard label="Total Laps" value={String(report.total_laps)} />
        <StatCard label="Race Time" value={formatDuration(report.total_time_s)} />
        <StatCard label="Stints" value={String(report.total_stints)} />
        <StatCard label="Drivers" value={String(report.drivers.length)} />
      </div>

      {/* Strategy Timeline */}
      <StrategyTimeline stints={stints} drivers={report.drivers} />

      {/* Driver Comparison Table */}
      <div className="bg-concrete rounded-xl border border-steel/10 p-6">
        <h3 className="text-lg font-monument text-chalk mb-4">Driver Comparison</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm font-body">
            <thead>
              <tr className="text-steel border-b border-steel/10 text-xs">
                <th className="py-2 text-left">Driver</th>
                <th className="py-2 text-right">Stints</th>
                <th className="py-2 text-right">Laps</th>
                <th className="py-2 text-right">Best Lap</th>
                <th className="py-2 text-right">Mean</th>
                <th className="py-2 text-right">CV%</th>
                <th className="py-2 text-right">Pace</th>
                <th className="py-2 text-right">Consistency</th>
                <th className="py-2 text-right">Robustness</th>
              </tr>
            </thead>
            <tbody>
              {drivers.map((driver: DriverReport, idx: number) => (
                <tr
                  key={driver.driver_name}
                  onClick={() => onSelectDriver(driver.driver_name)}
                  className="border-b border-steel/5 text-chalk hover:bg-asphalt/50 cursor-pointer transition-colors"
                >
                  <td className="py-3">
                    <div className="flex items-center gap-2">
                      <div
                        className="w-2.5 h-2.5 rounded-full"
                        style={{ backgroundColor: DRIVER_COLORS[idx % DRIVER_COLORS.length] }}
                      />
                      <span className="font-medium">{driver.driver_name}</span>
                    </div>
                  </td>
                  <td className="py-3 text-right font-telemetry">{driver.total_stints}</td>
                  <td className="py-3 text-right font-telemetry">{driver.total_laps}</td>
                  <td className="py-3 text-right font-telemetry text-acid-green">{formatTime(driver.best_lap_s)}</td>
                  <td className="py-3 text-right font-telemetry">{formatTime(driver.mean_lap_s)}</td>
                  <td className="py-3 text-right font-telemetry">{driver.consistency_cv_pct?.toFixed(1) ?? '--'}%</td>
                  <td className="py-3 text-right font-telemetry">{driver.scores.pace.toFixed(1)}</td>
                  <td className="py-3 text-right font-telemetry">{driver.scores.consistency.toFixed(1)}</td>
                  <td className="py-3 text-right font-telemetry">{driver.scores.robustness.toFixed(1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-steel/40 text-xs font-body mt-2">Click a driver to see their detailed report</p>
      </div>

      {/* Team Scores */}
      <div className="bg-concrete rounded-xl border border-steel/10 p-6">
        <h3 className="text-lg font-monument text-chalk mb-4">Team Score</h3>
        <div className="space-y-3">
          {(['pace', 'consistency', 'robustness'] as const).map((key) => {
            const score = report.scores[key];
            const max = 25;
            const pct = (score / max) * 100;
            const colors = {
              pace: '#B6FF2E',
              consistency: '#00d4ff',
              robustness: '#FF6A00',
            };
            return (
              <div key={key} className="flex items-center gap-3">
                <span className="text-xs font-body text-steel w-24 capitalize">{key}</span>
                <div className="flex-1 h-2 bg-asphalt rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all duration-500"
                    style={{ width: `${pct}%`, backgroundColor: colors[key] }}
                  />
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
