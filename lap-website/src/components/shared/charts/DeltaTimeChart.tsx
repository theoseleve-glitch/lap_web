/**
 * DeltaTimeChart.tsx — Cumulative time delta between two laps.
 *
 * Renders a filled area chart:
 *   - Green fill above zero = lap A faster (gaining time)
 *   - Red fill below zero = lap A slower (losing time)
 *   - X axis = distance (m), Y axis = cumulative Δt (seconds)
 *
 * Integrates with useChartHoverStore for cross-chart hover sync.
 */
'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { apiFetch } from '@/lib/api-client';
import { useChartHoverStore } from '@/lib/chart-hover-store';

interface DeltaData {
  distances: number[];
  delta_s: number[];
  lap_a: number;
  lap_b: number;
}

interface DeltaTimeChartProps {
  sessionId: string;
  gpsLaps: number[];
  bestLap: number | null;
  className?: string;
}

export function DeltaTimeChart({
  sessionId,
  gpsLaps,
  bestLap,
  className = '',
}: DeltaTimeChartProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const dataRef = useRef<DeltaData | null>(null);
  const boundsRef = useRef<{
    xMin: number; xMax: number; yMin: number; yMax: number;
    plotX: number; plotY: number; plotW: number; plotH: number;
  } | null>(null);

  const safeLaps = gpsLaps ?? [];
  const [lapA, setLapA] = useState<number>(bestLap ?? safeLaps[0] ?? 0);
  const [lapB, setLapB] = useState<number>(() => {
    // Default lap B: second lap or first non-best lap
    if (safeLaps.length < 2) return 0;
    const other = safeLaps.find((l) => l !== (bestLap ?? safeLaps[0]));
    return other ?? safeLaps[1] ?? 0;
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // ── Fetch delta data ──────────────────────────────────────────
  const fetchDelta = useCallback(async () => {
    if (!lapA || !lapB || lapA === lapB) {
      dataRef.current = null;
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch<DeltaData | { available: false }>(
        `/sessions/${encodeURIComponent(sessionId)}/delta?lap_a=${lapA}&lap_b=${lapB}`,
      );
      if ('available' in data && !data.available) {
        dataRef.current = null;
        setError('No delta data available for these laps');
      } else {
        dataRef.current = data as DeltaData;
      }
    } catch (err) {
      dataRef.current = null;
      setError(err instanceof Error ? err.message : 'Failed to load delta');
    } finally {
      setLoading(false);
    }
  }, [sessionId, lapA, lapB]);

  useEffect(() => {
    fetchDelta();
  }, [fetchDelta]);

  // ── Draw chart ────────────────────────────────────────────────
  const draw = useCallback((hoverDist: number | null = null) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const data = dataRef.current;

    const dpr = window.devicePixelRatio || 1;
    const w = canvas.parentElement?.clientWidth || canvas.clientWidth || 700;
    const h = 220;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = w + 'px';
    canvas.style.height = h + 'px';

    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const pad = { top: 20, right: 20, bottom: 38, left: 58 };
    const pW = w - pad.left - pad.right;
    const pH = h - pad.top - pad.bottom;

    // Background — matches SpeedTraceChart (#141414)
    ctx.fillStyle = '#141414';
    ctx.fillRect(0, 0, w, h);

    if (!data || !data.distances || data.distances.length < 2) {
      ctx.fillStyle = '#888888';
      ctx.font = '13px "Space Mono", monospace';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(
        lapA === lapB ? 'Select two different laps to compare' : 'No delta data available',
        w / 2,
        h / 2,
      );
      boundsRef.current = null;
      return;
    }

    const dists = data.distances;
    const deltas = data.delta_s;

    // Compute ranges
    const xMin = 0;
    const xMax = dists[dists.length - 1] || 1;
    let maxAbs = 0;
    for (let i = 0; i < deltas.length; i++) {
      const a = Math.abs(deltas[i]);
      if (a > maxAbs) maxAbs = a;
    }
    if (maxAbs < 0.05) maxAbs = 0.1;
    maxAbs = Math.ceil(maxAbs * 20) / 20; // round up to nearest 0.05

    const yMin = -maxAbs;
    const yMax = maxAbs;

    boundsRef.current = { xMin, xMax, yMin, yMax, plotX: pad.left, plotY: pad.top, plotW: pW, plotH: pH };

    const xToPixel = (v: number) => pad.left + ((v - xMin) / (xMax - xMin)) * pW;
    const yToPixel = (v: number) => pad.top + pH / 2 - (v / maxAbs) * (pH / 2);

    // Grid
    ctx.strokeStyle = '#30363d';
    ctx.lineWidth = 0.5;

    // Y grid — symmetric around zero
    const yStep = maxAbs <= 0.2 ? 0.05 : maxAbs <= 0.5 ? 0.1 : maxAbs <= 1 ? 0.2 : maxAbs <= 2 ? 0.5 : 1;
    for (let v = -maxAbs; v <= maxAbs + 0.001; v += yStep) {
      const y = yToPixel(v);
      ctx.beginPath();
      ctx.moveTo(pad.left, y);
      ctx.lineTo(w - pad.right, y);
      ctx.stroke();
    }

    // X grid
    const xRange = xMax - xMin;
    const xStep = xRange <= 200 ? 25 : xRange <= 500 ? 50 : xRange <= 1000 ? 100 : xRange <= 3000 ? 250 : 500;
    for (let v = 0; v <= xMax; v += xStep) {
      const x = xToPixel(v);
      ctx.beginPath();
      ctx.moveTo(x, pad.top);
      ctx.lineTo(x, pad.top + pH);
      ctx.stroke();
    }

    // Zero line (bold)
    ctx.strokeStyle = '#6e7681';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(pad.left, yToPixel(0));
    ctx.lineTo(w - pad.right, yToPixel(0));
    ctx.stroke();

    // Y axis labels
    ctx.fillStyle = '#888888';
    ctx.font = '11px "Space Mono", monospace';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    for (let v = -maxAbs; v <= maxAbs + 0.001; v += yStep) {
      const label = v === 0 ? '0' : (v > 0 ? '+' : '') + v.toFixed(v % 1 === 0 ? 0 : Math.abs(v) < 0.5 ? 2 : 1);
      ctx.fillText(label + 's', pad.left - 6, yToPixel(v));
    }

    // X axis labels
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    for (let v = 0; v <= xMax; v += xStep) {
      ctx.fillText(v.toFixed(0) + 'm', xToPixel(v), pad.top + pH + 6);
    }

    // Axis titles
    ctx.fillStyle = '#888888';
    ctx.font = '12px "Space Mono", monospace';
    ctx.textAlign = 'center';
    ctx.fillText('Distance (m)', pad.left + pW / 2, h - 4);
    ctx.save();
    ctx.translate(12, pad.top + pH / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText('Time Delta (s)', 0, 0);
    ctx.restore();

    // ── Clip to plot area ────────────────────────────────────
    ctx.save();
    ctx.beginPath();
    ctx.rect(pad.left, pad.top, pW, pH);
    ctx.clip();

    // Green fill (positive = lap A faster)
    ctx.beginPath();
    ctx.moveTo(xToPixel(dists[0]), yToPixel(0));
    for (let i = 0; i < dists.length; i++) {
      ctx.lineTo(xToPixel(dists[i]), yToPixel(Math.max(0, deltas[i])));
    }
    ctx.lineTo(xToPixel(dists[dists.length - 1]), yToPixel(0));
    ctx.closePath();
    ctx.fillStyle = 'rgba(16, 185, 129, 0.2)';
    ctx.fill();

    // Red fill (negative = lap A slower)
    ctx.beginPath();
    ctx.moveTo(xToPixel(dists[0]), yToPixel(0));
    for (let i = 0; i < dists.length; i++) {
      ctx.lineTo(xToPixel(dists[i]), yToPixel(Math.min(0, deltas[i])));
    }
    ctx.lineTo(xToPixel(dists[dists.length - 1]), yToPixel(0));
    ctx.closePath();
    ctx.fillStyle = 'rgba(239, 68, 68, 0.2)';
    ctx.fill();

    // Delta line
    ctx.strokeStyle = '#F0EDE5';
    ctx.lineWidth = 2;
    ctx.beginPath();
    for (let i = 0; i < dists.length; i++) {
      const x = xToPixel(dists[i]);
      const y = yToPixel(deltas[i]);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();

    ctx.restore(); // unclip

    // ── Final delta annotation ───────────────────────────────
    const finalDelta = deltas[deltas.length - 1];
    if (Math.abs(finalDelta) > 0.001) {
      const sign = finalDelta > 0 ? '+' : '';
      const color = finalDelta > 0 ? '#10b981' : '#ef4444';
      ctx.fillStyle = color;
      ctx.font = 'bold 12px "Space Mono", monospace';
      ctx.textAlign = 'right';
      ctx.textBaseline = finalDelta > 0 ? 'bottom' : 'top';
      const fx = xToPixel(dists[dists.length - 1]) - 4;
      const fy = yToPixel(finalDelta) + (finalDelta > 0 ? -4 : 4);
      ctx.fillText(sign + finalDelta.toFixed(3) + 's', fx, fy);
    }

    // ── Hover crosshair ─────────────────────────────────────
    if (hoverDist !== null && hoverDist >= xMin && hoverDist <= xMax) {
      const hx = xToPixel(hoverDist);

      // Vertical crosshair
      ctx.strokeStyle = 'rgba(255,255,255,0.3)';
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(hx, pad.top);
      ctx.lineTo(hx, pad.top + pH);
      ctx.stroke();
      ctx.setLineDash([]);

      // Find delta at this distance
      const idx = closestIdx(dists, hoverDist);
      if (idx >= 0 && idx < deltas.length) {
        const d = deltas[idx];
        const py = yToPixel(d);

        // Dot
        ctx.beginPath();
        ctx.arc(hx, py, 5, 0, Math.PI * 2);
        ctx.fillStyle = d >= 0 ? '#10b981' : '#ef4444';
        ctx.fill();
        ctx.strokeStyle = '#F0EDE5';
        ctx.lineWidth = 1.5;
        ctx.stroke();

        // Tooltip
        const sign = d >= 0 ? '+' : '';
        const label = sign + d.toFixed(3) + 's @ ' + hoverDist.toFixed(0) + 'm';
        ctx.fillStyle = 'rgba(0,0,0,0.85)';
        ctx.font = '11px "Space Mono", monospace';
        const metrics = ctx.measureText(label);
        const tipW = metrics.width + 12;
        const tipH = 20;
        let tipX = hx + 10;
        if (tipX + tipW > w - 10) tipX = hx - tipW - 10;
        ctx.fillRect(tipX, py - tipH / 2, tipW, tipH);
        ctx.fillStyle = '#F0EDE5';
        ctx.textAlign = 'left';
        ctx.textBaseline = 'middle';
        ctx.fillText(label, tipX + 6, py);
      }
    }

    // ── Legend ───────────────────────────────────────────────
    ctx.fillStyle = '#888888';
    ctx.font = '10px "Space Mono", monospace';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'top';
    const legend = `Lap ${lapA} vs Lap ${lapB}`;
    ctx.fillText(legend, w - pad.right, pad.top + 2);

    // Green/red legend items
    ctx.textAlign = 'right';
    ctx.fillStyle = '#10b981';
    ctx.fillText(`▲ Lap ${lapA} faster`, w - pad.right, pad.top + 16);
    ctx.fillStyle = '#ef4444';
    ctx.fillText(`▼ Lap ${lapA} slower`, w - pad.right, pad.top + 30);
  }, [lapA, lapB]);

  // ── Redraw when data changes ──────────────────────────────
  useEffect(() => {
    if (!loading) draw();
  }, [loading, draw]);

  // ── Resize observer ───────────────────────────────────────
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const ro = new ResizeObserver(() => draw());
    ro.observe(container);
    return () => ro.disconnect();
  }, [draw]);

  // ── Hover sync: subscribe to external hover events ────────
  useEffect(() => {
    const unsubscribe = useChartHoverStore.subscribe((state) => {
      if (state.hoverSource === 'delta-chart') return;
      draw(state.hoverDistance);
    });
    return unsubscribe;
  }, [draw]);

  // ── Hover sync: publish hover events from this chart ──────
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const setHover = useChartHoverStore.getState().setHover;
    const clearHover = useChartHoverStore.getState().clearHover;

    const handleMove = (e: MouseEvent) => {
      const bounds = boundsRef.current;
      if (!bounds) return;

      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;

      if (mx < bounds.plotX || mx > bounds.plotX + bounds.plotW) {
        clearHover();
        draw(null);
        return;
      }

      const dist = bounds.xMin + ((mx - bounds.plotX) / bounds.plotW) * (bounds.xMax - bounds.xMin);
      setHover(dist, 'delta-chart');
      draw(dist);
    };

    const handleLeave = () => {
      clearHover();
      draw(null);
    };

    canvas.addEventListener('mousemove', handleMove);
    canvas.addEventListener('mouseleave', handleLeave);
    return () => {
      canvas.removeEventListener('mousemove', handleMove);
      canvas.removeEventListener('mouseleave', handleLeave);
    };
  }, [draw]);

  // ── Render ────────────────────────────────────────────────
  if (safeLaps.length < 2) {
    return (
      <div className={`text-steel text-sm text-center p-4 ${className}`}>
        At least 2 laps with GPS data are needed for delta comparison.
      </div>
    );
  }

  return (
    <div ref={containerRef} className={className} role="img" aria-label="Delta time chart showing time difference between laps">
      {/* Lap selectors */}
      <div className="flex items-center gap-3 mb-3 flex-wrap text-sm">
        <label className="flex items-center gap-1.5 text-steel font-body">
          Primary:
          <select
            value={lapA}
            onChange={(e) => setLapA(Number(e.target.value))}
            className="bg-asphalt text-chalk text-sm rounded px-2 py-1 border border-steel/20 font-telemetry"
          >
            {safeLaps.map((l) => (
              <option key={l} value={l}>
                Lap {l}{l === bestLap ? ' (Best)' : ''}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1.5 text-steel font-body">
          Reference:
          <select
            value={lapB}
            onChange={(e) => setLapB(Number(e.target.value))}
            className="bg-asphalt text-chalk text-sm rounded px-2 py-1 border border-steel/20 font-telemetry"
          >
            {safeLaps.map((l) => (
              <option key={l} value={l}>
                Lap {l}{l === bestLap ? ' (Best)' : ''}
              </option>
            ))}
          </select>
        </label>
        {loading && <span className="text-xs text-steel animate-pulse">Loading...</span>}
        {error && <span className="text-xs text-red-400">{error}</span>}
      </div>

      {/* Chart canvas */}
      <div className="relative" style={{ width: '100%' }}>
        <canvas ref={canvasRef} style={{ width: '100%', height: '220px', display: 'block' }} />
      </div>
    </div>
  );
}

/** Binary search for closest index in a sorted array. */
function closestIdx(arr: number[], target: number): number {
  if (!arr || arr.length === 0) return -1;
  let lo = 0;
  let hi = arr.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (arr[mid] < target) lo = mid + 1;
    else hi = mid;
  }
  if (lo > 0 && Math.abs(arr[lo - 1] - target) < Math.abs(arr[lo] - target)) return lo - 1;
  return lo;
}
