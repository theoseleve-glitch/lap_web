/**
 * TheoreticalDeltaChart.tsx — Cumulative time delta (actual vs theoretical optimal).
 *
 * Like iRacing's delta bar but as a full-width canvas chart:
 *   - X axis = distance (m), Y axis = time delta (seconds) centered on 0
 *   - Red fill above zero = driver losing time vs theoretical
 *   - Green fill below zero = driver gaining time vs theoretical
 *   - Chalk-colored solid line for the delta curve
 *   - Dashed steel zero line
 *
 * Integrates with useChartHoverStore for cross-chart hover sync.
 */
'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { apiFetch, ApiError } from '@/lib/api-client';
import { useChartHoverStore } from '@/lib/chart-hover-store';

interface TheoreticalDeltaData {
  distance_m: number[];
  time_delta_s: number[];
  speed_delta_mps: number[];
  throttle_delta_pct: number[];
  brake_delta_pct: number[];
  steering_delta_deg: number[];
  total_time_loss_s: number;
}

interface TheoreticalDeltaChartProps {
  sessionId: string;
  bestLap: number | null;
  className?: string;
}

export function TheoreticalDeltaChart({
  sessionId,
  bestLap,
  className = '',
}: TheoreticalDeltaChartProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const dataRef = useRef<TheoreticalDeltaData | null>(null);
  const boundsRef = useRef<{
    xMin: number; xMax: number; yMin: number; yMax: number;
    plotX: number; plotY: number; plotW: number; plotH: number;
  } | null>(null);

  const [notAvailable, setNotAvailable] = useState(false);
  const fetchVersionRef = useRef(0);

  // ── Fetch theoretical delta data ─────────────────────────────
  useEffect(() => {
    if (!bestLap) {
      dataRef.current = null;
      setNotAvailable(true);
      return;
    }
    const ver = ++fetchVersionRef.current;
    setNotAvailable(false);
    dataRef.current = null;
    (async () => {
      try {
        const data = await apiFetch<TheoreticalDeltaData>(
          `/sessions/${encodeURIComponent(sessionId)}/theoretical/delta?lap=${bestLap}`,
        );
        if (ver !== fetchVersionRef.current) return;
        if (!data.distance_m || data.distance_m.length < 2) {
          setNotAvailable(true);
        } else {
          dataRef.current = data;
        }
      } catch (err) {
        if (ver !== fetchVersionRef.current) return;
        if (err instanceof ApiError && err.status === 404) {
          setNotAvailable(true);
        } else {
          setNotAvailable(true);
        }
      }
    })();
  }, [sessionId, bestLap]);

  // ── Draw chart ───────────────────────────────────────────────
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

    const pad = { top: 20, right: 100, bottom: 38, left: 58 };
    const pW = w - pad.left - pad.right;
    const pH = h - pad.top - pad.bottom;

    // Background
    ctx.fillStyle = '#141414';
    ctx.fillRect(0, 0, w, h);

    if (!data || !data.distance_m || data.distance_m.length < 2) {
      ctx.fillStyle = '#949494';
      ctx.font = '13px "Space Mono", monospace';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText('Theoretical analysis not available', w / 2, h / 2);
      boundsRef.current = null;
      return;
    }

    const dists = data.distance_m;
    const deltas = data.time_delta_s;

    // Compute ranges
    const xMin = 0;
    const xMax = dists[dists.length - 1] || 1;
    let maxAbs = 0;
    for (let i = 0; i < deltas.length; i++) {
      const a = Math.abs(deltas[i]);
      if (a > maxAbs) maxAbs = a;
    }
    if (maxAbs < 0.05) maxAbs = 0.1;
    maxAbs = Math.ceil(maxAbs * 20) / 20;

    const yMin = -maxAbs;
    const yMax = maxAbs;

    boundsRef.current = { xMin, xMax, yMin, yMax, plotX: pad.left, plotY: pad.top, plotW: pW, plotH: pH };

    const xToPixel = (v: number) => pad.left + ((v - xMin) / (xMax - xMin)) * pW;
    const yToPixel = (v: number) => pad.top + pH / 2 - (v / maxAbs) * (pH / 2);

    // Grid
    ctx.strokeStyle = '#30363d';
    ctx.lineWidth = 0.5;

    // Y grid
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

    // Zero line (dashed steel)
    ctx.strokeStyle = '#949494';
    ctx.lineWidth = 1;
    ctx.setLineDash([6, 4]);
    ctx.beginPath();
    ctx.moveTo(pad.left, yToPixel(0));
    ctx.lineTo(pad.left + pW, yToPixel(0));
    ctx.stroke();
    ctx.setLineDash([]);

    // Y axis labels
    ctx.fillStyle = '#949494';
    ctx.font = '11px "Space Mono", monospace';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    const yDecimals = yStep < 0.1 ? 3 : yStep < 1 ? 2 : 1;
    for (let v = -maxAbs; v <= maxAbs + 0.001; v += yStep) {
      const rv = Math.round(v * 1000) / 1000;
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
    ctx.fillText('vs Theoretical (s)', 0, 0);
    ctx.restore();

    // ── Clip to plot area ────────────────────────────────────
    ctx.save();
    ctx.beginPath();
    ctx.rect(pad.left, pad.top, pW, pH);
    ctx.clip();

    // Red fill (positive = losing time)
    ctx.beginPath();
    ctx.moveTo(xToPixel(dists[0]), yToPixel(0));
    for (let i = 0; i < dists.length; i++) {
      ctx.lineTo(xToPixel(dists[i]), yToPixel(Math.max(0, deltas[i])));
    }
    ctx.lineTo(xToPixel(dists[dists.length - 1]), yToPixel(0));
    ctx.closePath();
    ctx.fillStyle = 'rgba(255, 42, 42, 0.2)';
    ctx.fill();

    // Green fill (negative = gaining time)
    ctx.beginPath();
    ctx.moveTo(xToPixel(dists[0]), yToPixel(0));
    for (let i = 0; i < dists.length; i++) {
      ctx.lineTo(xToPixel(dists[i]), yToPixel(Math.min(0, deltas[i])));
    }
    ctx.lineTo(xToPixel(dists[dists.length - 1]), yToPixel(0));
    ctx.closePath();
    ctx.fillStyle = 'rgba(34, 197, 94, 0.2)';
    ctx.fill();

    // Delta line (chalk)
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

    // ── Total time loss annotation (right margin) ─────────────
    const totalLoss = data.total_time_loss_s;
    const rightCol = pad.left + pW + 10;
    if (typeof totalLoss === 'number') {
      const sign = totalLoss > 0 ? '+' : '';
      const color = totalLoss > 0 ? '#FF2A2A' : '#22C55E';
      ctx.fillStyle = color;
      ctx.font = 'bold 12px "Space Mono", monospace';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'middle';
      ctx.fillText(`${sign}${totalLoss.toFixed(3)}s`, rightCol, pad.top + 14);
      ctx.fillStyle = '#949494';
      ctx.font = '9px "Space Mono", monospace';
      ctx.fillText('total loss', rightCol, pad.top + 28);
    }

    // Legend
    ctx.font = '10px "Space Mono", monospace';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    const legendY = pad.top + pH - 28;
    ctx.fillStyle = '#FF2A2A';
    ctx.fillText('▲ Losing time', rightCol, legendY);
    ctx.fillStyle = '#22C55E';
    ctx.fillText('▼ Gaining time', rightCol, legendY + 14);

    // ── Hover crosshair ─────────────────────────────────────
    if (hoverDist !== null && hoverDist >= xMin && hoverDist <= xMax) {
      const hx = xToPixel(hoverDist);

      ctx.strokeStyle = 'rgba(255,255,255,0.3)';
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(hx, pad.top);
      ctx.lineTo(hx, pad.top + pH);
      ctx.stroke();
      ctx.setLineDash([]);

      const idx = closestIdx(dists, hoverDist);
      if (idx >= 0 && idx < deltas.length) {
        const d = deltas[idx];
        const py = yToPixel(d);

        // Dot
        ctx.beginPath();
        ctx.arc(hx, py, 5, 0, Math.PI * 2);
        ctx.fillStyle = d >= 0 ? '#FF2A2A' : '#22C55E';
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
  }, []);

  // ── Redraw when data changes ──────────────────────────────
  useEffect(() => {
    if (!notAvailable) draw();
  }, [notAvailable, draw, bestLap, sessionId]);

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
      if (state.hoverSource === 'theoretical-delta') return;
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
      setHover(dist, 'theoretical-delta');
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
  if (notAvailable) {
    return (
      <div className={`text-steel text-sm text-center p-4 ${className}`}>
        Theoretical analysis not available
      </div>
    );
  }

  return (
    <div ref={containerRef} className={`relative ${className}`} role="img" aria-label="Theoretical delta chart showing cumulative time difference versus optimal lap">
      <canvas
        ref={canvasRef}
        className="w-full"
        style={{ height: '220px', display: 'block' }}
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
