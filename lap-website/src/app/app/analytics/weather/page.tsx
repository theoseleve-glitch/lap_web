'use client';

import { useCallback, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import { PageHeader, ChartPanel } from '@/components/app';
import { useCanvas } from '@/hooks/useCanvas';

/* ---------- types ---------- */

interface WeatherPoint {
  temperature: number;
  lap_time: number;
  wind_speed: number;
  wind_direction: number;
}

interface WeatherResponse {
  points: WeatherPoint[];
}

/* ---------- component ---------- */

export default function WeatherAnalysisPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['analytics-weather'],
    queryFn: () => api.get<WeatherResponse>('/analytics/weather'),
  });

  const points = useMemo(() => data?.points ?? [], [data]);

  /* ---------- temperature vs lap time scatter ---------- */
  const drawTempChart = useCallback(
    (ctx: CanvasRenderingContext2D, width: number, height: number) => {
      ctx.fillStyle = '#0B0C0F';
      ctx.fillRect(0, 0, width, height);

      if (points.length === 0) {
        ctx.fillStyle = '#8A8F98';
        ctx.font = '12px "IBM Plex Mono", monospace';
        ctx.textAlign = 'center';
        ctx.fillText('No weather data available', width / 2, height / 2);
        return;
      }

      const pad = { top: 20, right: 20, bottom: 36, left: 52 };
      const drawW = width - pad.left - pad.right;
      const drawH = height - pad.top - pad.bottom;

      const temps = points.map((p) => p.temperature);
      const times = points.map((p) => p.lap_time);
      const minT = Math.min(...temps) - 2;
      const maxT = Math.max(...temps) + 2;
      const minL = Math.min(...times) * 0.98;
      const maxL = Math.max(...times) * 1.02;

      const toX = (t: number) => pad.left + ((t - minT) / (maxT - minT)) * drawW;
      const toY = (l: number) => pad.top + drawH - ((l - minL) / (maxL - minL)) * drawH;

      // Grid
      ctx.strokeStyle = '#8A8F9818';
      ctx.lineWidth = 1;
      for (let i = 0; i <= 4; i++) {
        const y = pad.top + (i / 4) * drawH;
        ctx.beginPath();
        ctx.moveTo(pad.left, y);
        ctx.lineTo(width - pad.right, y);
        ctx.stroke();
      }

      // Points
      for (const pt of points) {
        ctx.beginPath();
        ctx.arc(toX(pt.temperature), toY(pt.lap_time), 4, 0, Math.PI * 2);
        ctx.fillStyle = '#B6FF2E80';
        ctx.fill();
        ctx.strokeStyle = '#B6FF2E';
        ctx.lineWidth = 1;
        ctx.stroke();
      }

      // Axis labels
      ctx.fillStyle = '#8A8F98';
      ctx.font = '9px "IBM Plex Mono", monospace';
      ctx.textAlign = 'center';
      ctx.fillText('Temperature (C)', width / 2, height - 6);
      ctx.save();
      ctx.translate(14, height / 2);
      ctx.rotate(-Math.PI / 2);
      ctx.fillText('Lap Time (s)', 0, 0);
      ctx.restore();

      // Tick labels
      for (let i = 0; i <= 4; i++) {
        const t = minT + (i / 4) * (maxT - minT);
        ctx.textAlign = 'center';
        ctx.fillText(`${t.toFixed(0)}`, toX(t), height - pad.bottom + 14);
      }
      for (let i = 0; i <= 4; i++) {
        const l = minL + (i / 4) * (maxL - minL);
        const y = pad.top + drawH - (i / 4) * drawH;
        ctx.textAlign = 'right';
        ctx.fillText(`${l.toFixed(1)}`, pad.left - 6, y + 3);
      }
    },
    [points],
  );

  /* ---------- wind impact chart ---------- */
  const drawWindChart = useCallback(
    (ctx: CanvasRenderingContext2D, width: number, height: number) => {
      ctx.fillStyle = '#0B0C0F';
      ctx.fillRect(0, 0, width, height);

      if (points.length === 0) {
        ctx.fillStyle = '#8A8F98';
        ctx.font = '12px "IBM Plex Mono", monospace';
        ctx.textAlign = 'center';
        ctx.fillText('No wind data available', width / 2, height / 2);
        return;
      }

      const pad = { top: 20, right: 20, bottom: 36, left: 52 };
      const drawW = width - pad.left - pad.right;
      const drawH = height - pad.top - pad.bottom;

      const winds = points.map((p) => p.wind_speed);
      const times = points.map((p) => p.lap_time);
      const minW = 0;
      const maxW = Math.max(...winds) * 1.1 || 10;
      const minL = Math.min(...times) * 0.98;
      const maxL = Math.max(...times) * 1.02;

      const toX = (w: number) => pad.left + ((w - minW) / (maxW - minW)) * drawW;
      const toY = (l: number) => pad.top + drawH - ((l - minL) / (maxL - minL)) * drawH;

      // Grid
      ctx.strokeStyle = '#8A8F9818';
      ctx.lineWidth = 1;
      for (let i = 0; i <= 4; i++) {
        const y = pad.top + (i / 4) * drawH;
        ctx.beginPath();
        ctx.moveTo(pad.left, y);
        ctx.lineTo(width - pad.right, y);
        ctx.stroke();
      }

      // Points colored by wind direction
      for (const pt of points) {
        const hue = (pt.wind_direction / 360) * 360;
        ctx.beginPath();
        ctx.arc(toX(pt.wind_speed), toY(pt.lap_time), 4, 0, Math.PI * 2);
        ctx.fillStyle = `hsla(${hue}, 80%, 60%, 0.6)`;
        ctx.fill();
        ctx.strokeStyle = `hsla(${hue}, 80%, 60%, 1)`;
        ctx.lineWidth = 1;
        ctx.stroke();
      }

      // Axis labels
      ctx.fillStyle = '#8A8F98';
      ctx.font = '9px "IBM Plex Mono", monospace';
      ctx.textAlign = 'center';
      ctx.fillText('Wind Speed (m/s)', width / 2, height - 6);
      ctx.save();
      ctx.translate(14, height / 2);
      ctx.rotate(-Math.PI / 2);
      ctx.fillText('Lap Time (s)', 0, 0);
      ctx.restore();

      // Tick labels
      for (let i = 0; i <= 4; i++) {
        const w = minW + (i / 4) * (maxW - minW);
        ctx.textAlign = 'center';
        ctx.fillText(`${w.toFixed(0)}`, toX(w), height - pad.bottom + 14);
      }
      for (let i = 0; i <= 4; i++) {
        const l = minL + (i / 4) * (maxL - minL);
        const y = pad.top + drawH - (i / 4) * drawH;
        ctx.textAlign = 'right';
        ctx.fillText(`${l.toFixed(1)}`, pad.left - 6, y + 3);
      }
    },
    [points],
  );

  const tempRef = useCanvas(drawTempChart, [drawTempChart]);
  const windRef = useCanvas(drawWindChart, [drawWindChart]);

  const errorMsg = error ? 'Failed to load weather data' : null;

  return (
    <div>
      <PageHeader
        title="Weather Analysis"
        subtitle="Correlate weather conditions with on-track performance"
      />

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <ChartPanel
          title="Temperature vs Lap Time"
          subtitle="Scatter plot of ambient temp against best lap time"
          loading={isLoading}
          error={errorMsg}
        >
          <div className="h-72 relative">
            <canvas ref={tempRef} className="absolute inset-0 w-full h-full" />
          </div>
        </ChartPanel>

        <ChartPanel
          title="Wind Impact"
          subtitle="Wind speed vs lap time, colored by direction"
          loading={isLoading}
          error={errorMsg}
        >
          <div className="h-72 relative">
            <canvas ref={windRef} className="absolute inset-0 w-full h-full" />
          </div>
        </ChartPanel>
      </div>
    </div>
  );
}
