/**
 * StintChart.tsx — Stint analysis: segmented timeline or lap-time bar fallback.
 * Primary: horizontal blocks per stint, width proportional to lap count.
 * Fallback: vertical bars colored by session segment (1st/mid/last third).
 */
'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { apiFetch } from '@/lib/api-client';
import { chartColor } from '@/components/shared/chart-kit';

interface Stint {
  stint_number: number; start_lap: number; end_lap: number;
  avg_time: number; best_time: number; degradation_rate: number;
}
interface StintResponse { stints: Stint[]; available?: boolean; robustness_metrics?: { consistency_pct: number } }
interface LapProgressResponse { lap_numbers: number[]; times: number[] }
interface StintChartProps { sessionId: string; gpsLaps: number[]; bestLap: number | null; className?: string; controlledLap?: boolean }

type LapEntry = { lap_number: number; lap_time: number };

const FONT = '10px "Space Mono", monospace';
const ACCENT = chartColor.series.positive;
const TEXT = chartColor.textSecondary;
const DIM = chartColor.textMuted;
const PALETTE = chartColor.palette.slice() as string[];
const SEG = { first: chartColor.palette[3], middle: chartColor.series.positive, last: chartColor.series.warning };

const fmtTime = (s: number) => { const m = Math.floor(s / 60); const r = s - m * 60; return m > 0 ? `${m}:${r.toFixed(2).padStart(5, '0')}` : r.toFixed(2); };
const niceStep = (range: number, n: number) => { const r = range / n; const m = Math.pow(10, Math.floor(Math.log10(r))); const k = r / m; return (k < 1.5 ? 1 : k < 3 ? 2 : k < 7 ? 5 : 10) * m; };

export function StintChart({ sessionId, gpsLaps, bestLap, className = '' }: StintChartProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const stintsRef = useRef<Stint[]>([]);
  const fallbackRef = useRef<LapEntry[]>([]);
  const modeRef = useRef<'stints' | 'fallback' | 'none'>('none');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fetchVersionRef = useRef(0);

  useEffect(() => {
    const ver = ++fetchVersionRef.current;
    let done = false;
    setLoading(true); setError(null);
    stintsRef.current = []; fallbackRef.current = []; modeRef.current = 'none';
    (async () => {
      try {
        const res = await apiFetch<StintResponse>(`/sessions/${encodeURIComponent(sessionId)}/stint-analysis`);
        if (ver !== fetchVersionRef.current) return;
        if (res.stints && res.stints.length > 0) { stintsRef.current = res.stints; modeRef.current = 'stints'; done = true; }
      } catch { /* try fallback */ }
      if (done || ver !== fetchVersionRef.current) { if (!done) return; setLoading(false); return; }
      try {
        const p = await apiFetch<LapProgressResponse>(`/sessions/${encodeURIComponent(sessionId)}/lap-progress`);
        if (ver !== fetchVersionRef.current) return;
        if (p.lap_numbers && p.lap_numbers.length > 0) {
          fallbackRef.current = p.lap_numbers.map((num, i) => ({ lap_number: num, lap_time: p.times[i] ?? 0 })).filter(l => l.lap_time > 0);
          modeRef.current = fallbackRef.current.length > 0 ? 'fallback' : 'none';
        }
      } catch (err) {
        if (ver !== fetchVersionRef.current) return;
        setError(err instanceof Error ? err.message : 'Failed to load stint data');
      }
      setLoading(false);
    })();
  }, [sessionId]);

  const draw = useCallback(() => {
    const canvas = canvasRef.current; if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.parentElement?.clientWidth || canvas.clientWidth || 600, h = 220;
    canvas.width = w * dpr; canvas.height = h * dpr;
    canvas.style.width = w + 'px'; canvas.style.height = h + 'px';
    const ctx = canvas.getContext('2d'); if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, w, h);
    if (modeRef.current === 'stints') drawStints(ctx, w, h, stintsRef.current);
    else if (modeRef.current === 'fallback') drawFallback(ctx, w, h, fallbackRef.current);
    else { ctx.fillStyle = DIM; ctx.font = '13px "Space Mono", monospace'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText('No stint data available', w / 2, h / 2); }
  }, []);

  useEffect(() => { if (!loading) draw(); }, [loading, draw]);
  useEffect(() => { const c = containerRef.current; if (!c) return; const ro = new ResizeObserver(() => draw()); ro.observe(c); return () => ro.disconnect(); }, [draw]);

  // Stint analysis uses lap times, not GPS — no gpsLaps guard needed
  return (
    <div ref={containerRef} className={className} role="img" aria-label="Stint analysis chart">
      {loading && <span className="text-xs animate-pulse" style={{ color: TEXT }}>Loading...</span>}
      {error && <span className="text-xs text-safety-red">{error}</span>}
      <div className="relative" style={{ width: '100%' }}>
        <canvas ref={canvasRef} style={{ width: '100%', height: '220px', display: 'block' }} />
      </div>
    </div>
  );
}

