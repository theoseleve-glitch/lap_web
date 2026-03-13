/**
 * SpeedTraceChart.tsx — Pure React speed-vs-distance chart.
 *
 * Architecture mirrors CornerReplayCockpit: useRef<canvas>, pure draw function,
 * useEffect for rendering, ResizeObserver for responsiveness. No vanilla JS
 * modules, no DOMContentLoaded, no window globals.
 *
 * Fetches data from:
 *   GET /api/v1/sessions/{id}/speed-trace?lap=N     (distances, speeds)
 *   GET /api/v1/sessions/{id}/speed-trace?lap=N&avg=1 (avg_speeds overlay)
 */
'use client';

import { useEffect, useRef, useState, useCallback, useMemo } from 'react';
import { api } from '@/lib/api-client';
import { useChartHoverStore } from '@/lib/chart-hover-store';

// ── Design tokens ────────────────────────────────────────────────
const COLORS = {
  bg: '#141414',
  grid: '#30363d',
  text: '#888888',
  textBright: '#F0EDE5',
  accent: '#ff6b35',
  yellow: '#d29922',
  cyan: '#58a6ff',
};

// ── Types ────────────────────────────────────────────────────────
interface SpeedTraceData {
  distances: number[];
  speeds: number[];
  ref_speeds?: number[];
  avg_speeds?: number[];
  available?: boolean;
}

interface SpeedTraceChartProps {
  sessionId?: string;
  data?: SpeedTraceData;
  onHoverDistance?: (d: number) => void;
  className?: string;
  gpsLaps?: number[];
  bestLap?: number | null;
  apiBase?: string;
  /** When set, fetches ref lap and draws delta time sub-chart */
  compareLap?: number | null;
  /** Actual lap time of the primary lap (seconds) */
  primaryLapTime?: number | null;
  /** Actual lap time of the compare lap (seconds) */
  compareLapTime?: number | null;
  /** When true, lap selection is controlled by parent (hides per-chart selector) */
  controlledLap?: boolean;
}

// ── Helpers ──────────────────────────────────────────────────────
function speedColor(speed: number, min: number, max: number): string {
  let t = max > min ? (speed - min) / (max - min) : 0.5;
  t = Math.max(0, Math.min(1, t));
  let r: number, g: number, b: number;
  if (t < 0.25) {
    r = 0; g = Math.round(255 * (t / 0.25)); b = 255;
  } else if (t < 0.5) {
    r = 0; g = 255; b = Math.round(255 * (1 - (t - 0.25) / 0.25));
  } else if (t < 0.75) {
    r = Math.round(255 * ((t - 0.5) / 0.25)); g = 255; b = 0;
  } else {
    r = 255; g = Math.round(255 * (1 - (t - 0.75) / 0.25)); b = 0;
  }
  return `rgb(${r},${g},${b})`;
}

function niceRange(lo: number, hi: number, count: number): number[] {
  const range = hi - lo;
  if (range <= 0) return [lo];
  const step = range / count;
  const mag = Math.pow(10, Math.floor(Math.log10(step)));
  const residual = step / mag;
  let niceStep: number;
  if (residual <= 1.5) niceStep = 1;
  else if (residual <= 3) niceStep = 2;
  else if (residual <= 7) niceStep = 5;
  else niceStep = 10;
  niceStep *= mag;

  const ticks: number[] = [];
  const start = Math.ceil(lo / niceStep) * niceStep;
  for (let v = start; v <= hi; v += niceStep) {
    ticks.push(v);
  }
  return ticks;
}

function closestIndex(arr: number[], target: number): number {
  if (!arr || arr.length === 0) return -1;
  let lo = 0, hi = arr.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if ((arr[mid] ?? 0) < target) lo = mid + 1;
    else hi = mid;
  }
  if (lo > 0 && Math.abs((arr[lo - 1] ?? 0) - target) < Math.abs((arr[lo] ?? 0) - target)) {
    return lo - 1;
  }
  return lo;
}

