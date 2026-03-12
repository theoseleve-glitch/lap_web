/**
 * StintChart.tsx — Stint analysis chart showing lap times grouped by stint.
 *
 * Primary mode: horizontal segmented timeline with stint blocks proportional
 * to lap count, showing avg time, stint number, and degradation indicator.
 *
 * Fallback mode: vertical bars per lap colored by session segment
 * (first third = blue, middle = green, last third = amber).
 */
'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { apiFetch } from '@/lib/api-client';

interface Stint {
  stint_number: number;
  start_lap: number;
  end_lap: number;
  avg_time: number;
  best_time: number;
  degradation_rate: number;
}

interface StintResponse {
  stints: Stint[];
  available?: boolean;
  robustness_metrics?: { consistency_pct: number };
}

interface LapProgressResponse {
  lap_numbers: number[];
  times: number[];
}

interface StintChartProps {
  sessionId: string;
  gpsLaps: number[];
  bestLap: number | null;
  className?: string;
}

const FONT = '10px "JetBrains Mono", monospace';
const ACCENT = '#b4ff39';
const TEXT = '#c4c4c4';
const DIM = '#6b6b6b';
const STINT_PALETTE = ['#3b82f6', '#22d3ee', '#a78bfa', '#f97316', '#ec4899', '#10b981'];
const SEGMENT_COLORS = { first: '#3b82f6', middle: '#10b981', last: '#f59e0b' };

export function StintChart({ sessionId, gpsLaps, bestLap, className = '' }: StintChartProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const stintsRef = useRef<Stint[]>([]);
  const fallbackRef = useRef<{ lap_number: number; lap_time: number }[]>([]);
  const modeRef = useRef<'stints' | 'fallback' | 'none'>('none');

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    stintsRef.current = [];
    fallbackRef.current = [];
    modeRef.current = 'none';
    try {
      const res = await apiFetch<StintResponse>(
        `/sessions/${encodeURIComponent(sessionId)}/stint-analysis`,
      );
      if (res.stints && res.stints.length > 0) {
        stintsRef.current = res.stints;
        modeRef.current = 'stints';
        return;
      }
    } catch {
      // stint endpoint unavailable, try fallback
    }
    try {
      const prog = await apiFetch<LapProgressResponse>(
        `/sessions/${encodeURIComponent(sessionId)}/lap-progress`,
      );
      if (prog.lap_numbers && prog.lap_numbers.length > 0) {
        fallbackRef.current = prog.lap_numbers
          .map((num, i) => ({ lap_number: num, lap_time: prog.times[i] ?? 0 }))
          .filter((l) => l.lap_time > 0);
        modeRef.current = fallbackRef.current.length > 0 ? 'fallback' : 'none';
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load stint data');
    }
    setLoading(false);
  }, [sessionId]);

  useEffect(() => {
    fetchData().finally(() => setLoading(false));
  }, [fetchData]);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.parentElement?.clientWidth || canvas.clientWidth || 600;
    const h = 220;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = w + 'px';
    canvas.style.height = h + 'px';
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    ctx.clearRect(0, 0, w, h);

    if (modeRef.current === 'stints') {
      drawStints(ctx, w, h, stintsRef.current);
    } else if (modeRef.current === 'fallback') {
      drawFallback(ctx, w, h, fallbackRef.current);
    } else {
      ctx.fillStyle = DIM;
      ctx.font = '13px "JetBrains Mono", monospace';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText('No stint data available', w / 2, h / 2);
    }
  }, []);

  useEffect(() => {
    if (!loading) draw();
  }, [loading, draw]);

  useEffect(() => {
    const c = containerRef.current;
    if (!c) return;
    const ro = new ResizeObserver(() => draw());
    ro.observe(c);
    return () => ro.disconnect();
  }, [draw]);

  if (!gpsLaps.length) {
    return (
      <div className={`text-sm text-center p-4 ${className}`} style={{ color: TEXT }}>
        No laps with GPS data available.
      </div>
    );
  }

  return (
    <div ref={containerRef} className={className} role="img" aria-label="Stint analysis chart">
      {loading && <span className="text-xs animate-pulse" style={{ color: TEXT }}>Loading...</span>}
      {error && <span className="text-xs text-red-400">{error}</span>}
      <div className="relative" style={{ width: '100%' }}>
        <canvas ref={canvasRef} style={{ width: '100%', height: '220px', display: 'block' }} />
      </div>
    </div>
  );
}

