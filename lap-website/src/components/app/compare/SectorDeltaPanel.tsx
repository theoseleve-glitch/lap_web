'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api-client';

interface SectorData {
  sector_name: string;
  time_a: number | null;
  time_b: number | null;
  delta: number | null;
}

interface SectorsResponse {
  sectors: SectorData[];
  corners: unknown[];
}

export default function SectorDeltaPanel({
  sessionAId,
  sessionBId,
  colorA,
  colorB,
}: {
  sessionAId: string;
  sessionBId: string;
  colorA: string;
  colorB: string;
}) {
  const [sectors, setSectors] = useState<SectorData[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!sessionAId || !sessionBId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);

    api
      .get<SectorsResponse>(
        `/sessions/${encodeURIComponent(sessionAId)}/compare/sectors?sessionKeyB=${encodeURIComponent(sessionBId)}`,
      )
      .then((res) => {
        if (!cancelled) setSectors(res.sectors || []);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load sector data');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [sessionAId, sessionBId]);

  if (loading) {
    return (
      <div className="bg-zinc-900 rounded-lg p-4 flex items-center justify-center py-12">
        <div className="w-5 h-5 border-2 border-acid-green border-t-transparent rounded-full animate-spin mr-3" />
        <p className="text-zinc-500 text-sm">Loading sector data...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-zinc-900 rounded-lg p-4">
        <h3 className="text-sm font-medium text-zinc-300 mb-2">Sector Delta</h3>
        <p className="text-zinc-500 text-sm">{error}</p>
      </div>
    );
  }

  if (sectors.length === 0) {
    return (
      <div className="bg-zinc-900 rounded-lg p-4 text-center py-12">
        <p className="text-zinc-500 text-sm">No sector data available for these sessions.</p>
      </div>
    );
  }

  // Calculate total delta
  const totalDelta = sectors.reduce((sum, s) => {
    if (s.delta != null) return sum + s.delta;
    return sum;
  }, 0);

  // Find max time for bar scaling
  const allTimes = sectors.flatMap((s) => [s.time_a, s.time_b].filter((t): t is number => t != null));
  const maxTime = allTimes.length > 0 ? Math.max(...allTimes) : 1;

  return (
    <div className="bg-zinc-900 rounded-lg p-4">
      {/* Header with total delta */}
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-medium text-zinc-300">Sector Delta</h3>
        <div className="text-sm font-mono">
          <span className="text-zinc-500 mr-2">Total:</span>
          <span className={totalDelta < 0 ? 'text-emerald-400' : totalDelta > 0 ? 'text-red-400' : 'text-zinc-400'}>
            {totalDelta > 0 ? '+' : ''}{totalDelta.toFixed(3)}s
          </span>
        </div>
      </div>

      <div className="space-y-4">
        {sectors.map((sector, idx) => {
          const pctA = sector.time_a != null ? (sector.time_a / maxTime) * 100 : 0;
          const pctB = sector.time_b != null ? (sector.time_b / maxTime) * 100 : 0;

          return (
            <div key={idx} className="space-y-1.5">
              {/* Sector name + delta */}
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-zinc-400">{sector.sector_name}</span>
                <span
                  className={`text-xs font-mono ${
                    sector.delta != null && sector.delta < 0
                      ? 'text-emerald-400'
                      : sector.delta != null && sector.delta > 0
                      ? 'text-red-400'
                      : 'text-zinc-500'
                  }`}
                >
                  {sector.delta != null
                    ? `${sector.delta > 0 ? '+' : ''}${sector.delta.toFixed(3)}s`
                    : '--'}
                </span>
              </div>

              {/* Session A bar */}
              <div className="flex items-center gap-2">
                <span className="text-[10px] w-6 text-right" style={{ color: colorA }}>A</span>
                <div className="flex-1 h-3 bg-zinc-800 rounded-sm overflow-hidden">
                  <div
                    className="h-full rounded-sm transition-all duration-300"
                    style={{ width: `${pctA}%`, backgroundColor: colorA }}
                  />
                </div>
                <span className="text-[10px] font-mono text-zinc-400 w-14 text-right">
                  {sector.time_a != null ? `${sector.time_a.toFixed(3)}s` : '--'}
                </span>
              </div>

              {/* Session B bar */}
              <div className="flex items-center gap-2">
                <span className="text-[10px] w-6 text-right" style={{ color: colorB }}>B</span>
                <div className="flex-1 h-3 bg-zinc-800 rounded-sm overflow-hidden">
                  <div
                    className="h-full rounded-sm transition-all duration-300"
                    style={{ width: `${pctB}%`, backgroundColor: colorB }}
                  />
                </div>
                <span className="text-[10px] font-mono text-zinc-400 w-14 text-right">
                  {sector.time_b != null ? `${sector.time_b.toFixed(3)}s` : '--'}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
