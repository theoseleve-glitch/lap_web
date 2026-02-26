'use client';

import { useQuery } from '@tanstack/react-query';
import { useRef, useEffect } from 'react';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';

interface ConsistencyData {
  laps: number[];
  sectors: number[];
  deltas: number[][];
}

interface Props {
  sessionId: string;
}

function heatColor(val: number, maxAbs: number): string {
  const t = maxAbs > 0 ? val / maxAbs : 0;
  if (t > 0) {
    const intensity = Math.min(1, t);
    return `rgba(255, 42, 42, ${0.2 + intensity * 0.6})`;
  } else {
    const intensity = Math.min(1, -t);
    return `rgba(182, 255, 46, ${0.2 + intensity * 0.6})`;
  }
}

function draw(ctx: CanvasRenderingContext2D, w: number, h: number, data: ConsistencyData) {
  ctx.clearRect(0, 0, w, h);

  const { laps, sectors, deltas } = data;
  if (laps.length === 0 || sectors.length === 0) return;

  const pad = { top: 25, right: 15, bottom: 10, left: 40 };
  const plotW = w - pad.left - pad.right;
  const plotH = h - pad.top - pad.bottom;
  const cellW = plotW / sectors.length;
  const cellH = plotH / laps.length;

  const allVals = deltas.flat();
  const maxAbs = Math.max(...allVals.map(Math.abs), 0.001);

  // Header labels
  ctx.fillStyle = '#8A8F98';
  ctx.font = '9px "IBM Plex Mono", monospace';
  ctx.textAlign = 'center';
  for (let s = 0; s < sectors.length; s++) {
    ctx.fillText(`S${sectors[s]}`, pad.left + s * cellW + cellW / 2, pad.top - 8);
  }

  // Row labels + cells
  ctx.textAlign = 'right';
  for (let l = 0; l < laps.length; l++) {
    ctx.fillStyle = '#8A8F98';
    ctx.fillText(`L${laps[l]}`, pad.left - 5, pad.top + l * cellH + cellH / 2 + 3);

    for (let s = 0; s < sectors.length; s++) {
      const val = deltas[l]?.[s] ?? 0;
      ctx.fillStyle = heatColor(val, maxAbs);
      ctx.fillRect(
        pad.left + s * cellW + 1,
        pad.top + l * cellH + 1,
        cellW - 2,
        cellH - 2,
      );

      if (cellW > 30 && cellH > 14) {
        ctx.fillStyle = '#F3F0E8';
        ctx.font = '8px "IBM Plex Mono", monospace';
        ctx.textAlign = 'center';
        ctx.fillText(
          val > 0 ? `+${val.toFixed(2)}` : val.toFixed(2),
          pad.left + s * cellW + cellW / 2,
          pad.top + l * cellH + cellH / 2 + 3,
        );
      }
    }
  }
}

export function ConsistencyHeatmap({ sessionId }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'consistency'],
    queryFn: () => api.get<ConsistencyData>(`/sessions/${sessionId}/consistency`),
  });

  useEffect(() => {
    if (!data || !canvasRef.current) return;
    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);
    draw(ctx, rect.width, rect.height, data);
  }, [data]);

  if (isLoading) return <ChartPanel title="Consistency Heatmap"><div className="h-48 flex items-center justify-center"><div className="w-6 h-6 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" /></div></ChartPanel>;
  if (!data || data.laps.length === 0) return <ChartPanel title="Consistency Heatmap"><div className="h-48 flex items-center justify-center text-steel font-telemetry text-xs">No data available</div></ChartPanel>;

  return (
    <ChartPanel title="Consistency Heatmap" subtitle="Lap-sector time deltas">
      <canvas ref={canvasRef} className="w-full h-48" />
    </ChartPanel>
  );
}