function drawStints(ctx: CanvasRenderingContext2D, w: number, h: number, stints: Stint[]) {
  const pad = { top: 30, right: 20, bottom: 40, left: 20 };
  const pW = w - pad.left - pad.right, pH = h - pad.top - pad.bottom;
  const totalLaps = stints.reduce((s, st) => s + (st.end_lap - st.start_lap + 1), 0);
  if (totalLaps === 0) return;

  ctx.fillStyle = TEXT; ctx.font = '11px "Space Mono", monospace';
  ctx.textAlign = 'left'; ctx.textBaseline = 'top';
  ctx.fillText('STINT TIMELINE', pad.left, 8);

  let bestAvg = Infinity;
  for (const st of stints) if (st.avg_time < bestAvg) bestAvg = st.avg_time;

  let xOff = pad.left;
  const gap = Math.min(4, pW / stints.length / 20);

  for (let i = 0; i < stints.length; i++) {
    const st = stints[i]!;
    const lapCount = st.end_lap - st.start_lap + 1;
    const bW = (lapCount / totalLaps) * pW - gap;
    const col = PALETTE[i % PALETTE.length]!;
    const best = st.avg_time === bestAvg;
    const cx = xOff + bW / 2;

    // Block
    ctx.fillStyle = col + '30'; ctx.strokeStyle = best ? ACCENT : col; ctx.lineWidth = best ? 2 : 1;
    ctx.beginPath(); ctx.roundRect(xOff, pad.top, bW, pH, 4); ctx.fill(); ctx.stroke();
    if (best) { ctx.strokeStyle = ACCENT + '40'; ctx.lineWidth = 4; ctx.beginPath(); ctx.roundRect(xOff - 1, pad.top - 1, bW + 2, pH + 2, 5); ctx.stroke(); }

    // Stint label + lap range
    ctx.fillStyle = TEXT; ctx.font = 'bold 12px "Space Mono", monospace'; ctx.textAlign = 'center'; ctx.textBaseline = 'top';
    ctx.fillText(`S${st.stint_number}`, cx, pad.top + 8);
    ctx.fillStyle = DIM; ctx.font = FONT;
    ctx.fillText(`L${st.start_lap}-${st.end_lap}`, cx, pad.top + 24);

    // Avg + best time
    ctx.fillStyle = best ? ACCENT : TEXT; ctx.font = 'bold 11px "Space Mono", monospace'; ctx.textBaseline = 'middle';
    ctx.fillText(fmtTime(st.avg_time), cx, pad.top + pH / 2);
    ctx.fillStyle = DIM; ctx.font = FONT;
    ctx.fillText('best ' + fmtTime(st.best_time), cx, pad.top + pH / 2 + 16);

    // Degradation
    const dY = pad.top + pH - 20, deg = st.degradation_rate;
    if (Math.abs(deg) > 0.01) {
      const dc = deg > 0.3 ? chartColor.series.negative : deg > 0.1 ? chartColor.series.warning : chartColor.series.positive;
      ctx.fillStyle = dc; ctx.font = 'bold 11px "Space Mono", monospace'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText(`${deg > 0 ? '\u2191' : '\u2193'}${Math.abs(deg).toFixed(2)}s`, cx, dY);
      const sL = Math.min(bW * 0.3, 20);
      ctx.strokeStyle = dc; ctx.lineWidth = 1.5; ctx.beginPath();
      ctx.moveTo(cx - sL, dY + 10); ctx.lineTo(cx + sL, dY + 10 - (deg > 0 ? 3 : -3)); ctx.stroke();
    } else {
      ctx.fillStyle = DIM; ctx.font = FONT; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText('flat', cx, dY);
    }
    xOff += bW + gap;
  }

  ctx.fillStyle = DIM; ctx.font = FONT; ctx.textAlign = 'center'; ctx.textBaseline = 'bottom';
  ctx.fillText('Block width proportional to stint lap count', w / 2, h - 4);
}

