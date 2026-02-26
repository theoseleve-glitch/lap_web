'use client';

import { useQuery } from '@tanstack/react-query';
import { useRef, useEffect } from 'react';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';

interface StyleData {
  labels: string[];
  values: number[];
}

interface Props {
  sessionId: string;
}

function draw(ctx: CanvasRenderingContext2D, w: number, h: number, data: StyleData) {
  ctx.clearRect(0, 0, w, h);

  const { labels, values } = data;
  if (labels.length === 0) return;

  const cx = w / 2;
  const cy = h / 2;
  const radius = Math.min(cx, cy) - 30;
  const n = labels.length;
  const angleStep = (Math.PI * 2) / n;

  // Grid rings
  for (let ring = 1; ring <= 5; ring++) {
    const r = (ring / 5) * radius;
    ctx.beginPath();
    ctx.strokeStyle = 'rgba(138, 143, 152, 0.15)';
    ctx.lineWidth = 0.5;
    for (let i = 0; i <= n; i++) {
      const angle = i * angleStep - Math.PI / 2;
      const x = cx + Math.cos(angle) * r;
      const y = cy + Math.sin(angle) * r;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.closePath();
    ctx.stroke();
  }

  // Axis lines + labels
  ctx.fillStyle = '#8A8F98';
  ctx.font = '10px "IBM Plex Mono", monospace';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  for (let i = 0; i < n; i++) {
    const angle = i * angleStep - Math.PI / 2;
    const xEnd = cx + Math.cos(angle) * radius;
    const yEnd = cy + Math.sin(angle) * radius;

    ctx.beginPath();
    ctx.strokeStyle = 'rgba(138, 143, 152, 0.2)';
    ctx.moveTo(cx, cy);
    ctx.lineTo(xEnd, yEnd);
    ctx.stroke();

    const labelR = radius + 15;
    const lx = cx + Math.cos(angle) * labelR;
    const ly = cy + Math.sin(angle) * labelR;
    ctx.fillText(labels[i], lx, ly);
  }

  // Data polygon
  ctx.beginPath();
  for (let i = 0; i < n; i++) {
    const val = Math.max(0, Math.min(1, values[i]));
    const angle = i * angleStep - Math.PI / 2;
    const r = val * radius;
    const x = cx + Math.cos(angle) * r;
    const y = cy + Math.sin(angle) * r;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.closePath();
  ctx.fillStyle = '#B6FF2E22';
  ctx.fill();
  ctx.strokeStyle = '#B6FF2E';
  ctx.lineWidth = 2;
  ctx.stroke();

  // Data points
  for (let i = 0; i < n; i++) {
    const val = Math.max(0, Math.min(1, values[i]));
    const angle = i * angleStep - Math.PI / 2;
    const r = val * radius;
    const x = cx + Math.cos(angle) * r;
    const y = cy + Math.sin(angle) * r;
    ctx.beginPath();
    ctx.arc(x, y, 3, 0, Math.PI * 2);
    ctx.fillStyle = '#B6FF2E';
    ctx.fill();
  }
}

export function DrivingStyle({ sessionId }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'style'],
    queryFn: () => api.get<StyleData>(`/sessions/${sessionId}/style`),
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

  if (isLoading) return <ChartPanel title="Driving Style"><div className="h-48 flex items-center justify-center"><div className="w-6 h-6 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" /></div></ChartPanel>;
  if (!data || data.labels.length === 0) return <ChartPanel title="Driving Style"><div className="h-48 flex items-center justify-center text-steel font-telemetry text-xs">No data available</div></ChartPanel>;

  return (
    <ChartPanel title="Driving Style" subtitle="Radar chart of style metrics">
      <canvas ref={canvasRef} className="w-full h-48" />
    </ChartPanel>
  );
}
