'use client';

import { useMemo } from 'react';
import { StatCard } from '@/components/app';
import type { TeamReport as TeamReportType, DriverReport, Stint } from './types';
import { DRIVER_COLORS } from './types';
import { StrategyTimeline } from './StrategyTimeline';

interface TeamReportProps {
  report: TeamReportType;
  stints: Stint[];
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

  // Compute derived race metrics
  const raceMetrics = useMemo(() => {
    const overallBest = drivers.length > 0 ? Math.min(...drivers.map((d) => d.best_lap_s ?? Infinity)) : null;
    const overallBestDriver = drivers.find((d) => d.best_lap_s === overallBest);

    // Pit efficiency: total pit time vs total race time
    const pitStints = stints.filter((s) => s.pit_lap_time_s != null && s.pit_lap_time_s > 0);
    const totalPitTime = pitStints.reduce((sum, s) => sum + (s.pit_lap_time_s || 0), 0);
    // Subtract median lap from pit laps (the "extra" time is the actual pit stop duration)
    const medianLap = drivers.length > 0
      ? drivers.reduce((sum, d) => sum + (d.mean_lap_s || 0), 0) / drivers.length
      : 50;
    const actualPitTime = pitStints.reduce((sum, s) => sum + Math.max(0, (s.pit_lap_time_s || 0) - medianLap), 0);
    const pitCount = pitStints.length;
    const avgPitTime = pitCount > 0 ? actualPitTime / pitCount : 0;

    // Pace delta between drivers
    const sortedByBest = [...drivers].sort((a, b) => (a.best_lap_s ?? Infinity) - (b.best_lap_s ?? Infinity));
    const paceDelta = sortedByBest.length >= 2
      ? (sortedByBest[1].best_lap_s ?? 0) - (sortedByBest[0].best_lap_s ?? 0)
      : 0;

    return {
      overallBest,
      overallBestDriver: overallBestDriver?.driver_name ?? '--',
      totalPitTime: actualPitTime,
      pitCount,
      avgPitTime,
      paceDelta,
      sortedByBest,
    };
  }, [drivers, stints]);

