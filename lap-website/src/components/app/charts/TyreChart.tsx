'use client';

import { useQuery } from '@tanstack/react-query';
import { useRef, useEffect } from 'react';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';

interface TyreData {
  laps: number[];
  fl_deg: number[];
  fr_deg: number[];
  rl_deg: number[];
  rr_deg: number[];
}

interface Props {
  sessionId: string;
}

const TYRE_COLORS = {
  fl: '#B6FF2E',
  fr: '#FFD400',
  rl: '#FF6A00',
  rr: '#FF2A2A',
};

function draw(ctx: CanvasRenderingContext2D, w: number, h: number, data: TyreData) {
  ctx.clearRect(0, 0, w, h);

  const { laps, fl_deg, fr_deg, rl_deg, rr_deg } = data;
  if (laps.length === 0) return;

  const pad = { top: 15, right: 15, bottom: 30, left: 40 };
  const plotW = w - pad.left - pad.right;
  const plotH = h - pad.top - pad.bottom;

  const allVals = [...fl_deg, ...fr_deg, ...rl_deg, ...rr_deg];
  const maxVal = Math.max(...allVals, 1);

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
    const val = maxVal - (i / 4) * maxVal;
    ctx.fillText(`${val.toFixed(0)}%`, pad.left - 5, pad.top + (i / 4) * plotH + 3);
  }

  const toX = (i: number) => pad.left + (i / (laps.length - 1 || 1)) * plotW;
  const toY = (v: number) => pad.top + plotH - (v / maxVal) * plotH;

  const lines: [number[], string, string][] = [
    [fl_deg, TYRE_COLORS.fl, 'FL'],
    [fr_deg, TYRE_COLORS.fr, 'FR'],
    [rl_deg, TYRE_COLORS.rl, 'RL'],
    [rr_deg, TYRE_COLORS.rr, 'RR'],
  ];

  for (const [vals, color] of lines) {
    ctx.beginPath();
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    for (let i = 0; i < laps.length; i++) {
      const x = toX(i);
      const y = toY(vals[i]);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
  }

  // X-axis labels
  ctx.fillStyle = '#8A8F98';
  ctx.font = '9px "IBM Plex Mono", monospace';
  ctx.textAlign = 'center';
  for (let i = 0; i < laps.length; i++) {
    if (laps.length <= 15 || i % Math.ceil(laps.length / 10) === 0) {
      ctx.fillText(`L${laps[i]}`, toX(i), h - 8);
    }
  }

  // Legend
  ctx.font = '9px "IBM Plex Mono", monospace';
  ctx.textAlign = 'left';
  let lx = pad.left + 5;
  for (const [, color, label] of lines) {
    ctx.fillStyle = color;
    ctx.fillRect(lx, pad.top + 2, 10, 3);
    ctx.fillStyle = '#8A8F98';
    ctx.fillText(label, lx + 14, pad.top + 6);
    lx += 38;
  }
}

export function TyreChart({ sessionId }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'tyre-data'],
    queryFn: () => api.get<TyreData>(`/sessions/${sessionId}/tyre-data`),
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

  if (isLoading) return <ChartPanel title="Tyre Degradation"><div className="h-48 flex items-center justify-center"><div className="w-6 h-6 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" /></div></ChartPanel>;
  if (!data || data.laps.length === 0) return <ChartPanel title="Tyre Degradation"><div className="h-48 flex items-center justify-center text-steel font-telemetry text-xs">No data available</div></ChartPanel>;

  return (
    <ChartPanel title="Tyre Degradation" subtitle="Wear per corner over laps">
      <canvas ref={canvasRef} className="w-full h-48" />
    </ChartPanel>
  );
}
