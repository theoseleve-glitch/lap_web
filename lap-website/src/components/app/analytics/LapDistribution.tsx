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

interface LapDistributionProps {
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
  bar: '#58a6ff',
  barBest: '#00ff64',
  barInvalid: '#ff3c3c50',
  median: '#d29922',
  mean: '#ff6b35',
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

function draw(
  canvas: HTMLCanvasElement,
  laps: LapData[],
) {
  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const w = rect.width, h = rect.height;
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
    ctx.fillText('Not enough laps for distribution', w / 2, h / 2);
    return;
  }

  const times = valid.map((l) => l.lap_time_s!);
  const bestIdx = valid.findIndex((l) => l.is_best === 1);
  const sorted = [...times].sort((a, b) => a - b);
  const minT = sorted[0];
  const maxT = sorted[sorted.length - 1];
  const range = maxT - minT;
  const mean = times.reduce((s, t) => s + t, 0) / times.length;
  const median = sorted.length % 2 === 0
    ? (sorted[sorted.length / 2 - 1] + sorted[sorted.length / 2]) / 2
    : sorted[Math.floor(sorted.length / 2)];

  // Histogram bins
  const nBins = Math.min(Math.max(Math.ceil(Math.sqrt(times.length)), 4), 15);
  const binWidth = range > 0 ? range / nBins : 1;
  const bins: number[] = new Array(nBins).fill(0);
  const binLaps: number[][] = Array.from({ length: nBins }, () => []);

  for (let i = 0; i < times.length; i++) {
    let bi = Math.floor((times[i] - minT) / binWidth);
    if (bi >= nBins) bi = nBins - 1;
    bins[bi]++;
    binLaps[bi].push(i);
  }

  const maxCount = Math.max(...bins);

  // Layout
  const pad = { top: 20, right: 20, bottom: 50, left: 50 };
  const pW = w - pad.left - pad.right;
  const pH = h - pad.top - pad.bottom;

  // Scales
  const xToPixel = (t: number) => pad.left + ((t - minT) / (range || 1)) * pW;
  const yToPixel = (c: number) => pad.top + pH - (c / (maxCount * 1.15)) * pH;

  // Grid
  ctx.strokeStyle = C.grid;
  ctx.lineWidth = 0.5;
  for (let i = 1; i <= maxCount; i++) {
    const y = yToPixel(i);
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(pad.left + pW, y);
    ctx.stroke();
  }

  // Bars
  const barW = Math.max(2, pW / nBins - 2);
  for (let i = 0; i < nBins; i++) {
    if (bins[i] === 0) continue;
    const binStart = minT + i * binWidth;
    const x = xToPixel(binStart + binWidth / 2) - barW / 2;
    const y = yToPixel(bins[i]);
    const barH = yToPixel(0) - y;

    // Color: check if best lap is in this bin
    const hasBest = binLaps[i].some((li) => li === bestIdx);
    ctx.fillStyle = hasBest ? C.barBest : C.bar;
    ctx.globalAlpha = 0.7;
    ctx.beginPath();
    ctx.roundRect(x, y, barW, barH, 2);
    ctx.fill();
    ctx.globalAlpha = 1;

    // Count label
    if (bins[i] > 0) {
      ctx.fillStyle = C.bright;
      ctx.font = '10px "Space Mono", monospace';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'bottom';
      ctx.fillText(String(bins[i]), x + barW / 2, y - 2);
    }
  }

  // Mean line
  const meanX = xToPixel(mean);
  ctx.strokeStyle = C.mean;
  ctx.lineWidth = 1.5;
  ctx.setLineDash([6, 3]);
  ctx.beginPath();
  ctx.moveTo(meanX, pad.top);
  ctx.lineTo(meanX, pad.top + pH);
  ctx.stroke();
  ctx.setLineDash([]);

  // Median line
  const medX = xToPixel(median);
  ctx.strokeStyle = C.median;
  ctx.lineWidth = 1.5;
  ctx.setLineDash([3, 3]);
  ctx.beginPath();
  ctx.moveTo(medX, pad.top);
  ctx.lineTo(medX, pad.top + pH);
  ctx.stroke();
  ctx.setLineDash([]);

  // X-axis labels
  ctx.fillStyle = C.text;
  ctx.font = '10px "Space Mono", monospace';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  const nTicks = Math.min(6, nBins);
  for (let i = 0; i <= nTicks; i++) {
    const t = minT + (range * i) / nTicks;
    ctx.fillText(formatTime(t), xToPixel(t), pad.top + pH + 6);
  }

  // Y-axis
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  for (let i = 1; i <= maxCount; i++) {
    ctx.fillText(String(i), pad.left - 6, yToPixel(i));
  }

  // Axis title
  ctx.textAlign = 'center';
  ctx.fillText('Lap Time', pad.left + pW / 2, pad.top + pH + 28);

  // Legend
  ctx.font = '10px "Space Mono", monospace';
  ctx.textAlign = 'left';
  ctx.textBaseline = 'top';
  let lx = pad.left + 8, ly = pad.top + 4;

  ctx.fillStyle = C.mean;
  ctx.fillText(`--- Mean: ${formatTime(mean)}`, lx, ly);
  ly += 13;
  ctx.fillStyle = C.median;
  ctx.fillText(`... Median: ${formatTime(median)}`, lx, ly);
  ly += 13;

  // Std dev
  const variance = times.reduce((s, t) => s + (t - mean) ** 2, 0) / times.length;
  const stdDev = Math.sqrt(variance);
  ctx.fillStyle = C.text;
  ctx.fillText(`σ ${stdDev.toFixed(3)}s`, lx, ly);
}

/* ── Component ──────────────────────────────── */

export function LapDistribution({ sessionId, className = '' }: LapDistributionProps) {
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
        aria-label="Lap time distribution histogram"
      />
    </div>
  );
}
