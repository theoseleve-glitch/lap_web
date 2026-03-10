'use client';

import { useQuery } from '@tanstack/react-query';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { api } from '@/lib/api-client';
import { QueryError, SkeletonBox } from '@/components/app';
import { PageIntro } from '@/components/ui/PageIntro';

/* ── Types ──────────────────────────────────────────────── */

interface LapTrendEntry {
  session_id: string;
  session_date: string;
  best_lap_time_s: number;
  total_score: number | null;
  n_laps: number | null;
  track_state: string | null;
  driver_name: string | null;
}

interface SectorEntry {
  session_id: string;
  session_date: string;
  sectors: { sector_index: number; best_sector_time_s: number }[];
}

interface CornerMetric {
  corner_index: number;
  avg_time_loss_s: number;
  avg_min_speed_mps: number;
  sample_count: number;
}

interface EvolutionData {
  lap_trend: LapTrendEntry[];
  sector_breakdown: SectorEntry[];
  corner_metrics: CornerMetric[];
}

/* ── Helpers ────────────────────────────────────────────── */

function fmtTime(s: number | null): string {
  if (s == null) return '\u2014';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}

function fmtDate(d: string | null): string {
  if (!d) return '\u2014';
  return new Date(d).toLocaleDateString('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  });
}

function ConditionBadge({ state }: { state: string | null }) {
  const s = (state || 'dry').toLowerCase();
  const colors: Record<string, string> = {
    dry: 'bg-acid-green/20 text-acid-green',
    wet: 'bg-blue-500/20 text-blue-400',
    damp: 'bg-yellow-500/20 text-yellow-400',
    mixed: 'bg-purple-500/20 text-purple-400',
  };
  return (
    <span
      className={`px-2 py-0.5 rounded text-[10px] font-telemetry uppercase ${colors[s] || colors.dry}`}
    >
      {s}
    </span>
  );
}

/* ── Page ───────────────────────────────────────────────── */

export default function TrackEvolutionPage() {
  const params = useParams();
  const id = params.id as string;

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['track-evolution', id],
    queryFn: () => api.get<EvolutionData>(`/tracks/${id}/evolution`),
  });

  if (isLoading) {
    return (
      <div>
        <SkeletonBox className="h-8 w-48 mb-4" />
        <SkeletonBox className="h-64 w-full mb-4" />
        <SkeletonBox className="h-48 w-full" />
      </div>
    );
  }

  if (error) {
    return (
      <QueryError
        message="Couldn't load evolution data."
        onRetry={() => refetch()}
      />
    );
  }

  if (!data) return null;

  const { lap_trend, sector_breakdown, corner_metrics } = data;

  // Compute rolling average (5-session window)
  const rollingAvg = lap_trend.map((entry, i) => {
    const windowSize = Math.min(5, i + 1);
    const window = lap_trend.slice(Math.max(0, i - windowSize + 1), i + 1);
    const avg =
      window.reduce((sum, e) => sum + e.best_lap_time_s, 0) / window.length;
    return { ...entry, rolling_avg: avg };
  });

  // Best and worst corners
  const sortedCorners = [...corner_metrics].sort(
    (a, b) => b.avg_time_loss_s - a.avg_time_loss_s,
  );
  const maxTimeLoss =
    sortedCorners.length > 0 ? sortedCorners[0].avg_time_loss_s : 1;

  return (
    <div>
      <PageIntro
        title="Track Evolution"
        subtitle={`${lap_trend.length} session${lap_trend.length !== 1 ? 's' : ''} analysed`}
        actions={
          <Link
            href={`/app/tracks/${id}`}
            className="px-4 py-2 border border-steel/30 text-steel font-telemetry text-sm rounded hover:text-chalk hover:border-steel/60 transition-colors"
          >
            &larr; Track Detail
          </Link>
        }
      />

      {lap_trend.length === 0 ? (
        <div className="bg-concrete rounded-lg border border-steel/20 p-12 text-center">
          <h2 className="font-monument text-lg text-chalk mb-2">
            No session data yet
          </h2>
          <p className="text-steel font-body text-sm">
            Upload sessions at this track to see your evolution.
          </p>
        </div>
      ) : (
        <div className="space-y-6">
          {/* ── Lap Time Trend ─────────────────────────────── */}
          <div className="bg-concrete rounded-lg border border-steel/20 p-4">
            <h2 className="font-telemetry text-xs uppercase tracking-wider text-steel mb-3">
              Lap Time Trend
            </h2>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-steel font-telemetry text-xs uppercase border-b border-steel/20">
                    <th className="text-left py-2 pr-4">Date</th>
                    <th className="text-left py-2 pr-4">Driver</th>
                    <th className="text-right py-2 pr-4">Best Lap</th>
                    <th className="text-right py-2 pr-4">Rolling Avg</th>
                    <th className="text-right py-2 pr-4">Score</th>
                    <th className="text-right py-2 pr-4">Laps</th>
                    <th className="text-center py-2">Condition</th>
                  </tr>
                </thead>
                <tbody>
                  {rollingAvg.map((entry, i) => {
                    const prev = i > 0 ? rollingAvg[i - 1] : null;
                    const improved =
                      prev && entry.best_lap_time_s < prev.best_lap_time_s;
                    const worsened =
                      prev && entry.best_lap_time_s > prev.best_lap_time_s;
                    return (
                      <tr
                        key={entry.session_id}
                        className="border-b border-steel/10 hover:bg-steel/5"
                      >
                        <td className="py-2 pr-4 text-chalk font-body">
                          {fmtDate(entry.session_date)}
                        </td>
                        <td className="py-2 pr-4 text-chalk font-body">
                          {entry.driver_name || '\u2014'}
                        </td>
                        <td
                          className={`py-2 pr-4 text-right font-telemetry ${
                            improved
                              ? 'text-acid-green'
                              : worsened
                                ? 'text-safety-red'
                                : 'text-chalk'
                          }`}
                        >
                          {fmtTime(entry.best_lap_time_s)}
                          {improved && ' \u2193'}
                          {worsened && ' \u2191'}
                        </td>
                        <td className="py-2 pr-4 text-right font-telemetry text-steel">
                          {fmtTime(entry.rolling_avg)}
                        </td>
                        <td className="py-2 pr-4 text-right font-telemetry text-chalk">
                          {entry.total_score != null
                            ? entry.total_score.toFixed(0)
                            : '\u2014'}
                        </td>
                        <td className="py-2 pr-4 text-right font-telemetry text-steel">
                          {entry.n_laps ?? '\u2014'}
                        </td>
                        <td className="py-2 text-center">
                          <ConditionBadge state={entry.track_state} />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* ── Sector Breakdown ───────────────────────────── */}
          {sector_breakdown.length > 0 && (
            <div className="bg-concrete rounded-lg border border-steel/20 p-4">
              <h2 className="font-telemetry text-xs uppercase tracking-wider text-steel mb-3">
                Sector Breakdown
              </h2>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-steel font-telemetry text-xs uppercase border-b border-steel/20">
                      <th className="text-left py-2 pr-4">Date</th>
                      {sector_breakdown[0]?.sectors.map((s) => (
                        <th
                          key={s.sector_index}
                          className="text-right py-2 pr-4"
                        >
                          S{s.sector_index + 1}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {sector_breakdown.map((entry) => (
                      <tr
                        key={entry.session_id}
                        className="border-b border-steel/10 hover:bg-steel/5"
                      >
                        <td className="py-2 pr-4 text-chalk font-body">
                          {fmtDate(entry.session_date)}
                        </td>
                        {entry.sectors.map((s) => (
                          <td
                            key={s.sector_index}
                            className="py-2 pr-4 text-right font-telemetry text-chalk"
                          >
                            {s.best_sector_time_s.toFixed(3)}s
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* ── Corner Performance ─────────────────────────── */}
          {corner_metrics.length > 0 && (
            <div className="bg-concrete rounded-lg border border-steel/20 p-4">
              <h2 className="font-telemetry text-xs uppercase tracking-wider text-steel mb-3">
                Corner Performance (worst &rarr; best)
              </h2>
              <div className="space-y-2">
                {sortedCorners.map((corner) => {
                  const pct =
                    maxTimeLoss > 0
                      ? (corner.avg_time_loss_s / maxTimeLoss) * 100
                      : 0;
                  return (
                    <div
                      key={corner.corner_index}
                      className="flex items-center gap-3"
                    >
                      <span className="w-12 text-right font-telemetry text-xs text-steel shrink-0">
                        T{corner.corner_index + 1}
                      </span>
                      <div className="flex-1 h-5 bg-asphalt rounded overflow-hidden">
                        <div
                          className="h-full bg-gradient-to-r from-safety-red to-pit-orange rounded"
                          style={{ width: `${Math.max(pct, 2)}%` }}
                        />
                      </div>
                      <span className="w-20 text-right font-telemetry text-xs text-chalk shrink-0">
                        {corner.avg_time_loss_s.toFixed(3)}s
                      </span>
                      <span className="w-16 text-right font-telemetry text-[10px] text-steel shrink-0">
                        ({corner.sample_count} samples)
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
