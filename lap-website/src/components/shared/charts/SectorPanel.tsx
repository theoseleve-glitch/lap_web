/**
 * SectorPanel.tsx — Sector analysis panel with ideal lap, heatmap, and insights.
 *
 * Shows best/mean/gap per sector with color-coded cells (green=close to best,
 * red=far from best). Auto-generates coaching insights from sector stats.
 */
'use client';

import { useMemo } from 'react';
import { useChartData } from './useChartData';

interface SectorStat {
  sector: number;
  best_s: number;
  mean_s: number;
  std_s: number;
}

interface SectorAnalysisData {
  n_sectors: number;
  ideal_lap_time_s: number;
  sector_stats: SectorStat[];
  sector_timings?: unknown[];
  coaching?: string[];
}

interface SectorPanelProps {
  sessionId?: string;
  data?: SectorAnalysisData;
  className?: string;
}

function gapColor(gap: number, maxGap: number): string {
  if (maxGap === 0) return 'text-green-400';
  const ratio = gap / maxGap;
  if (ratio < 0.33) return 'text-green-400';
  if (ratio < 0.66) return 'text-yellow-400';
  return 'text-red-400';
}

function gapBgColor(gap: number, maxGap: number): string {
  if (maxGap === 0) return 'bg-green-900/30';
  const ratio = gap / maxGap;
  if (ratio < 0.33) return 'bg-green-900/30';
  if (ratio < 0.66) return 'bg-yellow-900/30';
  return 'bg-red-900/30';
}

export function SectorPanel({ sessionId, data: preFetched, className = '' }: SectorPanelProps) {
  const { data, loading, error } = useChartData<SectorAnalysisData>({
    data: preFetched,
    sessionId,
    endpoint: 'sectors',
    transform: (raw) => raw as unknown as SectorAnalysisData,
  });

  const insights = useMemo(() => {
    if (!data?.sector_stats) return [];
    const stats = data.sector_stats;
    const result: string[] = [];

    // Find sector with lowest variance
    const sortedByStd = [...stats].sort((a, b) => a.std_s - b.std_s);
    if (sortedByStd.length > 0) {
      const best = sortedByStd[0];
      const cv = best.mean_s > 0 ? ((best.std_s / best.mean_s) * 100).toFixed(1) : '0';
      result.push(`Sector ${best.sector} lowest variance (${cv}%)`);
    }

    // Find sector with highest time loss (gap)
    const gaps = stats.map((s) => ({ sector: s.sector, gap: s.mean_s - s.best_s }));
    const sortedByGap = [...gaps].sort((a, b) => b.gap - a.gap);
    if (sortedByGap.length > 0 && sortedByGap[0].gap > 0) {
      const worst = sortedByGap[0];
      result.push(`Sector ${worst.sector} highest time loss (${worst.gap.toFixed(3)}s)`);
    }

    return result;
  }, [data]);

  if (loading) {
    return <div className={`text-gray-500 p-4 ${className}`}>Loading sector data...</div>;
  }

  if (error) {
    return <div className={`text-red-400 p-4 ${className}`}>Failed to load sectors: {error}</div>;
  }

  if (!data || !data.sector_stats || data.sector_stats.length === 0) {
    return <div className={`text-gray-500 p-4 ${className}`}>No sector data available</div>;
  }

  const maxGap = Math.max(
    ...data.sector_stats.map((s) =>
      s.mean_s != null && s.best_s != null ? s.mean_s - s.best_s : 0,
    ),
    0.001,
  );

  return (
    <div className={`bg-gray-900 rounded-lg p-4 ${className}`}>
      {/* Ideal lap header */}
      <div className="text-sm text-gray-400 mb-3">
        Ideal Lap:{' '}
        <span className="text-white font-mono font-semibold">
          {data.ideal_lap_time_s != null ? `${data.ideal_lap_time_s.toFixed(3)}s` : '--'}
        </span>
        <span className="text-gray-500 ml-2">(sum of best sectors)</span>
      </div>

      {/* Sector table */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-gray-500 text-xs">
              <th className="text-left pr-4 pb-2" />
              {data.sector_stats.map((s) => (
                <th key={s.sector} className="text-center px-3 pb-2 font-normal">
                  S{s.sector}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr className="text-gray-300">
              <td className="pr-4 py-1 text-gray-500 text-xs">Best</td>
              {data.sector_stats.map((s) => (
                <td key={s.sector} className="text-center px-3 py-1 font-mono">
                  {s.best_s != null ? s.best_s.toFixed(1) : '--'}
                </td>
              ))}
            </tr>
            <tr className="text-gray-300">
              <td className="pr-4 py-1 text-gray-500 text-xs">Mean</td>
              {data.sector_stats.map((s) => (
                <td key={s.sector} className="text-center px-3 py-1 font-mono">
                  {s.mean_s != null ? s.mean_s.toFixed(1) : '--'}
                </td>
              ))}
            </tr>
            <tr>
              <td className="pr-4 py-1 text-gray-500 text-xs">Gap</td>
              {data.sector_stats.map((s) => {
                const gap = s.mean_s != null && s.best_s != null ? s.mean_s - s.best_s : 0;
                return (
                  <td
                    key={s.sector}
                    className={`text-center px-3 py-1 font-mono ${gapColor(gap, maxGap)} ${gapBgColor(gap, maxGap)} rounded`}
                  >
                    {s.mean_s != null && s.best_s != null ? gap.toFixed(1) : '--'}
                  </td>
                );
              })}
            </tr>
          </tbody>
        </table>
      </div>

      {/* Heatmap bar */}
      <div className="flex gap-1 mt-3">
        {data.sector_stats.map((s) => {
          const gap = s.mean_s != null && s.best_s != null ? s.mean_s - s.best_s : 0;
          const ratio = maxGap > 0 ? gap / maxGap : 0;
          const hue = 120 - ratio * 120; // 120=green, 0=red
          return (
            <div
              key={s.sector}
              className="flex-1 h-3 rounded"
              style={{ backgroundColor: `hsl(${hue}, 70%, 40%)` }}
              title={`S${s.sector}: ${gap.toFixed(3)}s gap`}
            />
          );
        })}
      </div>
      <div className="text-xs text-gray-600 mt-1">
        green = close to best, red = far from best
      </div>

      {/* Insights */}
      {insights.length > 0 && (
        <div className="mt-3 text-xs text-gray-400 space-y-1">
          {insights.map((insight, i) => (
            <div key={i}>Insight: {insight}</div>
          ))}
        </div>
      )}
    </div>
  );
}