function drawFallback(ctx: CanvasRenderingContext2D, w: number, h: number, laps: LapEntry[]) {
  const pad = { top: 30, right: 20, bottom: 40, left: 50 };
  const pW = w - pad.left - pad.right, pH = h - pad.top - pad.bottom, n = laps.length;
  if (n === 0) return;

  ctx.fillStyle = TEXT; ctx.font = '11px "Space Mono", monospace'; ctx.textAlign = 'left'; ctx.textBaseline = 'top';
  ctx.fillText('LAP TIMES (no stint data)', pad.left, 8);

  let yMin = Infinity, yMax = -Infinity;
  for (const l of laps) { if (l.lap_time < yMin) yMin = l.lap_time; if (l.lap_time > yMax) yMax = l.lap_time; }
  const yP = (yMax - yMin) * 0.15 || 1; yMin = Math.max(0, yMin - yP); yMax += yP;
  const barW = Math.min(pW / n - 2, 30), sp = (pW - barW * n) / (n + 1);
  const yPx = (v: number) => pad.top + ((yMax - v) / (yMax - yMin)) * pH;

  // Y grid
  const yStep = niceStep(yMax - yMin, 5);
  ctx.strokeStyle = chartColor.grid; ctx.lineWidth = 0.5; ctx.fillStyle = DIM; ctx.font = FONT; ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
  for (let v = Math.ceil(yMin / yStep) * yStep; v <= yMax; v += yStep) {
    const y = yPx(v); ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(w - pad.right, y); ctx.stroke();
    ctx.fillText(fmtTime(v), pad.left - 6, y);
  }

  const third = Math.ceil(n / 3);
  for (let i = 0; i < n; i++) {
    const l = laps[i]!;
    const x = pad.left + sp + i * (barW + sp), y = yPx(l.lap_time), bH = pad.top + pH - y;
    const col = i < third ? SEG.first : i < third * 2 ? SEG.middle : SEG.last;
    ctx.fillStyle = col + '80'; ctx.beginPath(); ctx.roundRect(x, y, barW, bH, [2, 2, 0, 0]); ctx.fill();
    ctx.strokeStyle = col; ctx.lineWidth = 1; ctx.beginPath(); ctx.roundRect(x, y, barW, bH, [2, 2, 0, 0]); ctx.stroke();
    if (n <= 30 || i % Math.ceil(n / 15) === 0) {
      ctx.fillStyle = DIM; ctx.font = FONT; ctx.textAlign = 'center'; ctx.textBaseline = 'top';
      ctx.fillText(String(l.lap_number), x + barW / 2, pad.top + pH + 4);
    }
  }

  ctx.fillStyle = DIM; ctx.font = FONT; ctx.textAlign = 'center'; ctx.textBaseline = 'bottom';
  ctx.fillText('Lap', w / 2, h - 4);

  // Legend
  ctx.textAlign = 'right'; ctx.textBaseline = 'top';
  const labels: { color: string; text: string }[] = [
    { color: SEG.first, text: '1st third' }, { color: SEG.middle, text: 'Middle' }, { color: SEG.last, text: 'Last third' },
  ];
  let lx = w - pad.right;
  for (let i = labels.length - 1; i >= 0; i--) {
    const lb = labels[i]!; const tw = ctx.measureText(lb.text).width + 14;
    ctx.fillStyle = lb.color; ctx.fillRect(lx - tw, pad.top + 2, 8, 8);
    ctx.fillStyle = TEXT; ctx.fillText(lb.text, lx, pad.top + 2); lx -= tw + 8;
  }
}
