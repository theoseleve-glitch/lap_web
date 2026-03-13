'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { api } from '@/lib/api-client';

/* ── Types ──────────────────────────────────── */

interface LapData {
  lap_number: number;
  lap_time_s: number | null;
  is_best: number;
  is_valid: number;
}

interface LapProgressTrackerProps {
  sessionId: string;
  apiBase?: string;
  className?: string;
}

/* ── Colors ─────────────────────────────────── */

const C = {
  bg: '#0B0C0F',
  grid: '#30363d',
  text: '#888',
  bright: '#F0EDE5',
  line: '#58a6ff',
  dot: '#58a6ff',
  best: '#00ff64',
  pb: '#d29922',
  avg: '#ff6b35',
  invalid: '#ff3c3c',
  zone_fast: 'rgba(0,255,100,0.08)',
  zone_slow: 'rgba(255,60,60,0.06)',
};

/* ── Helpers ────────────────────────────────── */

function formatTime(s: number): string {
  if (s >= 60) {
    const m = Math.floor(s / 60);
    const sec = s - m * 60;
    return `${m}:${sec.toFixed(2).padStart(5, '0')}`;
  }
  return `${s.toFixed(2)}s`;
}

/* ── Draw ───────────────────────────────────── */

function draw(canvas: HTMLCanvasElement, laps: LapData[]) {
  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const w = rect.width, h = rect.height;
  if (w === 0 || h === 0) return;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = C.bg;
  ctx.fillRect(0, 0, w, h);

  const valid = laps.filter((l) => l.is_valid && l.lap_time_s != null && l.lap_time_s > 0);
  if (valid.length < 2) {
    ctx.fillStyle = C.text;
    ctx.font = '13px "Space Mono", monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('Not enough laps for progress chart', w / 2, h / 2);
    return;
  }

  const times = valid.map((l) => l.lap_time_s!);
  const lapNums = valid.map((l) => l.lap_number);
  const mean = times.reduce((s, t) => s + t, 0) / times.length;

  // Running personal best
  const runningPB: number[] = [];
  let pb = Infinity;
  for (const t of times) {
    if (t < pb) pb = t;
    runningPB.push(pb);
  }

  const minT = Math.min(...times) * 0.995;
  const maxT = Math.max(...times) * 1.005;

  // Layout
  const pad = { top: 20, right: 20, bottom: 50, left: 60 };
  const pW = w - pad.left - pad.right;
  const pH = h - pad.top - pad.bottom;

  const xToPixel = (i: number) => pad.left + (i / (valid.length - 1)) * pW;
  const yToPixel = (t: number) => pad.top + pH - ((t - minT) / (maxT - minT)) * pH;

  // Grid
  ctx.strokeStyle = C.grid;
  ctx.lineWidth = 0.5;
  const nYTicks = 5;
  for (let i = 0; i <= nYTicks; i++) {
    const t = minT + ((maxT - minT) * i) / nYTicks;
    const y = yToPixel(t);
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(pad.left + pW, y);
    ctx.stroke();
  }

  // Pace zones (above/below mean)
  const meanY = yToPixel(mean);
  ctx.fillStyle = C.zone_fast;
  ctx.fillRect(pad.left, meanY, pW, pad.top + pH - meanY);
  ctx.fillStyle = C.zone_slow;
  ctx.fillRect(pad.left, pad.top, pW, meanY - pad.top);

  // Mean line
  ctx.strokeStyle = C.avg;
  ctx.lineWidth = 1;
  ctx.setLineDash([6, 3]);
  ctx.beginPath();
  ctx.moveTo(pad.left, meanY);
  ctx.lineTo(pad.left + pW, meanY);
  ctx.stroke();
  ctx.setLineDash([]);

  // Running PB line
  ctx.strokeStyle = C.pb;
  ctx.lineWidth = 1.5;
  ctx.setLineDash([4, 3]);
  ctx.beginPath();
  for (let i = 0; i < valid.length; i++) {
    const x = xToPixel(i), y = yToPixel(runningPB[i]);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }
  ctx.stroke();
  ctx.setLineDash([]);

  // Lap time line
  ctx.strokeStyle = C.line;
  ctx.lineWidth = 2;
  ctx.beginPath();
  for (let i = 0; i < valid.length; i++) {
    const x = xToPixel(i), y = yToPixel(times[i]);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }
  ctx.stroke();

  // Dots
  for (let i = 0; i < valid.length; i++) {
    const x = xToPixel(i), y = yToPixel(times[i]);
    const isBest = !!valid[i].is_best;
    ctx.beginPath();
    ctx.arc(x, y, isBest ? 5 : 3, 0, Math.PI * 2);
    ctx.fillStyle = isBest ? C.best : C.dot;
    ctx.fill();
    if (isBest) {
      ctx.strokeStyle = C.best;
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }
  }

  // Y-axis labels
  ctx.fillStyle = C.text;
  ctx.font = '10px "Space Mono", monospace';
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  for (let i = 0; i <= nYTicks; i++) {
    const t = minT + ((maxT - minT) * i) / nYTicks;
    ctx.fillText(formatTime(t), pad.left - 6, yToPixel(t));
  }

  // X-axis labels
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  const step = Math.max(1, Math.floor(valid.length / 8));
  for (let i = 0; i < valid.length; i += step) {
    ctx.fillText(`L${lapNums[i]}`, xToPixel(i), pad.top + pH + 6);
  }
  // Always label last
  if ((valid.length - 1) % step !== 0) {
    ctx.fillText(`L${lapNums[valid.length - 1]}`, xToPixel(valid.length - 1), pad.top + pH + 6);
  }

  // Axis title
  ctx.fillText('Lap', pad.left + pW / 2, pad.top + pH + 26);

  // Legend
  ctx.font = '10px "Space Mono", monospace';
  ctx.textAlign = 'left';
  ctx.textBaseline = 'top';
  let lx = pad.left + 8, ly = pad.top + 4;

  ctx.fillStyle = C.line;
  ctx.fillText('── Lap Time', lx, ly); ly += 13;
  ctx.fillStyle = C.pb;
  ctx.fillText('--- Running PB', lx, ly); ly += 13;
  ctx.fillStyle = C.avg;
  ctx.fillText(`--- Mean: ${formatTime(mean)}`, lx, ly);
}