// ── Pure draw function ───────────────────────────────────────────
interface DrawOptions {
  distances: number[];
  speeds: number[];       // m/s
  avgSpeeds?: number[];   // m/s
  refSpeeds?: number[];   // m/s
  hoverDistanceM: number | null;
  /** When set, ref line legend shows "Lap N" instead of "Theoretical" */
  refLapLabel?: string | null;
  /** Primary lap label shown in legend */
  primaryLapLabel?: string | null;
}

function drawSpeedTrace(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  opts: DrawOptions,
): { xMin: number; xMax: number; yMin: number; yMax: number; plotX: number; plotY: number; plotW: number; plotH: number } | null {
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = COLORS.bg;
  ctx.fillRect(0, 0, w, h);

  const { distances, speeds, avgSpeeds, refSpeeds, hoverDistanceM } = opts;
  if (!distances || distances.length < 2) {
    ctx.fillStyle = COLORS.text;
    ctx.font = '13px "Space Mono", monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('No speed trace data', w / 2, h / 2);
    return null;
  }

  const pad = { top: 20, right: 20, bottom: 50, left: 60 };
  const pW = w - pad.left - pad.right;
  const pH = h - pad.top - pad.bottom;

  // Data ranges — use loop-based max to avoid stack overflow on large arrays
  const safeMax = (arr: number[]): number => {
    let m = -Infinity;
    for (const v of arr) { if (v != null && isFinite(v) && v > m) m = v; }
    return m === -Infinity ? 0 : m;
  };
  const safeMin = (arr: number[]): number => {
    let m = Infinity;
    for (const v of arr) { if (v != null && isFinite(v) && v < m) m = v; }
    return m === Infinity ? 0 : m;
  };
  const validSpeeds = speeds.filter((s): s is number => s != null && isFinite(s));
  const xMin = 0;
  const xMax = safeMax(distances);
  const yMin = 0;
  let yMax = (validSpeeds.length > 0 ? safeMax(validSpeeds) : 1) * 3.6 * 1.1;

  // Extend yMax for reference/avg overlays
  if (refSpeeds && refSpeeds.length > 0) {
    const refMax = safeMax(refSpeeds) * 3.6 * 1.1;
    if (refMax > yMax) yMax = refMax;
  }
  if (avgSpeeds && avgSpeeds.length > 0) {
    const avgMax = safeMax(avgSpeeds) * 3.6 * 1.1;
    if (avgMax > yMax) yMax = avgMax;
  }

  const bounds = { xMin, xMax, yMin, yMax, plotX: pad.left, plotY: pad.top, plotW: pW, plotH: pH };

  const xToPixel = (v: number) => pad.left + (v - xMin) / (xMax - xMin) * pW;
  const yToPixel = (v: number) => pad.top + pH - (v - yMin) / (yMax - yMin) * pH;

  // Grid lines
  ctx.strokeStyle = COLORS.grid;
  ctx.lineWidth = 0.5;
  const yTicks = niceRange(yMin, yMax, 5);
  for (const tick of yTicks) {
    const y = yToPixel(tick);
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(w - pad.right, y);
    ctx.stroke();
  }
  const xTicks = niceRange(xMin, xMax, 6);
  for (const tick of xTicks) {
    const x = xToPixel(tick);
    ctx.beginPath();
    ctx.moveTo(x, pad.top);
    ctx.lineTo(x, pad.top + pH);
    ctx.stroke();
  }

  // Y-axis labels
  ctx.fillStyle = COLORS.text;
  ctx.font = '11px "Space Mono", monospace';
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  for (const tick of yTicks) {
    ctx.fillText(tick.toFixed(0), pad.left - 8, yToPixel(tick));
  }

  // X-axis labels
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  for (const tick of xTicks) {
    ctx.fillText(`${tick.toFixed(0)}m`, xToPixel(tick), pad.top + pH + 8);
  }

  // Axis titles
  ctx.fillStyle = COLORS.text;
  ctx.font = '12px "Space Mono", monospace';
  ctx.textAlign = 'center';
  ctx.fillText('Distance (m)', pad.left + pW / 2, pad.top + pH + 30);
  ctx.save();
  ctx.translate(14, pad.top + pH / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText('Speed (km/h)', 0, 0);
  ctx.restore();

  // Legend y-offset tracker
  let legendY = pad.top + 4;

  // Reference line (dashed gold)
  if (refSpeeds && refSpeeds.length > 0) {
    ctx.strokeStyle = COLORS.yellow;
    ctx.lineWidth = 2;
    ctx.setLineDash([8, 4]);
    ctx.beginPath();
    let started = false;
    for (let i = 0; i < Math.min(distances.length, refSpeeds.length); i++) {
      const d = distances[i]!, rs = refSpeeds[i]!;
      if (d == null || rs == null || !isFinite(rs)) continue;
      const x = xToPixel(d);
      const y = yToPixel(rs * 3.6);
      if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
    }
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = COLORS.yellow;
    ctx.font = '10px "Space Mono", monospace';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    ctx.fillText(opts.refLapLabel ? `--- ${opts.refLapLabel}` : '--- Theoretical', pad.left + 8, legendY);
    legendY += 12;
  }

  // Average pace (dotted cyan)
  if (avgSpeeds && avgSpeeds.length > 0) {
    ctx.strokeStyle = COLORS.cyan;
    ctx.lineWidth = 1.5;
    ctx.setLineDash([4, 4]);
    ctx.globalAlpha = 0.6;
    ctx.beginPath();
    let started = false;
    for (let i = 0; i < Math.min(distances.length, avgSpeeds.length); i++) {
      const d = distances[i]!, as_ = avgSpeeds[i]!;
      if (d == null || as_ == null || !isFinite(as_)) continue;
      const x = xToPixel(d);
      const y = yToPixel(as_ * 3.6);
      if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
    }
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.globalAlpha = 1.0;
    ctx.fillStyle = COLORS.cyan;
    ctx.font = '10px "Space Mono", monospace';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    ctx.fillText('... Avg Pace', pad.left + 8, legendY);
    legendY += 12;
  }

  // Primary lap label
  if (opts.primaryLapLabel) {
    ctx.fillStyle = COLORS.accent;
    ctx.font = '10px "Space Mono", monospace';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    ctx.fillText(`── ${opts.primaryLapLabel}`, pad.left + 8, legendY);
    legendY += 12;
  }

  // Main speed trace (color gradient)
  const sMin = validSpeeds.length > 0 ? safeMin(validSpeeds) : 0;
  const sMax = validSpeeds.length > 0 ? safeMax(validSpeeds) : 1;
  ctx.lineWidth = 2;
  for (let i = 0; i < distances.length - 1; i++) {
    const d0 = distances[i]!, s0 = speeds[i]!;
    const d1 = distances[i + 1]!, s1 = speeds[i + 1]!;
    if (d0 == null || s0 == null || d1 == null || s1 == null) continue;
    ctx.strokeStyle = speedColor(s0, sMin, sMax);
    ctx.beginPath();
    ctx.moveTo(xToPixel(d0), yToPixel(s0 * 3.6));
    ctx.lineTo(xToPixel(d1), yToPixel(s1 * 3.6));
    ctx.stroke();
  }

  // Hover crosshair
  if (hoverDistanceM !== null && hoverDistanceM >= xMin && hoverDistanceM <= xMax) {
    const hx = xToPixel(hoverDistanceM);
    ctx.strokeStyle = COLORS.textBright + '60';
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 3]);
    ctx.beginPath();
    ctx.moveTo(hx, pad.top);
    ctx.lineTo(hx, pad.top + pH);
    ctx.stroke();
    ctx.setLineDash([]);

    // Tooltip at hover position
    const idx = closestIndex(distances, hoverDistanceM);
    if (idx >= 0 && idx < speeds.length && speeds[idx] != null && isFinite(speeds[idx])) {
      const kmh = (speeds[idx] * 3.6).toFixed(0);
      const label = `${kmh} km/h @ ${hoverDistanceM.toFixed(0)}m`;
      const speedY = yToPixel(speeds[idx] * 3.6);

      // Speed dot
      ctx.beginPath();
      ctx.arc(hx, speedY, 4, 0, Math.PI * 2);
      ctx.fillStyle = COLORS.accent;
      ctx.fill();

      // Tooltip background
      ctx.font = '11px "Space Mono", monospace';
      const tw = ctx.measureText(label).width + 12;
      const tx = Math.min(hx + 8, w - pad.right - tw);
      const ty = Math.max(pad.top, speedY - 24);
      ctx.fillStyle = 'rgba(0,0,0,0.85)';
      ctx.beginPath();
      ctx.roundRect(tx, ty, tw, 20, 4);
      ctx.fill();
      ctx.fillStyle = COLORS.textBright;
      ctx.textAlign = 'left';
      ctx.textBaseline = 'middle';
      ctx.fillText(label, tx + 6, ty + 10);
    }
  }

  return bounds;
}

