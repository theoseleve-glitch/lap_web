'use client';

import { useQuery } from '@tanstack/react-query';
import { useRef, useEffect } from 'react';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';

interface TrendData {
  distances: number[];
  pace_delta: number[];
  consistency_index: number[];
}

interface Props {
  sessionId: string;
}

function draw(ctx: CanvasRenderingContext2D, w: number, h: number, data: TrendData) {
  ctx.clearRect(0, 0, w, h);

  const { distances, pace_delta, consistency_index } = data;
  if (distances.length === 0) return;

  const pad = { top: 15, right: 40, bottom: 30, left: 45 };
  const plotW = w - pad.left - pad.right;
  const plotH = h - pad.top - pad.bottom;

  const minDist = distances[0];
  const maxDist = distances[distances.length - 1];
  const distRange = maxDist - minDist || 1;

  const maxPace = Math.max(...pace_delta.map(Math.abs), 0.1);
  const maxConsist = Math.max(...consistency_index, 0.01);

  // Grid
  ctx.strokeStyle = 'rgba(138, 143, 152, 0.15)';
  ctx.lineWidth = 0.5;
  for (let i = 0; i <= 4; i++) {
    const y = pad.top + (i / 4) * plotH;
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(pad.left + plotW, y);
    ctx.stroke();
  }

  const toX = (d: number) => pad.left + ((d - minDist) / distRange) * plotW;
  const cy = pad.top + plotH / 2;

  // Pace delta (centered on zero)
  ctx.beginPath();
  ctx.strokeStyle = '#B6FF2E';
  ctx.lineWidth = 1.5;
  for (let i = 0; i < distances.length; i++) {
    const x = toX(distances[i]);
    const y = cy - (pace_delta[i] / maxPace) * (plotH / 2);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();

  // Consistency index
  ctx.beginPath();
  ctx.strokeStyle = '#FFD400';
  ctx.lineWidth = 1.5;
  ctx.setLineDash([4, 3]);
  for (let i = 0; i < distances.length; i++) {
    const x = toX(distances[i]);
    const y = pad.top + plotH - (consistency_index[i] / maxConsist) * plotH;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();
  ctx.setLineDash([]);

  // Zero line
  ctx.beginPath();
  ctx.strokeStyle = '#8A8F98';
  ctx.lineWidth = 0.5;
  ctx.moveTo(pad.left, cy);
  ctx.lineTo(pad.left + plotW, cy);
  ctx.stroke();

  // Legend
  ctx.font = '9px "IBM Plex Mono", monospace';
  ctx.textAlign = 'left';
  ctx.fillStyle = '#B6FF2E';
  ctx.fillRect(pad.left + 5, pad.top + 2, 10, 3);
  ctx.fillStyle = '#8A8F98';
  ctx.fillText('Pace delta', pad.left + 20, pad.top + 6);
  ctx.fillStyle = '#FFD400';
  ctx.fillRect(pad.left + 95, pad.top + 2, 10, 3);
  ctx.fillStyle = '#8A8F98';
  ctx.fillText('Consistency', pad.left + 110, pad.top + 6);
}

export function TrendChart({ sessionId }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'trends'],
    queryFn: () => api.get<TrendData>(`/sessions/${sessionId}/trends`),
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

  if (isLoading) return <ChartPanel title="Performance Trend"><div className="h-48 flex items-center justify-center"><div className="w-6 h-6 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" /></div></ChartPanel>;
  if (!data || data.distances.length === 0) return <ChartPanel title="Performance Trend"><div className="h-48 flex items-center justify-center text-steel font-telemetry text-xs">No data available</div></ChartPanel>;

  return (
    <ChartPanel title="Performance Trend" subtitle="Pace and consistency over distance">
      <canvas ref={canvasRef} className="w-full h-48" />
    </ChartPanel>
  );
}
