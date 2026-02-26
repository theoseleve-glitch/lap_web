'use client';

import { useQuery } from '@tanstack/react-query';
import { useRef, useEffect } from 'react';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';

interface ThrottleMapData {
  distances: number[];
  laps: number[];
  throttle: number[][];
}

interface Props {
  sessionId: string;
}

function throttleColor(pct: number): string {
  if (pct >= 0.8) return '#B6FF2E';
  if (pct >= 0.5) return '#FFD400';
  if (pct >= 0.2) return '#FF6A00';
  return '#FF2A2A';
}

function draw(ctx: CanvasRenderingContext2D, w: number, h: number, data: ThrottleMapData) {
  ctx.clearRect(0, 0, w, h);

  const { distances, laps, throttle } = data;
  if (distances.length === 0 || laps.length === 0) return;

  const pad = { top: 25, right: 15, bottom: 10, left: 40 };
  const plotW = w - pad.left - pad.right;
  const plotH = h - pad.top - pad.bottom;
  const cellW = plotW / distances.length;
  const cellH = plotH / laps.length;

  // Column headers (sample distances)
  ctx.fillStyle = '#8A8F98';
  ctx.font = '8px "IBM Plex Mono", monospace';
  ctx.textAlign = 'center';
  const step = Math.max(1, Math.floor(distances.length / 8));
  for (let d = 0; d < distances.length; d += step) {
    ctx.fillText(`${distances[d].toFixed(0)}m`, pad.left + d * cellW + cellW / 2, pad.top - 8);
  }

  // Rows
  for (let l = 0; l < laps.length; l++) {
    ctx.fillStyle = '#8A8F98';
    ctx.font = '9px "IBM Plex Mono", monospace';
    ctx.textAlign = 'right';
    ctx.fillText(`L${laps[l]}`, pad.left - 5, pad.top + l * cellH + cellH / 2 + 3);

    for (let d = 0; d < distances.length; d++) {
      const val = throttle[l]?.[d] ?? 0;
      ctx.fillStyle = throttleColor(val);
      ctx.globalAlpha = 0.3 + val * 0.7;
      ctx.fillRect(
        pad.left + d * cellW,
        pad.top + l * cellH,
        cellW + 0.5,
        cellH,
      );
    }
    ctx.globalAlpha = 1;
  }
}

export function ThrottleHeatmap({ sessionId }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'throttle-map'],
    queryFn: () => api.get<ThrottleMapData>(`/sessions/${sessionId}/throttle-map`),
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

  if (isLoading) return <ChartPanel title="Throttle Heatmap"><div className="h-48 flex items-center justify-center"><div className="w-6 h-6 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" /></div></ChartPanel>;
  if (!data || data.distances.length === 0) return <ChartPanel title="Throttle Heatmap"><div className="h-48 flex items-center justify-center text-steel font-telemetry text-xs">No data available</div></ChartPanel>;

  return (
    <ChartPanel title="Throttle Heatmap" subtitle="Throttle application per lap/distance">
      <canvas ref={canvasRef} className="w-full h-48" />
    </ChartPanel>
  );
}
