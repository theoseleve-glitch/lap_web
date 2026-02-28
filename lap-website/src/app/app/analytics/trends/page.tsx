'use client';

import { useState, useCallback, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import { PageHeader, ChartPanel, StatCard } from '@/components/app';
import { ChartTooltip } from '@/components/app/ChartTooltip';
import { useInteractiveCanvas, type HoverPoint, type TooltipData } from '@/hooks/useInteractiveCanvas';

/* ── Types ──────────────────────────────────────────────── */

interface TrendPoint {
  date: string;
  score: number | null;
  best_time: number | null;
}

interface TrendsResponse {
  points: TrendPoint[];
}

/* ── Helpers ────────────────────────────────────────────── */

function formatDate(iso: string): string {
  const d = new Date(iso);
  return `${d.getDate()}/${d.getMonth() + 1}`;
}

function fmtTime(s: number | null): string {
  if (s == null) return '—';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function monthsAgo(n: number): string {
  const d = new Date();
  d.setMonth(d.getMonth() - n);
  return d.toISOString().slice(0, 10);
}

/* ── Score Trend Chart ──────────────────────────────────── */

const SCORE_PAD = { top: 15, right: 15, bottom: 30, left: 48 };

function ScoreTrendChart({ points }: { points: TrendPoint[] }) {
  const scored = useMemo(() => points.filter((p) => p.score != null), [points]);
  const { minS, maxS, sRange } = useMemo(() => {
    if (scored.length === 0) return { minS: 0, maxS: 100, sRange: 100 };
    const scores = scored.map((p) => p.score!);
    const mn = Math.max(0, Math.min(...scores) - 5);
    const mx = Math.min(100, Math.max(...scores) + 5);
    return { minS: mn, maxS: mx, sRange: mx - mn || 1 };
  }, [scored]);

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number, hover: HoverPoint | null) => {
      ctx.clearRect(0, 0, w, h);
      if (scored.length === 0) {
        ctx.fillStyle = '#8A8F98';
        ctx.font = '12px "IBM Plex Mono", monospace';
        ctx.textAlign = 'center';
        ctx.fillText('No score data in range', w / 2, h / 2);
        return;
      }

      const plotW = w - SCORE_PAD.left - SCORE_PAD.right;
      const plotH = h - SCORE_PAD.top - SCORE_PAD.bottom;
      const n = scored.length;

      const toX = (i: number) => SCORE_PAD.left + (i / Math.max(n - 1, 1)) * plotW;
      const toY = (s: number) => SCORE_PAD.top + plotH - ((s - minS) / sRange) * plotH;
      const hovIdx = hover ? Math.round(hover.nx * (n - 1)) : -1;

      // Grid
      ctx.strokeStyle = 'rgba(138, 143, 152, 0.15)';
      ctx.lineWidth = 0.5;
      for (let i = 0; i <= 4; i++) {
        const y = SCORE_PAD.top + (i / 4) * plotH;
        ctx.beginPath();
        ctx.moveTo(SCORE_PAD.left, y);
        ctx.lineTo(SCORE_PAD.left + plotW, y);
        ctx.stroke();
      }

      // Y-axis labels
      ctx.fillStyle = '#8A8F98';
      ctx.font = '10px "IBM Plex Mono", monospace';
      ctx.textAlign = 'right';
      for (let i = 0; i <= 4; i++) {
        const val = maxS - (i / 4) * sRange;
        ctx.fillText(val.toFixed(0), SCORE_PAD.left - 5, SCORE_PAD.top + (i / 4) * plotH + 3);
      }

      // Area fill
      ctx.beginPath();
      ctx.moveTo(toX(0), toY(scored[0].score!));
      for (let i = 1; i < n; i++) ctx.lineTo(toX(i), toY(scored[i].score!));
      ctx.lineTo(toX(n - 1), SCORE_PAD.top + plotH);
      ctx.lineTo(toX(0), SCORE_PAD.top + plotH);
      ctx.closePath();
      ctx.fillStyle = 'rgba(182, 255, 46, 0.06)';
      ctx.fill();

      // Line
      ctx.beginPath();
      for (let i = 0; i < n; i++) {
        const x = toX(i);
        const y = toY(scored[i].score!);
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.strokeStyle = '#B6FF2E';
      ctx.lineWidth = 2;
      ctx.stroke();

      // Points
      for (let i = 0; i < n; i++) {
        ctx.beginPath();
        ctx.arc(toX(i), toY(scored[i].score!), i === hovIdx ? 5 : 2.5, 0, Math.PI * 2);
        ctx.fillStyle = i === hovIdx ? '#B6FF2E' : '#B6FF2EAA';
        ctx.fill();
      }

      // X dates
      ctx.textAlign = 'center';
      ctx.fillStyle = '#8A8F98';
      const step = Math.max(1, Math.floor(n / 6));
      for (let i = 0; i < n; i += step) {
        ctx.fillText(formatDate(scored[i].date), toX(i), h - 8);
      }
    },
    [scored, minS, maxS, sRange],
  );

  const getTooltipData = useCallback(
    (hover: HoverPoint): TooltipData | null => {
      const idx = Math.round(hover.nx * (scored.length - 1));
      if (idx < 0 || idx >= scored.length) return null;
      const d = scored[idx];
      return {
        header: d.date,
        lines: [
          { label: 'Score', value: d.score?.toFixed(1) ?? '—', color: '#B6FF2E' },
        ],
      };
    },
    [scored],
  );

  const { canvasRef, containerRef, tooltip } = useInteractiveCanvas({
    draw,
    deps: [scored],
    padding: SCORE_PAD,
    getTooltipData,
    crosshair: true,
  });

  return (
    <div ref={containerRef} className="relative">
      <canvas ref={canvasRef} className="w-full h-72" />
      <ChartTooltip tooltip={tooltip} />
    </div>
  );
}

/* ── Lap Time Trend Chart ──────────────────────────────── */

const LAP_PAD = { top: 15, right: 15, bottom: 30, left: 52 };

function LapTimeTrendChart({ points }: { points: TrendPoint[] }) {
  const timed = useMemo(() => points.filter((p) => p.best_time != null), [points]);
  const { minT, maxT, tRange } = useMemo(() => {
    if (timed.length === 0) return { minT: 0, maxT: 60, tRange: 60 };
    const times = timed.map((p) => p.best_time!);
    const mn = Math.min(...times) * 0.98;
    const mx = Math.max(...times) * 1.02;
    return { minT: mn, maxT: mx, tRange: mx - mn || 1 };
  }, [timed]);

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number, hover: HoverPoint | null) => {
      ctx.clearRect(0, 0, w, h);
      if (timed.length === 0) {
        ctx.fillStyle = '#8A8F98';
        ctx.font = '12px "IBM Plex Mono", monospace';
        ctx.textAlign = 'center';
        ctx.fillText('No lap time data in range', w / 2, h / 2);
        return;
      }

      const plotW = w - LAP_PAD.left - LAP_PAD.right;
      const plotH = h - LAP_PAD.top - LAP_PAD.bottom;
      const n = timed.length;

      const toX = (i: number) => LAP_PAD.left + (i / Math.max(n - 1, 1)) * plotW;
      // Inverted: lower time = better = higher on chart
      const toY = (t: number) => LAP_PAD.top + ((t - minT) / tRange) * plotH;
      const hovIdx = hover ? Math.round(hover.nx * (n - 1)) : -1;

      // Grid
      ctx.strokeStyle = 'rgba(138, 143, 152, 0.15)';
      ctx.lineWidth = 0.5;
      for (let i = 0; i <= 4; i++) {
        const y = LAP_PAD.top + (i / 4) * plotH;
        ctx.beginPath();
        ctx.moveTo(LAP_PAD.left, y);
        ctx.lineTo(LAP_PAD.left + plotW, y);
        ctx.stroke();
      }

      // Y-axis labels (inverted — top is fastest)
      ctx.fillStyle = '#8A8F98';
      ctx.font = '10px "IBM Plex Mono", monospace';
      ctx.textAlign = 'right';
      for (let i = 0; i <= 4; i++) {
        const t = minT + (i / 4) * tRange;
        ctx.fillText(fmtTime(t), LAP_PAD.left - 5, LAP_PAD.top + (i / 4) * plotH + 3);
      }

      // Running best line (dashed)
      let runningBest = Infinity;
      const bests: number[] = [];
      for (const p of timed) {
        runningBest = Math.min(runningBest, p.best_time!);
        bests.push(runningBest);
      }
      ctx.beginPath();
      for (let i = 0; i < n; i++) {
        const x = toX(i);
        const y = toY(bests[i]);
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.strokeStyle = '#B6FF2E40';
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 4]);
      ctx.stroke();
      ctx.setLineDash([]);

      // Main line
      ctx.beginPath();
      for (let i = 0; i < n; i++) {
        const x = toX(i);
        const y = toY(timed[i].best_time!);
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.strokeStyle = '#FF6A00';
      ctx.lineWidth = 2;
      ctx.stroke();

      // Points
      for (let i = 0; i < n; i++) {
        ctx.beginPath();
        ctx.arc(toX(i), toY(timed[i].best_time!), i === hovIdx ? 5 : 2.5, 0, Math.PI * 2);
        ctx.fillStyle = i === hovIdx ? '#FF6A00' : '#FF6A00AA';
        ctx.fill();
      }

      // X dates
      ctx.textAlign = 'center';
      ctx.fillStyle = '#8A8F98';
      const step = Math.max(1, Math.floor(n / 6));
      for (let i = 0; i < n; i += step) {
        ctx.fillText(formatDate(timed[i].date), toX(i), h - 8);
      }
    },
    [timed, minT, maxT, tRange],
  );

  const getTooltipData = useCallback(
    (hover: HoverPoint): TooltipData | null => {
      const idx = Math.round(hover.nx * (timed.length - 1));
      if (idx < 0 || idx >= timed.length) return null;
      const d = timed[idx];
      return {
        header: d.date,
        lines: [
          { label: 'Best Lap', value: fmtTime(d.best_time), color: '#FF6A00' },
        ],
      };
    },
    [timed],
  );

  const { canvasRef, containerRef, tooltip } = useInteractiveCanvas({
    draw,
    deps: [timed],
    padding: LAP_PAD,
    getTooltipData,
    crosshair: true,
    crosshairColor: 'rgba(255, 106, 0, 0.4)',
  });

  return (
    <div ref={containerRef} className="relative">
      <canvas ref={canvasRef} className="w-full h-72" />
      <ChartTooltip tooltip={tooltip} />
    </div>
  );
}

