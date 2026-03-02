'use client';

import { useRef, useEffect, useCallback } from 'react';
import type { AnalyzerTrace, ChartConfig } from './types';

interface AnalyzerChartProps {
  trace: AnalyzerTrace;
  overlayTrace: AnalyzerTrace | null;
  config: ChartConfig;
  currentDistance: number;
  /** If set, only show this distance range */
  sectionRange: { min: number; max: number } | null;
  onScrub?: (distance: number) => void;
}

/* ── Extract the relevant data channel from a trace ─────── */

function getChannel(trace: AnalyzerTrace, type: string): number[] {
  switch (type) {
    case 'speed': return trace.speed;
    case 'g-lat': return trace.gLat;
    case 'brake': return trace.brake;
    case 'throttle': return trace.throttle;
    case 'steering': return trace.steering;
    default: return trace.speed;
  }
}

/* ── Closest index binary search ─────────────────────────── */

function closestIdx(arr: number[], target: number): number {
  let lo = 0, hi = arr.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (arr[mid] < target) lo = mid + 1;
    else hi = mid;
  }
  if (lo > 0 && Math.abs(arr[lo - 1] - target) < Math.abs(arr[lo] - target)) return lo - 1;
  return lo;
}

/* ── Component ────────────────────────────────────────────── */

export function AnalyzerChart({
  trace,
  overlayTrace,
  config,
  currentDistance,
  sectionRange,
  onScrub,
}: AnalyzerChartProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const boundsRef = useRef<{
    xMin: number; xMax: number; plotX: number; plotW: number;
  } | null>(null);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;

    const dpr = window.devicePixelRatio || 1;
    const w = container.clientWidth;
    const h = container.clientHeight;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = w + 'px';
    canvas.style.height = h + 'px';
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const pad = { top: 16, right: 12, bottom: 20, left: 46 };
    const pW = w - pad.left - pad.right;
    const pH = h - pad.top - pad.bottom;

    // Background
    ctx.fillStyle = '#0d1117';
    ctx.fillRect(0, 0, w, h);

    const dist = trace.distance;
    if (dist.length < 2) return;

    // Determine visible distance range
    const xMin = sectionRange?.min ?? 0;
    const xMax = sectionRange?.max ?? dist[dist.length - 1];
    boundsRef.current = { xMin, xMax, plotX: pad.left, plotW: pW };

    // Find index range for visible window
    const startIdx = closestIdx(dist, xMin);
    const endIdx = closestIdx(dist, xMax);

    const xToPixel = (d: number) => pad.left + ((d - xMin) / (xMax - xMin || 1)) * pW;

    // Get data values for range computation
    const isDual = config.dual;
    const values1 = isDual ? trace.brake : getChannel(trace, config.type);
    const values2 = isDual ? trace.throttle : null;

    // Compute Y range
    let yMin = Infinity, yMax = -Infinity;
    for (let i = startIdx; i <= endIdx; i++) {
      const v = values1[i];
      if (v < yMin) yMin = v;
      if (v > yMax) yMax = v;
      if (values2) {
        const v2 = values2[i];
        if (v2 < yMin) yMin = v2;
        if (v2 > yMax) yMax = v2;
      }
    }

    // For symmetric channels (g-lat, steering), center around 0
    if (config.type === 'g-lat' || config.type === 'steering') {
      const absMax = Math.max(Math.abs(yMin), Math.abs(yMax), 0.1);
      yMin = -absMax;
      yMax = absMax;
    } else if (isDual) {
      yMin = 0;
      yMax = Math.max(yMax, 1);
    } else {
      // Speed — add 5% padding
      const range = yMax - yMin || 1;
      yMin -= range * 0.05;
      yMax += range * 0.05;
    }

    const yToPixel = (v: number) => pad.top + pH - ((v - yMin) / (yMax - yMin || 1)) * pH;

    // Grid lines
    ctx.strokeStyle = '#1b2332';
    ctx.lineWidth = 0.5;
    const ySteps = 4;
    for (let i = 0; i <= ySteps; i++) {
      const v = yMin + (i / ySteps) * (yMax - yMin);
      const y = yToPixel(v);
      ctx.beginPath();
      ctx.moveTo(pad.left, y);
      ctx.lineTo(w - pad.right, y);
      ctx.stroke();
    }

    // Y axis labels
    ctx.fillStyle = '#6e7681';
    ctx.font = '9px "Space Mono", monospace';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    for (let i = 0; i <= ySteps; i++) {
      const v = yMin + (i / ySteps) * (yMax - yMin);
      ctx.fillText(formatValue(v, config.type), pad.left - 4, yToPixel(v));
    }

    // Zero line for symmetric charts
    if (config.type === 'g-lat' || config.type === 'steering') {
      ctx.strokeStyle = '#4e5561';
      ctx.lineWidth = 0.8;
      ctx.beginPath();
      const zy = yToPixel(0);
      ctx.moveTo(pad.left, zy);
      ctx.lineTo(w - pad.right, zy);
      ctx.stroke();
    }

    // Clip to plot area
    ctx.save();
    ctx.beginPath();
    ctx.rect(pad.left, pad.top, pW, pH);
    ctx.clip();

    // Draw overlay trace first (dimmer)
    if (overlayTrace) {
      const ov1 = isDual ? overlayTrace.brake : getChannel(overlayTrace, config.type);
      drawLine(ctx, overlayTrace.distance, ov1, xToPixel, yToPixel, 'rgba(201,168,76,0.35)', 1.5, xMin, xMax);
      if (isDual) {
        drawLine(ctx, overlayTrace.distance, overlayTrace.throttle, xToPixel, yToPixel, 'rgba(201,168,76,0.25)', 1.5, xMin, xMax);
      }
    }

    // Draw primary trace
    if (isDual) {
      // Brake (red) + Throttle (green)
      drawFilled(ctx, dist, trace.brake, xToPixel, yToPixel, yToPixel(0), 'rgba(255,42,42,0.25)');
      drawLine(ctx, dist, trace.brake, xToPixel, yToPixel, '#FF2A2A', 1.5, xMin, xMax);
      drawFilled(ctx, dist, trace.throttle, xToPixel, yToPixel, yToPixel(0), 'rgba(240,237,229,0.12)');
      drawLine(ctx, dist, trace.throttle, xToPixel, yToPixel, '#F0EDE5', 1.5, xMin, xMax);
    } else {
      drawLine(ctx, dist, values1, xToPixel, yToPixel, config.color, 2, xMin, xMax);
    }

    ctx.restore(); // unclip

    // Cursor line
    if (currentDistance >= xMin && currentDistance <= xMax) {
      const cx = xToPixel(currentDistance);
      ctx.strokeStyle = 'rgba(240,237,229,0.5)';
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(cx, pad.top);
      ctx.lineTo(cx, pad.top + pH);
      ctx.stroke();
      ctx.setLineDash([]);

      // Value dot
      const valIdx = closestIdx(dist, currentDistance);
      if (valIdx >= 0 && valIdx < values1.length) {
        const val = values1[valIdx];
        const dy = yToPixel(val);
        ctx.beginPath();
        ctx.arc(cx, dy, 4, 0, Math.PI * 2);
        ctx.fillStyle = config.color;
        ctx.fill();
      }
    }

    // Chart label
    ctx.fillStyle = '#6e7681';
    ctx.font = '9px "Space Mono", monospace';
    ctx.textAlign = 'left';
    ctx.fillText(`${config.label} (${config.unit})`, pad.left + 4, pad.top + 10);

    // Dual legend
    if (isDual) {
      ctx.fillStyle = '#FF2A2A';
      ctx.fillText('BRK', w - pad.right - 60, pad.top + 10);
      ctx.fillStyle = '#F0EDE5';
      ctx.fillText('THR', w - pad.right - 30, pad.top + 10);
    }
  }, [trace, overlayTrace, config, currentDistance, sectionRange]);

  useEffect(() => { draw(); }, [draw]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const ro = new ResizeObserver(() => draw());
    ro.observe(container);
    return () => ro.disconnect();
  }, [draw]);

  // Mouse scrubbing
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !onScrub) return;

    const handleMove = (e: MouseEvent) => {
      const bounds = boundsRef.current;
      if (!bounds) return;
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      if (mx < bounds.plotX || mx > bounds.plotX + bounds.plotW) return;
      const d = bounds.xMin + ((mx - bounds.plotX) / bounds.plotW) * (bounds.xMax - bounds.xMin);
      onScrub(d);
    };

    canvas.addEventListener('mousemove', handleMove);
    return () => canvas.removeEventListener('mousemove', handleMove);
  }, [onScrub, draw]);

  return (
    <div ref={containerRef} className="w-full h-full min-h-[60px]">
      <canvas ref={canvasRef} className="w-full h-full cursor-crosshair" />
    </div>
  );
}

