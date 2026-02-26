'use client';

import { useQuery } from '@tanstack/react-query';
import { useRef, useEffect } from 'react';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';

interface ComparisonMatrixData {
  metrics: string[];
  laps: number[];
  values: number[][];
}

interface Props {
  sessionId: string;
}

function cellColor(val: number, min: number, max: number): string {
  const range = max - min || 1;
  const t = (val - min) / range;
  if (t >= 0.7) return 'rgba(182, 255, 46, 0.5)';
  if (t >= 0.4) return 'rgba(255, 212, 0, 0.4)';
  return 'rgba(255, 106, 0, 0.3)';
}

function draw(ctx: CanvasRenderingContext2D, w: number, h: number, data: ComparisonMatrixData) {
  ctx.clearRect(0, 0, w, h);

  const { metrics, laps, values } = data;
  if (metrics.length === 0 || laps.length === 0) return;

  const pad = { top: 30, right: 10, bottom: 10, left: 80 };
  const plotW = w - pad.left - pad.right;
  const plotH = h - pad.top - pad.bottom;
  const cellW = plotW / laps.length;
  const cellH = plotH / metrics.length;

  // Column headers (laps)
  ctx.fillStyle = '#8A8F98';
  ctx.font = '8px "IBM Plex Mono", monospace';
  ctx.textAlign = 'center';
  for (let j = 0; j < laps.length; j++) {
    ctx.fillText(`L${laps[j]}`, pad.left + j * cellW + cellW / 2, pad.top - 8);
  }

  // For each metric, compute min/max for color scaling
  for (let m = 0; m < metrics.length; m++) {
    const row = values[m] ?? [];
    const min = Math.min(...row);
    const max = Math.max(...row);

    // Row label
    ctx.fillStyle = '#8A8F98';
    ctx.font = '9px "IBM Plex Mono", monospace';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    ctx.fillText(metrics[m], pad.left - 5, pad.top + m * cellH + cellH / 2);

    for (let j = 0; j < row.length; j++) {
      const x = pad.left + j * cellW;
      const y = pad.top + m * cellH;

      ctx.fillStyle = cellColor(row[j], min, max);
      ctx.fillRect(x + 0.5, y + 0.5, cellW - 1, cellH - 1);

      // Value text
      if (cellW > 25 && cellH > 12) {
        ctx.fillStyle = '#F3F0E8';
        ctx.font = '7px "IBM Plex Mono", monospace';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(
          row[j].toFixed(1),
          x + cellW / 2,
          y + cellH / 2,
        );
      }
    }
  }
}

export function ComparisonMatrix({ sessionId }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'comparison-matrix'],
    queryFn: () => api.get<ComparisonMatrixData>(`/sessions/${sessionId}/comparison-matrix`),
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

  if (isLoading) return <ChartPanel title="Comparison Matrix"><div className="h-48 flex items-center justify-center"><div className="w-6 h-6 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" /></div></ChartPanel>;
  if (!data || data.metrics.length === 0) return <ChartPanel title="Comparison Matrix"><div className="h-48 flex items-center justify-center text-steel font-telemetry text-xs">No data available</div></ChartPanel>;

  return (
    <ChartPanel title="Comparison Matrix" subtitle="Multi-metric lap comparison">
      <canvas ref={canvasRef} className="w-full h-48" />
    </ChartPanel>
  );
}