/* ── Main Page ──────────────────────────────────────────── */

const RANGE_OPTIONS = [
  { label: '1M', months: 1 },
  { label: '3M', months: 3 },
  { label: '6M', months: 6 },
  { label: '1Y', months: 12 },
];

export default function TrendsPage() {
  const [from, setFrom] = useState(monthsAgo(3));
  const [to, setTo] = useState(todayIso());
  const [activeRange, setActiveRange] = useState('3M');

  const { data, isLoading, error } = useQuery({
    queryKey: ['analytics-trends', from, to],
    queryFn: () => api.get<TrendsResponse>(`/analytics/trends?from=${from}&to=${to}`),
  });

  const points = useMemo(() => data?.points ?? [], [data]);

  // Summary stats
  const scoredPoints = points.filter((p) => p.score != null);
  const timedPoints = points.filter((p) => p.best_time != null);
  const latestScore = scoredPoints.length > 0 ? scoredPoints[scoredPoints.length - 1].score : null;
  const bestTime = timedPoints.length > 0 ? Math.min(...timedPoints.map((p) => p.best_time!)) : null;
  const avgScore = scoredPoints.length > 0
    ? scoredPoints.reduce((s, p) => s + p.score!, 0) / scoredPoints.length
    : null;

  // Trend: compare first half avg to second half avg
  const scoreTrend = (() => {
    if (scoredPoints.length < 4) return undefined;
    const mid = Math.floor(scoredPoints.length / 2);
    const firstHalf = scoredPoints.slice(0, mid).reduce((s, p) => s + p.score!, 0) / mid;
    const secondHalf = scoredPoints.slice(mid).reduce((s, p) => s + p.score!, 0) / (scoredPoints.length - mid);
    return secondHalf > firstHalf ? 'up' as const : secondHalf < firstHalf ? 'down' as const : undefined;
  })();

  return (
    <div>
      <PageHeader
        title="Performance Trends"
        subtitle="Track your improvement over time"
      />

      {/* ── Stats ───────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <StatCard label="Sessions" value={points.length} />
        <StatCard label="Latest Score" value={latestScore?.toFixed(1) ?? '—'} unit="/100" trend={scoreTrend} />
        <StatCard label="Avg Score" value={avgScore?.toFixed(1) ?? '—'} unit="/100" />
        <StatCard label="Best Lap" value={fmtTime(bestTime)} />
      </div>

      {/* ── Date Range Selector ─────────────────────────── */}
      <div className="bg-concrete rounded-lg border border-steel/20 p-4 mb-6">
        <div className="flex flex-wrap items-end gap-4">
          <div>
            <label className="block text-steel font-telemetry text-xs uppercase tracking-wider mb-1.5">
              From
            </label>
            <input
              type="date"
              value={from}
              onChange={(e) => { setFrom(e.target.value); setActiveRange(''); }}
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
              onChange={(e) => { setTo(e.target.value); setActiveRange(''); }}
              className="bg-asphalt border border-steel/30 rounded px-3 py-2 text-chalk font-body text-sm
                focus:outline-none focus:border-pit-orange transition-colors"
            />
          </div>
          <div className="flex gap-2">
            {RANGE_OPTIONS.map((opt) => (
              <button
                key={opt.label}
                onClick={() => {
                  setFrom(monthsAgo(opt.months));
                  setTo(todayIso());
                  setActiveRange(opt.label);
                }}
                className={`px-3 py-2 text-xs font-telemetry rounded border transition-colors ${
                  activeRange === opt.label
                    ? 'border-acid-green bg-acid-green/10 text-acid-green'
                    : 'border-steel/30 bg-asphalt text-steel hover:text-chalk'
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* ── Charts ──────────────────────────────────────── */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <ChartPanel
          title="Score Progression"
          subtitle="Session score trend over time"
          loading={isLoading}
          error={error ? 'Failed to load trend data' : null}
        >
          <ScoreTrendChart points={points} />
        </ChartPanel>

        <ChartPanel
          title="Best Lap Time"
          subtitle="Best lap per session — dashed line = running record"
          loading={isLoading}
          error={error ? 'Failed to load trend data' : null}
        >
          <LapTimeTrendChart points={points} />
        </ChartPanel>
      </div>
    </div>
  );
}
