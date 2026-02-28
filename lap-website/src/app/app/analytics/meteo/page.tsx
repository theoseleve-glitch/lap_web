'use client';

import { useCallback, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import { PageHeader, ChartPanel, StatCard } from '@/components/app';
import { ChartTooltip } from '@/components/app/ChartTooltip';
import { useInteractiveCanvas, type HoverPoint, type TooltipData } from '@/hooks/useInteractiveCanvas';

/* ── Types ──────────────────────────────────────────────── */

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

/* ── Helpers ────────────────────────────────────────────── */

function fmtTime(s: number | null): string {
  if (s == null) return '—';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}

/* ── Interactive Scatter Chart ──────────────────────────── */

const SCATTER_PAD = { top: 15, right: 15, bottom: 30, left: 52 };

function ScatterChart({
  points,
  xField,
  yField,
  xLabel,
  yLabel,
  dotColor,
  xUnit,
  yUnit,
  yFormatter,
}: {
  points: MeteoPoint[];
  xField: keyof MeteoPoint;
  yField: keyof MeteoPoint;
  xLabel: string;
  yLabel: string;
  dotColor: string;
  xUnit?: string;
  yUnit?: string;
  yFormatter?: (v: number) => string;
}) {
  const { minX, maxX, xR, minY, maxY, yR } = useMemo(() => {
    if (points.length === 0) return { minX: 0, maxX: 1, xR: 1, minY: 0, maxY: 1, yR: 1 };
    const xs = points.map((p) => p[xField] as number);
    const ys = points.map((p) => p[yField] as number);
    const xRange = Math.max(...xs) - Math.min(...xs) || 1;
    const yRange = Math.max(...ys) - Math.min(...ys) || 1;
    return {
      minX: Math.min(...xs) - xRange * 0.05,
      maxX: Math.max(...xs) + xRange * 0.05,
      xR: (Math.max(...xs) + xRange * 0.05) - (Math.min(...xs) - xRange * 0.05),
      minY: Math.min(...ys) - yRange * 0.05,
      maxY: Math.max(...ys) + yRange * 0.05,
      yR: (Math.max(...ys) + yRange * 0.05) - (Math.min(...ys) - yRange * 0.05),
    };
  }, [points, xField, yField]);

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number, hover: HoverPoint | null) => {
      ctx.clearRect(0, 0, w, h);
      if (points.length === 0) {
        ctx.fillStyle = '#8A8F98';
        ctx.font = '12px "IBM Plex Mono", monospace';
        ctx.textAlign = 'center';
        ctx.fillText('No data available', w / 2, h / 2);
        return;
      }

      const plotW = w - SCATTER_PAD.left - SCATTER_PAD.right;
      const plotH = h - SCATTER_PAD.top - SCATTER_PAD.bottom;

      const toX = (v: number) => SCATTER_PAD.left + ((v - minX) / xR) * plotW;
      const toY = (v: number) => SCATTER_PAD.top + plotH - ((v - minY) / yR) * plotH;

      // Grid
      ctx.strokeStyle = 'rgba(138, 143, 152, 0.15)';
      ctx.lineWidth = 0.5;
      for (let i = 0; i <= 4; i++) {
        const y = SCATTER_PAD.top + (i / 4) * plotH;
        ctx.beginPath();
        ctx.moveTo(SCATTER_PAD.left, y);
        ctx.lineTo(SCATTER_PAD.left + plotW, y);
        ctx.stroke();
      }
      for (let i = 0; i <= 4; i++) {
        const x = SCATTER_PAD.left + (i / 4) * plotW;
        ctx.beginPath();
        ctx.moveTo(x, SCATTER_PAD.top);
        ctx.lineTo(x, SCATTER_PAD.top + plotH);
        ctx.stroke();
      }

      // Find nearest point for hover
      let nearestIdx = -1;
      let nearestDist = Infinity;
      if (hover) {
        const hoverXVal = minX + hover.nx * xR;
        const hoverYVal = maxY - hover.ny * yR;
        for (let i = 0; i < points.length; i++) {
          const dx = ((points[i][xField] as number) - hoverXVal) / xR;
          const dy = ((points[i][yField] as number) - hoverYVal) / yR;
          const dist = dx * dx + dy * dy;
          if (dist < nearestDist) {
            nearestDist = dist;
            nearestIdx = i;
          }
        }
        // Only highlight if close enough (within ~10% of chart)
        if (nearestDist > 0.02) nearestIdx = -1;
      }

      // Draw points
      for (let i = 0; i < points.length; i++) {
        const px = toX(points[i][xField] as number);
        const py = toY(points[i][yField] as number);
        const isHov = i === nearestIdx;
        ctx.beginPath();
        ctx.arc(px, py, isHov ? 6 : 4, 0, Math.PI * 2);
        ctx.fillStyle = isHov ? dotColor : dotColor + '70';
        ctx.fill();
        if (isHov) {
          ctx.strokeStyle = dotColor;
          ctx.lineWidth = 2;
          ctx.stroke();
        }
      }

      // Axis labels
      ctx.fillStyle = '#8A8F98';
      ctx.font = '9px "IBM Plex Mono", monospace';
      ctx.textAlign = 'center';
      ctx.fillText(xLabel, w / 2, h - 6);

      // X tick labels
      for (let i = 0; i <= 4; i++) {
        const v = minX + (i / 4) * xR;
        ctx.fillText(v.toFixed(1), SCATTER_PAD.left + (i / 4) * plotW, h - SCATTER_PAD.bottom + 14);
      }
      // Y tick labels
      ctx.textAlign = 'right';
      for (let i = 0; i <= 4; i++) {
        const v = minY + (i / 4) * yR;
        const y = SCATTER_PAD.top + plotH - (i / 4) * plotH;
        ctx.fillText(yFormatter ? yFormatter(v) : v.toFixed(1), SCATTER_PAD.left - 5, y + 3);
      }
    },
    [points, xField, yField, minX, maxX, xR, minY, maxY, yR, dotColor, xLabel, yFormatter],
  );

  const getTooltipData = useCallback(
    (hover: HoverPoint): TooltipData | null => {
      if (points.length === 0) return null;
      const hoverXVal = minX + hover.nx * xR;
      const hoverYVal = maxY - hover.ny * yR;
      let nearestIdx = -1;
      let nearestDist = Infinity;
      for (let i = 0; i < points.length; i++) {
        const dx = ((points[i][xField] as number) - hoverXVal) / xR;
        const dy = ((points[i][yField] as number) - hoverYVal) / yR;
        const dist = dx * dx + dy * dy;
        if (dist < nearestDist) {
          nearestDist = dist;
          nearestIdx = i;
        }
      }
      if (nearestDist > 0.02 || nearestIdx < 0) return null;
      const p = points[nearestIdx];
      return {
        lines: [
          { label: xLabel, value: `${(p[xField] as number).toFixed(1)}${xUnit ?? ''}`, color: dotColor },
          { label: yLabel, value: yFormatter ? yFormatter(p[yField] as number) : `${(p[yField] as number).toFixed(1)}${yUnit ?? ''}` },
        ],
      };
    },
    [points, xField, yField, minX, maxX, xR, minY, maxY, yR, dotColor, xLabel, yLabel, xUnit, yUnit, yFormatter],
  );

  const { canvasRef, containerRef, tooltip } = useInteractiveCanvas({
    draw,
    deps: [points],
    padding: SCATTER_PAD,
    getTooltipData,
  });

  return (
    <div ref={containerRef} className="relative">
      <canvas ref={canvasRef} className="w-full h-64" />
      <ChartTooltip tooltip={tooltip} />
    </div>
  );
}