  return (
    <div className="space-y-6">
      {/* Race Overview Header */}
      <div className="bg-concrete rounded-xl border border-steel/10 p-6">
        <h2 className="text-xl font-monument text-chalk mb-4">Race Report</h2>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          <StatCard label="Total Laps" value={String(report.total_laps)} />
          <StatCard label="Race Time" value={formatDuration(report.total_time_s)} />
          <StatCard label="Stints" value={String(report.total_stints)} />
          <StatCard label="Pit Stops" value={String(raceMetrics.pitCount)} />
          <StatCard label="Race Best" value={formatTime(raceMetrics.overallBest)} accent="text-acid-green" />
          <StatCard label="Avg Pit Stop" value={raceMetrics.avgPitTime > 0 ? `${raceMetrics.avgPitTime.toFixed(1)}s` : '--'} />
        </div>
      </div>

      {/* Strategy Timeline */}
      <StrategyTimeline stints={stints} drivers={report.drivers} />

      {/* Driver Head-to-Head Comparison */}
      <div className="bg-concrete rounded-xl border border-steel/10 p-6">
        <h3 className="text-lg font-monument text-chalk mb-4">Driver Comparison</h3>

        {/* Visual bar comparison for key metrics */}
        {drivers.length >= 2 && (
          <div className="space-y-4 mb-6">
            {/* Best Lap Comparison */}
            <div>
              <span className="text-xs font-telemetry text-steel uppercase tracking-wider">Best Lap</span>
              <div className="mt-1 space-y-1">
                {raceMetrics.sortedByBest.map((d, idx) => {
                  const fastest = raceMetrics.sortedByBest[0].best_lap_s ?? 1;
                  const pct = fastest && d.best_lap_s ? (fastest / d.best_lap_s) * 100 : 0;
                  const delta = d.best_lap_s && fastest ? d.best_lap_s - fastest : 0;
                  return (
                    <div key={d.driver_name} className="flex items-center gap-2">
                      <span className="text-xs font-body text-steel w-24 truncate">{d.driver_name}</span>
                      <div className="flex-1 h-4 bg-asphalt rounded overflow-hidden relative">
                        <div
                          className="h-full rounded"
                          style={{ width: `${pct}%`, backgroundColor: DRIVER_COLORS[drivers.indexOf(d) % DRIVER_COLORS.length], opacity: 0.6 }}
                        />
                        <span className="absolute inset-0 flex items-center px-2 text-[10px] font-telemetry text-chalk">
                          {formatTime(d.best_lap_s)} {delta > 0 ? `(+${delta.toFixed(3)})` : ''}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Mean Pace Comparison */}
            <div>
              <span className="text-xs font-telemetry text-steel uppercase tracking-wider">Mean Pace</span>
              <div className="mt-1 space-y-1">
                {[...drivers].sort((a, b) => (a.mean_lap_s ?? Infinity) - (b.mean_lap_s ?? Infinity)).map((d, idx) => {
                  const fastest = Math.min(...drivers.map((dr) => dr.mean_lap_s ?? Infinity));
                  const pct = fastest && d.mean_lap_s ? (fastest / d.mean_lap_s) * 100 : 0;
                  const delta = d.mean_lap_s && fastest ? d.mean_lap_s - fastest : 0;
                  return (
                    <div key={d.driver_name} className="flex items-center gap-2">
                      <span className="text-xs font-body text-steel w-24 truncate">{d.driver_name}</span>
                      <div className="flex-1 h-4 bg-asphalt rounded overflow-hidden relative">
                        <div
                          className="h-full rounded"
                          style={{ width: `${pct}%`, backgroundColor: DRIVER_COLORS[drivers.indexOf(d) % DRIVER_COLORS.length], opacity: 0.6 }}
                        />
                        <span className="absolute inset-0 flex items-center px-2 text-[10px] font-telemetry text-chalk">
                          {formatTime(d.mean_lap_s)} {delta > 0 ? `(+${delta.toFixed(3)})` : ''}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Consistency (CV%) — lower is better */}
            <div>
              <span className="text-xs font-telemetry text-steel uppercase tracking-wider">Consistency (lower = better)</span>
              <div className="mt-1 space-y-1">
                {[...drivers].sort((a, b) => (a.consistency_cv_pct ?? Infinity) - (b.consistency_cv_pct ?? Infinity)).map((d) => {
                  const cv = d.consistency_cv_pct ?? 0;
                  const barPct = Math.min(cv * 10, 100); // 10% CV fills bar
                  return (
                    <div key={d.driver_name} className="flex items-center gap-2">
                      <span className="text-xs font-body text-steel w-24 truncate">{d.driver_name}</span>
                      <div className="flex-1 h-4 bg-asphalt rounded overflow-hidden relative">
                        <div
                          className="h-full rounded"
                          style={{
                            width: `${barPct}%`,
                            backgroundColor: cv < 2 ? '#B6FF2E' : cv < 4 ? '#FFD400' : '#FF6A00',
                            opacity: 0.6,
                          }}
                        />
                        <span className="absolute inset-0 flex items-center px-2 text-[10px] font-telemetry text-chalk">
                          {cv.toFixed(2)}%
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        )}

        {/* Full comparison table */}
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
              {drivers.map((driver: DriverReport, idx: number) => {
                const isOverallBest = driver.best_lap_s === raceMetrics.overallBest;
                return (
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
                        {isOverallBest && <span className="text-[9px] bg-acid-green/20 text-acid-green px-1.5 py-0.5 rounded font-telemetry">FASTEST</span>}
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
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="text-steel/40 text-xs font-body mt-2">Click a driver to see their detailed report</p>
      </div>

      {/* Pit Stop Analysis */}
      {raceMetrics.pitCount > 0 && (
        <div className="bg-concrete rounded-xl border border-steel/10 p-6">
          <h3 className="text-lg font-monument text-chalk mb-4">Pit Stops</h3>
          <div className="grid grid-cols-3 gap-4 mb-4">
            <div className="text-center">
              <p className="text-2xl font-monument text-chalk">{raceMetrics.pitCount}</p>
              <p className="text-xs font-body text-steel">Pit Stops</p>
            </div>
            <div className="text-center">
              <p className="text-2xl font-monument text-pit-orange">{raceMetrics.avgPitTime.toFixed(1)}s</p>
              <p className="text-xs font-body text-steel">Avg Pit Duration</p>
            </div>
            <div className="text-center">
              <p className="text-2xl font-monument text-chalk">{formatDuration(raceMetrics.totalPitTime)}</p>
              <p className="text-xs font-body text-steel">Total Pit Time</p>
            </div>
          </div>
          <div className="space-y-1">
            {stints.filter((s) => s.pit_lap_time_s != null && s.pit_lap_time_s > 0).map((s, i) => {
              const medianLap = drivers.length > 0
                ? drivers.reduce((sum, d) => sum + (d.mean_lap_s || 0), 0) / drivers.length
                : 50;
              const pitDuration = Math.max(0, (s.pit_lap_time_s || 0) - medianLap);
              return (
                <div key={i} className="flex items-center gap-3 text-xs font-body">
                  <span className="text-steel w-16">Pit {i + 1}</span>
                  <span className="text-chalk font-telemetry w-16">After S{s.stint_number}</span>
                  <div className="flex-1 h-3 bg-asphalt rounded overflow-hidden">
                    <div
                      className="h-full bg-pit-orange/50 rounded"
                      style={{ width: `${Math.min((pitDuration / 300) * 100, 100)}%` }}
                    />
                  </div>
                  <span className="text-pit-orange font-telemetry w-16 text-right">{pitDuration.toFixed(1)}s</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Team Scores */}
      <div className="bg-concrete rounded-xl border border-steel/10 p-6">
        <h3 className="text-lg font-monument text-chalk mb-4">Team Score</h3>
        <div className="space-y-3">
          {(['pace', 'consistency', 'robustness'] as const).map((key) => {
            const score = report.scores[key];
            const max = 25;
            const pct = (score / max) * 100;
            const colors = { pace: '#B6FF2E', consistency: '#00d4ff', robustness: '#FF6A00' };
            const labels = { pace: 'Pace', consistency: 'Consistency', robustness: 'Robustness' };
            return (
              <div key={key} className="flex items-center gap-3">
                <span className="text-xs font-body text-steel w-24">{labels[key]}</span>
                <div className="flex-1 h-2 bg-asphalt rounded-full overflow-hidden">
                  <div className="h-full rounded-full transition-all duration-500" style={{ width: `${pct}%`, backgroundColor: colors[key] }} />
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