/* ── Component ──────────────────────────────── */

export function LapProgressTracker({ sessionId, className = '' }: LapProgressTrackerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [laps, setLaps] = useState<LapData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const res = await api.get<{ laps: LapData[] }>(`/sessions/${sessionId}/laps`);
        if (!cancelled) setLaps(res.laps ?? []);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [sessionId]);

  const render = useCallback(() => {
    if (!canvasRef.current || laps.length === 0) return;
    draw(canvasRef.current, laps);
  }, [laps]);

  useEffect(() => { render(); }, [render]);
  useEffect(() => {
    const c = canvasRef.current;
    if (!c) return;
    const ro = new ResizeObserver(() => render());
    ro.observe(c);
    return () => ro.disconnect();
  }, [render]);

  if (error) {
    return <div className={`text-red-400 p-4 text-sm ${className}`}>{error}</div>;
  }

  return (
    <div className={`relative ${className}`} style={{ minHeight: '220px' }}>
      {loading && (
        <div className="absolute inset-0 flex items-center justify-center z-10">
          <div className="w-5 h-5 border-2 border-steel/30 border-t-chalk rounded-full animate-spin" />
        </div>
      )}
      <canvas
        ref={canvasRef}
        className="w-full h-full cursor-default"
        style={{ display: 'block', minHeight: '220px' }}
        role="img"
        aria-label="Lap time progress chart showing improvement over the session"
      />
    </div>
  );
}