/* ── Draw helpers ─────────────────────────────────────────── */

function drawLine(
  ctx: CanvasRenderingContext2D,
  dist: number[], values: number[],
  xToPixel: (d: number) => number, yToPixel: (v: number) => number,
  color: string, lineWidth: number,
  xMin: number, xMax: number,
) {
  ctx.strokeStyle = color;
  ctx.lineWidth = lineWidth;
  ctx.lineJoin = 'round';
  ctx.beginPath();
  let started = false;
  for (let i = 0; i < dist.length; i++) {
    if (dist[i] < xMin || dist[i] > xMax) continue;
    const x = xToPixel(dist[i]);
    const y = yToPixel(values[i] ?? 0);
    if (!started) { ctx.moveTo(x, y); started = true; }
    else ctx.lineTo(x, y);
  }
  ctx.stroke();
}

function drawFilled(
  ctx: CanvasRenderingContext2D,
  dist: number[], values: number[],
  xToPixel: (d: number) => number, yToPixel: (v: number) => number,
  baseline: number, fillColor: string,
) {
  ctx.fillStyle = fillColor;
  ctx.beginPath();
  let firstX = 0;
  let started = false;
  for (let i = 0; i < dist.length; i++) {
    const x = xToPixel(dist[i]);
    const y = yToPixel(values[i] ?? 0);
    if (!started) { firstX = x; ctx.moveTo(x, baseline); ctx.lineTo(x, y); started = true; }
    else ctx.lineTo(x, y);
  }
  if (started) {
    ctx.lineTo(xToPixel(dist[dist.length - 1]), baseline);
    ctx.lineTo(firstX, baseline);
    ctx.closePath();
    ctx.fill();
  }
}

function formatValue(v: number, type: string): string {
  switch (type) {
    case 'speed': return Math.round(v).toString();
    case 'g-lat': return v.toFixed(1);
    case 'brake-throttle': return Math.round(v * 100).toString();
    case 'steering': return Math.round(v).toString();
    default: return v.toFixed(1);
  }
}
