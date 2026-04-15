/**
 * LapProgressChart.tsx — Canvas-based lap progress bar chart with rolling average.
 *
 * Shows lap times as vertical bars with a rolling average line overlaid.
 * Best-lap and at-or-below-best bars highlighted in acid-green; others in steel.
 * Trend indicator in top-right shows whether pace is improving or degrading.
 *
 * Fetches from: GET /api/v1/sessions/{id}/lap-progress
 */
'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { apiFetch } from '@/lib/api-client';
import { useChartHoverStore } from '@/lib/chart-hover-store';
import { chartColor } from '@/components/shared/chart-kit';

interface LapProgressData {
  lap_numbers: number[];
  times: number[];
  rolling_avg: number[];
  trend_slope: number;
  is_improving: boolean;
}

interface LapProgressChartProps {
  sessionId: string;
  gpsLaps: number[];
  bestLap: number | null;
  className?: string;
  controlledLap?: boolean;
}

const STEEL = chartColor.textSecondary;
const STEEL_40 = `${chartColor.textSecondary}66`;
const ACID = chartColor.series.positive;
const ACID_BRIGHT = chartColor.series.positive;
const GRID = chartColor.grid;
const FONT = '10px "Space Mono", monospace';

/** Format seconds as M:SS.s */
function fmtTime(s: number): string {
  const m = Math.floor(s / 60);
  const sec = s - m * 60;
  return m > 0 ? `${m}:${sec < 10 ? '0' : ''}${sec.toFixed(1)}` : sec.toFixed(1);
}

function drawChart(
  ctx: CanvasRenderingContext2D, w: number, h: number,
  data: LapProgressData, bestLapTime: number | null,
) {
  ctx.clearRect(0, 0, w, h);
  const { lap_numbers, times, rolling_avg, is_improving, trend_slope } = data;
  const n = lap_numbers.length;

  if (n === 0) {
    ctx.fillStyle = STEEL; ctx.font = FONT;
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText('No lap progress data', w / 2, h / 2);
    return;
  }

  const best = bestLapTime ?? Math.min(...times);
  const pad = { top: 28, right: 16, bottom: 36, left: 56 };
  const pW = w - pad.left - pad.right;
  const pH = h - pad.top - pad.bottom;

  // Y range with 2s padding
  const tMin = Math.min(...times, ...rolling_avg);
  const tMax = Math.max(...times, ...rolling_avg);
  const yMin = Math.max(0, tMin - 2);
  const yMax = tMax + 2;
  const yToP = (v: number) => pad.top + pH - ((v - yMin) / (yMax - yMin)) * pH;

  // Bar geometry
  const gap = Math.max(2, pW * 0.04);
  const barW = Math.max(4, (pW - (n - 1) * gap) / n);
  const bx = (i: number) => pad.left + i * (barW + gap);
  const bcx = (i: number) => bx(i) + barW / 2;

  // Grid + Y labels
  const rawStep = (yMax - yMin) / 4;
  const mag = Math.pow(10, Math.floor(Math.log10(rawStep)));
  const r = rawStep / mag;
  const step = (r <= 1.5 ? 1 : r <= 3 ? 2 : r <= 7 ? 5 : 10) * mag;

  ctx.strokeStyle = GRID; ctx.lineWidth = 0.5;
  ctx.fillStyle = STEEL; ctx.font = FONT;
  ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
  for (let v = Math.ceil(yMin / step) * step; v <= yMax; v += step) {
    const y = yToP(v);
    ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(w - pad.right, y); ctx.stroke();
    ctx.fillText(fmtTime(v), pad.left - 6, y);
  }

  // Bars
  const baseY = yToP(yMin);
  for (let i = 0; i < n; i++) {
    const t = times[i]!;
    const topY = yToP(t);
    const isBest = t === best;
    ctx.fillStyle = isBest ? ACID_BRIGHT : t <= best ? ACID : STEEL_40;
    ctx.fillRect(bx(i), topY, barW, baseY - topY);
    if (isBest) {
      ctx.strokeStyle = ACID; ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.moveTo(bx(i), topY); ctx.lineTo(bx(i) + barW, topY); ctx.stroke();
    }
  }

  // Rolling average line
  if (rolling_avg.length > 0) {
    const cnt = Math.min(n, rolling_avg.length);
    ctx.strokeStyle = chartColor.text; ctx.lineWidth = 1.5;
    ctx.beginPath();
    for (let i = 0; i < cnt; i++) {
      const x = bcx(i), y = yToP(rolling_avg[i]!);
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    }
    ctx.stroke();
    ctx.fillStyle = chartColor.text;
    for (let i = 0; i < cnt; i++) {
      ctx.beginPath(); ctx.arc(bcx(i), yToP(rolling_avg[i]!), 2, 0, Math.PI * 2); ctx.fill();
    }
  }

  // X axis labels
  ctx.fillStyle = STEEL; ctx.font = FONT;
  ctx.textAlign = 'center'; ctx.textBaseline = 'top';
  const every = barW < 14 ? Math.ceil(14 / (barW + gap)) : 1;
  for (let i = 0; i < n; i++) {
    if (i % every !== 0 && i !== n - 1) continue;
    ctx.fillText(String(lap_numbers[i]), bcx(i), pad.top + pH + 6);
  }
  ctx.fillText('Lap', pad.left + pW / 2, h - 4);

  // Trend indicator (top-right)
  const tx = w - pad.right - 4;
  ctx.font = FONT; ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
  if (is_improving) {
    ctx.fillStyle = ACID;
    ctx.fillText('\u25BC Improving', tx, 12);
  } else {
    ctx.fillStyle = chartColor.series.negative;
    ctx.fillText('\u25B2 Degrading', tx, 12);
  }
  ctx.fillStyle = STEEL; ctx.font = '9px "Space Mono", monospace';
  ctx.fillText(`${trend_slope > 0 ? '+' : ''}${trend_slope.toFixed(2)}s/lap`, tx, 25);

  // Title (top-left)
  ctx.fillStyle = STEEL; ctx.font = FONT;
  ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
  ctx.fillText('Lap Progress', pad.left, 12);
}