// ── Delta time drawing ──────────────────────────────────────────
/** Compute cumulative time delta between primary and ref speeds.
 *  Uses trapezoidal integration, then scales to match actual lap time diff.
 *  Positive = primary is slower (losing time). */
function computeDeltaTime(
  distances: number[],
  primarySpeeds: number[],
  refSpeeds: number[],
  actualDeltaS: number | null,
): number[] {
  const n = Math.min(distances.length, primarySpeeds.length, refSpeeds.length);
  const delta: number[] = [0];
  const MIN_SPEED = 0.5; // m/s floor to avoid div-by-zero
  for (let i = 1; i < n; i++) {
    const ds = distances[i] - distances[i - 1];
    if (ds <= 0) { delta.push(delta[delta.length - 1]); continue; }
    // Trapezoidal: average speed over segment
    const sp = Math.max(MIN_SPEED, (primarySpeeds[i - 1] + primarySpeeds[i]) / 2);
    const sr = Math.max(MIN_SPEED, (refSpeeds[i - 1] + refSpeeds[i]) / 2);
    const dt = ds / sp - ds / sr;
    delta.push(delta[delta.length - 1] + dt);
  }
  // Scale to match actual lap time difference if available
  if (actualDeltaS != null && delta.length > 1) {
    const rawFinal = delta[delta.length - 1];
    if (Math.abs(rawFinal) > 0.001) {
      const scale = actualDeltaS / rawFinal;
      for (let i = 1; i < delta.length; i++) {
        delta[i] *= scale;
      }
    }
  }
  return delta;
}

