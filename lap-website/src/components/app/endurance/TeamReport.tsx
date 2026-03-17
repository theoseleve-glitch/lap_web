'use client';

import { useMemo } from 'react';
import { StatCard } from '@/components/app';
import type { TeamReport as TeamReportType, DriverReport, Stint } from './types';
import { DRIVER_COLORS } from './types';
import { StrategyTimeline } from './StrategyTimeline';

interface TeamReportProps {
  report: TeamReportType;
  stints: Stint[];
  pitThreshold?: number;
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

export function TeamReport({ report, stints, pitThreshold = 30, onSelectDriver }: TeamReportProps) {
  const drivers = report.driver_comparison;

  // Compute derived race metrics
  const raceMetrics = useMemo(() => {
    const overallBest = drivers.length > 0 ? Math.min(...drivers.map((d) => d.best_lap_s ?? Infinity)) : null;
    const overallBestDriver = drivers.find((d) => d.best_lap_s === overallBest);

    // Pit stops: only stints that have a pit_lap_number (not the last stint)
    const pitStints = stints.filter((s) => s.pit_lap_number != null && s.pit_lap_time_s != null && s.pit_lap_time_s > 0);
    const pitCount = pitStints.length;
    // Pit duration = pit_lap_time - stint's mean_lap (the "extra" time beyond a normal lap)
    const getPitDuration = (s: Stint) => {
      const meanLap = s.mean_lap_s ?? (s.best_lap_s ?? 0);
      return Math.ceil(Math.max(0, (s.pit_lap_time_s ?? 0) - meanLap));
    };
    const totalPitTime = pitStints.reduce((sum, s) => sum + getPitDuration(s), 0);
    const avgPitTime = pitCount > 0 ? totalPitTime / pitCount : 0;

    // Pace delta between drivers
    const sortedByBest = [...drivers].sort((a, b) => (a.best_lap_s ?? Infinity) - (b.best_lap_s ?? Infinity));
    const paceDelta = sortedByBest.length >= 2
      ? (sortedByBest[1].best_lap_s ?? 0) - (sortedByBest[0].best_lap_s ?? 0)
      : 0;

    return {
      overallBest,
      overallBestDriver: overallBestDriver?.driver_name ?? '--',
      totalPitTime,
      pitCount,
      avgPitTime,
      getPitDuration,
      paceDelta,
      sortedByBest,
    };
  }, [drivers, stints]);

  return (
    <div className="space-y-6">
      {/* Total Time Loss — hero metric */}
      {((report as any).total_time_loss_s > 0) && (
        <div className="bg-concrete rounded-xl border border-safety-red/30 p-6">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-xl font-monument text-chalk">Time Lost</h2>
            <span className="text-3xl font-monument text-safety-red">{((report as any).total_time_loss_s).toFixed(1)}s</span>
          </div>
          <div className="flex gap-6 text-sm font-telemetry mb-4">
            {(report as any).traffic_total_s > 0 && (
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-safety-red" />
                <span className="text-steel">Traffic</span>
                <span className="text-chalk">{((report as any).traffic_total_s).toFixed(1)}s</span>
                <span className="text-steel/50">({(report as any).traffic_count} inc.)</span>
              </div>
            )}
            {(report as any).pit_time_loss_s > 0 && (
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-pit-orange" />
                <span className="text-steel">Slow Pits</span>
                <span className="text-chalk">{((report as any).pit_time_loss_s).toFixed(1)}s</span>
                <span className="text-steel/50">({(report as any).n_pits} × {Math.ceil(((report as any).avg_pit_s || 0) - ((report as any).pit_threshold_s || 0))}s excess)</span>
              </div>
            )}
          </div>
          {/* Coaching tips */}
          {((report as any).coaching as any[])?.map((tip: any, i: number) => (
            <div key={i} className={`text-xs font-body p-2.5 rounded-lg mb-1.5 border ${
              tip.priority === 'high' ? 'bg-safety-red/5 border-safety-red/20 text-chalk' :
              tip.priority === 'medium' ? 'bg-marshal-yellow/5 border-marshal-yellow/20 text-chalk' :
              'bg-asphalt/50 border-steel/10 text-steel'
            }`}>
              {tip.message}
            </div>
          ))}
        </div>
      )}

      {/* Race Overview Header */}
      <div className="bg-concrete rounded-xl border border-steel/10 p-6">
        <h2 className="text-xl font-monument text-chalk mb-4">Race Report</h2>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          <StatCard label="Total Laps" value={String(report.total_laps)} />
          <StatCard label="Race Time" value={formatDuration(report.total_time_s)} />
          <StatCard label="Stints" value={String(report.total_stints)} />
          <StatCard label="Pit Stops" value={String((report as any).n_pits ?? raceMetrics.pitCount)} />
          <StatCard label="Race Best" value={formatTime(raceMetrics.overallBest)} accent="text-acid-green" />
          <StatCard label="Avg Pit Stop" value={(report as any).avg_pit_s > 0 ? `${Math.ceil((report as any).avg_pit_s)}s` : raceMetrics.avgPitTime > 0 ? `${Math.ceil(raceMetrics.avgPitTime)}s` : '--'} />
        </div>
      </div>

      {/* Strategy Timeline */}
      <StrategyTimeline stints={stints} drivers={report.drivers} />

      {/* Driver Head-to-Head Comparison */}
      <div className="bg-concrete rounded-xl border border-steel/10 p-6">
        <h3 className="text-lg font-monument text-chalk mb-4">Driver Comparison</h3>

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
                <th className="py-2 text-right">Execution</th>
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
                    <td className="py-3 text-right font-telemetry">{((driver.scores as any).execution ?? 0).toFixed(1)}</td>
                    <td className="py-3 text-right font-telemetry">{driver.scores.robustness.toFixed(1)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="text-steel/40 text-xs font-body mt-2">Click a driver to see their detailed report</p>
      </div>

      {/* Pit Stop Analysis — uses backend pit_stops when available, else falls back to frontend calc */}
      {((report as any).pit_stops?.length > 0 || raceMetrics.pitCount > 0) && (() => {
        const backendPits: { stint_number: number; driver_name: string; pit_duration_s: number }[] = (report as any).pit_stops || [];
        const pits = backendPits.length > 0
          ? backendPits
          : stints
              .filter((s) => s.pit_lap_number != null && s.pit_lap_time_s != null && s.pit_lap_time_s > 0)
              .map((s) => ({
                stint_number: s.stint_number,
                driver_name: s.driver_name ?? '',
                pit_duration_s: raceMetrics.getPitDuration(s),
              }));
        const nPits = pits.length;
        const avgPit = nPits > 0 ? pits.reduce((sum, p) => sum + p.pit_duration_s, 0) / nPits : 0;
        const totalPit = pits.reduce((sum, p) => sum + p.pit_duration_s, 0);

        return (
        <div className="bg-concrete rounded-xl border border-steel/10 p-6">
          <h3 className="text-lg font-monument text-chalk mb-4">Pit Stops</h3>
          <div className="grid grid-cols-3 gap-4 mb-4">
            <div className="text-center">
              <p className="text-2xl font-monument text-chalk">{nPits}</p>
              <p className="text-xs font-body text-steel">Pit Stops</p>
            </div>
            <div className="text-center">
              <p className="text-2xl font-monument text-pit-orange">{Math.ceil(avgPit)}s</p>
              <p className="text-xs font-body text-steel">Avg Pit Duration</p>
            </div>
            <div className="text-center">
              <p className="text-2xl font-monument text-chalk">{formatDuration(totalPit)}</p>
              <p className="text-xs font-body text-steel">Total Pit Time</p>
            </div>
          </div>
          <div className="space-y-2">
            {pits.map((p, i) => {
              const pitTime = p.pit_duration_s;
              // Grade: compare actual pit duration vs threshold
              const ratio = pitThreshold > 0 ? pitTime / pitThreshold : 1;
              const grade = ratio <= 1.1 ? 'gold' : ratio <= 1.5 ? 'silver' : ratio <= 2.0 ? 'bronze' : 'over';
              const gradeColor = {
                gold: 'text-gold bg-gold/10 border-gold/30',
                silver: 'text-steel bg-steel/10 border-steel/30',
                bronze: 'text-pit-orange bg-pit-orange/10 border-pit-orange/30',
                over: 'text-safety-red bg-safety-red/10 border-safety-red/30',
              }[grade];
              const gradeLabel = {
                gold: 'Excellent',
                silver: 'Good',
                bronze: 'Slow',
                over: 'Too slow',
              }[grade];
              const barColor = {
                gold: '#FFD400',
                silver: '#8B8B8B',
                bronze: '#FF6A00',
                over: '#FF3B6B',
              }[grade];
              return (
                <div key={i} className="flex items-center gap-3 text-xs font-body">
                  <span className="text-steel w-16">Pit {i + 1}</span>
                  <span className="text-chalk font-telemetry w-20">After S{p.stint_number}</span>
                  <div className="flex-1 h-4 bg-asphalt rounded overflow-hidden relative">
                    <div
                      className="h-full rounded"
                      style={{ width: `${Math.min((pitTime / (pitThreshold * 3)) * 100, 100)}%`, backgroundColor: barColor, opacity: 0.6 }}
                    />
                    {/* Threshold marker */}
                    <div
                      className="absolute top-0 bottom-0 w-px bg-gold/60"
                      style={{ left: `${Math.min((1 / 3) * 100, 100)}%` }}
                      title={`Target: ${pitThreshold}s`}
                    />
                  </div>
                  <span className="font-telemetry w-12 text-right" style={{ color: barColor }}>{Math.ceil(pitTime)}s</span>
                  <span className={`text-[9px] font-telemetry px-1.5 py-0.5 rounded border ${gradeColor}`}>
                    {gradeLabel}
                  </span>
                </div>
              );
            })}
            <p className="text-steel/40 text-[10px] font-body mt-1">
              Target: {pitThreshold}s &middot; Gold line = pit threshold
            </p>
          </div>
        </div>
        );
      })()}

      {/* Traffic Time Loss */}
      {((report as any).traffic_count > 0 || (report as any).traffic_total_s > 0) && (
        <div className="bg-concrete rounded-xl border border-steel/10 p-6">
          <h3 className="text-lg font-monument text-chalk mb-4">Traffic Time Loss</h3>
          <div className="grid grid-cols-2 gap-4 mb-4">
            <div className="text-center">
              <p className="text-2xl font-monument text-safety-red">{(report as any).traffic_count || 0}</p>
              <p className="text-xs font-body text-steel">Incidents</p>
            </div>
            <div className="text-center">
              <p className="text-2xl font-monument text-safety-red">{((report as any).traffic_total_s || 0).toFixed(1)}s</p>
              <p className="text-xs font-body text-steel">Total Time Lost</p>
            </div>
          </div>
          {/* Per-stint breakdown */}
          <div className="space-y-1 mb-3">
            {stints.map((s) => {
              const tc = (s as any).traffic_count || 0;
              const tt = (s as any).traffic_total_s || 0;
              if (tc === 0) return null;
              return (
                <div key={s.stint_number} className="flex items-center gap-3 text-xs font-body">
                  <span className="text-steel font-telemetry w-12">S{s.stint_number}</span>
                  <span className="text-steel w-20 truncate">{s.driver_name}</span>
                  <div className="flex-1 h-3 bg-asphalt rounded overflow-hidden">
                    <div className="h-full bg-safety-red/40 rounded" style={{ width: `${Math.min((tt / 30) * 100, 100)}%` }} />
                  </div>
                  <span className="text-safety-red font-telemetry w-24 text-right">{tc} inc. / {tt.toFixed(1)}s</span>
                </div>
              );
            })}
          </div>
          {/* Per-driver totals */}
          <div className="pt-3 border-t border-steel/10 space-y-1">
            {drivers.map((d: DriverReport) => (
              <div key={d.driver_name} className="flex items-center gap-2 text-xs font-body">
                <span className="text-steel w-24 truncate">{d.driver_name}</span>
                <span className="text-safety-red font-telemetry">{(d as any).traffic_count || 0} incidents</span>
                <span className="text-steel/50">&middot;</span>
                <span className="text-safety-red font-telemetry">{((d as any).traffic_total_s || 0).toFixed(1)}s lost</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Team Scores */}
      <div className="bg-concrete rounded-xl border border-steel/10 p-6">
        <h3 className="text-lg font-monument text-chalk mb-4">Team Score</h3>
        <div className="space-y-3">
          {(['pace', 'consistency', 'execution', 'robustness'] as const).map((key) => {
            const score = (report.scores as any)[key] ?? 0;
            const max = 25;
            const pct = (score / max) * 100;
            const colors: Record<string, string> = { pace: '#B6FF2E', consistency: '#00d4ff', execution: '#D946EF', robustness: '#FF6A00' };
            const labels: Record<string, string> = { pace: 'Pace', consistency: 'Consistency', execution: 'Execution', robustness: 'Robustness' };
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
