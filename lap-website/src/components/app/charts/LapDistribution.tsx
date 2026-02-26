'use client';

import { useQuery } from '@tanstack/react-query';
import { useRef, useEffect } from 'react';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';

interface LapDistData {
  bins: number[];
  counts: number[];
  mean: number;
  median: number;
}

interface Props {
  sessionId: string;
}

function draw(ctx: CanvasRenderingContext2D, w: number, h: number, data: LapDistData) {
  ctx.clearRect(0, 0, w, h);

  const { bins, counts, mean, median } = data;
  if (bins.length === 0) return;

  const pad = { top: 10, right: 15, bottom: 30, left: 40 };
  const plotW = w - pad.left - pad.right;
  const plotH = h - pad.top - pad.bottom;

  const maxCount = Math.max(...counts, 1);
  const barW = plotW / bins.length;

  // Grid
  ctx.strokeStyle = 'rgba(138, 143, 152, 0.15)';
  ctx.lineWidth = 0.5;
  for (let i = 0; i <= 3; i++) {
    const y = pad.top + (i / 3) * plotH;
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(pad.left + plotW, y);
    ctx.stroke();
  }

  // Bars
  for (let i = 0; i < bins.length; i++) {
    const barH = (counts[i] / maxCount) * plotH;
    const x = pad.left + i * barW;
    const y = pad.top + plotH - barH;

    ctx.fillStyle = '#B6FF2E88';
    ctx.fillRect(x + 1, y, barW - 2, barH);
  }

  // Mean line
  const minBin = bins[0];
  const maxBin = bins[bins.length - 1];
  const binRange = maxBin - minBin || 1;

  if (mean >= minBin && mean <= maxBin) {
    const mx = pad.left + ((mean - minBin) / binRange) * plotW;
    ctx.beginPath();
    ctx.strokeStyle = '#FFD400';
    ctx.lineWidth = 1.5;
    ctx.setLineDash([4, 3]);
    ctx.moveTo(mx, pad.top);
    ctx.lineTo(mx, pad.top + plotH);
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.fillStyle = '#FFD400';
    ctx.font = '9px "IBM Plex Mono", monospace';
    ctx.textAlign = 'center';
    ctx.fillText('mean', mx, pad.top - 2);
  }

  // Median line
  if (median >= minBin && median <= maxBin) {
    const medX = pad.left + ((median - minBin) / binRange) * plotW;
    ctx.beginPath();
    ctx.strokeStyle = '#FF6A00';
    ctx.lineWidth = 1.5;
    ctx.setLineDash([4, 3]);
    ctx.moveTo(medX, pad.top);
    ctx.lineTo(medX, pad.top + plotH);
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.fillStyle = '#FF6A00';
    ctx.font = '9px "IBM Plex Mono", monospace';
    ctx.textAlign = 'center';
    ctx.fillText('med', medX, pad.top + 10);
  }

  // X-axis labels
  ctx.fillStyle = '#8A8F98';
  ctx.font = '9px "IBM Plex Mono", monospace';
  ctx.textAlign = 'center';
  const labelStep = Math.max(1, Math.floor(bins.length / 6));
  for (let i = 0; i < bins.length; i += labelStep) {
    const x = pad.left + (i + 0.5) * barW;
    ctx.fillText(`${bins[i].toFixed(1)}`, x, h - 8);
  }
}

export function LapDistribution({ sessionId }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'lap-distribution'],
    queryFn: () => api.get<LapDistData>(`/sessions/${sessionId}/lap-distribution`),
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

  if (isLoading) return <ChartPanel title="Lap Distribution"><div className="h-48 flex items-center justify-center"><div className="w-6 h-6 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" /></div></ChartPanel>;
  if (!data || data.bins.length === 0) return <ChartPanel title="Lap Distribution"><div className="h-48 flex items-center justify-center text-steel font-telemetry text-xs">No data available</div></ChartPanel>;

  return (
    <ChartPanel title="Lap Distribution" subtitle="Lap time histogram">
      <canvas ref={canvasRef} className="w-full h-48" />
    </ChartPanel>
  );
}
