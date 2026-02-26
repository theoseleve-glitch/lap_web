'use client';

import { useQuery } from '@tanstack/react-query';
import { useRef, useEffect } from 'react';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';

interface SpeedProfileData {
  distances: number[];
  best_lap: number[];
  average: number[];
  worst_lap: number[];
}

interface Props {
  sessionId: string;
}

function draw(ctx: CanvasRenderingContext2D, w: number, h: number, data: SpeedProfileData) {
  ctx.clearRect(0, 0, w, h);

  const { distances, best_lap, average, worst_lap } = data;
  if (distances.length === 0) return;

  const pad = { top: 15, right: 15, bottom: 30, left: 45 };
  const plotW = w - pad.left - pad.right;
  const plotH = h - pad.top - pad.bottom;

  const allSpeeds = [...best_lap, ...average, ...worst_lap];
  const maxSpeed = Math.max(...allSpeeds);
  const minSpeed = Math.min(...allSpeeds);
  const speedRange = maxSpeed - minSpeed || 1;
  const minDist = distances[0];
  const maxDist = distances[distances.length - 1];
  const distRange = maxDist - minDist || 1;

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

  ctx.fillStyle = '#8A8F98';
  ctx.font = '10px "IBM Plex Mono", monospace';
  ctx.textAlign = 'right';
  for (let i = 0; i <= 4; i++) {
    const val = maxSpeed - (i / 4) * speedRange;
    ctx.fillText(`${val.toFixed(0)}`, pad.left - 5, pad.top + (i / 4) * plotH + 3);
  }

  const toX = (d: number) => pad.left + ((d - minDist) / distRange) * plotW;
  const toY = (s: number) => pad.top + plotH - ((s - minSpeed) / speedRange) * plotH;

  // Fill between best and worst
  ctx.beginPath();
  for (let i = 0; i < distances.length; i++) {
    const x = toX(distances[i]);
    if (i === 0) ctx.moveTo(x, toY(best_lap[i]));
    else ctx.lineTo(x, toY(best_lap[i]));
  }
  for (let i = distances.length - 1; i >= 0; i--) {
    ctx.lineTo(toX(distances[i]), toY(worst_lap[i]));
  }
  ctx.closePath();
  ctx.fillStyle = 'rgba(138, 143, 152, 0.08)';
  ctx.fill();

  // Lines
  const lines = [
    { data: worst_lap, color: '#FF2A2A66', width: 1 },
    { data: average, color: '#FFD40099', width: 1 },
    { data: best_lap, color: '#B6FF2E', width: 2 },
  ];

  for (const line of lines) {
    ctx.beginPath();
    ctx.strokeStyle = line.color;
    ctx.lineWidth = line.width;
    for (let i = 0; i < distances.length; i++) {
      const x = toX(distances[i]);
      const y = toY(line.data[i]);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
  }

  // Legend
  ctx.font = '9px "IBM Plex Mono", monospace';
  ctx.textAlign = 'left';
  ctx.fillStyle = '#B6FF2E';
  ctx.fillRect(pad.left + 5, pad.top + 2, 10, 3);
  ctx.fillStyle = '#8A8F98';
  ctx.fillText('Best', pad.left + 20, pad.top + 6);
  ctx.fillStyle = '#FFD400';
  ctx.fillRect(pad.left + 55, pad.top + 2, 10, 3);
  ctx.fillStyle = '#8A8F98';
  ctx.fillText('Avg', pad.left + 70, pad.top + 6);
  ctx.fillStyle = '#FF2A2A';
  ctx.fillRect(pad.left + 100, pad.top + 2, 10, 3);
  ctx.fillStyle = '#8A8F98';
  ctx.fillText('Worst', pad.left + 115, pad.top + 6);
}

export function SpeedProfile({ sessionId }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'speed-profile'],
    queryFn: () => api.get<SpeedProfileData>(`/sessions/${sessionId}/speed-profile`),
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

  if (isLoading) return <ChartPanel title="Speed Profile"><div className="h-48 flex items-center justify-center"><div className="w-6 h-6 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" /></div></ChartPanel>;
  if (!data || data.distances.length === 0) return <ChartPanel title="Speed Profile"><div className="h-48 flex items-center justify-center text-steel font-telemetry text-xs">No data available</div></ChartPanel>;

  return (
    <ChartPanel title="Speed Profile" subtitle="Best / avg / worst overlay">
      <canvas ref={canvasRef} className="w-full h-48" />
    </ChartPanel>
  );
}
