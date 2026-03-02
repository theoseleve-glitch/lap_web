'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api-client';

interface CornerData {
  corner_name: string;
  time_a: number | null;
  time_b: number | null;
  delta: number | null;
  min_speed_a: number | null;
  min_speed_b: number | null;
  entry_speed_a: number | null;
  entry_speed_b: number | null;
  exit_speed_a: number | null;
  exit_speed_b: number | null;
}

interface SectorsResponse {
  sectors: unknown[];
  corners: CornerData[];
}

function mpsToKmh(mps: number | null): string {
  if (mps == null || !isFinite(mps)) return '--';
  return (mps * 3.6).toFixed(1);
}

export default function CornerComparePanel({
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
  const [corners, setCorners] = useState<CornerData[]>([]);
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
        if (!cancelled) setCorners(res.corners || []);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load corner data');
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
        <p className="text-zinc-500 text-sm">Loading corner data...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-zinc-900 rounded-lg p-4">
        <h3 className="text-sm font-medium text-zinc-300 mb-2">Corner Detail</h3>
        <p className="text-zinc-500 text-sm">{error}</p>
      </div>
    );
  }

  if (corners.length === 0) {
    return (
      <div className="bg-zinc-900 rounded-lg p-4 text-center py-12">
        <p className="text-zinc-500 text-sm">No corner data available for these sessions.</p>
      </div>
    );
  }

  return (
    <div className="bg-zinc-900 rounded-lg p-4">
      <h3 className="text-sm font-medium text-zinc-300 mb-4">Corner Detail</h3>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-zinc-700">
              <th className="text-left px-2 py-2 text-zinc-500 font-normal">Corner</th>
              <th className="text-right px-2 py-2 font-normal" style={{ color: colorA }}>Time A</th>
              <th className="text-right px-2 py-2 font-normal" style={{ color: colorB }}>Time B</th>
              <th className="text-right px-2 py-2 text-zinc-500 font-normal">Delta</th>
              <th className="text-right px-2 py-2 font-normal" style={{ color: colorA }}>Min Spd A</th>
              <th className="text-right px-2 py-2 font-normal" style={{ color: colorB }}>Min Spd B</th>
              <th className="text-right px-2 py-2 font-normal" style={{ color: colorA }}>Entry A</th>
              <th className="text-right px-2 py-2 font-normal" style={{ color: colorB }}>Entry B</th>
              <th className="text-right px-2 py-2 font-normal" style={{ color: colorA }}>Exit A</th>
              <th className="text-right px-2 py-2 font-normal" style={{ color: colorB }}>Exit B</th>
            </tr>
          </thead>
          <tbody>
            {corners.map((c, idx) => (
              <tr key={idx} className="border-b border-zinc-800 hover:bg-zinc-800/50 transition-colors">
                <td className="px-2 py-2 text-zinc-300 font-medium">{c.corner_name}</td>
                <td className="px-2 py-2 text-right font-mono text-zinc-300">
                  {c.time_a != null ? `${c.time_a.toFixed(3)}s` : '--'}
                </td>
                <td className="px-2 py-2 text-right font-mono text-zinc-300">
                  {c.time_b != null ? `${c.time_b.toFixed(3)}s` : '--'}
                </td>
                <td
                  className={`px-2 py-2 text-right font-mono ${
                    c.delta != null && c.delta < 0
                      ? 'text-emerald-400'
                      : c.delta != null && c.delta > 0
                      ? 'text-red-400'
                      : 'text-zinc-500'
                  }`}
                >
                  {c.delta != null
                    ? `${c.delta > 0 ? '+' : ''}${c.delta.toFixed(3)}s`
                    : '--'}
                </td>
                <td className="px-2 py-2 text-right font-mono text-zinc-300">
                  {mpsToKmh(c.min_speed_a)}
                </td>
                <td className="px-2 py-2 text-right font-mono text-zinc-300">
                  {mpsToKmh(c.min_speed_b)}
                </td>
                <td className="px-2 py-2 text-right font-mono text-zinc-300">
                  {mpsToKmh(c.entry_speed_a)}
                </td>
                <td className="px-2 py-2 text-right font-mono text-zinc-300">
                  {mpsToKmh(c.entry_speed_b)}
                </td>
                <td className="px-2 py-2 text-right font-mono text-zinc-300">
                  {mpsToKmh(c.exit_speed_a)}
                </td>
                <td className="px-2 py-2 text-right font-mono text-zinc-300">
                  {mpsToKmh(c.exit_speed_b)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
