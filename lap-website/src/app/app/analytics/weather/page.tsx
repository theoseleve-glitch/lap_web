'use client';

import { useCallback, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import { PageHeader, ChartPanel, StatCard } from '@/components/app';
import { ChartTooltip } from '@/components/app/ChartTooltip';
import { useInteractiveCanvas, type HoverPoint, type TooltipData } from '@/hooks/useInteractiveCanvas';

/* ── Types ──────────────────────────────────────────────── */

interface WeatherPoint {
  temperature: number;
  lap_time: number;
  wind_speed: number;
  wind_direction: number;
}

interface WeatherResponse {
  points: WeatherPoint[];
}

/* ── Helpers ────────────────────────────────────────────── */

function fmtTime(s: number): string {
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}

function windDirLabel(deg: number): string {
  const dirs = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
  return dirs[Math.round(deg / 45) % 8];
}

/* ── Temperature vs Lap Time Chart ─────────────────────── */

const TEMP_PAD = { top: 15, right: 15, bottom: 30, left: 52 };

function TempLapChart({ points }: { points: WeatherPoint[] }) {
  const { minT, maxT, tR, minL, maxL, lR } = useMemo(() => {
    if (points.length === 0) return { minT: 0, maxT: 40, tR: 40, minL: 30, maxL: 60, lR: 30 };
    const temps = points.map((p) => p.temperature);
    const times = points.map((p) => p.lap_time);
    const tRange = Math.max(...temps) - Math.min(...temps) || 1;
    const lRange = Math.max(...times) - Math.min(...times) || 1;
    return {
      minT: Math.min(...temps) - tRange * 0.05,
      maxT: Math.max(...temps) + tRange * 0.05,
      tR: (Math.max(...temps) + tRange * 0.05) - (Math.min(...temps) - tRange * 0.05),
      minL: Math.min(...times) - lRange * 0.05,
      maxL: Math.max(...times) + lRange * 0.05,
      lR: (Math.max(...times) + lRange * 0.05) - (Math.min(...times) - lRange * 0.05),
    };
  }, [points]);

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number, hover: HoverPoint | null) => {
      ctx.clearRect(0, 0, w, h);
      if (points.length === 0) {
        ctx.fillStyle = '#8A8F98';
        ctx.font = '12px "IBM Plex Mono", monospace';
        ctx.textAlign = 'center';
        ctx.fillText('No weather data available', w / 2, h / 2);
        return;
      }

      const plotW = w - TEMP_PAD.left - TEMP_PAD.right;
      const plotH = h - TEMP_PAD.top - TEMP_PAD.bottom;
      const toX = (t: number) => TEMP_PAD.left + ((t - minT) / tR) * plotW;
      const toY = (l: number) => TEMP_PAD.top + plotH - ((l - minL) / lR) * plotH;

      // Grid
      ctx.strokeStyle = 'rgba(138, 143, 152, 0.15)';
      ctx.lineWidth = 0.5;
      for (let i = 0; i <= 4; i++) {
        const y = TEMP_PAD.top + (i / 4) * plotH;
        ctx.beginPath();
        ctx.moveTo(TEMP_PAD.left, y);
        ctx.lineTo(TEMP_PAD.left + plotW, y);
        ctx.stroke();
      }
      for (let i = 0; i <= 4; i++) {
        const x = TEMP_PAD.left + (i / 4) * plotW;
        ctx.beginPath();
        ctx.moveTo(x, TEMP_PAD.top);
        ctx.lineTo(x, TEMP_PAD.top + plotH);
        ctx.stroke();
      }

      // Find nearest point
      let nearIdx = -1;
      let nearDist = Infinity;
      if (hover) {
        const hxVal = minT + hover.nx * tR;
        const hyVal = maxL - hover.ny * lR;
        for (let i = 0; i < points.length; i++) {
          const dx = (points[i].temperature - hxVal) / tR;
          const dy = (points[i].lap_time - hyVal) / lR;
          const d = dx * dx + dy * dy;
          if (d < nearDist) { nearDist = d; nearIdx = i; }
        }
        if (nearDist > 0.02) nearIdx = -1;
      }

      // Draw dots — color by temperature (cool=blue, warm=orange, hot=red)
      for (let i = 0; i < points.length; i++) {
        const pt = points[i];
        const tempNorm = (pt.temperature - minT) / tR;
        const r = Math.round(50 + tempNorm * 200);
        const g = Math.round(200 - tempNorm * 150);
        const b = Math.round(255 - tempNorm * 200);
        const isHov = i === nearIdx;

        ctx.beginPath();
        ctx.arc(toX(pt.temperature), toY(pt.lap_time), isHov ? 6 : 4, 0, Math.PI * 2);
        ctx.fillStyle = isHov ? `rgb(${r}, ${g}, ${b})` : `rgba(${r}, ${g}, ${b}, 0.6)`;
        ctx.fill();
        if (isHov) {
          ctx.strokeStyle = `rgb(${r}, ${g}, ${b})`;
          ctx.lineWidth = 2;
          ctx.stroke();
        }
      }

      // Axis labels
      ctx.fillStyle = '#8A8F98';
      ctx.font = '9px "IBM Plex Mono", monospace';
      ctx.textAlign = 'center';
      ctx.fillText('Temperature (°C)', w / 2, h - 6);

      // X ticks
      for (let i = 0; i <= 4; i++) {
        const v = minT + (i / 4) * tR;
        ctx.fillText(`${v.toFixed(0)}°`, TEMP_PAD.left + (i / 4) * plotW, h - TEMP_PAD.bottom + 14);
      }
      // Y ticks
      ctx.textAlign = 'right';
      for (let i = 0; i <= 4; i++) {
        const v = minL + (i / 4) * lR;
        ctx.fillText(fmtTime(v), TEMP_PAD.left - 5, TEMP_PAD.top + plotH - (i / 4) * plotH + 3);
      }
    },
    [points, minT, maxT, tR, minL, maxL, lR],
  );

  const getTooltipData = useCallback(
    (hover: HoverPoint): TooltipData | null => {
      if (points.length === 0) return null;
      const hxVal = minT + hover.nx * tR;
      const hyVal = maxL - hover.ny * lR;
      let nearIdx = -1;
      let nearDist = Infinity;
      for (let i = 0; i < points.length; i++) {
        const dx = (points[i].temperature - hxVal) / tR;
        const dy = (points[i].lap_time - hyVal) / lR;
        const d = dx * dx + dy * dy;
        if (d < nearDist) { nearDist = d; nearIdx = i; }
      }
      if (nearDist > 0.02 || nearIdx < 0) return null;
      const p = points[nearIdx];
      return {
        lines: [
          { label: 'Temp', value: `${p.temperature.toFixed(1)}°C`, color: '#FF6A00' },
          { label: 'Lap Time', value: fmtTime(p.lap_time) },
        ],
      };
    },
    [points, minT, maxL, tR, lR],
  );

  const { canvasRef, containerRef, tooltip } = useInteractiveCanvas({
    draw,
    deps: [points],
    padding: TEMP_PAD,
    getTooltipData,
  });

  return (
    <div ref={containerRef} className="relative">
      <canvas ref={canvasRef} className="w-full h-72" />
      <ChartTooltip tooltip={tooltip} />
    </div>
  );
}

