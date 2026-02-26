'use client';

import { useQuery } from '@tanstack/react-query';
import { useRef, useEffect } from 'react';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';

interface WorkloadData {
  timestamps: number[];
  steering: number[];
  braking: number[];
  throttle: number[];
  total: number[];
}

interface Props {
  sessionId: string;
}

function draw(ctx: CanvasRenderingContext2D, w: number, h: number, data: WorkloadData) {
  ctx.clearRect(0, 0, w, h);

  const { timestamps, steering, braking, throttle, total } = data;
  if (timestamps.length === 0) return;

  const pad = { top: 15, right: 15, bottom: 25, left: 40 };
  const plotW = w - pad.left - pad.right;
  const plotH = h - pad.top - pad.bottom;

  const maxVal = Math.max(...total, 0.01);
  const minT = timestamps[0];
  const maxT = timestamps[timestamps.length - 1];
  const tRange = maxT - minT || 1;

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

  const toX = (t: number) => pad.left + ((t - minT) / tRange) * plotW;
  const toY = (v: number) => pad.top + plotH - (v / maxVal) * plotH;

  // Stacked area: steering, braking, throttle
  const channels = [
    { data: steering, color: '#FFD400', label: 'Steer' },
    { data: braking, color: '#FF2A2A', label: 'Brake' },
    { data: throttle, color: '#B6FF2E', label: 'Throttle' },
  ];

  for (const ch of channels) {
    ctx.beginPath();
    for (let i = 0; i < timestamps.length; i++) {
      const x = toX(timestamps[i]);
      const y = toY(ch.data[i]);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.strokeStyle = ch.color;
    ctx.lineWidth = 1;
    ctx.stroke();
  }

  // Total workload line
  ctx.beginPath();
  ctx.strokeStyle = '#F3F0E8';
  ctx.lineWidth = 2;
  for (let i = 0; i < timestamps.length; i++) {
    const x = toX(timestamps[i]);
    const y = toY(total[i]);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();

  // Legend
  ctx.font = '9px "IBM Plex Mono", monospace';
  ctx.textAlign = 'left';
  let lx = pad.left + 5;
  for (const ch of channels) {
    ctx.fillStyle = ch.color;
    ctx.fillRect(lx, pad.top + 2, 10, 3);
    ctx.fillStyle = '#8A8F98';
    ctx.fillText(ch.label, lx + 14, pad.top + 6);
    lx += 60;
  }
  ctx.fillStyle = '#F3F0E8';
  ctx.fillRect(lx, pad.top + 2, 10, 3);
  ctx.fillStyle = '#8A8F98';
  ctx.fillText('Total', lx + 14, pad.top + 6);
}

export function WorkloadChart({ sessionId }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'workload'],
    queryFn: () => api.get<WorkloadData>(`/sessions/${sessionId}/workload`),
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

  if (isLoading) return <ChartPanel title="Driver Workload"><div className="h-48 flex items-center justify-center"><div className="w-6 h-6 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" /></div></ChartPanel>;
  if (!data || data.timestamps.length === 0) return <ChartPanel title="Driver Workload"><div className="h-48 flex items-center justify-center text-steel font-telemetry text-xs">No data available</div></ChartPanel>;

  return (
    <ChartPanel title="Driver Workload" subtitle="Input workload over time">
      <canvas ref={canvasRef} className="w-full h-48" />
    </ChartPanel>
  );
}
