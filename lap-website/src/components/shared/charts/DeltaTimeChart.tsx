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
import { useReferenceOverlay } from '@/components/app/reference';

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
  controlledLap?: boolean;
  distRange?: [number, number] | null;
}

export function DeltaTimeChart({
  sessionId,
  gpsLaps,
  bestLap,
  className = '',
  controlledLap = false,
  distRange,
}: DeltaTimeChartProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const dataRef = useRef<DeltaData | null>(null);
  const boundsRef = useRef<{
    xMin: number; xMax: number; yMin: number; yMax: number;
    plotX: number; plotY: number; plotW: number; plotH: number;
  } | null>(null);

  const { referenceData } = useReferenceOverlay();

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
  const fetchVersionRef = useRef(0);

  useEffect(() => {
    if (controlledLap && bestLap != null) setLapA(bestLap);
  }, [controlledLap, bestLap]);

  // ── Fetch delta data ──────────────────────────────────────────
  useEffect(() => {
    if (!lapA || !lapB || lapA === lapB) {
      dataRef.current = null;
      return;
    }
    const ver = ++fetchVersionRef.current;
    setLoading(true);
    setError(null);
    dataRef.current = null;
    (async () => {
      try {
        const data = await apiFetch<DeltaData | { available: false }>(
          `/sessions/${encodeURIComponent(sessionId)}/delta?lap_a=${lapA}&lap_b=${lapB}`,
        );
        if (ver !== fetchVersionRef.current) return;
        if ('available' in data && !data.available) {
          setError('No delta data available for these laps');
        } else {
          dataRef.current = data as DeltaData;
        }
      } catch (err) {
        if (ver !== fetchVersionRef.current) return;
        setError(err instanceof Error ? err.message : 'Failed to load delta');
      }
      setLoading(false);
    })();
  }, [sessionId, lapA, lapB]);

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

    const pad = { top: 20, right: 120, bottom: 38, left: 58 };
    const pW = w - pad.left - pad.right;
    const pH = h - pad.top - pad.bottom;

    // Background — matches SpeedTraceChart (#141414)
    ctx.fillStyle = '#141414';
    ctx.fillRect(0, 0, w, h);

    if (!data || !data.distances || data.distances.length < 2) {
      ctx.fillStyle = '#949494';
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

    // Cross-session reference delta (if active)
    const refDists = referenceData?.distances ?? null;
    const refDeltas = referenceData?.speed?.delta_s ?? null;
    const hasRef = !!(refDists && refDeltas && refDists.length > 1);

    // Compute ranges (including reference if present)
    const xMin = distRange ? distRange[0] : 0;
    const xMax = distRange ? distRange[1] : (dists[dists.length - 1] || 1);
    let maxAbs = 0;
    for (let i = 0; i < deltas.length; i++) {
      const a = Math.abs(deltas[i]);
      if (a > maxAbs) maxAbs = a;
    }
    if (hasRef) {
      for (let i = 0; i < refDeltas!.length; i++) {
        const a = Math.abs(refDeltas![i]);
        if (a > maxAbs) maxAbs = a;
      }
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
      const rv = Math.round(v * 1000) / 1000;
      const y = yToPixel(rv);
      ctx.beginPath();
      ctx.moveTo(pad.left, y);
      ctx.lineTo(pad.left + pW, y);
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

    // Y axis labels — use consistent decimal places per step size
    ctx.fillStyle = '#949494';
    ctx.font = '11px "Space Mono", monospace';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    const yDecimals = yStep < 0.1 ? 3 : yStep < 1 ? 2 : 1;
    for (let v = -maxAbs; v <= maxAbs + 0.001; v += yStep) {
      const rv = Math.round(v * 1000) / 1000; // snap to avoid floating-point drift
      const label = rv === 0 ? '0' : (rv > 0 ? '+' : '') + rv.toFixed(yDecimals);
      ctx.fillText(label + 's', pad.left - 6, yToPixel(rv));
    }

    // X axis labels
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    for (let v = 0; v <= xMax; v += xStep) {
      ctx.fillText(v.toFixed(0) + 'm', xToPixel(v), pad.top + pH + 6);
    }

    // Axis titles
    ctx.fillStyle = '#949494';
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

    // Delta line (intra-session)
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

    // Cross-session reference delta line (dashed racing-purple)
    if (hasRef) {
      ctx.save();
      ctx.strokeStyle = '#8B5CF6';
      ctx.lineWidth = 2;
      ctx.setLineDash([6, 4]);
      ctx.globalAlpha = 0.85;
      ctx.beginPath();
      for (let i = 0; i < refDists!.length; i++) {
        const x = xToPixel(refDists![i]);
        const y = yToPixel(refDeltas![i]);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
      ctx.restore();
    }

    ctx.restore(); // unclip

    // ── Final delta annotation (in right margin) ───────────
    const finalDelta = deltas.length > 0 ? deltas[deltas.length - 1] : 0;
    const rightCol = pad.left + pW + 10; // right margin start
    if (Math.abs(finalDelta) > 0.001) {
      const sign = finalDelta > 0 ? '+' : '';
      const color = finalDelta > 0 ? '#10b981' : '#ef4444';
      ctx.fillStyle = color;
      ctx.font = 'bold 12px "Space Mono", monospace';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'middle';
      const labelY = Math.max(pad.top + 8, Math.min(pad.top + pH - 8, yToPixel(finalDelta)));
      ctx.fillText(`${sign}${finalDelta.toFixed(3)}s`, rightCol, labelY);
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

    // ── Final reference delta annotation (purple, below intra-session) ──
    if (hasRef && refDeltas!.length > 0) {
      const finalRefDelta = refDeltas![refDeltas!.length - 1];
      if (Math.abs(finalRefDelta) > 0.001) {
        const sign = finalRefDelta > 0 ? '+' : '';
        ctx.fillStyle = '#8B5CF6';
        ctx.font = 'bold 12px "Space Mono", monospace';
        ctx.textAlign = 'left';
        ctx.textBaseline = 'middle';
        const labelY = Math.max(pad.top + 22, Math.min(pad.top + pH - 8, yToPixel(finalRefDelta)));
        ctx.fillText(`${sign}${finalRefDelta.toFixed(3)}s`, rightCol, labelY);
      }
    }

    // ── Legend (right margin, below final delta) ────────────
    ctx.font = '10px "Space Mono", monospace';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';

    // Green/red legend items at bottom of right margin
    const legendY = hasRef ? pad.top + pH - 42 : pad.top + pH - 28;
    ctx.fillStyle = '#10b981';
    ctx.fillText(`▲ Lap ${lapA} faster`, rightCol, legendY);
    ctx.fillStyle = '#ef4444';
    ctx.fillText(`▼ Lap ${lapA} slower`, rightCol, legendY + 14);
    if (hasRef) {
      ctx.fillStyle = '#8B5CF6';
      ctx.fillText(`- - vs reference`, rightCol, legendY + 28);
    }
  }, [lapA, lapB, distRange, referenceData]);

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
    <div ref={containerRef} className={`relative ${className}`} role="img" aria-label="Delta time chart showing time difference between laps">
      {/* Lap selectors — absolute overlay in controlled mode to avoid eating vertical space */}
      <div className={controlledLap
        ? 'absolute top-1 right-2 z-10 flex items-center gap-2 text-xs'
        : 'flex items-center gap-3 mb-3 flex-wrap text-sm'
      }>
        {!controlledLap && (
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
        )}
        <label className="flex items-center gap-1.5 text-steel font-body">
          <span className={controlledLap ? 'text-[9px] text-steel/50 uppercase' : ''}>Ref:</span>
          <select
            value={lapB}
            onChange={(e) => setLapB(Number(e.target.value))}
            className={controlledLap
              ? 'bg-concrete text-chalk text-[10px] rounded px-1.5 py-0.5 border border-steel/20 font-telemetry'
              : 'bg-asphalt text-chalk text-sm rounded px-2 py-1 border border-steel/20 font-telemetry'
            }
          >
            {safeLaps.map((l) => (
              <option key={l} value={l}>
                Lap {l}{l === bestLap ? ' (Best)' : ''}
              </option>
            ))}
          </select>
        </label>
        {loading && <span className="text-xs text-steel animate-pulse">...</span>}
      </div>

      {/* Chart canvas — fills available space in focus mode */}
      <canvas
        ref={canvasRef}
        className="w-full"
        style={{ height: controlledLap ? '100%' : '220px', display: 'block' }}
      />
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
