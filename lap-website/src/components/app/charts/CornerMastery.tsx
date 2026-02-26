'use client';

import { useQuery } from '@tanstack/react-query';
import { useRef, useEffect } from 'react';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';

interface CornerMasteryData {
  corners: {
    name: string;
    score: number;
    entry_speed: number;
    apex_speed: number;
    exit_speed: number;
  }[];
}

interface Props {
  sessionId: string;
}

function draw(ctx: CanvasRenderingContext2D, w: number, h: number, data: CornerMasteryData) {
  ctx.clearRect(0, 0, w, h);

  const { corners } = data;
  if (corners.length === 0) return;

  const pad = { top: 15, right: 15, bottom: 30, left: 55 };
  const plotW = w - pad.left - pad.right;
  const plotH = h - pad.top - pad.bottom;
  const rowH = Math.min(20, plotH / corners.length);

  for (let i = 0; i < corners.length; i++) {
    const c = corners[i];
    const y = pad.top + i * rowH;

    // Corner name
    ctx.fillStyle = '#8A8F98';
    ctx.font = '9px "IBM Plex Mono", monospace';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    ctx.fillText(c.name, pad.left - 5, y + rowH / 2);

    // Score bar
    const score = Math.max(0, Math.min(1, c.score));
    const barW = score * plotW;

    const barColor = score >= 0.8 ? '#B6FF2E' : score >= 0.5 ? '#FFD400' : '#FF2A2A';
    ctx.fillStyle = 'rgba(138, 143, 152, 0.08)';
    ctx.fillRect(pad.left, y + 2, plotW, rowH - 4);
    ctx.fillStyle = barColor + '88';
    ctx.fillRect(pad.left, y + 2, barW, rowH - 4);

    // Speed indicators
    if (plotW > 200) {
      ctx.font = '8px "IBM Plex Mono", monospace';
      ctx.textAlign = 'left';
      ctx.fillStyle = '#F3F0E8';
      ctx.fillText(
        `E:${c.entry_speed.toFixed(0)} A:${c.apex_speed.toFixed(0)} X:${c.exit_speed.toFixed(0)}`,
        pad.left + barW + 5,
        y + rowH / 2,
      );
    }
  }

  // Legend
  ctx.fillStyle = '#8A8F98';
  ctx.font = '9px "IBM Plex Mono", monospace';
  ctx.textAlign = 'center';
  ctx.fillText('E=Entry  A=Apex  X=Exit (km/h)', w / 2, h - 5);
}

export function CornerMastery({ sessionId }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'corner-mastery'],
    queryFn: () => api.get<CornerMasteryData>(`/sessions/${sessionId}/corner-mastery`),
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

  if (isLoading) return <ChartPanel title="Corner Mastery"><div className="h-48 flex items-center justify-center"><div className="w-6 h-6 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" /></div></ChartPanel>;
  if (!data || data.corners.length === 0) return <ChartPanel title="Corner Mastery"><div className="h-48 flex items-center justify-center text-steel font-telemetry text-xs">No data available</div></ChartPanel>;

  return (
    <ChartPanel title="Corner Mastery" subtitle="Corner-by-corner performance">
      <canvas ref={canvasRef} className="w-full h-48" />
    </ChartPanel>
  );
}
