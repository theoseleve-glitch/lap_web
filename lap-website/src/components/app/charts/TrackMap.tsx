'use client';

import { useQuery } from '@tanstack/react-query';
import { useRef, useEffect } from 'react';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';

interface GpsTraceData {
  lat: number[];
  lon: number[];
  speed: number[];
}

interface Props {
  sessionId: string;
}

function lerpColor(t: number): string {
  // 0 = safetyRed, 0.5 = marshalYellow, 1 = acidGreen
  const r = t < 0.5 ? 255 : Math.round(255 - (t - 0.5) * 2 * (255 - 182));
  const g = t < 0.5 ? Math.round(42 + t * 2 * (212 - 42)) : Math.round(212 + (t - 0.5) * 2 * (255 - 212));
  const b = t < 0.5 ? Math.round(42 - t * 2 * 42) : Math.round((t - 0.5) * 2 * 46);
  return `rgb(${r},${g},${b})`;
}

function draw(ctx: CanvasRenderingContext2D, w: number, h: number, data: GpsTraceData) {
  ctx.clearRect(0, 0, w, h);

  const { lat, lon, speed } = data;
  if (lat.length < 2) return;

  const pad = 20;
  const plotW = w - pad * 2;
  const plotH = h - pad * 2;

  const minLat = Math.min(...lat);
  const maxLat = Math.max(...lat);
  const minLon = Math.min(...lon);
  const maxLon = Math.max(...lon);
  const latRange = maxLat - minLat || 0.001;
  const lonRange = maxLon - minLon || 0.001;

  // Maintain aspect ratio
  const scaleX = plotW / lonRange;
  const scaleY = plotH / latRange;
  const scale = Math.min(scaleX, scaleY);
  const offsetX = pad + (plotW - lonRange * scale) / 2;
  const offsetY = pad + (plotH - latRange * scale) / 2;

  const toX = (lo: number) => offsetX + (lo - minLon) * scale;
  const toY = (la: number) => h - offsetY - (la - minLat) * scale;

  const minSpeed = Math.min(...speed);
  const maxSpeed = Math.max(...speed);
  const speedRange = maxSpeed - minSpeed || 1;

  // Draw track segments colored by speed
  ctx.lineWidth = 2;
  ctx.lineCap = 'round';
  for (let i = 1; i < lat.length; i++) {
    const t = (speed[i] - minSpeed) / speedRange;
    ctx.beginPath();
    ctx.strokeStyle = lerpColor(t);
    ctx.moveTo(toX(lon[i - 1]), toY(lat[i - 1]));
    ctx.lineTo(toX(lon[i]), toY(lat[i]));
    ctx.stroke();
  }

  // Start marker
  ctx.beginPath();
  ctx.arc(toX(lon[0]), toY(lat[0]), 4, 0, Math.PI * 2);
  ctx.fillStyle = '#B6FF2E';
  ctx.fill();

  // Legend
  ctx.fillStyle = '#8A8F98';
  ctx.font = '9px "IBM Plex Mono", monospace';
  ctx.textAlign = 'left';
  ctx.fillText(`${minSpeed.toFixed(0)} km/h`, pad, h - 5);
  ctx.textAlign = 'right';
  ctx.fillText(`${maxSpeed.toFixed(0)} km/h`, w - pad, h - 5);
}

export function TrackMap({ sessionId }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'gps-trace'],
    queryFn: () => api.get<GpsTraceData>(`/sessions/${sessionId}/gps-trace`),
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

  if (isLoading) return <ChartPanel title="Track Map"><div className="h-48 flex items-center justify-center"><div className="w-6 h-6 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" /></div></ChartPanel>;
  if (!data || data.lat.length === 0) return <ChartPanel title="Track Map"><div className="h-48 flex items-center justify-center text-steel font-telemetry text-xs">No data available</div></ChartPanel>;

  return (
    <ChartPanel title="Track Map" subtitle="GPS trace colored by speed">
      <canvas ref={canvasRef} className="w-full h-48" />
    </ChartPanel>
  );
}