/* ── Wind Rose + Speed Chart ───────────────────────────── */

const WIND_PAD = { top: 15, right: 15, bottom: 30, left: 52 };

function WindImpactChart({ points }: { points: WeatherPoint[] }) {
  const { minW, maxW, wR, minL, maxL, lR } = useMemo(() => {
    if (points.length === 0) return { minW: 0, maxW: 10, wR: 10, minL: 30, maxL: 60, lR: 30 };
    const winds = points.map((p) => p.wind_speed);
    const times = points.map((p) => p.lap_time);
    const lRange = Math.max(...times) - Math.min(...times) || 1;
    return {
      minW: 0,
      maxW: Math.max(...winds) * 1.1 || 10,
      wR: Math.max(...winds) * 1.1 || 10,
      minL: Math.min(...times) - lRange * 0.05,
      maxL: Math.max(...times) + lRange * 0.05,
      lR: (Math.max(...times) + lRange * 0.05) - (Math.min(...times) - lRange * 0.05),
    };
  }, [points]);

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number, hover: HoverPoint | null) => {
      ctx.clearRect(0, 0, w, h);
      if (points.length === 0) {
        ctx.fillStyle = '#8A8F98';
        ctx.font = '12px "IBM Plex Mono", monospace';
        ctx.textAlign = 'center';
        ctx.fillText('No wind data available', w / 2, h / 2);
        return;
      }

      const plotW = w - WIND_PAD.left - WIND_PAD.right;
      const plotH = h - WIND_PAD.top - WIND_PAD.bottom;
      const toX = (ws: number) => WIND_PAD.left + ((ws - minW) / wR) * plotW;
      const toY = (l: number) => WIND_PAD.top + plotH - ((l - minL) / lR) * plotH;

      // Grid
      ctx.strokeStyle = 'rgba(138, 143, 152, 0.15)';
      ctx.lineWidth = 0.5;
      for (let i = 0; i <= 4; i++) {
        const y = WIND_PAD.top + (i / 4) * plotH;
        ctx.beginPath();
        ctx.moveTo(WIND_PAD.left, y);
        ctx.lineTo(WIND_PAD.left + plotW, y);
        ctx.stroke();
      }

      // Find nearest
      let nearIdx = -1;
      let nearDist = Infinity;
      if (hover) {
        const hxVal = minW + hover.nx * wR;
        const hyVal = maxL - hover.ny * lR;
        for (let i = 0; i < points.length; i++) {
          const dx = (points[i].wind_speed - hxVal) / wR;
          const dy = (points[i].lap_time - hyVal) / lR;
          const d = dx * dx + dy * dy;
          if (d < nearDist) { nearDist = d; nearIdx = i; }
        }
        if (nearDist > 0.02) nearIdx = -1;
      }

      // Draw dots colored by wind direction (hue-mapped)
      for (let i = 0; i < points.length; i++) {
        const pt = points[i];
        const hue = (pt.wind_direction / 360) * 360;
        const isHov = i === nearIdx;
        ctx.beginPath();
        ctx.arc(toX(pt.wind_speed), toY(pt.lap_time), isHov ? 6 : 4, 0, Math.PI * 2);
        ctx.fillStyle = isHov ? `hsla(${hue}, 80%, 60%, 1)` : `hsla(${hue}, 80%, 60%, 0.6)`;
        ctx.fill();
        if (isHov) {
          ctx.strokeStyle = `hsla(${hue}, 80%, 60%, 1)`;
          ctx.lineWidth = 2;
          ctx.stroke();
        }
      }

      // Axis labels
      ctx.fillStyle = '#8A8F98';
      ctx.font = '9px "IBM Plex Mono", monospace';
      ctx.textAlign = 'center';
      ctx.fillText('Wind Speed (m/s)', w / 2, h - 6);

      // X ticks
      for (let i = 0; i <= 4; i++) {
        const v = minW + (i / 4) * wR;
        ctx.fillText(`${v.toFixed(0)}`, WIND_PAD.left + (i / 4) * plotW, h - WIND_PAD.bottom + 14);
      }
      // Y ticks
      ctx.textAlign = 'right';
      for (let i = 0; i <= 4; i++) {
        const v = minL + (i / 4) * lR;
        ctx.fillText(fmtTime(v), WIND_PAD.left - 5, WIND_PAD.top + plotH - (i / 4) * plotH + 3);
      }

      // Direction legend (bottom-right)
      const legX = w - WIND_PAD.right - 60;
      const legY = WIND_PAD.top + 5;
      ctx.fillStyle = '#8A8F9880';
      ctx.font = '8px "IBM Plex Mono", monospace';
      ctx.textAlign = 'left';
      ctx.fillText('Color = direction', legX, legY);
      for (let i = 0; i < 8; i++) {
        const hue = (i / 8) * 360;
        ctx.beginPath();
        ctx.arc(legX + i * 7, legY + 10, 2.5, 0, Math.PI * 2);
        ctx.fillStyle = `hsl(${hue}, 80%, 60%)`;
        ctx.fill();
      }
    },
    [points, minW, maxW, wR, minL, maxL, lR],
  );

  const getTooltipData = useCallback(
    (hover: HoverPoint): TooltipData | null => {
      if (points.length === 0) return null;
      const hxVal = minW + hover.nx * wR;
      const hyVal = maxL - hover.ny * lR;
      let nearIdx = -1;
      let nearDist = Infinity;
      for (let i = 0; i < points.length; i++) {
        const dx = (points[i].wind_speed - hxVal) / wR;
        const dy = (points[i].lap_time - hyVal) / lR;
        const d = dx * dx + dy * dy;
        if (d < nearDist) { nearDist = d; nearIdx = i; }
      }
      if (nearDist > 0.02 || nearIdx < 0) return null;
      const p = points[nearIdx];
      return {
        lines: [
          { label: 'Wind', value: `${p.wind_speed.toFixed(1)} m/s ${windDirLabel(p.wind_direction)}` },
          { label: 'Direction', value: `${p.wind_direction.toFixed(0)}°` },
          { label: 'Lap Time', value: fmtTime(p.lap_time) },
        ],
      };
    },
    [points, minW, maxL, wR, lR],
  );

  const { canvasRef, containerRef, tooltip } = useInteractiveCanvas({
    draw,
    deps: [points],
    padding: WIND_PAD,
    getTooltipData,
  });

  return (
    <div ref={containerRef} className="relative">
      <canvas ref={canvasRef} className="w-full h-72" />
      <ChartTooltip tooltip={tooltip} />
    </div>
  );
}

