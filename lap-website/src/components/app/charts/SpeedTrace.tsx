'use client';

import { useQuery } from '@tanstack/react-query';
import { useRef, useEffect } from 'react';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';

interface SpeedTraceData {
  distances: number[];
  speeds: number[];
}

interface Props {
  sessionId: string;
}

function draw(ctx: CanvasRenderingContext2D, w: number, h: number, data: SpeedTraceData) {
  ctx.clearRect(0, 0, w, h);

  const { distances, speeds } = data;
  if (distances.length === 0) return;

  const pad = { top: 10, right: 15, bottom: 30, left: 45 };
  const plotW = w - pad.left - pad.right;
  const plotH = h - pad.top - pad.bottom;

  const minDist = distances[0];
  const maxDist = distances[distances.length - 1];
  const distRange = maxDist - minDist || 1;
  const maxSpeed = Math.max(...speeds);
  const minSpeed = Math.min(...speeds);
  const speedRange = maxSpeed - minSpeed || 1;

  // Grid lines
  ctx.strokeStyle = 'rgba(138, 143, 152, 0.15)';
  ctx.lineWidth = 0.5;
  for (let i = 0; i <= 4; i++) {
    const y = pad.top + (i / 4) * plotH;
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(pad.left + plotW, y);
    ctx.stroke();
  }

  // Axis labels
  ctx.fillStyle = '#8A8F98';
  ctx.font = '10px "IBM Plex Mono", monospace';
  ctx.textAlign = 'right';
  for (let i = 0; i <= 4; i++) {
    const val = maxSpeed - (i / 4) * speedRange;
    const y = pad.top + (i / 4) * plotH;
    ctx.fillText(`${val.toFixed(0)}`, pad.left - 5, y + 3);
  }

  ctx.textAlign = 'center';
  for (let i = 0; i <= 4; i++) {
    const val = minDist + (i / 4) * distRange;
    const x = pad.left + (i / 4) * plotW;
    ctx.fillText(`${(val / 1000).toFixed(1)}km`, x, h - 5);
  }

  // Speed trace
  ctx.beginPath();
  ctx.strokeStyle = '#B6FF2E';
  ctx.lineWidth = 1.5;
  ctx.lineJoin = 'round';

  for (let i = 0; i < distances.length; i++) {
    const x = pad.left + ((distances[i] - minDist) / distRange) * plotW;
    const y = pad.top + plotH - ((speeds[i] - minSpeed) / speedRange) * plotH;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();

  // Fill under curve
  ctx.lineTo(pad.left + plotW, pad.top + plotH);
  ctx.lineTo(pad.left, pad.top + plotH);
  ctx.closePath();
  const grad = ctx.createLinearGradient(0, pad.top, 0, pad.top + plotH);
  grad.addColorStop(0, '#B6FF2E22');
  grad.addColorStop(1, '#B6FF2E02');
  ctx.fillStyle = grad;
  ctx.fill();
}

export function SpeedTrace({ sessionId }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'speed-trace'],
    queryFn: () => api.get<SpeedTraceData>(`/sessions/${sessionId}/speed-trace`),
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

  if (isLoading) return <ChartPanel title="Speed Trace"><div className="h-48 flex items-center justify-center"><div className="w-6 h-6 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" /></div></ChartPanel>;
  if (!data || data.distances.length === 0) return <ChartPanel title="Speed Trace"><div className="h-48 flex items-center justify-center text-steel font-telemetry text-xs">No data available</div></ChartPanel>;

  return (
    <ChartPanel title="Speed Trace" subtitle="Speed over distance">
      <canvas ref={canvasRef} className="w-full h-48" />
    </ChartPanel>
  );
}
