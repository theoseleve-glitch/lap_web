'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api-client';

interface CornerChip {
  corner_id: number;
  corner_name: string;
  time_loss_ms: number;
}

interface CornerNavBarProps {
  sessionId: string;
}

export function CornerNavBar({ sessionId }: CornerNavBarProps) {
  const [corners, setCorners] = useState<CornerChip[]>([]);

  useEffect(() => {
    api
      .get<{ corners: CornerChip[] }>(`/sessions/${sessionId}/corners`)
      .then((data) => {
        if (data.corners) setCorners(data.corners);
      })
      .catch(() => {});
  }, [sessionId]);

  if (corners.length === 0) return null;

  return (
    <div className="flex items-center gap-1.5 px-4 py-1.5 bg-concrete/50 border-b border-steel/10 overflow-x-auto">
      <span className="text-[10px] font-telemetry text-steel/60 shrink-0">CORNERS</span>
      {corners.map((c) => {
        const ms = c.time_loss_ms;
        const sign = ms >= 0 ? '+' : '';
        const color =
          ms > 100
            ? 'text-safety-red'
            : ms > 50
              ? 'text-marshal-yellow'
              : 'text-acid-green';
        return (
          <button
            type="button"
            key={c.corner_id}
            className={`shrink-0 px-2 py-0.5 rounded text-[10px] font-telemetry bg-asphalt/50 border border-steel/10 hover:border-acid-green/30 transition-colors ${color}`}
            title={c.corner_name}
          >
            {c.corner_name} {sign}{(ms / 1000).toFixed(3)}s
          </button>
        );
      })}
    </div>
  );
}