// ── Component ────────────────────────────────────────────────────
export function LapProgressChart({
  sessionId, gpsLaps, bestLap, className = '',
}: LapProgressChartProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [data, setData] = useState<LapProgressData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const bestLapTime = data && bestLap != null
    ? data.times[data.lap_numbers.indexOf(bestLap)] ?? null
    : null;

  // Fetch
  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    setLoading(true); setError(null);
    (async () => {
      try {
        const result = await apiFetch<LapProgressData>(
          `/sessions/${encodeURIComponent(sessionId)}/lap-progress`,
        );
        if (!cancelled) setData(result);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load lap progress');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [sessionId]);

  // Draw
  const render = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas || !data) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);
    drawChart(ctx, rect.width, rect.height, data, bestLapTime);
  }, [data, bestLapTime]);

  useEffect(() => { render(); }, [render]);

  // ResizeObserver
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => render());
    ro.observe(el);
    return () => ro.disconnect();
  }, [render]);

  if (error && !data) {
    return (
      <div className={`flex items-center justify-center rounded-lg border border-steel/10 bg-concrete ${className}`}
        style={{ minHeight: '220px' }}>
        <div className="text-steel p-4 text-sm text-center">
          <p className="font-telemetry text-chalk mb-1">Lap Progress</p>
          <p className="text-safety-red text-xs">{error}</p>
        </div>
      </div>
    );
  }

  return (
    <div ref={containerRef} className={`relative ${className}`}>
      {loading && (
        <div className="absolute inset-0 flex items-center justify-center bg-concrete/80 z-10 rounded-lg">
          <div className="w-5 h-5 border-2 border-accent border-t-transparent rounded-full animate-spin" />
        </div>
      )}
      <div className="relative w-full rounded-lg border border-steel/10" style={{ minHeight: '220px' }}>
        <canvas ref={canvasRef} className="w-full h-full"
          style={{ display: 'block', minHeight: '220px' }}
          role="img" aria-label="Lap progress chart showing lap times with rolling average" />
        {!data && !loading && (
          <div className="absolute inset-0 flex items-center justify-center">
            <p className="text-steel text-sm font-telemetry">No lap data</p>
          </div>
        )}
      </div>
    </div>
  );
}
