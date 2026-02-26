'use client';

import { useState, useCallback, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import { PageHeader, ChartPanel } from '@/components/app';
import { useCanvas } from '@/hooks/useCanvas';

/* ---------- types ---------- */

interface TrendPoint {
  date: string;
  score: number | null;
  best_time: number | null;
}

interface TrendsResponse {
  points: TrendPoint[];
}

/* ---------- helpers ---------- */

function formatDate(iso: string): string {
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function monthsAgo(n: number): string {
  const d = new Date();
  d.setMonth(d.getMonth() - n);
  return d.toISOString().slice(0, 10);
}

/* ---------- component ---------- */

export default function TrendsPage() {
  const [from, setFrom] = useState(monthsAgo(3));
  const [to, setTo] = useState(todayIso());

  const { data, isLoading, error } = useQuery({
    queryKey: ['analytics-trends', from, to],
    queryFn: () => api.get<TrendsResponse>(`/analytics/trends?from=${from}&to=${to}`),
  });

  const points = useMemo(() => data?.points ?? [], [data]);

  /* ---------- score progression ---------- */
  const drawScoreChart = useCallback(
    (ctx: CanvasRenderingContext2D, width: number, height: number) => {
      ctx.fillStyle = '#0B0C0F';
      ctx.fillRect(0, 0, width, height);

      const validPts = points.filter((p) => p.score != null);
      if (validPts.length === 0) {
        ctx.fillStyle = '#8A8F98';
        ctx.font = '12px "IBM Plex Mono", monospace';
        ctx.textAlign = 'center';
        ctx.fillText('No score data in range', width / 2, height / 2);
        return;
      }

      const pad = { top: 20, right: 20, bottom: 36, left: 48 };
      const drawW = width - pad.left - pad.right;
      const drawH = height - pad.top - pad.bottom;

      const scores = validPts.map((p) => p.score!);
      const minS = Math.max(0, Math.min(...scores) - 5);
      const maxS = Math.min(100, Math.max(...scores) + 5);
      const sRange = maxS - minS || 1;

      const toX = (i: number) => pad.left + (i / Math.max(validPts.length - 1, 1)) * drawW;
      const toY = (s: number) => pad.top + drawH - ((s - minS) / sRange) * drawH;

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

      // Area fill
      ctx.beginPath();
      ctx.moveTo(toX(0), toY(validPts[0].score!));
      for (let i = 1; i < validPts.length; i++) {
        ctx.lineTo(toX(i), toY(validPts[i].score!));
      }
      ctx.lineTo(toX(validPts.length - 1), pad.top + drawH);
      ctx.lineTo(toX(0), pad.top + drawH);
      ctx.closePath();
      ctx.fillStyle = '#B6FF2E10';
      ctx.fill();

      // Line
      ctx.beginPath();
      ctx.moveTo(toX(0), toY(validPts[0].score!));
      for (let i = 1; i < validPts.length; i++) {
        ctx.lineTo(toX(i), toY(validPts[i].score!));
      }
      ctx.strokeStyle = '#B6FF2E';
      ctx.lineWidth = 2;
      ctx.stroke();

      // Dots
      for (let i = 0; i < validPts.length; i++) {
        ctx.beginPath();
        ctx.arc(toX(i), toY(validPts[i].score!), 3, 0, Math.PI * 2);
        ctx.fillStyle = '#B6FF2E';
        ctx.fill();
      }

      // Axis labels
      ctx.fillStyle = '#8A8F98';
      ctx.font = '9px "IBM Plex Mono", monospace';
      ctx.textAlign = 'center';
      ctx.fillText('Session Date', width / 2, height - 6);

      // X tick labels (show subset)
      const maxLabels = 6;
      const step = Math.max(1, Math.floor(validPts.length / maxLabels));
      for (let i = 0; i < validPts.length; i += step) {
        ctx.fillText(formatDate(validPts[i].date), toX(i), height - pad.bottom + 14);
      }

      // Y tick labels
      ctx.textAlign = 'right';
      for (let i = 0; i <= 4; i++) {
        const s = minS + (i / 4) * sRange;
        const y = pad.top + drawH - (i / 4) * drawH;
        ctx.fillText(`${s.toFixed(0)}`, pad.left - 6, y + 3);
      }
    },
    [points],
  );

  /* ---------- best lap time trend ---------- */
  const drawLapTimeChart = useCallback(
    (ctx: CanvasRenderingContext2D, width: number, height: number) => {
      ctx.fillStyle = '#0B0C0F';
      ctx.fillRect(0, 0, width, height);

      const validPts = points.filter((p) => p.best_time != null);
      if (validPts.length === 0) {
        ctx.fillStyle = '#8A8F98';
        ctx.font = '12px "IBM Plex Mono", monospace';
        ctx.textAlign = 'center';
        ctx.fillText('No lap time data in range', width / 2, height / 2);
        return;
      }

      const pad = { top: 20, right: 20, bottom: 36, left: 52 };
      const drawW = width - pad.left - pad.right;
      const drawH = height - pad.top - pad.bottom;

      const times = validPts.map((p) => p.best_time!);
      const minT = Math.min(...times) * 0.98;
      const maxT = Math.max(...times) * 1.02;
      const tRange = maxT - minT || 1;

      const toX = (i: number) => pad.left + (i / Math.max(validPts.length - 1, 1)) * drawW;
      const toY = (t: number) => pad.top + drawH - ((maxT - t) / tRange) * drawH;

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

      // Line
      ctx.beginPath();
      ctx.moveTo(toX(0), toY(validPts[0].best_time!));
      for (let i = 1; i < validPts.length; i++) {
        ctx.lineTo(toX(i), toY(validPts[i].best_time!));
      }
      ctx.strokeStyle = '#FF6A00';
      ctx.lineWidth = 2;
      ctx.stroke();

      // Dots
      for (let i = 0; i < validPts.length; i++) {
        ctx.beginPath();
        ctx.arc(toX(i), toY(validPts[i].best_time!), 3, 0, Math.PI * 2);
        ctx.fillStyle = '#FF6A00';
        ctx.fill();
      }

      // Axis labels
      ctx.fillStyle = '#8A8F98';
      ctx.font = '9px "IBM Plex Mono", monospace';
      ctx.textAlign = 'center';
      ctx.fillText('Session Date', width / 2, height - 6);

      // X tick labels
      const maxLabels = 6;
      const step = Math.max(1, Math.floor(validPts.length / maxLabels));
      for (let i = 0; i < validPts.length; i += step) {
        ctx.fillText(formatDate(validPts[i].date), toX(i), height - pad.bottom + 14);
      }

      // Y tick labels (note: inverted — lower time = better = higher on chart)
      ctx.textAlign = 'right';
      for (let i = 0; i <= 4; i++) {
        const t = minT + (i / 4) * tRange;
        const y = pad.top + (i / 4) * drawH;
        ctx.fillText(`${t.toFixed(1)}s`, pad.left - 6, y + 3);
      }
    },
    [points],
  );

  const scoreRef = useCanvas(drawScoreChart, [drawScoreChart]);
  const lapTimeRef = useCanvas(drawLapTimeChart, [drawLapTimeChart]);

  const errorMsg = error ? 'Failed to load trend data' : null;

  return (
    <div>
      <PageHeader
        title="Performance Trends"
        subtitle="Track your improvement over time"
      />

      {/* Date range selector */}
      <div className="bg-concrete rounded-lg border border-steel/20 p-4 mb-6">
        <div className="flex items-end gap-4">
          <div>
            <label className="block text-steel font-telemetry text-xs uppercase tracking-wider mb-1.5">
              From
            </label>
            <input
              type="date"
              value={from}
              onChange={(e) => setFrom(e.target.value)}
              className="bg-asphalt border border-steel/30 rounded px-3 py-2 text-chalk font-body text-sm
                focus:outline-none focus:border-pit-orange transition-colors"
            />
          </div>
          <div>
            <label className="block text-steel font-telemetry text-xs uppercase tracking-wider mb-1.5">
              To
            </label>
            <input
              type="date"
              value={to}
              onChange={(e) => setTo(e.target.value)}
              className="bg-asphalt border border-steel/30 rounded px-3 py-2 text-chalk font-body text-sm
                focus:outline-none focus:border-pit-orange transition-colors"
            />
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => { setFrom(monthsAgo(1)); setTo(todayIso()); }}
              className="px-3 py-2 text-xs font-telemetry text-steel hover:text-chalk bg-asphalt border border-steel/30 rounded transition-colors"
            >
              1M
            </button>
            <button
              onClick={() => { setFrom(monthsAgo(3)); setTo(todayIso()); }}
              className="px-3 py-2 text-xs font-telemetry text-steel hover:text-chalk bg-asphalt border border-steel/30 rounded transition-colors"
            >
              3M
            </button>
            <button
              onClick={() => { setFrom(monthsAgo(6)); setTo(todayIso()); }}
              className="px-3 py-2 text-xs font-telemetry text-steel hover:text-chalk bg-asphalt border border-steel/30 rounded transition-colors"
            >
              6M
            </button>
            <button
              onClick={() => { setFrom(monthsAgo(12)); setTo(todayIso()); }}
              className="px-3 py-2 text-xs font-telemetry text-steel hover:text-chalk bg-asphalt border border-steel/30 rounded transition-colors"
            >
              1Y
            </button>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <ChartPanel
          title="Score Progression"
          subtitle="Session score trend over time"
          loading={isLoading}
          error={errorMsg}
        >
          <div className="h-72 relative">
            <canvas ref={scoreRef} className="absolute inset-0 w-full h-full" />
          </div>
        </ChartPanel>

        <ChartPanel
          title="Best Lap Time"
          subtitle="Best lap per session (lower is better)"
          loading={isLoading}
          error={errorMsg}
        >
          <div className="h-72 relative">
            <canvas ref={lapTimeRef} className="absolute inset-0 w-full h-full" />
          </div>
        </ChartPanel>
      </div>
    </div>
  );
}
