'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { api } from '@/lib/api-client';

/* ── Types ──────────────────────────────────── */

interface SpeedTraceData {
  distances: number[];
  speeds: number[];
  available?: boolean;
}

interface LapSpeedOverlayProps {
  sessionId: string;
  apiBase?: string;
  gpsLaps: number[];
  bestLap: number | null;
  className?: string;
}

/* ── Colors ─────────────────────────────────── */

const PALETTE = [
  '#00ff64', '#58a6ff', '#ff6b35', '#d29922', '#ff3c8e',
  '#8b5cf6', '#06b6d4', '#eab308', '#f87171', '#34d399',
];

const C = {
  bg: '#0B0C0F',
  grid: '#30363d',
  text: '#888',
  bright: '#F0EDE5',
};

/* ── Helpers ────────────────────────────────── */

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
  for (let v = start; v <= hi; v += niceStep) ticks.push(v);
  return ticks;
}

/* ── Draw ───────────────────────────────────── */

function draw(
  canvas: HTMLCanvasElement,
  traces: Map<number, SpeedTraceData>,
  enabledLaps: Set<number>,
  bestLap: number | null,
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

  if (enabledLaps.size === 0 || traces.size === 0) {
    ctx.fillStyle = C.text;
    ctx.font = '13px "Space Mono", monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('Select laps to overlay', w / 2, h / 2);
    return;
  }

  // Find data ranges across all enabled laps
  let maxDist = 0, maxSpeed = 0;
  for (const [lap, data] of traces) {
    if (!enabledLaps.has(lap) || !data.distances || data.distances.length < 2) continue;
    const d = data.distances[data.distances.length - 1];
    if (d > maxDist) maxDist = d;
    for (const s of data.speeds) {
      const kmh = s * 3.6;
      if (kmh > maxSpeed) maxSpeed = kmh;
    }
  }
  maxSpeed *= 1.1;

  const pad = { top: 20, right: 20, bottom: 50, left: 60 };
  const pW = w - pad.left - pad.right;
  const pH = h - pad.top - pad.bottom;

  const xToPixel = (d: number) => pad.left + (d / maxDist) * pW;
  const yToPixel = (v: number) => pad.top + pH - (v / maxSpeed) * pH;

  // Grid
  ctx.strokeStyle = C.grid;
  ctx.lineWidth = 0.5;
  const yTicks = niceRange(0, maxSpeed, 5);
  for (const tick of yTicks) {
    const y = yToPixel(tick);
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(pad.left + pW, y);
    ctx.stroke();
  }
  const xTicks = niceRange(0, maxDist, 6);
  for (const tick of xTicks) {
    const x = xToPixel(tick);
    ctx.beginPath();
    ctx.moveTo(x, pad.top);
    ctx.lineTo(x, pad.top + pH);
    ctx.stroke();
  }

  // Y-axis labels
  ctx.fillStyle = C.text;
  ctx.font = '10px "Space Mono", monospace';
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  for (const tick of yTicks) ctx.fillText(tick.toFixed(0), pad.left - 6, yToPixel(tick));

  // X-axis labels
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  for (const tick of xTicks) ctx.fillText(`${tick.toFixed(0)}m`, xToPixel(tick), pad.top + pH + 6);

  // Axis titles
  ctx.fillText('Distance (m)', pad.left + pW / 2, pad.top + pH + 26);
  ctx.save();
  ctx.translate(14, pad.top + pH / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText('Speed (km/h)', 0, 0);
  ctx.restore();

  // Draw each enabled lap
  const lapOrder = [...enabledLaps].sort((a, b) => a - b);
  let legendY = pad.top + 4;

  for (let li = 0; li < lapOrder.length; li++) {
    const lap = lapOrder[li];
    const data = traces.get(lap);
    if (!data || !data.distances || data.distances.length < 2) continue;

    const color = PALETTE[li % PALETTE.length];
    const isBest = lap === bestLap;

    ctx.strokeStyle = color;
    ctx.lineWidth = isBest ? 2.5 : 1.5;
    ctx.globalAlpha = isBest ? 1 : 0.7;
    ctx.beginPath();
    for (let i = 0; i < data.distances.length; i++) {
      const x = xToPixel(data.distances[i]);
      const y = yToPixel(data.speeds[i] * 3.6);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke();
    ctx.globalAlpha = 1;

    // Legend entry
    ctx.fillStyle = color;
    ctx.font = '10px "Space Mono", monospace';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    const label = isBest ? `Lap ${lap} (Best)` : `Lap ${lap}`;
    ctx.fillText(`── ${label}`, pad.left + 8, legendY);
    legendY += 13;
  }
}

/* ── Component ──────────────────────────────── */

export function LapSpeedOverlay({
  sessionId,
  gpsLaps,
  bestLap,
  className = '',
}: LapSpeedOverlayProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [traces, setTraces] = useState<Map<number, SpeedTraceData>>(new Map());
  const [enabledLaps, setEnabledLaps] = useState<Set<number>>(new Set());
  const [loading, setLoading] = useState(false);

  // Initialize: enable best lap + first 2 others
  useEffect(() => {
    if (gpsLaps.length === 0) return;
    const initial = new Set<number>();
    if (bestLap != null) initial.add(bestLap);
    for (const l of gpsLaps) {
      if (initial.size >= 3) break;
      initial.add(l);
    }
    setEnabledLaps(initial);
  }, [gpsLaps, bestLap]);

  // Fetch speed traces for enabled laps
  useEffect(() => {
    if (enabledLaps.size === 0) return;
    let cancelled = false;
    setLoading(true);

    const toFetch = [...enabledLaps].filter((l) => !traces.has(l));

    if (toFetch.length === 0) {
      setLoading(false);
      return;
    }

    Promise.all(
      toFetch.map(async (lap) => {
        try {
          const data = await api.get<SpeedTraceData>(
            `/sessions/${encodeURIComponent(sessionId)}/speed-trace?lap=${lap}`,
          );
          return [lap, data] as const;
        } catch {
          return [lap, { distances: [], speeds: [], available: false }] as const;
        }
      }),
    ).then((results) => {
      if (cancelled) return;
      setTraces((prev) => {
        const next = new Map(prev);
        for (const [lap, data] of results) {
          if (data.available !== false) next.set(lap, data);
        }
        return next;
      });
      setLoading(false);
    });

    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, enabledLaps]);

  const toggleLap = useCallback((lap: number) => {
    setEnabledLaps((prev) => {
      const next = new Set(prev);
      if (next.has(lap)) next.delete(lap); else next.add(lap);
      return next;
    });
  }, []);

  const selectAll = useCallback(() => {
    setEnabledLaps(new Set(gpsLaps));
  }, [gpsLaps]);

  const clearAll = useCallback(() => {
    setEnabledLaps(new Set());
  }, []);

  const render = useCallback(() => {
    if (!canvasRef.current) return;
    draw(canvasRef.current, traces, enabledLaps, bestLap);
  }, [traces, enabledLaps, bestLap]);

  useEffect(() => { render(); }, [render]);
  useEffect(() => {
    const c = canvasRef.current;
    if (!c) return;
    const ro = new ResizeObserver(() => render());
    ro.observe(c);
    return () => ro.disconnect();
  }, [render]);

  return (
    <div className={`relative ${className}`}>
      {/* Lap toggle buttons */}
      <div className="flex items-center gap-2 mb-2 flex-wrap">
        <button
          type="button"
          onClick={selectAll}
          className="px-2 py-0.5 text-[10px] rounded bg-concrete text-steel border border-steel/20 hover:text-chalk transition-colors font-telemetry"
        >
          All
        </button>
        <button
          type="button"
          onClick={clearAll}
          className="px-2 py-0.5 text-[10px] rounded bg-concrete text-steel border border-steel/20 hover:text-chalk transition-colors font-telemetry"
        >
          None
        </button>
        {gpsLaps.map((lap, i) => {
          const on = enabledLaps.has(lap);
          const color = PALETTE[i % PALETTE.length];
          return (
            <button
              key={lap}
              type="button"
              onClick={() => toggleLap(lap)}
              className={`px-2 py-0.5 text-[10px] rounded font-telemetry transition-colors border ${
                on
                  ? 'border-current'
                  : 'border-steel/20 text-steel/40'
              }`}
              style={on ? { color, borderColor: color + '60' } : undefined}
            >
              {lap}{lap === bestLap ? ' B' : ''}
            </button>
          );
        })}
      </div>

      {/* Canvas */}
      <div className="relative" style={{ minHeight: '250px' }}>
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center z-10">
            <div className="w-5 h-5 border-2 border-steel/30 border-t-chalk rounded-full animate-spin" />
          </div>
        )}
        <canvas
          ref={canvasRef}
          className="w-full h-full cursor-crosshair"
          style={{ display: 'block', minHeight: '250px' }}
          role="img"
          aria-label="Speed overlay comparing multiple laps"
        />
      </div>
    </div>
  );
}
