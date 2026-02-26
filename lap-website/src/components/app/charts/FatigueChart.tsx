'use client';

import { useQuery } from '@tanstack/react-query';
import { useRef, useEffect } from 'react';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';

interface FatigueData {
  laps: number[];
  fatigue_index: number[];
  reaction_time: number[];
}

interface Props {
  sessionId: string;
}

function draw(ctx: CanvasRenderingContext2D, w: number, h: number, data: FatigueData) {
  ctx.clearRect(0, 0, w, h);

  const { laps, fatigue_index, reaction_time } = data;
  if (laps.length === 0) return;

  const pad = { top: 15, right: 45, bottom: 30, left: 45 };
  const plotW = w - pad.left - pad.right;
  const plotH = h - pad.top - pad.bottom;

  const maxFatigue = Math.max(...fatigue_index, 0.1);
  const maxReaction = Math.max(...reaction_time, 0.1);

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

  // Left Y-axis (fatigue)
  ctx.fillStyle = '#FFD400';
  ctx.font = '10px "IBM Plex Mono", monospace';
  ctx.textAlign = 'right';
  for (let i = 0; i <= 4; i++) {
    const val = maxFatigue - (i / 4) * maxFatigue;
    ctx.fillText(`${val.toFixed(1)}`, pad.left - 5, pad.top + (i / 4) * plotH + 3);
  }

  // Right Y-axis (reaction)
  ctx.fillStyle = '#FF6A00';
  ctx.textAlign = 'left';
  for (let i = 0; i <= 4; i++) {
    const val = maxReaction - (i / 4) * maxReaction;
    ctx.fillText(`${val.toFixed(2)}s`, pad.left + plotW + 5, pad.top + (i / 4) * plotH + 3);
  }

  const toX = (idx: number) => pad.left + (idx / (laps.length - 1 || 1)) * plotW;

  // Fatigue line
  ctx.beginPath();
  ctx.strokeStyle = '#FFD400';
  ctx.lineWidth = 2;
  for (let i = 0; i < laps.length; i++) {
    const x = toX(i);
    const y = pad.top + plotH - (fatigue_index[i] / maxFatigue) * plotH;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();

  // Reaction time line
  ctx.beginPath();
  ctx.strokeStyle = '#FF6A00';
  ctx.lineWidth = 2;
  ctx.setLineDash([4, 3]);
  for (let i = 0; i < laps.length; i++) {
    const x = toX(i);
    const y = pad.top + plotH - (reaction_time[i] / maxReaction) * plotH;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();
  ctx.setLineDash([]);

  // X-axis labels
  ctx.fillStyle = '#8A8F98';
  ctx.font = '9px "IBM Plex Mono", monospace';
  ctx.textAlign = 'center';
  for (let i = 0; i < laps.length; i++) {
    if (laps.length <= 20 || i % Math.ceil(laps.length / 10) === 0) {
      ctx.fillText(`L${laps[i]}`, toX(i), h - 8);
    }
  }

  // Legend
  ctx.font = '9px "IBM Plex Mono", monospace';
  ctx.textAlign = 'left';
  ctx.fillStyle = '#FFD400';
  ctx.fillRect(pad.left + 5, pad.top + 2, 10, 3);
  ctx.fillStyle = '#8A8F98';
  ctx.fillText('Fatigue', pad.left + 20, pad.top + 6);
  ctx.fillStyle = '#FF6A00';
  ctx.fillRect(pad.left + 80, pad.top + 2, 10, 3);
  ctx.fillStyle = '#8A8F98';
  ctx.fillText('Reaction', pad.left + 95, pad.top + 6);
}

export function FatigueChart({ sessionId }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'fatigue'],
    queryFn: () => api.get<FatigueData>(`/sessions/${sessionId}/fatigue`),
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

  if (isLoading) return <ChartPanel title="Fatigue Trend"><div className="h-48 flex items-center justify-center"><div className="w-6 h-6 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" /></div></ChartPanel>;
  if (!data || data.laps.length === 0) return <ChartPanel title="Fatigue Trend"><div className="h-48 flex items-center justify-center text-steel font-telemetry text-xs">No data available</div></ChartPanel>;

  return (
    <ChartPanel title="Fatigue Trend" subtitle="Driver fatigue over session">
      <canvas ref={canvasRef} className="w-full h-48" />
    </ChartPanel>
  );
}
