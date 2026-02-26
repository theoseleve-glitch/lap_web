'use client';

import { useQuery } from '@tanstack/react-query';
import { useRef, useEffect } from 'react';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';

interface StintData {
  stints: {
    stint_number: number;
    start_lap: number;
    end_lap: number;
    avg_time: number;
    best_time: number;
    laps_count: number;
  }[];
}

interface Props {
  sessionId: string;
}

function draw(ctx: CanvasRenderingContext2D, w: number, h: number, data: StintData) {
  ctx.clearRect(0, 0, w, h);

  const { stints } = data;
  if (stints.length === 0) return;

  const pad = { top: 10, right: 15, bottom: 30, left: 50 };
  const plotW = w - pad.left - pad.right;
  const plotH = h - pad.top - pad.bottom;

  const allTimes = stints.flatMap((s) => [s.avg_time, s.best_time]);
  const maxTime = Math.max(...allTimes);
  const minTime = Math.min(...allTimes);
  const timeRange = maxTime - minTime || 1;

  const groupW = plotW / stints.length;
  const barW = Math.min(40, groupW * 0.6);

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

  // Y-axis
  ctx.fillStyle = '#8A8F98';
  ctx.font = '10px "IBM Plex Mono", monospace';
  ctx.textAlign = 'right';
  for (let i = 0; i <= 4; i++) {
    const val = maxTime - (i / 4) * timeRange;
    const m = Math.floor(val / 60);
    const s = (val % 60).toFixed(1);
    ctx.fillText(`${m}:${s.padStart(4, '0')}`, pad.left - 5, pad.top + (i / 4) * plotH + 3);
  }

  for (let i = 0; i < stints.length; i++) {
    const cx = pad.left + i * groupW + groupW / 2;
    const s = stints[i];

    // Avg time bar
    const avgH = ((s.avg_time - minTime) / timeRange) * plotH * 0.85 + plotH * 0.15;
    ctx.fillStyle = '#FFD40088';
    ctx.fillRect(cx - barW / 2, pad.top + plotH - avgH, barW / 2 - 1, avgH);

    // Best time bar
    const bestH = ((s.best_time - minTime) / timeRange) * plotH * 0.85 + plotH * 0.15;
    ctx.fillStyle = '#B6FF2E';
    ctx.fillRect(cx + 1, pad.top + plotH - bestH, barW / 2 - 1, bestH);

    // Label
    ctx.fillStyle = '#8A8F98';
    ctx.font = '9px "IBM Plex Mono", monospace';
    ctx.textAlign = 'center';
    ctx.fillText(`Stint ${s.stint_number}`, cx, h - 15);
    ctx.fillText(`${s.laps_count}L`, cx, h - 5);
  }

  // Legend
  ctx.font = '9px "IBM Plex Mono", monospace';
  ctx.textAlign = 'left';
  ctx.fillStyle = '#FFD400';
  ctx.fillRect(pad.left + 5, pad.top + 3, 10, 3);
  ctx.fillStyle = '#8A8F98';
  ctx.fillText('Avg', pad.left + 20, pad.top + 6);
  ctx.fillStyle = '#B6FF2E';
  ctx.fillRect(pad.left + 50, pad.top + 3, 10, 3);
  ctx.fillStyle = '#8A8F98';
  ctx.fillText('Best', pad.left + 65, pad.top + 6);
}

export function StintChart({ sessionId }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'stints'],
    queryFn: () => api.get<StintData>(`/sessions/${sessionId}/stints`),
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

  if (isLoading) return <ChartPanel title="Stint Analysis"><div className="h-48 flex items-center justify-center"><div className="w-6 h-6 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" /></div></ChartPanel>;
  if (!data || data.stints.length === 0) return <ChartPanel title="Stint Analysis"><div className="h-48 flex items-center justify-center text-steel font-telemetry text-xs">No data available</div></ChartPanel>;

  return (
    <ChartPanel title="Stint Analysis" subtitle="Performance breakdown by stint">
      <canvas ref={canvasRef} className="w-full h-48" />
    </ChartPanel>
  );
}
