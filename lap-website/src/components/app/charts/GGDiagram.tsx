'use client';

import { useQuery } from '@tanstack/react-query';
import { useRef, useEffect } from 'react';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';

interface GGData {
  lat_g: number[];
  lon_g: number[];
}

interface Props {
  sessionId: string;
}

function draw(ctx: CanvasRenderingContext2D, w: number, h: number, data: GGData) {
  ctx.clearRect(0, 0, w, h);

  const { lat_g, lon_g } = data;
  if (lat_g.length === 0) return;

  const pad = { top: 15, right: 15, bottom: 30, left: 45 };
  const plotW = w - pad.left - pad.right;
  const plotH = h - pad.top - pad.bottom;

  const allG = [...lat_g, ...lon_g];
  const maxG = Math.max(...allG.map(Math.abs), 0.5);
  // Grid / crosshairs
  ctx.strokeStyle = 'rgba(138, 143, 152, 0.2)';
  ctx.lineWidth = 0.5;
  const cx = pad.left + plotW / 2;
  const cy = pad.top + plotH / 2;

  ctx.beginPath();
  ctx.moveTo(pad.left, cy);
  ctx.lineTo(pad.left + plotW, cy);
  ctx.moveTo(cx, pad.top);
  ctx.lineTo(cx, pad.top + plotH);
  ctx.stroke();

  // Circle guides
  ctx.strokeStyle = 'rgba(138, 143, 152, 0.1)';
  for (let r = 0.25; r <= maxG; r += 0.25) {
    const rPx = (r / maxG) * (Math.min(plotW, plotH) / 2);
    ctx.beginPath();
    ctx.arc(cx, cy, rPx, 0, Math.PI * 2);
    ctx.stroke();
  }

  // Labels
  ctx.fillStyle = '#8A8F98';
  ctx.font = '10px "IBM Plex Mono", monospace';
  ctx.textAlign = 'center';
  ctx.fillText('Lateral G', cx, h - 5);
  ctx.save();
  ctx.translate(12, cy);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText('Lon G', 0, 0);
  ctx.restore();

  // Scatter points
  for (let i = 0; i < lat_g.length; i++) {
    const x = cx + (lat_g[i] / maxG) * (plotW / 2);
    const y = cy - (lon_g[i] / maxG) * (plotH / 2);
    ctx.beginPath();
    ctx.arc(x, y, 1.5, 0, Math.PI * 2);
    ctx.fillStyle = lon_g[i] > 0 ? '#B6FF2E88' : '#FF2A2A88';
    ctx.fill();
  }
}

export function GGDiagram({ sessionId }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'gg-data'],
    queryFn: () => api.get<GGData>(`/sessions/${sessionId}/gg-data`),
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

  if (isLoading) return <ChartPanel title="GG Diagram"><div className="h-48 flex items-center justify-center"><div className="w-6 h-6 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" /></div></ChartPanel>;
  if (!data || data.lat_g.length === 0) return <ChartPanel title="GG Diagram"><div className="h-48 flex items-center justify-center text-steel font-telemetry text-xs">No data available</div></ChartPanel>;

  return (
    <ChartPanel title="GG Diagram" subtitle="Lateral vs longitudinal G">
      <canvas ref={canvasRef} className="w-full h-48" />
    </ChartPanel>
  );
}