/* ── Main Page ──────────────────────────────────────────── */

export default function MeteoCorrelationPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['analytics-meteo'],
    queryFn: () => api.get<MeteoResponse>('/analytics/meteo'),
  });

  const points = useMemo(() => data?.points ?? [], [data]);

  // Summary stats
  const avgTemp = points.length > 0
    ? points.reduce((s, p) => s + p.temperature, 0) / points.length : null;
  const avgHumidity = points.length > 0
    ? points.reduce((s, p) => s + p.humidity, 0) / points.length : null;
  const bestLap = points.length > 0
    ? Math.min(...points.map((p) => p.best_time)) : null;

  return (
    <div>
      <PageHeader
        title="Meteo Correlation"
        subtitle="Atmospheric conditions vs performance metrics"
      />

      {/* ── Stats ───────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <StatCard label="Data Points" value={points.length} />
        <StatCard label="Avg Temp" value={avgTemp != null ? `${avgTemp.toFixed(1)}` : '—'} unit="°C" />
        <StatCard label="Avg Humidity" value={avgHumidity != null ? `${avgHumidity.toFixed(0)}` : '—'} unit="%" />
        <StatCard label="Best Lap" value={fmtTime(bestLap)} />
      </div>

      {/* ── Charts ──────────────────────────────────────── */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
        <ChartPanel
          title="Temperature vs Score"
          subtitle="Ambient temperature correlation"
          loading={isLoading}
          error={error ? 'Failed to load meteo data' : null}
        >
          <ScatterChart
            points={points}
            xField="temperature"
            yField="score"
            xLabel="Temperature (°C)"
            yLabel="Score"
            dotColor="#B6FF2E"
            xUnit="°C"
            yUnit="/100"
          />
        </ChartPanel>

        <ChartPanel
          title="Humidity vs Score"
          subtitle="Relative humidity correlation"
          loading={isLoading}
          error={error ? 'Failed to load meteo data' : null}
        >
          <ScatterChart
            points={points}
            xField="humidity"
            yField="score"
            xLabel="Humidity (%)"
            yLabel="Score"
            dotColor="#FF6A00"
            xUnit="%"
            yUnit="/100"
          />
        </ChartPanel>
      </div>

      <ChartPanel
        title="Pressure vs Best Time"
        subtitle="Atmospheric pressure vs fastest lap"
        loading={isLoading}
        error={error ? 'Failed to load meteo data' : null}
      >
        <ScatterChart
          points={points}
          xField="pressure"
          yField="best_time"
          xLabel="Pressure (hPa)"
          yLabel="Best Time"
          dotColor="#FFD400"
          xUnit=" hPa"
          yFormatter={(v) => fmtTime(v)}
        />
      </ChartPanel>
    </div>
  );
}
