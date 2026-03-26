/** Canvas histogram of lap time distribution with mean/median/Q1/Q3 markers. */
'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { apiFetch } from '@/lib/api-client';

interface DistributionData {
  bins: number[];
  counts: number[];
  mean: number;
  median: number;
  std: number;
  q1: number;
  q3: number;
  n_valid: number;
}

interface LapDistributionChartProps {
  sessionId: string;
  gpsLaps: number[];
  bestLap: number | null;
  className?: string;
  controlledLap?: boolean;
}

const ACID = '#b4ff39';
const STEEL = '#c4c4c4';
const FONT = '10px "Space Mono", monospace';

export function LapDistributionChart({
  sessionId,
  gpsLaps,
  bestLap,
  className = '',
}: LapDistributionChartProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const dataRef = useRef<DistributionData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fetchVersionRef = useRef(0);

  useEffect(() => {
    const ver = ++fetchVersionRef.current;
    setLoading(true); setError(null); dataRef.current = null;
    (async () => {
      try {
        const data = await apiFetch<DistributionData>(
          `/sessions/${encodeURIComponent(sessionId)}/lap-distribution`,
        );
        if (ver !== fetchVersionRef.current) return;
        if (!data.bins || data.bins.length < 2) {
          setError('Not enough laps for distribution');
        } else {
          dataRef.current = data;
        }
      } catch (e) {
        if (ver !== fetchVersionRef.current) return;
        setError(e instanceof Error ? e.message : 'Failed to load distribution');
      }
      setLoading(false);
    })();
  }, [sessionId]);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const d = dataRef.current;

    const dpr = window.devicePixelRatio || 1;
    const w = canvas.parentElement?.clientWidth || canvas.clientWidth || 600;
    const h = 240;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = w + 'px';
    canvas.style.height = h + 'px';

    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    ctx.clearRect(0, 0, w, h);

    const pad = { top: 20, right: 16, bottom: 38, left: 44 };
    const pW = w - pad.left - pad.right;
    const pH = h - pad.top - pad.bottom;

    if (!d || d.bins.length < 2 || d.counts.length === 0) {
      ctx.fillStyle = STEEL;
      ctx.font = '13px "Space Mono", monospace';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText('No data', w / 2, h / 2);
      return;
    }

    const bins = d.bins;
    const counts = d.counts;
    const nBars = counts.length;
    const xMin = bins[0];
    const xMax = bins[bins.length - 1];
    const xRange = xMax - xMin || 1;
    const yMax = Math.max(...counts);
    const yTop = yMax + Math.max(1, Math.ceil(yMax * 0.15));

    const xPx = (v: number) => pad.left + ((v - xMin) / xRange) * pW;
    const yPx = (v: number) => pad.top + pH - (v / yTop) * pH;

    // Y grid lines
    ctx.strokeStyle = 'rgba(196,196,196,0.12)';
    ctx.lineWidth = 0.5;
    const yStep = yTop <= 5 ? 1 : yTop <= 15 ? 2 : yTop <= 40 ? 5 : 10;
    for (let v = 0; v <= yTop; v += yStep) {
      const y = yPx(v);
      ctx.beginPath();
      ctx.moveTo(pad.left, y);
      ctx.lineTo(pad.left + pW, y);
      ctx.stroke();
    }

    // Histogram bars
    const barGap = Math.max(1, Math.round(pW / nBars * 0.08));
    ctx.fillStyle = 'rgba(180, 255, 57, 0.6)';
    for (let i = 0; i < nBars; i++) {
      const x1 = xPx(bins[i]) + barGap;
      const x2 = xPx(bins[i + 1]) - barGap;
      const barW = x2 - x1;
      if (barW <= 0) continue;
      const barH = (counts[i] / yTop) * pH;
      ctx.fillRect(x1, pad.top + pH - barH, barW, barH);
    }

    // Vertical reference lines
    const drawVLine = (val: number, color: string, dash: number[]) => {
      if (val < xMin || val > xMax) return;
      const x = xPx(val);
      ctx.strokeStyle = color;
      ctx.lineWidth = 1;
      ctx.setLineDash(dash);
      ctx.beginPath();
      ctx.moveTo(x, pad.top);
      ctx.lineTo(x, pad.top + pH);
      ctx.stroke();
      ctx.setLineDash([]);
    };

    drawVLine(d.q1, 'rgba(196,196,196,0.4)', [3, 4]);
    drawVLine(d.q3, 'rgba(196,196,196,0.4)', [3, 4]);
    drawVLine(d.mean, 'rgba(255,255,255,0.7)', [5, 4]);
    drawVLine(d.median, ACID, [5, 4]);

    // X axis labels
    ctx.fillStyle = STEEL;
    ctx.font = FONT;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    const labelStep = Math.max(1, Math.ceil(bins.length / Math.floor(pW / 50)));
    for (let i = 0; i < bins.length; i += labelStep) {
      ctx.fillText(bins[i].toFixed(1) + 's', xPx(bins[i]), pad.top + pH + 6);
    }

    // X axis title
    ctx.fillStyle = STEEL;
    ctx.font = FONT;
    ctx.textAlign = 'center';
    ctx.fillText('Lap Time (s)', pad.left + pW / 2, h - 4);

    // Y axis labels
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    for (let v = 0; v <= yTop; v += yStep) {
      ctx.fillText(String(v), pad.left - 6, yPx(v));
    }

    // Y axis title
    ctx.save();
    ctx.translate(10, pad.top + pH / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.textAlign = 'center';
    ctx.fillText('Count', 0, 0);
    ctx.restore();

    // Legend (top-right)
    ctx.font = FONT;
    ctx.textAlign = 'right';
    ctx.textBaseline = 'top';
    const lx = pad.left + pW;
    const ly = pad.top + 2;
    const lineH = 14;

    ctx.fillStyle = 'rgba(255,255,255,0.7)';
    ctx.fillText('Mean: ' + d.mean.toFixed(2) + 's', lx, ly);
    ctx.fillStyle = ACID;
    ctx.fillText('Median: ' + d.median.toFixed(2) + 's', lx, ly + lineH);
    ctx.fillStyle = STEEL;
    ctx.fillText('Std: ' + d.std.toFixed(2) + 's', lx, ly + lineH * 2);
    ctx.fillText('n=' + d.n_valid, lx, ly + lineH * 3);
  }, []);

  useEffect(() => { if (!loading) draw(); }, [loading, draw]);

  useEffect(() => {
    const c = containerRef.current;
    if (!c) return;
    const ro = new ResizeObserver(() => draw());
    ro.observe(c);
    return () => ro.disconnect();
  }, [draw]);

  return (
    <div ref={containerRef} className={className} role="img" aria-label="Lap time distribution histogram">
      {loading && <span className="text-xs text-steel animate-pulse block mb-2">Loading...</span>}
      {error && <span className="text-xs text-red-400 block mb-2">{error}</span>}
      <div className="relative" style={{ width: '100%' }}>
        <canvas ref={canvasRef} style={{ width: '100%', height: '240px', display: 'block' }} />
      </div>
    </div>
  );
}
