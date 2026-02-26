'use client';

import { useQuery } from '@tanstack/react-query';
import { useRef, useEffect } from 'react';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';

interface PitWindowData {
  laps: number[];
  cumulative_time: number[];
  optimal_pit_lap: number | null;
  pit_window_start: number | null;
  pit_window_end: number | null;
}

interface Props {
  sessionId: string;
}

function draw(ctx: CanvasRenderingContext2D, w: number, h: number, data: PitWindowData) {
  ctx.clearRect(0, 0, w, h);

  const { laps, cumulative_time, optimal_pit_lap, pit_window_start, pit_window_end } = data;
  if (laps.length === 0) return;

  const pad = { top: 10, right: 15, bottom: 30, left: 50 };
  const plotW = w - pad.left - pad.right;
  const plotH = h - pad.top - pad.bottom;

  const maxTime = Math.max(...cumulative_time, 1);
  const maxLap = laps[laps.length - 1];
  const minLap = laps[0];
  const lapRange = maxLap - minLap || 1;

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

  const toX = (lap: number) => pad.left + ((lap - minLap) / lapRange) * plotW;
  const toY = (t: number) => pad.top + plotH - (t / maxTime) * plotH;

  // Pit window highlight
  if (pit_window_start != null && pit_window_end != null) {
    const x1 = toX(pit_window_start);
    const x2 = toX(pit_window_end);
    ctx.fillStyle = '#B6FF2E11';
    ctx.fillRect(x1, pad.top, x2 - x1, plotH);
    ctx.strokeStyle = '#B6FF2E44';
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(x1, pad.top);
    ctx.lineTo(x1, pad.top + plotH);
    ctx.moveTo(x2, pad.top);
    ctx.lineTo(x2, pad.top + plotH);
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.fillStyle = '#B6FF2E';
    ctx.font = '9px "IBM Plex Mono", monospace';
    ctx.textAlign = 'center';
    ctx.fillText('PIT WINDOW', (x1 + x2) / 2, pad.top + 12);
  }

  // Cumulative time line
  ctx.beginPath();
  ctx.strokeStyle = '#F3F0E8';
  ctx.lineWidth = 2;
  for (let i = 0; i < laps.length; i++) {
    const x = toX(laps[i]);
    const y = toY(cumulative_time[i]);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();

  // Optimal pit marker
  if (optimal_pit_lap != null) {
    const ox = toX(optimal_pit_lap);
    ctx.beginPath();
    ctx.arc(ox, pad.top + plotH * 0.3, 5, 0, Math.PI * 2);
    ctx.fillStyle = '#B6FF2E';
    ctx.fill();
    ctx.fillStyle = '#B6FF2E';
    ctx.font = '9px "IBM Plex Mono", monospace';
    ctx.textAlign = 'center';
    ctx.fillText(`Opt: L${optimal_pit_lap}`, ox, pad.top + plotH * 0.3 - 10);
  }

  // X-axis labels
  ctx.fillStyle = '#8A8F98';
  ctx.font = '9px "IBM Plex Mono", monospace';
  ctx.textAlign = 'center';
  for (let i = 0; i < laps.length; i++) {
    if (laps.length <= 15 || i % Math.ceil(laps.length / 10) === 0) {
      ctx.fillText(`L${laps[i]}`, toX(laps[i]), h - 8);
    }
  }
}

export function PitWindowChart({ sessionId }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'pit-window'],
    queryFn: () => api.get<PitWindowData>(`/sessions/${sessionId}/pit-window`),
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

  if (isLoading) return <ChartPanel title="Pit Window"><div className="h-48 flex items-center justify-center"><div className="w-6 h-6 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" /></div></ChartPanel>;
  if (!data || data.laps.length === 0) return <ChartPanel title="Pit Window"><div className="h-48 flex items-center justify-center text-steel font-telemetry text-xs">No data available</div></ChartPanel>;

  return (
    <ChartPanel title="Pit Window" subtitle="Optimal pit stop timing">
      <canvas ref={canvasRef} className="w-full h-48" />
    </ChartPanel>
  );
}
