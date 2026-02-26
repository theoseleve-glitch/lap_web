'use client';

import { useQuery } from '@tanstack/react-query';
import { useRef, useEffect } from 'react';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';

interface BrakePointData {
  distances: number[];
  speeds: number[];
  pressures: number[];
}

interface Props {
  sessionId: string;
}

function draw(ctx: CanvasRenderingContext2D, w: number, h: number, data: BrakePointData) {
  ctx.clearRect(0, 0, w, h);

  const { distances, speeds, pressures } = data;
  if (distances.length === 0) return;

  const pad = { top: 10, right: 15, bottom: 30, left: 45 };
  const plotW = w - pad.left - pad.right;
  const plotH = h - pad.top - pad.bottom;

  const minDist = Math.min(...distances);
  const maxDist = Math.max(...distances);
  const distRange = maxDist - minDist || 1;
  const minSpeed = Math.min(...speeds);
  const maxSpeed = Math.max(...speeds);
  const speedRange = maxSpeed - minSpeed || 1;
  const maxPressure = Math.max(...pressures, 1);

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

  // Axis labels
  ctx.fillStyle = '#8A8F98';
  ctx.font = '10px "IBM Plex Mono", monospace';
  ctx.textAlign = 'right';
  for (let i = 0; i <= 4; i++) {
    const val = maxSpeed - (i / 4) * speedRange;
    ctx.fillText(`${val.toFixed(0)}`, pad.left - 5, pad.top + (i / 4) * plotH + 3);
  }
  ctx.textAlign = 'center';
  ctx.fillText('Distance (m)', w / 2, h - 3);

  // Scatter points — size by brake pressure
  for (let i = 0; i < distances.length; i++) {
    const x = pad.left + ((distances[i] - minDist) / distRange) * plotW;
    const y = pad.top + plotH - ((speeds[i] - minSpeed) / speedRange) * plotH;
    const r = 2 + (pressures[i] / maxPressure) * 5;

    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fillStyle = '#FF2A2A99';
    ctx.fill();
    ctx.strokeStyle = '#FF2A2A';
    ctx.lineWidth = 0.5;
    ctx.stroke();
  }
}

export function BrakeScatter({ sessionId }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'brake-points'],
    queryFn: () => api.get<BrakePointData>(`/sessions/${sessionId}/brake-points`),
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

  if (isLoading) return <ChartPanel title="Brake Points"><div className="h-48 flex items-center justify-center"><div className="w-6 h-6 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" /></div></ChartPanel>;
  if (!data || data.distances.length === 0) return <ChartPanel title="Brake Points"><div className="h-48 flex items-center justify-center text-steel font-telemetry text-xs">No data available</div></ChartPanel>;

  return (
    <ChartPanel title="Brake Points" subtitle="Brake point scatter by distance">
      <canvas ref={canvasRef} className="w-full h-48" />
    </ChartPanel>
  );
}
