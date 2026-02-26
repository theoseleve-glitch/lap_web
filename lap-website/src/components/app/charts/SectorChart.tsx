'use client';

import { useQuery } from '@tanstack/react-query';
import { useRef, useEffect } from 'react';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';

interface SectorData {
  sectors: { name: string; best: number; avg: number; worst: number }[];
}

interface Props {
  sessionId: string;
}

const COLORS = { best: '#B6FF2E', avg: '#FFD400', worst: '#FF2A2A' };

function draw(ctx: CanvasRenderingContext2D, w: number, h: number, data: SectorData) {
  ctx.clearRect(0, 0, w, h);

  const { sectors } = data;
  if (sectors.length === 0) return;

  const pad = { top: 20, right: 15, bottom: 30, left: 50 };
  const plotW = w - pad.left - pad.right;
  const plotH = h - pad.top - pad.bottom;

  const allTimes = sectors.flatMap((s) => [s.best, s.avg, s.worst]);
  const maxTime = Math.max(...allTimes);

  const groupW = plotW / sectors.length;
  const barW = Math.min(12, groupW / 4);

  // Y-axis grid
  ctx.strokeStyle = 'rgba(138, 143, 152, 0.15)';
  ctx.lineWidth = 0.5;
  for (let i = 0; i <= 4; i++) {
    const y = pad.top + (i / 4) * plotH;
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(pad.left + plotW, y);
    ctx.stroke();

    ctx.fillStyle = '#8A8F98';
    ctx.font = '10px "IBM Plex Mono", monospace';
    ctx.textAlign = 'right';
    const val = maxTime - (i / 4) * maxTime;
    ctx.fillText(`${val.toFixed(1)}s`, pad.left - 5, y + 3);
  }

  // Legend
  ctx.font = '9px "IBM Plex Mono", monospace';
  ctx.textAlign = 'left';
  let lx = pad.left;
  for (const [label, color] of Object.entries(COLORS)) {
    ctx.fillStyle = color;
    ctx.fillRect(lx, pad.top - 14, 8, 8);
    ctx.fillStyle = '#8A8F98';
    ctx.fillText(label, lx + 11, pad.top - 7);
    lx += 50;
  }

  // Bars per sector
  for (let i = 0; i < sectors.length; i++) {
    const s = sectors[i];
    const cx = pad.left + i * groupW + groupW / 2;

    const vals = [
      { v: s.best, c: COLORS.best },
      { v: s.avg, c: COLORS.avg },
      { v: s.worst, c: COLORS.worst },
    ];

    for (let j = 0; j < vals.length; j++) {
      const barH = (vals[j].v / maxTime) * plotH;
      const x = cx + (j - 1) * (barW + 2) - barW / 2;
      ctx.fillStyle = vals[j].c;
      ctx.fillRect(x, pad.top + plotH - barH, barW, barH);
    }

    // Sector label
    ctx.fillStyle = '#8A8F98';
    ctx.font = '10px "IBM Plex Mono", monospace';
    ctx.textAlign = 'center';
    ctx.fillText(s.name, cx, h - 8);
  }
}

export function SectorChart({ sessionId }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'sectors'],
    queryFn: () => api.get<SectorData>(`/sessions/${sessionId}/sectors`),
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

  if (isLoading) return <ChartPanel title="Sector Times"><div className="h-48 flex items-center justify-center"><div className="w-6 h-6 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" /></div></ChartPanel>;
  if (!data || data.sectors.length === 0) return <ChartPanel title="Sector Times"><div className="h-48 flex items-center justify-center text-steel font-telemetry text-xs">No data available</div></ChartPanel>;

  return (
    <ChartPanel title="Sector Times" subtitle="Best / avg / worst comparison">
      <canvas ref={canvasRef} className="w-full h-48" />
    </ChartPanel>
  );
}
