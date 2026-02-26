'use client';

import { useQuery } from '@tanstack/react-query';
import { useRef, useEffect } from 'react';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';

interface LapOverlayData {
  distances: number[];
  laps: { lap_number: number; speeds: number[] }[];
  best_lap: number;
}

interface Props {
  sessionId: string;
}

const LAP_COLORS = [
  '#B6FF2E', '#FF6A00', '#FFD400', '#FF2A2A',
  '#8A8F98', '#B6FF2E88', '#FF6A0088', '#FFD40088',
];

function draw(ctx: CanvasRenderingContext2D, w: number, h: number, data: LapOverlayData) {
  ctx.clearRect(0, 0, w, h);

  const { distances, laps, best_lap } = data;
  if (distances.length === 0 || laps.length === 0) return;

  const pad = { top: 15, right: 15, bottom: 30, left: 45 };
  const plotW = w - pad.left - pad.right;
  const plotH = h - pad.top - pad.bottom;

  const allSpeeds = laps.flatMap((l) => l.speeds);
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

  // Draw non-best laps first (dimmer)
  for (let li = 0; li < laps.length; li++) {
    if (laps[li].lap_number === best_lap) continue;
    ctx.beginPath();
    ctx.strokeStyle = LAP_COLORS[li % LAP_COLORS.length] + '66';
    ctx.lineWidth = 1;
    for (let i = 0; i < distances.length && i < laps[li].speeds.length; i++) {
      const x = toX(distances[i]);
      const y = toY(laps[li].speeds[i]);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
  }

  // Draw best lap on top
  for (let li = 0; li < laps.length; li++) {
    if (laps[li].lap_number !== best_lap) continue;
    ctx.beginPath();
    ctx.strokeStyle = '#B6FF2E';
    ctx.lineWidth = 2;
    for (let i = 0; i < distances.length && i < laps[li].speeds.length; i++) {
      const x = toX(distances[i]);
      const y = toY(laps[li].speeds[i]);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
  }

  // Legend
  ctx.font = '9px "IBM Plex Mono", monospace';
  ctx.textAlign = 'left';
  let lx = pad.left + 5;
  for (let li = 0; li < Math.min(laps.length, 5); li++) {
    const isBest = laps[li].lap_number === best_lap;
    ctx.fillStyle = isBest ? '#B6FF2E' : LAP_COLORS[li % LAP_COLORS.length];
    ctx.fillRect(lx, pad.top + 2, 10, 3);
    ctx.fillStyle = '#8A8F98';
    ctx.fillText(`L${laps[li].lap_number}`, lx + 14, pad.top + 6);
    lx += 40;
  }
}

export function LapOverlay({ sessionId }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'lap-overlay'],
    queryFn: () => api.get<LapOverlayData>(`/sessions/${sessionId}/lap-overlay`),
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

  if (isLoading) return <ChartPanel title="Lap Overlay"><div className="h-48 flex items-center justify-center"><div className="w-6 h-6 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" /></div></ChartPanel>;
  if (!data || data.laps.length === 0) return <ChartPanel title="Lap Overlay"><div className="h-48 flex items-center justify-center text-steel font-telemetry text-xs">No data available</div></ChartPanel>;

  return (
    <ChartPanel title="Lap Overlay" subtitle="Multi-lap speed comparison">
      <canvas ref={canvasRef} className="w-full h-48" />
    </ChartPanel>
  );
}
