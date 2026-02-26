'use client';

import { useQuery } from '@tanstack/react-query';
import { useRef, useEffect } from 'react';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';

interface RivalGapData {
  laps: number[];
  gap: number[];
  rival_name: string;
}

interface Props {
  sessionId: string;
}

function draw(ctx: CanvasRenderingContext2D, w: number, h: number, data: RivalGapData) {
  ctx.clearRect(0, 0, w, h);

  const { laps, gap } = data;
  if (laps.length === 0) return;

  const pad = { top: 10, right: 15, bottom: 30, left: 45 };
  const plotW = w - pad.left - pad.right;
  const plotH = h - pad.top - pad.bottom;

  const maxGap = Math.max(...gap.map(Math.abs), 0.1);
  const cy = pad.top + plotH / 2;

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

  // Zero line
  ctx.beginPath();
  ctx.strokeStyle = '#8A8F98';
  ctx.lineWidth = 1;
  ctx.moveTo(pad.left, cy);
  ctx.lineTo(pad.left + plotW, cy);
  ctx.stroke();

  // Y labels
  ctx.fillStyle = '#8A8F98';
  ctx.font = '10px "IBM Plex Mono", monospace';
  ctx.textAlign = 'right';
  ctx.fillText(`+${maxGap.toFixed(1)}s`, pad.left - 5, pad.top + 4);
  ctx.fillText(`-${maxGap.toFixed(1)}s`, pad.left - 5, pad.top + plotH + 4);
  ctx.fillText('0.0s', pad.left - 5, cy + 4);

  const toX = (i: number) => pad.left + (i / (laps.length - 1 || 1)) * plotW;
  const toY = (g: number) => cy - (g / maxGap) * (plotH / 2);

  // Fill areas
  ctx.beginPath();
  for (let i = 0; i < laps.length; i++) {
    const x = toX(i);
    const y = toY(gap[i]);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.lineTo(toX(laps.length - 1), cy);
  ctx.lineTo(toX(0), cy);
  ctx.closePath();

  const grad = ctx.createLinearGradient(0, pad.top, 0, pad.top + plotH);
  grad.addColorStop(0, '#B6FF2E33');
  grad.addColorStop(0.5, 'transparent');
  grad.addColorStop(1, '#FF2A2A33');
  ctx.fillStyle = grad;
  ctx.fill();

  // Line
  ctx.beginPath();
  ctx.strokeStyle = '#F3F0E8';
  ctx.lineWidth = 2;
  for (let i = 0; i < laps.length; i++) {
    const x = toX(i);
    const y = toY(gap[i]);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();

  // X-axis labels
  ctx.fillStyle = '#8A8F98';
  ctx.font = '9px "IBM Plex Mono", monospace';
  ctx.textAlign = 'center';
  for (let i = 0; i < laps.length; i++) {
    if (laps.length <= 15 || i % Math.ceil(laps.length / 10) === 0) {
      ctx.fillText(`L${laps[i]}`, toX(i), h - 8);
    }
  }
}

export function RivalChart({ sessionId }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'rival-gap'],
    queryFn: () => api.get<RivalGapData>(`/sessions/${sessionId}/rival-gap`),
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

  if (isLoading) return <ChartPanel title="Rival Gap"><div className="h-48 flex items-center justify-center"><div className="w-6 h-6 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" /></div></ChartPanel>;
  if (!data || data.laps.length === 0) return <ChartPanel title="Rival Gap"><div className="h-48 flex items-center justify-center text-steel font-telemetry text-xs">No data available</div></ChartPanel>;

  return (
    <ChartPanel title="Rival Gap" subtitle={`Gap to ${data.rival_name}`}>
      <canvas ref={canvasRef} className="w-full h-48" />
    </ChartPanel>
  );
}