function drawDeltaChart(
  ctx: CanvasRenderingContext2D,
  x0: number,
  y0: number,
  w: number,
  h: number,
  distances: number[],
  deltaSeconds: number[],
  hoverDistanceM: number | null,
  primaryLapNum: number,
  compareLapNum: number,
) {
  const pad = { top: 6, right: 20, bottom: 22, left: 60 };
  const pW = w - pad.left - pad.right;
  const pH = h - pad.top - pad.bottom;
  const ox = x0 + pad.left;
  const oy = y0 + pad.top;

  // Separator line
  ctx.strokeStyle = COLORS.grid;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(x0, y0);
  ctx.lineTo(x0 + w, y0);
  ctx.stroke();

  // Background
  ctx.fillStyle = '#0d0d0d';
  ctx.fillRect(x0, y0, w, h);

  if (distances.length < 2 || deltaSeconds.length < 2) return;

  const n = Math.min(distances.length, deltaSeconds.length);
  const xMin = 0;
  const xMax = distances[distances.length - 1];

  // Y range — symmetric around zero
  let maxAbs = 0;
  for (let i = 0; i < n; i++) {
    const a = Math.abs(deltaSeconds[i]);
    if (a > maxAbs) maxAbs = a;
  }
  if (maxAbs < 0.1) maxAbs = 0.1;
  const yMax = maxAbs * 1.15;
  const yMin = -yMax;

  const xToPixel = (v: number) => ox + (v - xMin) / (xMax - xMin) * pW;
  const yToPixel = (v: number) => oy + pH - (v - yMin) / (yMax - yMin) * pH;

  // Zero line
  const zeroY = yToPixel(0);
  ctx.strokeStyle = '#555';
  ctx.lineWidth = 0.5;
  ctx.setLineDash([4, 3]);
  ctx.beginPath();
  ctx.moveTo(ox, zeroY);
  ctx.lineTo(ox + pW, zeroY);
  ctx.stroke();
  ctx.setLineDash([]);

  // Y-axis ticks
  ctx.fillStyle = COLORS.text;
  ctx.font = '10px "Space Mono", monospace';
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  const yTicks = niceRange(yMin, yMax, 3);
  for (const tick of yTicks) {
    const ty = yToPixel(tick);
    ctx.fillText(`${tick > 0 ? '+' : ''}${tick.toFixed(1)}s`, ox - 6, ty);
    if (tick !== 0) {
      ctx.strokeStyle = COLORS.grid;
      ctx.lineWidth = 0.3;
      ctx.beginPath();
      ctx.moveTo(ox, ty);
      ctx.lineTo(ox + pW, ty);
      ctx.stroke();
    }
  }

  // Delta area fill + line
  ctx.beginPath();
  ctx.moveTo(xToPixel(distances[0]), zeroY);
  for (let i = 0; i < n; i++) {
    ctx.lineTo(xToPixel(distances[i]), yToPixel(deltaSeconds[i]));
  }
  ctx.lineTo(xToPixel(distances[n - 1]), zeroY);
  ctx.closePath();

  // Fill: green when faster (negative delta), red when slower (positive)
  // Use gradient from the actual data
  const lastDelta = deltaSeconds[n - 1];
  ctx.fillStyle = lastDelta <= 0 ? 'rgba(0,255,100,0.12)' : 'rgba(255,60,60,0.12)';
  ctx.fill();

  // Line colored by sign
  for (let i = 0; i < n - 1; i++) {
    const d = deltaSeconds[i];
    ctx.strokeStyle = d <= 0 ? '#00ff64' : '#ff3c3c';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(xToPixel(distances[i]), yToPixel(deltaSeconds[i]));
    ctx.lineTo(xToPixel(distances[i + 1]), yToPixel(deltaSeconds[i + 1]));
    ctx.stroke();
  }

  // Label
  ctx.fillStyle = COLORS.text;
  ctx.font = '9px "Space Mono", monospace';
  ctx.textAlign = 'left';
  ctx.textBaseline = 'top';
  ctx.fillText(`\u0394t Lap ${primaryLapNum} vs ${compareLapNum}`, ox + 4, oy + 2);

  // Final delta value
  const finalDelta = deltaSeconds[n - 1];
  const sign = finalDelta <= 0 ? '' : '+';
  ctx.fillStyle = finalDelta <= 0 ? '#00ff64' : '#ff3c3c';
  ctx.font = '11px "Space Mono", monospace';
  ctx.textAlign = 'right';
  ctx.fillText(`${sign}${finalDelta.toFixed(3)}s`, ox + pW - 4, oy + 2);

  // Hover crosshair
  if (hoverDistanceM !== null && hoverDistanceM >= xMin && hoverDistanceM <= xMax) {
    const hx = xToPixel(hoverDistanceM);
    ctx.strokeStyle = COLORS.textBright + '60';
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 3]);
    ctx.beginPath();
    ctx.moveTo(hx, oy);
    ctx.lineTo(hx, oy + pH);
    ctx.stroke();
    ctx.setLineDash([]);

    // Find closest delta value
    const idx = closestIndex(distances, hoverDistanceM);
    if (idx >= 0 && idx < deltaSeconds.length) {
      const dt = deltaSeconds[idx];
      const dtSign = dt <= 0 ? '' : '+';
      const label = `${dtSign}${dt.toFixed(3)}s`;
      ctx.font = '10px "Space Mono", monospace';
      const tw = ctx.measureText(label).width + 8;
      const tx = Math.min(hx + 6, x0 + w - pad.right - tw);
      const ty = Math.max(oy, yToPixel(dt) - 14);
      ctx.fillStyle = 'rgba(0,0,0,0.85)';
      ctx.beginPath();
      ctx.roundRect(tx, ty, tw, 16, 3);
      ctx.fill();
      ctx.fillStyle = dt <= 0 ? '#00ff64' : '#ff3c3c';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'middle';
      ctx.fillText(label, tx + 4, ty + 8);
    }
  }
}

