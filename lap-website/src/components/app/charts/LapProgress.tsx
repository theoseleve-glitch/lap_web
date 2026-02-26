'use client';

import { useQuery } from '@tanstack/react-query';
import { useRef, useEffect } from 'react';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';

interface LapData {
  laps: { lap_number: number; time: number; valid: boolean }[];
}

interface Props {
  sessionId: string;
}

function draw(ctx: CanvasRenderingContext2D, w: number, h: number, data: LapData) {
  ctx.clearRect(0, 0, w, h);

  const { laps } = data;
  if (laps.length === 0) return;

  const pad = { top: 10, right: 15, bottom: 30, left: 50 };
  const plotW = w - pad.left - pad.right;
  const plotH = h - pad.top - pad.bottom;

  const times = laps.map((l) => l.time);
  const maxTime = Math.max(...times);
  const minTime = Math.min(...times);
  const timeRange = maxTime - minTime || 1;

  const barW = Math.min(30, (plotW / laps.length) * 0.7);
  const gap = (plotW - barW * laps.length) / (laps.length + 1);

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

  // Y-axis labels
  ctx.fillStyle = '#8A8F98';
  ctx.font = '10px "IBM Plex Mono", monospace';
  ctx.textAlign = 'right';
  for (let i = 0; i <= 4; i++) {
    const val = maxTime - (i / 4) * timeRange;
    const y = pad.top + (i / 4) * plotH;
    const m = Math.floor(val / 60);
    const s = (val % 60).toFixed(1);
    ctx.fillText(`${m}:${s.padStart(4, '0')}`, pad.left - 5, y + 3);
  }

  // Bars
  const bestIdx = times.indexOf(minTime);
  for (let i = 0; i < laps.length; i++) {
    const barH = ((laps[i].time - minTime) / timeRange) * plotH * 0.85 + plotH * 0.15;
    const x = pad.left + gap + i * (barW + gap);
    const y = pad.top + plotH - barH;

    ctx.fillStyle = i === bestIdx ? '#B6FF2E' : laps[i].valid ? '#B6FF2E66' : '#FF2A2A66';
    ctx.fillRect(x, y, barW, barH);

    // Lap number
    ctx.fillStyle = '#8A8F98';
    ctx.font = '9px "IBM Plex Mono", monospace';
    ctx.textAlign = 'center';
    ctx.fillText(`${laps[i].lap_number}`, x + barW / 2, h - 8);
  }
}

export function LapProgress({ sessionId }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'laps-chart'],
    queryFn: () => api.get<LapData>(`/sessions/${sessionId}/laps`),
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

  if (isLoading) return <ChartPanel title="Lap Progress"><div className="h-48 flex items-center justify-center"><div className="w-6 h-6 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" /></div></ChartPanel>;
  if (!data || data.laps.length === 0) return <ChartPanel title="Lap Progress"><div className="h-48 flex items-center justify-center text-steel font-telemetry text-xs">No data available</div></ChartPanel>;

  return (
    <ChartPanel title="Lap Progress" subtitle="Lap times bar chart">
      <canvas ref={canvasRef} className="w-full h-48" />
    </ChartPanel>
  );
}