/* ── Main Page ──────────────────────────────────────────── */

export default function WeatherAnalysisPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['analytics-weather'],
    queryFn: () => api.get<WeatherResponse>('/analytics/weather'),
  });

  const points = useMemo(() => data?.points ?? [], [data]);

  // Stats
  const avgTemp = points.length > 0
    ? points.reduce((s, p) => s + p.temperature, 0) / points.length : null;
  const avgWind = points.length > 0
    ? points.reduce((s, p) => s + p.wind_speed, 0) / points.length : null;
  const bestLap = points.length > 0
    ? Math.min(...points.map((p) => p.lap_time)) : null;

  return (
    <div>
      <PageHeader
        title="Weather Analysis"
        subtitle="Correlate weather conditions with on-track performance"
      />

      {/* ── Stats ───────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <StatCard label="Data Points" value={points.length} />
        <StatCard label="Avg Temp" value={avgTemp != null ? `${avgTemp.toFixed(1)}` : '—'} unit="°C" />
        <StatCard label="Avg Wind" value={avgWind != null ? `${avgWind.toFixed(1)}` : '—'} unit="m/s" />
        <StatCard label="Best Lap" value={bestLap != null ? fmtTime(bestLap) : '—'} />
      </div>

      {/* ── Charts ──────────────────────────────────────── */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <ChartPanel
          title="Temperature vs Lap Time"
          subtitle="Ambient temp against best lap — colors indicate temperature gradient"
          loading={isLoading}
          error={error ? 'Failed to load weather data' : null}
        >
          <TempLapChart points={points} />
        </ChartPanel>

        <ChartPanel
          title="Wind Impact"
          subtitle="Wind speed vs lap time — dot color indicates wind direction"
          loading={isLoading}
          error={error ? 'Failed to load weather data' : null}
        >
          <WindImpactChart points={points} />
        </ChartPanel>
      </div>
    </div>
  );
}