// ── Component ────────────────────────────────────────────────────
export function SpeedTraceChart({
  sessionId,
  data: externalData,
  onHoverDistance,
  className = '',
  gpsLaps = [],
  bestLap = null,
  compareLap = null,
  primaryLapTime = null,
  compareLapTime = null,
  controlledLap = false,
}: SpeedTraceChartProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const boundsRef = useRef<ReturnType<typeof drawSpeedTrace>>(null);

  const [traceData, setTraceData] = useState<SpeedTraceData | null>(null);
  const [avgSpeeds, setAvgSpeeds] = useState<number[] | null>(null);
  const [refSpeeds, setRefSpeeds] = useState<number[] | null>(null);
  const [activeCompareLap, setActiveCompareLap] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedLap, setSelectedLap] = useState<number | null>(null);

  const hoverDistance = useChartHoverStore((s) => s.hoverDistance);
  const setHover = useChartHoverStore((s) => s.setHover);
  const clearHover = useChartHoverStore((s) => s.clearHover);

  // Sync selectedLap when controlled externally (e.g. Focus Mode unified selector)
  useEffect(() => {
    if (controlledLap && bestLap != null) setSelectedLap(bestLap);
  }, [controlledLap, bestLap]);

  const activeLap = selectedLap ?? bestLap ?? (gpsLaps.length > 0 ? gpsLaps[0] : null);

  // Determine data source
  const chartData = externalData || traceData;

  // ── Fetch speed trace data ──────────────────────────────────
  useEffect(() => {
    if (externalData || !sessionId || activeLap == null) return;
    let cancelled = false;
    setLoading(true);
    setError(null);

    const fetchTrace = async () => {
      try {
        const data = await api.get<SpeedTraceData>(
          `/sessions/${encodeURIComponent(sessionId)}/speed-trace?lap=${activeLap}&avg=1`,
        );
        if (cancelled) return;
        if (data.available === false) {
          setError('No speed trace data available');
          setTraceData(null);
        } else {
          setTraceData(data);
          if (data.avg_speeds) setAvgSpeeds(data.avg_speeds);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load speed trace');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    fetchTrace();
    return () => { cancelled = true; };
  }, [sessionId, activeLap, externalData]);

  // ── Fetch reference lap for comparison ────────────────────────
  useEffect(() => {
    if (!sessionId || !compareLap || activeLap == null || compareLap === activeLap) {
      setRefSpeeds(null);
      setActiveCompareLap(null);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const data = await api.get<SpeedTraceData & { ref_speeds?: number[] }>(
          `/sessions/${encodeURIComponent(sessionId)}/speed-trace?lap=${activeLap}&ref=${compareLap}`,
        );
        if (cancelled) return;
        if (data.ref_speeds) {
          setRefSpeeds(data.ref_speeds);
          setActiveCompareLap(compareLap);
        }
      } catch {
        if (!cancelled) { setRefSpeeds(null); setActiveCompareLap(null); }
      }
    })();
    return () => { cancelled = true; };
  }, [sessionId, activeLap, compareLap]);

  // ── Draw ────────────────────────────────────────────────────
  // Compute delta time when ref data is available
  const actualDelta = (primaryLapTime != null && compareLapTime != null)
    ? primaryLapTime - compareLapTime
    : null;

  const deltaSeconds = useMemo(() => {
    if (!chartData?.distances || !chartData?.speeds || !refSpeeds) return null;
    return computeDeltaTime(chartData.distances, chartData.speeds, refSpeeds, actualDelta);
  }, [chartData, refSpeeds, actualDelta]);

  const render = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);

    if (!chartData || !chartData.distances || chartData.distances.length < 2) {
      drawSpeedTrace(ctx, rect.width, rect.height, {
        distances: [],
        speeds: [],
        hoverDistanceM: null,
      });
      boundsRef.current = null;
      return;
    }

    // Split: if delta data, top 65% speed trace, bottom 35% delta
    const hasDelta = deltaSeconds && deltaSeconds.length > 1 && activeCompareLap != null;
    const speedH = hasDelta ? Math.round(rect.height * 0.65) : rect.height;
    const deltaH = hasDelta ? rect.height - speedH : 0;

    boundsRef.current = drawSpeedTrace(ctx, rect.width, speedH, {
      distances: chartData.distances,
      speeds: chartData.speeds,
      refSpeeds: refSpeeds ?? chartData.ref_speeds,
      avgSpeeds: !refSpeeds ? (avgSpeeds ?? chartData.avg_speeds) : undefined,
      hoverDistanceM: hoverDistance,
      refLapLabel: activeCompareLap != null ? `Lap ${activeCompareLap}` : null,
      primaryLapLabel: activeCompareLap != null ? `Lap ${activeLap}` : null,
    });

    if (hasDelta && deltaSeconds) {
      drawDeltaChart(
        ctx, 0, speedH, rect.width, deltaH,
        chartData.distances, deltaSeconds,
        hoverDistance, activeLap!, activeCompareLap!,
      );
    }
  }, [chartData, avgSpeeds, refSpeeds, deltaSeconds, activeCompareLap, hoverDistance]);

  useEffect(() => {
    render();
  }, [render]);

  // ── ResizeObserver ──────────────────────────────────────────
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const observer = new ResizeObserver(() => render());
    observer.observe(canvas);
    return () => observer.disconnect();
  }, [render]);

  // ── Mouse hover → emit distance ────────────────────────────
  const handleMouseMove = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const bounds = boundsRef.current;
      if (!bounds || !chartData) return;
      const canvas = canvasRef.current;
      if (!canvas) return;

      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;

      const distM = bounds.xMin + (mx - bounds.plotX) / bounds.plotW * (bounds.xMax - bounds.xMin);
      if (distM < bounds.xMin || distM > bounds.xMax) return;

      setHover(distM, 'speed-trace');
      onHoverDistance?.(distM);
    },
    [chartData, setHover, onHoverDistance],
  );

  const handleMouseLeave = useCallback(() => {
    clearHover();
  }, [clearHover]);

  // ── Hover from ANY chart → redraw crosshair ────────────────
  // Handled by hoverDistance in the render callback — any chart
  // (including self) setting hover triggers a React re-render.

  // ── Lap selector ───────────────────────────────────────────
  const showLapSelector = !controlledLap && !!sessionId && gpsLaps.length > 1;

  // ── Render ─────────────────────────────────────────────────
  if (error && !chartData) {
    return (
      <div className={`flex items-center justify-center rounded-lg border border-steel/10 bg-concrete ${className}`} style={{ minHeight: '250px' }}>
        <div className="text-steel p-4 text-sm text-center">
          <p className="font-telemetry text-chalk mb-1">Speed Trace</p>
          <p className="text-red-400 text-xs">{error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className={`relative flex flex-col ${className}`}>
      {/* Lap selector */}
      {showLapSelector && (
        <div className="flex items-center gap-2 mb-2">
          <span className="text-steel text-xs font-telemetry">Lap:</span>
          <div className="flex gap-1 flex-wrap">
            {gpsLaps.map((lap) => (
              <button
                key={lap}
                type="button"
                onClick={() => setSelectedLap(lap)}
                className={`px-2 py-0.5 text-xs font-telemetry rounded transition-colors ${
                  lap === activeLap
                    ? 'bg-accent/20 text-accent border border-accent/40'
                    : 'bg-asphalt text-steel border border-steel/20 hover:text-chalk hover:border-steel/40'
                }`}
              >
                {lap}
                {lap === bestLap && <span className="ml-1 text-[9px] text-acid-green">best</span>}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Loading overlay */}
      {loading && (
        <div className="absolute inset-0 flex items-center justify-center bg-concrete/80 z-10 rounded-lg">
          <div className="w-5 h-5 border-2 border-accent border-t-transparent rounded-full animate-spin" />
        </div>
      )}

      {/* Canvas */}
      <div
        className="relative w-full flex-1 min-h-0 rounded-lg bg-concrete border border-steel/10"
        style={!className.includes('h-full') ? { minHeight: '280px' } : undefined}
      >
        <canvas
          ref={canvasRef}
          className="w-full h-full cursor-crosshair"
          style={{ display: 'block' }}
          onMouseMove={handleMouseMove}
          onMouseLeave={handleMouseLeave}
          role="img"
          aria-label="Speed versus distance chart"
        />
        {!chartData && !loading && (
          <div className="absolute inset-0 flex items-center justify-center">
            <p className="text-steel text-sm font-telemetry">No speed data</p>
          </div>
        )}
      </div>
    </div>
  );
}
