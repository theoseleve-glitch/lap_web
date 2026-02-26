'use client';

import { useQuery } from '@tanstack/react-query';
import { useRef, useEffect } from 'react';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';

interface FingerprintData {
  metrics: { name: string; value: number; max: number }[];
}

interface Props {
  sessionId: string;
}

function draw(ctx: CanvasRenderingContext2D, w: number, h: number, data: FingerprintData) {
  ctx.clearRect(0, 0, w, h);

  const { metrics } = data;
  if (metrics.length === 0) return;

  const pad = { top: 10, right: 15, bottom: 10, left: 100 };
  const plotW = w - pad.left - pad.right;
  const plotH = h - pad.top - pad.bottom;
  const rowH = plotH / metrics.length;

  for (let i = 0; i < metrics.length; i++) {
    const y = pad.top + i * rowH;
    const pct = metrics[i].max > 0 ? metrics[i].value / metrics[i].max : 0;
    const barW = Math.max(0, pct * plotW);

    // Label
    ctx.fillStyle = '#8A8F98';
    ctx.font = '10px "IBM Plex Mono", monospace';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    ctx.fillText(metrics[i].name, pad.left - 8, y + rowH / 2);

    // Background bar
    ctx.fillStyle = 'rgba(138, 143, 152, 0.1)';
    ctx.fillRect(pad.left, y + 4, plotW, rowH - 8);

    // Value bar
    const hue = pct > 0.7 ? '#B6FF2E' : pct > 0.4 ? '#FFD400' : '#FF6A00';
    ctx.fillStyle = hue;
    ctx.fillRect(pad.left, y + 4, barW, rowH - 8);

    // Value text
    ctx.fillStyle = '#F3F0E8';
    ctx.font = '9px "IBM Plex Mono", monospace';
    ctx.textAlign = 'left';
    ctx.fillText(
      `${metrics[i].value.toFixed(1)}`,
      pad.left + barW + 5,
      y + rowH / 2,
    );
  }
}

export function Fingerprint({ sessionId }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'fingerprint'],
    queryFn: () => api.get<FingerprintData>(`/sessions/${sessionId}/fingerprint`),
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

  if (isLoading) return <ChartPanel title="Driver Fingerprint"><div className="h-48 flex items-center justify-center"><div className="w-6 h-6 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" /></div></ChartPanel>;
  if (!data || data.metrics.length === 0) return <ChartPanel title="Driver Fingerprint"><div className="h-48 flex items-center justify-center text-steel font-telemetry text-xs">No data available</div></ChartPanel>;

  return (
    <ChartPanel title="Driver Fingerprint" subtitle="Unique driving signature">
      <canvas ref={canvasRef} className="w-full h-48" />
    </ChartPanel>
  );
}
