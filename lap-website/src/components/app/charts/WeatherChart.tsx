'use client';

import { useQuery } from '@tanstack/react-query';
import { useRef, useEffect } from 'react';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';

interface WeatherData {
  timestamps: number[];
  temperature: number[];
  humidity: number[];
  wind_speed: number[];
}

interface Props {
  sessionId: string;
}

function draw(ctx: CanvasRenderingContext2D, w: number, h: number, data: WeatherData) {
  ctx.clearRect(0, 0, w, h);

  const { timestamps, temperature, humidity, wind_speed } = data;
  if (timestamps.length === 0) return;

  const pad = { top: 15, right: 45, bottom: 25, left: 45 };
  const plotW = w - pad.left - pad.right;
  const plotH = h - pad.top - pad.bottom;

  const minT = timestamps[0];
  const maxT = timestamps[timestamps.length - 1];
  const tRange = maxT - minT || 1;

  const maxTemp = Math.max(...temperature, 1);
  const minTemp = Math.min(...temperature, 0);
  const tempRange = maxTemp - minTemp || 1;

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

  // Left Y-axis (temp)
  ctx.fillStyle = '#FF6A00';
  ctx.font = '10px "IBM Plex Mono", monospace';
  ctx.textAlign = 'right';
  for (let i = 0; i <= 4; i++) {
    const val = maxTemp - (i / 4) * tempRange;
    ctx.fillText(`${val.toFixed(0)}C`, pad.left - 5, pad.top + (i / 4) * plotH + 3);
  }

  const toX = (t: number) => pad.left + ((t - minT) / tRange) * plotW;

  // Temperature line
  ctx.beginPath();
  ctx.strokeStyle = '#FF6A00';
  ctx.lineWidth = 2;
  for (let i = 0; i < timestamps.length; i++) {
    const x = toX(timestamps[i]);
    const y = pad.top + plotH - ((temperature[i] - minTemp) / tempRange) * plotH;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();

  // Humidity (0-100%)
  const maxHumid = 100;
  ctx.beginPath();
  ctx.strokeStyle = '#B6FF2E88';
  ctx.lineWidth = 1;
  ctx.setLineDash([3, 3]);
  for (let i = 0; i < timestamps.length; i++) {
    const x = toX(timestamps[i]);
    const y = pad.top + plotH - (humidity[i] / maxHumid) * plotH;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();
  ctx.setLineDash([]);

  // Wind speed
  const maxWind = Math.max(...wind_speed, 1);
  ctx.beginPath();
  ctx.strokeStyle = '#FFD400';
  ctx.lineWidth = 1;
  for (let i = 0; i < timestamps.length; i++) {
    const x = toX(timestamps[i]);
    const y = pad.top + plotH - (wind_speed[i] / maxWind) * plotH;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();

  // Legend
  ctx.font = '9px "IBM Plex Mono", monospace';
  ctx.textAlign = 'left';
  let lx = pad.left + 5;
  const items: [string, string][] = [
    ['#FF6A00', 'Temp'],
    ['#B6FF2E', 'Humid'],
    ['#FFD400', 'Wind'],
  ];
  for (const [color, label] of items) {
    ctx.fillStyle = color;
    ctx.fillRect(lx, pad.top + 2, 10, 3);
    ctx.fillStyle = '#8A8F98';
    ctx.fillText(label, lx + 14, pad.top + 6);
    lx += 55;
  }
}

export function WeatherChart({ sessionId }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'weather'],
    queryFn: () => api.get<WeatherData>(`/sessions/${sessionId}/weather`),
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

  if (isLoading) return <ChartPanel title="Weather Conditions"><div className="h-48 flex items-center justify-center"><div className="w-6 h-6 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" /></div></ChartPanel>;
  if (!data || data.timestamps.length === 0) return <ChartPanel title="Weather Conditions"><div className="h-48 flex items-center justify-center text-steel font-telemetry text-xs">No data available</div></ChartPanel>;

  return (
    <ChartPanel title="Weather Conditions" subtitle="Temperature, humidity, wind">
      <canvas ref={canvasRef} className="w-full h-48" />
    </ChartPanel>
  );
}
