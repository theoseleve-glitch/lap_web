'use client';

import { useCallback, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import { PageHeader, ChartPanel } from '@/components/app';
import { useCanvas } from '@/hooks/useCanvas';

/* ---------- types ---------- */

interface MeteoPoint {
  temperature: number;
  humidity: number;
  pressure: number;
  score: number;
  best_time: number;
}

interface MeteoResponse {
  points: MeteoPoint[];
}

/* ---------- generic scatter helper ---------- */

function drawScatter(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  points: MeteoPoint[],
  xField: keyof MeteoPoint,
  yField: keyof MeteoPoint,
  xLabel: string,
  yLabel: string,
  dotColor: string,
) {
  ctx.fillStyle = '#0B0C0F';
  ctx.fillRect(0, 0, width, height);

  if (points.length === 0) {
    ctx.fillStyle = '#8A8F98';
    ctx.font = '12px "IBM Plex Mono", monospace';
    ctx.textAlign = 'center';
    ctx.fillText('No data available', width / 2, height / 2);
    return;
  }

  const pad = { top: 20, right: 20, bottom: 36, left: 52 };
  const drawW = width - pad.left - pad.right;
  const drawH = height - pad.top - pad.bottom;

  const xs = points.map((p) => p[xField] as number);
  const ys = points.map((p) => p[yField] as number);
  const xRange = Math.max(...xs) - Math.min(...xs) || 1;
  const yRange = Math.max(...ys) - Math.min(...ys) || 1;
  const minX = Math.min(...xs) - xRange * 0.05;
  const maxX = Math.max(...xs) + xRange * 0.05;
  const minY = Math.min(...ys) - yRange * 0.05;
  const maxY = Math.max(...ys) + yRange * 0.05;
  const xR = maxX - minX;
  const yR = maxY - minY;

  const toX = (v: number) => pad.left + ((v - minX) / xR) * drawW;
  const toY = (v: number) => pad.top + drawH - ((v - minY) / yR) * drawH;

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
  for (let i = 0; i <= 4; i++) {
    const x = pad.left + (i / 4) * drawW;
    ctx.beginPath();
    ctx.moveTo(x, pad.top);
    ctx.lineTo(x, pad.top + drawH);
    ctx.stroke();
  }

  // Points
  for (const pt of points) {
    ctx.beginPath();
    ctx.arc(toX(pt[xField] as number), toY(pt[yField] as number), 4, 0, Math.PI * 2);
    ctx.fillStyle = dotColor + '70';
    ctx.fill();
    ctx.strokeStyle = dotColor;
    ctx.lineWidth = 1;
    ctx.stroke();
  }

  // Axis labels
  ctx.fillStyle = '#8A8F98';
  ctx.font = '9px "IBM Plex Mono", monospace';
  ctx.textAlign = 'center';
  ctx.fillText(xLabel, width / 2, height - 6);
  ctx.save();
  ctx.translate(14, height / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText(yLabel, 0, 0);
  ctx.restore();

  // Tick labels
  for (let i = 0; i <= 4; i++) {
    const v = minX + (i / 4) * xR;
    ctx.textAlign = 'center';
    ctx.fillText(v.toFixed(1), pad.left + (i / 4) * drawW, height - pad.bottom + 14);
  }
  for (let i = 0; i <= 4; i++) {
    const v = minY + (i / 4) * yR;
    const y = pad.top + drawH - (i / 4) * drawH;
    ctx.textAlign = 'right';
    ctx.fillText(v.toFixed(1), pad.left - 6, y + 3);
  }
}

/* ---------- component ---------- */

export default function MeteoCorrelationPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['analytics-meteo'],
    queryFn: () => api.get<MeteoResponse>('/analytics/meteo'),
  });

  const points = useMemo(() => data?.points ?? [], [data]);

  const drawTemp = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number) =>
      drawScatter(ctx, w, h, points, 'temperature', 'score', 'Temperature (C)', 'Score', '#B6FF2E'),
    [points],
  );

  const drawHumidity = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number) =>
      drawScatter(ctx, w, h, points, 'humidity', 'score', 'Humidity (%)', 'Score', '#FF6A00'),
    [points],
  );

  const drawPressure = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number) =>
      drawScatter(ctx, w, h, points, 'pressure', 'best_time', 'Pressure (hPa)', 'Best Time (s)', '#FFD400'),
    [points],
  );

  const tempRef = useCanvas(drawTemp, [drawTemp]);
  const humidityRef = useCanvas(drawHumidity, [drawHumidity]);
  const pressureRef = useCanvas(drawPressure, [drawPressure]);

  const errorMsg = error ? 'Failed to load meteo data' : null;

  return (
    <div>
      <PageHeader
        title="Meteo Correlation"
        subtitle="Atmospheric conditions vs performance metrics"
      />

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
        <ChartPanel
          title="Temperature vs Score"
          subtitle="Ambient temperature correlation"
          loading={isLoading}
          error={errorMsg}
        >
          <div className="h-64 relative">
            <canvas ref={tempRef} className="absolute inset-0 w-full h-full" />
          </div>
        </ChartPanel>

        <ChartPanel
          title="Humidity vs Score"
          subtitle="Relative humidity correlation"
          loading={isLoading}
          error={errorMsg}
        >
          <div className="h-64 relative">
            <canvas ref={humidityRef} className="absolute inset-0 w-full h-full" />
          </div>
        </ChartPanel>
      </div>

      <ChartPanel
        title="Pressure vs Best Time"
        subtitle="Atmospheric pressure vs fastest lap"
        loading={isLoading}
        error={errorMsg}
      >
        <div className="h-64 relative">
          <canvas ref={pressureRef} className="absolute inset-0 w-full h-full" />
        </div>
      </ChartPanel>
    </div>
  );
}