function drawStints(ctx: CanvasRenderingContext2D, w: number, h: number, stints: Stint[]) {
  const pad = { top: 30, right: 20, bottom: 40, left: 20 };
  const pW = w - pad.left - pad.right;
  const pH = h - pad.top - pad.bottom;
  const totalLaps = stints.reduce((s, st) => s + (st.end_lap - st.start_lap + 1), 0);
  if (totalLaps === 0) return;

  // Title
  ctx.fillStyle = TEXT;
  ctx.font = '11px "JetBrains Mono", monospace';
  ctx.textAlign = 'left';
  ctx.textBaseline = 'top';
  ctx.fillText('STINT TIMELINE', pad.left, 8);

  // Best avg across stints for highlighting
  let bestAvg = Infinity;
  for (const st of stints) if (st.avg_time < bestAvg) bestAvg = st.avg_time;

  let xOff = pad.left;
  const gap = Math.min(4, pW / stints.length / 20);

  for (let i = 0; i < stints.length; i++) {
    const st = stints[i]!;
    const lapCount = st.end_lap - st.start_lap + 1;
    const blockW = (lapCount / totalLaps) * pW - gap;
    const color = STINT_PALETTE[i % STINT_PALETTE.length]!;
    const isBest = st.avg_time === bestAvg;

    // Block background
    ctx.fillStyle = color + '30';
    ctx.strokeStyle = isBest ? ACCENT : color;
    ctx.lineWidth = isBest ? 2 : 1;
    ctx.beginPath();
    ctx.roundRect(xOff, pad.top, blockW, pH, 4);
    ctx.fill();
    ctx.stroke();

    // Best stint highlight glow
    if (isBest) {
      ctx.strokeStyle = ACCENT + '40';
      ctx.lineWidth = 4;
      ctx.beginPath();
      ctx.roundRect(xOff - 1, pad.top - 1, blockW + 2, pH + 2, 5);
      ctx.stroke();
    }

    const cx = xOff + blockW / 2;

    // Stint number
    ctx.fillStyle = TEXT;
    ctx.font = 'bold 12px "JetBrains Mono", monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillText(`S${st.stint_number}`, cx, pad.top + 8);

    // Lap range
    ctx.fillStyle = DIM;
    ctx.font = FONT;
    ctx.fillText(`L${st.start_lap}-${st.end_lap}`, cx, pad.top + 24);

    // Avg time
    ctx.fillStyle = isBest ? ACCENT : TEXT;
    ctx.font = 'bold 11px "JetBrains Mono", monospace';
    ctx.textBaseline = 'middle';
    ctx.fillText(formatTime(st.avg_time), cx, pad.top + pH / 2);

    // Best time (smaller, below avg)
    ctx.fillStyle = DIM;
    ctx.font = FONT;
    ctx.fillText('best ' + formatTime(st.best_time), cx, pad.top + pH / 2 + 16);

    // Degradation indicator
    const dY = pad.top + pH - 20;
    const deg = st.degradation_rate;
    if (Math.abs(deg) > 0.01) {
      const arrow = deg > 0 ? '\u2191' : '\u2193';
      const degColor = deg > 0.3 ? '#ef4444' : deg > 0.1 ? '#f59e0b' : '#10b981';
      ctx.fillStyle = degColor;
      ctx.font = 'bold 11px "JetBrains Mono", monospace';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(`${arrow}${Math.abs(deg).toFixed(2)}s`, cx, dY);

      // Small slope line visualizing degradation direction
      const slopeLen = Math.min(blockW * 0.3, 20);
      const slopeY = deg > 0 ? 3 : -3;
      ctx.strokeStyle = degColor;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(cx - slopeLen, dY + 10);
      ctx.lineTo(cx + slopeLen, dY + 10 - slopeY);
      ctx.stroke();
    } else {
      ctx.fillStyle = DIM;
      ctx.font = FONT;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText('flat', cx, dY);
    }

    xOff += blockW + gap;
  }

  // Bottom label
  ctx.fillStyle = DIM;
  ctx.font = FONT;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'bottom';
  ctx.fillText('Block width proportional to stint lap count', w / 2, h - 4);
}

