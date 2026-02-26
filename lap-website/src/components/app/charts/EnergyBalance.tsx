'use client';

import { useQuery } from '@tanstack/react-query';
import { useRef, useEffect } from 'react';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';

interface EnergyData {
  distances: number[];
  kinetic_energy: number[];
  braking_energy: number[];
}

interface Props {
  sessionId: string;
}

function draw(ctx: CanvasRenderingContext2D, w: number, h: number, data: EnergyData) {
  ctx.clearRect(0, 0, w, h);

  const { distances, kinetic_energy, braking_energy } = data;
  if (distances.length === 0) return;

  const pad = { top: 10, right: 15, bottom: 30, left: 50 };
  const plotW = w - pad.left - pad.right;
  const plotH = h - pad.top - pad.bottom;

  const minDist = distances[0];
  const maxDist = distances[distances.length - 1];
  const distRange = maxDist - minDist || 1;
  const allE = [...kinetic_energy, ...braking_energy];
  const maxE = Math.max(...allE, 0.001);
  const minE = Math.min(...allE, 0);
  const eRange = maxE - minE || 1;

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

  // Y labels
  ctx.fillStyle = '#8A8F98';
  ctx.font = '10px "IBM Plex Mono", monospace';
  ctx.textAlign = 'right';
  for (let i = 0; i <= 4; i++) {
    const val = maxE - (i / 4) * eRange;
    ctx.fillText(`${(val / 1000).toFixed(1)}kJ`, pad.left - 5, pad.top + (i / 4) * plotH + 3);
  }

  const toX = (d: number) => pad.left + ((d - minDist) / distRange) * plotW;
  const toY = (e: number) => pad.top + plotH - ((e - minE) / eRange) * plotH;

  // KE line
  ctx.beginPath();
  ctx.strokeStyle = '#B6FF2E';
  ctx.lineWidth = 1.5;
  for (let i = 0; i < distances.length; i++) {
    const x = toX(distances[i]);
    const y = toY(kinetic_energy[i]);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();

  // Braking energy line
  ctx.beginPath();
  ctx.strokeStyle = '#FF2A2A';
  ctx.lineWidth = 1.5;
  for (let i = 0; i < distances.length; i++) {
    const x = toX(distances[i]);
    const y = toY(braking_energy[i]);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();

  // Legend
  ctx.font = '9px "IBM Plex Mono", monospace';
  ctx.textAlign = 'left';
  ctx.fillStyle = '#B6FF2E';
  ctx.fillRect(pad.left + 5, pad.top + 5, 10, 3);
  ctx.fillStyle = '#8A8F98';
  ctx.fillText('Kinetic', pad.left + 20, pad.top + 9);

  ctx.fillStyle = '#FF2A2A';
  ctx.fillRect(pad.left + 75, pad.top + 5, 10, 3);
  ctx.fillStyle = '#8A8F98';
  ctx.fillText('Braking', pad.left + 90, pad.top + 9);
}

export function EnergyBalance({ sessionId }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'energy'],
    queryFn: () => api.get<EnergyData>(`/sessions/${sessionId}/energy`),
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

  if (isLoading) return <ChartPanel title="Energy Balance"><div className="h-48 flex items-center justify-center"><div className="w-6 h-6 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" /></div></ChartPanel>;
  if (!data || data.distances.length === 0) return <ChartPanel title="Energy Balance"><div className="h-48 flex items-center justify-center text-steel font-telemetry text-xs">No data available</div></ChartPanel>;

  return (
    <ChartPanel title="Energy Balance" subtitle="Kinetic energy management">
      <canvas ref={canvasRef} className="w-full h-48" />
    </ChartPanel>
  );
}