function drawFallback(
  ctx: CanvasRenderingContext2D, w: number, h: number,
  laps: { lap_number: number; lap_time: number }[],
) {
  const pad = { top: 30, right: 20, bottom: 40, left: 50 };
  const pW = w - pad.left - pad.right;
  const pH = h - pad.top - pad.bottom;
  const n = laps.length;
  if (n === 0) return;

  // Title
  ctx.fillStyle = TEXT;
  ctx.font = '11px "JetBrains Mono", monospace';
  ctx.textAlign = 'left';
  ctx.textBaseline = 'top';
  ctx.fillText('LAP TIMES (no stint data)', pad.left, 8);

  let yMin = Infinity, yMax = -Infinity;
  for (const l of laps) { if (l.lap_time < yMin) yMin = l.lap_time; if (l.lap_time > yMax) yMax = l.lap_time; }
  const yPad = (yMax - yMin) * 0.15 || 1;
  yMin = Math.max(0, yMin - yPad);
  yMax = yMax + yPad;

  const barW = Math.min(pW / n - 2, 30);
  const spacing = (pW - barW * n) / (n + 1);
  const yPx = (v: number) => pad.top + ((yMax - v) / (yMax - yMin)) * pH;

  // Y grid + labels
  const yStep = niceStep(yMax - yMin, 5);
  ctx.strokeStyle = 'rgba(255,255,255,0.06)';
  ctx.lineWidth = 0.5;
  ctx.fillStyle = DIM;
  ctx.font = FONT;
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  for (let v = Math.ceil(yMin / yStep) * yStep; v <= yMax; v += yStep) {
    const y = yPx(v);
    ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(w - pad.right, y); ctx.stroke();
    ctx.fillText(formatTime(v), pad.left - 6, y);
  }

  // Segment thresholds
  const third = Math.ceil(n / 3);

  // Draw bars
  for (let i = 0; i < n; i++) {
    const l = laps[i]!;
    const x = pad.left + spacing + i * (barW + spacing);
    const y = yPx(l.lap_time);
    const barH = pad.top + pH - y;
    const color = i < third ? SEGMENT_COLORS.first : i < third * 2 ? SEGMENT_COLORS.middle : SEGMENT_COLORS.last;

    ctx.fillStyle = color + '80';
    ctx.beginPath();
    ctx.roundRect(x, y, barW, barH, [2, 2, 0, 0]);
    ctx.fill();

    ctx.strokeStyle = color;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.roundRect(x, y, barW, barH, [2, 2, 0, 0]);
    ctx.stroke();

    // Lap number below bar
    ctx.fillStyle = DIM;
    ctx.font = FONT;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    if (n <= 30 || i % Math.ceil(n / 15) === 0) {
      ctx.fillText(String(l.lap_number), x + barW / 2, pad.top + pH + 4);
    }
  }

  // X axis label
  ctx.fillStyle = DIM;
  ctx.font = FONT;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'bottom';
  ctx.fillText('Lap', w / 2, h - 4);

  // Legend
  ctx.font = FONT;
  ctx.textAlign = 'right';
  ctx.textBaseline = 'top';
  const labels = [
    { color: SEGMENT_COLORS.first, text: '1st third' },
    { color: SEGMENT_COLORS.middle, text: 'Middle' },
    { color: SEGMENT_COLORS.last, text: 'Last third' },
  ];
  let lx = w - pad.right;
  for (let i = labels.length - 1; i >= 0; i--) {
    const lb = labels[i]!;
    const tw = ctx.measureText(lb.text).width + 14;
    ctx.fillStyle = lb.color;
    ctx.fillRect(lx - tw, pad.top + 2, 8, 8);
    ctx.fillStyle = TEXT;
    ctx.fillText(lb.text, lx, pad.top + 2);
    lx -= tw + 8;
  }
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds - m * 60;
  return m > 0 ? `${m}:${s.toFixed(2).padStart(5, '0')}` : s.toFixed(2);
}

function niceStep(range: number, targetTicks: number): number {
  const rough = range / targetTicks;
  const mag = Math.pow(10, Math.floor(Math.log10(rough)));
  const norm = rough / mag;
  const nice = norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10;
  return nice * mag;
}
