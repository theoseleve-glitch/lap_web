/**
 * PedalTraceChart.tsx — Throttle, brake, and steering pedal trace chart.
 *
 * Renders:
 *   - Green filled area for throttle (0-100%, left Y axis)
 *   - Red filled area for brake (0-100%, left Y axis, stacked)
 *   - Blue line for steering angle (right Y axis, centered on 0)
 *   - Yellow tint in trail-braking zones (brake > 5% AND |steering| > 10deg)
 *   - X axis = distance (m)
 *
 * Integrates with useChartHoverStore for cross-chart hover sync.
 */
'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { apiFetch } from '@/lib/api-client';
import { useChartHoverStore } from '@/lib/chart-hover-store';
import { chartColor } from '@/components/shared/chart-kit';

interface PedalData {
  distances: number[];
  throttle: number[];
  brake: number[];
  steering: number[];
  available: boolean;
}

interface TheoreticalInputs {
  distances: number[];
  throttle: number[];
  brake: number[];
  steering: number[];
}

interface PedalTraceChartProps {
  sessionId: string;
  gpsLaps: number[];
  bestLap: number | null;
  className?: string;
  controlledLap?: boolean;
  showTheoretical?: boolean;
}

export function PedalTraceChart({
  sessionId,
  gpsLaps,
  bestLap,
  className = '',
  controlledLap = false,
  showTheoretical = false,
}: PedalTraceChartProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const dataRef = useRef<PedalData | null>(null);
  const boundsRef = useRef<{
    xMin: number; xMax: number;
    plotX: number; plotY: number; plotW: number; plotH: number;
  } | null>(null);

  const [selectedLap, setSelectedLap] = useState<number>(bestLap ?? gpsLaps[0] ?? 0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fetchVersionRef = useRef(0);
  const [theoreticalInputs, setTheoreticalInputs] = useState<TheoreticalInputs | null>(null);
  const theoVersionRef = useRef(0);

  useEffect(() => {
    if (controlledLap && bestLap != null) setSelectedLap(bestLap);
  }, [controlledLap, bestLap]);

  // -- Fetch pedal data -------------------------------------------------
  useEffect(() => {
    if (!selectedLap) { dataRef.current = null; return; }
    const ver = ++fetchVersionRef.current;
    setLoading(true); setError(null); dataRef.current = null;
    (async () => {
      try {
        const data = await apiFetch<PedalData>(
          `/sessions/${encodeURIComponent(sessionId)}/pedals?lap=${selectedLap}`,
        );
        if (ver !== fetchVersionRef.current) return;
        if (!data.available) {
          setError('No pedal data available for this lap');
        } else {
          dataRef.current = data;
        }
      } catch (err) {
        if (ver !== fetchVersionRef.current) return;
        setError(err instanceof Error ? err.message : 'Failed to load pedal data');
      }
      setLoading(false);
    })();
  }, [sessionId, selectedLap]);

  // -- Fetch theoretical inputs ------------------------------------------
  useEffect(() => {
    if (!showTheoretical || !sessionId) {
      setTheoreticalInputs(null);
      return;
    }
    const ver = ++theoVersionRef.current;
    (async () => {
      try {
        const res = await apiFetch<{
          speed_profile?: {
            distance_m: number[];
            throttle_pct: number[];
            brake_pct: number[];
            steering_deg: number[];
          };
        }>(`/sessions/${encodeURIComponent(sessionId)}/theoretical`);
        if (ver !== theoVersionRef.current) return;
        if (res?.speed_profile) {
          setTheoreticalInputs({
            distances: res.speed_profile.distance_m,
            throttle: res.speed_profile.throttle_pct,
            brake: res.speed_profile.brake_pct,
            steering: res.speed_profile.steering_deg,
          });
        }
      } catch {
        // Silently skip — theoretical data is optional (404 is expected)
        if (ver === theoVersionRef.current) setTheoreticalInputs(null);
      }
    })();
  }, [showTheoretical, sessionId]);

  // -- Draw chart -------------------------------------------------------
  const draw = useCallback((hoverDist: number | null = null) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const data = dataRef.current;

    const dpr = window.devicePixelRatio || 1;
    const w = canvas.parentElement?.clientWidth || canvas.clientWidth || 700;
    const h = 260;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = w + 'px';
    canvas.style.height = h + 'px';

    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const pad = { top: 20, right: 56, bottom: 38, left: 58 };
    const pW = w - pad.left - pad.right;
    const pH = h - pad.top - pad.bottom;

    // Background
    ctx.fillStyle = chartColor.surface;
    ctx.fillRect(0, 0, w, h);

    if (!data || !data.distances || data.distances.length < 2) {
      ctx.fillStyle = chartColor.textSecondary;
      ctx.font = '13px "Inter", "Segoe UI", sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText('No pedal data available', w / 2, h / 2);
      boundsRef.current = null;
      return;
    }

    const dists = data.distances;
    const throttle = data.throttle;
    const brake = data.brake;
    const steering = data.steering;

    // Ranges
    const xMin = 0;
    const xMax = dists[dists.length - 1] || 1;

    // Steering range (symmetric)
    let maxSteer = 0;
    for (let i = 0; i < steering.length; i++) {
      const a = Math.abs(steering[i]);
      if (a > maxSteer) maxSteer = a;
    }
    if (maxSteer < 10) maxSteer = 10;
    maxSteer = Math.ceil(maxSteer / 10) * 10;

    boundsRef.current = { xMin, xMax, plotX: pad.left, plotY: pad.top, plotW: pW, plotH: pH };

    const xToPixel = (v: number) => pad.left + ((v - xMin) / (xMax - xMin)) * pW;
    const yPedalToPixel = (v: number) => pad.top + pH - (v / 100) * pH;
    const ySteerToPixel = (v: number) => pad.top + pH / 2 - (v / maxSteer) * (pH / 2);

    // Grid
    ctx.strokeStyle = chartColor.grid;
    ctx.lineWidth = 0.5;

    // Y grid (pedal 0-100%)
    for (let v = 0; v <= 100; v += 25) {
      const y = yPedalToPixel(v);
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

    // Left Y axis labels (pedal %)
    ctx.fillStyle = chartColor.textSecondary;
    ctx.font = '10px "Inter", "Segoe UI", sans-serif';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    for (let v = 0; v <= 100; v += 25) {
      ctx.fillText(v + '%', pad.left - 6, yPedalToPixel(v));
    }

    // Right Y axis labels (steering deg)
    ctx.textAlign = 'left';
    const steerStep = maxSteer <= 30 ? 10 : maxSteer <= 90 ? 30 : 45;
    for (let v = -maxSteer; v <= maxSteer; v += steerStep) {
      const label = (v > 0 ? '+' : '') + v + '\u00b0';
      ctx.fillText(label, w - pad.right + 6, ySteerToPixel(v));
    }

    // X axis labels
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    for (let v = 0; v <= xMax; v += xStep) {
      ctx.fillText(v.toFixed(0) + 'm', xToPixel(v), pad.top + pH + 6);
    }

    // Axis titles
    ctx.font = '11px "Inter", "Segoe UI", sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('Distance (m)', pad.left + pW / 2, h - 4);
    ctx.save();
    ctx.translate(12, pad.top + pH / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText('Pedal %', 0, 0);
    ctx.restore();
    ctx.save();
    ctx.translate(w - 6, pad.top + pH / 2);
    ctx.rotate(Math.PI / 2);
    ctx.fillText('Steering (\u00b0)', 0, 0);
    ctx.restore();

    // -- Clip to plot area ------------------------------------------------
    ctx.save();
    ctx.beginPath();
    ctx.rect(pad.left, pad.top, pW, pH);
    ctx.clip();

    // Trail-braking zones: brake > 5% AND |steering| > 10deg
    for (let i = 0; i < dists.length - 1; i++) {
      if (brake[i] > 5 && Math.abs(steering[i]) > 10) {
        const x0 = xToPixel(dists[i]);
        const x1 = xToPixel(dists[i + 1]);
        ctx.fillStyle = 'rgba(255, 200, 50, 0.08)';
        ctx.fillRect(x0, pad.top, x1 - x0, pH);
      }
    }

    // Throttle filled area (green)
    ctx.beginPath();
    ctx.moveTo(xToPixel(dists[0]), yPedalToPixel(0));
    for (let i = 0; i < dists.length; i++) {
      ctx.lineTo(xToPixel(dists[i]), yPedalToPixel(throttle[i]));
    }
    ctx.lineTo(xToPixel(dists[dists.length - 1]), yPedalToPixel(0));
    ctx.closePath();
    ctx.fillStyle = 'rgba(34, 197, 94, 0.25)';
    ctx.fill();

    // Throttle outline
    ctx.strokeStyle = chartColor.series.positive;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    for (let i = 0; i < dists.length; i++) {
      const x = xToPixel(dists[i]);
      const y = yPedalToPixel(throttle[i]);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();

    // Brake filled area (red)
    ctx.beginPath();
    ctx.moveTo(xToPixel(dists[0]), yPedalToPixel(0));
    for (let i = 0; i < dists.length; i++) {
      ctx.lineTo(xToPixel(dists[i]), yPedalToPixel(brake[i]));
    }
    ctx.lineTo(xToPixel(dists[dists.length - 1]), yPedalToPixel(0));
    ctx.closePath();
    ctx.fillStyle = 'rgba(255, 42, 42, 0.25)';
    ctx.fill();

    // Brake outline
    ctx.strokeStyle = chartColor.series.negative;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    for (let i = 0; i < dists.length; i++) {
      const x = xToPixel(dists[i]);
      const y = yPedalToPixel(brake[i]);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();

    // Steering line (blue)
    ctx.strokeStyle = chartColor.palette[3];
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    for (let i = 0; i < dists.length; i++) {
      const x = xToPixel(dists[i]);
      const y = ySteerToPixel(steering[i]);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();

    // Steering zero reference (thin dashed)
    ctx.strokeStyle = `${chartColor.palette[3]}4D`;
    ctx.lineWidth = 0.5;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(pad.left, ySteerToPixel(0));
    ctx.lineTo(w - pad.right, ySteerToPixel(0));
    ctx.stroke();
    ctx.setLineDash([]);

    // -- Theoretical input overlays (dashed lines) -------------------------
    if (theoreticalInputs && theoreticalInputs.distances.length >= 2) {
      const theoDists = theoreticalInputs.distances;
      const theoMaxDist = theoDists[theoDists.length - 1] || 1;

      /**
       * Interpolate a value from the theoretical arrays at a given distance.
       * Uses linear interpolation between nearest bracketing points.
       */
      const interpTheo = (dist: number, arr: number[], dArr: number[]): number => {
        if (dist <= dArr[0]) return arr[0];
        if (dist >= dArr[dArr.length - 1]) return arr[arr.length - 1];
        // Binary search for left bracket
        let lo = 0, hi = dArr.length - 1;
        while (lo < hi - 1) {
          const mid = (lo + hi) >> 1;
          if (dArr[mid] <= dist) lo = mid; else hi = mid;
        }
        const t = (dist - dArr[lo]) / (dArr[hi] - dArr[lo] || 1);
        return arr[lo] + t * (arr[hi] - arr[lo]);
      };

      /**
       * Draw a dashed trace line mapping theoretical values onto the plot.
       * yMap converts a value to pixel Y coordinate.
       */
      const drawDashedTrace = (
        values: number[],
        dArr: number[],
        yMap: (v: number) => number,
      ) => {
        ctx.beginPath();
        // Sample at actual data distances for smooth alignment
        const sampleDists = dists.length > 0 ? dists : theoDists;
        const maxD = Math.min(xMax, theoMaxDist);
        for (let i = 0; i < sampleDists.length; i++) {
          const d = sampleDists[i];
          if (d > maxD) break;
          const val = interpTheo(d, values, dArr);
          const px = xToPixel(d);
          const py = yMap(val);
          if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
        }
        ctx.stroke();
      };

      ctx.save();
      ctx.setLineDash([4, 3]);
      ctx.lineWidth = 1.5;

      // Theoretical throttle — dashed acid-green
      ctx.strokeStyle = 'rgba(34, 197, 94, 0.7)';
      drawDashedTrace(theoreticalInputs.throttle, theoDists, yPedalToPixel);

      // Theoretical brake — dashed safety-red
      ctx.strokeStyle = 'rgba(255, 42, 42, 0.7)';
      drawDashedTrace(theoreticalInputs.brake, theoDists, yPedalToPixel);

      // Theoretical steering — dashed chalk
      ctx.strokeStyle = 'rgba(240, 237, 229, 0.5)';
      drawDashedTrace(theoreticalInputs.steering, theoDists, ySteerToPixel);

      ctx.restore();
    }

    ctx.restore(); // unclip

    // -- Hover crosshair --------------------------------------------------
    if (hoverDist !== null && hoverDist >= xMin && hoverDist <= xMax) {
      const hx = xToPixel(hoverDist);
      const idx = closestIdx(dists, hoverDist);

      // Vertical crosshair
      ctx.strokeStyle = chartColor.crosshair;
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(hx, pad.top);
      ctx.lineTo(hx, pad.top + pH);
      ctx.stroke();
      ctx.setLineDash([]);

      if (idx >= 0 && idx < dists.length) {
        const tVal = throttle[idx];
        const bVal = brake[idx];
        const sVal = steering[idx];

        // Dots
        const dots: Array<{ y: number; color: string }> = [
          { y: yPedalToPixel(tVal), color: chartColor.series.positive },
          { y: yPedalToPixel(bVal), color: chartColor.series.negative },
          { y: ySteerToPixel(sVal), color: chartColor.palette[3] },
        ];
        for (const dot of dots) {
          ctx.beginPath();
          ctx.arc(hx, dot.y, 4, 0, Math.PI * 2);
          ctx.fillStyle = dot.color;
          ctx.fill();
          ctx.strokeStyle = chartColor.text;
          ctx.lineWidth = 1;
          ctx.stroke();
        }

        // Tooltip
        const lines = [
          `Throttle: ${tVal.toFixed(1)}%`,
          `Brake: ${bVal.toFixed(1)}%`,
          `Steering: ${sVal.toFixed(1)}\u00b0`,
          `@ ${hoverDist.toFixed(0)}m`,
        ];
        ctx.font = '11px "Inter", "Segoe UI", sans-serif';
        let maxLineW = 0;
        for (const line of lines) {
          const lw = ctx.measureText(line).width;
          if (lw > maxLineW) maxLineW = lw;
        }
        const tipW = maxLineW + 16;
        const tipH = lines.length * 16 + 8;
        let tipX = hx + 12;
        if (tipX + tipW > w - 10) tipX = hx - tipW - 12;
        let tipY = pad.top + 10;

        ctx.fillStyle = chartColor.tooltipBg;
        ctx.beginPath();
        ctx.roundRect(tipX, tipY, tipW, tipH, 4);
        ctx.fill();

        ctx.fillStyle = chartColor.text;
        ctx.textAlign = 'left';
        ctx.textBaseline = 'top';
        for (let i = 0; i < lines.length; i++) {
          ctx.fillText(lines[i], tipX + 8, tipY + 4 + i * 16);
        }
      }
    }

    // -- Legend ------------------------------------------------------------
    ctx.font = '10px "Inter", "Segoe UI", sans-serif';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'top';
    ctx.fillStyle = chartColor.series.positive;
    ctx.fillText('\u25a0 Throttle', w - pad.right - 120, pad.top + 2);
    ctx.fillStyle = chartColor.series.negative;
    ctx.fillText('\u25a0 Brake', w - pad.right - 60, pad.top + 2);
    ctx.fillStyle = chartColor.palette[3];
    ctx.fillText('\u2014 Steering', w - pad.right, pad.top + 2);

    // Theoretical legend (second row, only when data loaded)
    if (theoreticalInputs && theoreticalInputs.distances.length >= 2) {
      const legendY = pad.top + 14;

      // Draw dashed line indicator + label for each
      const drawDashedLegend = (label: string, color: string, xEnd: number) => {
        const textW = ctx.measureText(label).width;
        const lineX = xEnd - textW - 18;
        ctx.strokeStyle = color;
        ctx.lineWidth = 1.5;
        ctx.setLineDash([4, 3]);
        ctx.beginPath();
        ctx.moveTo(lineX, legendY + 5);
        ctx.lineTo(lineX + 14, legendY + 5);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = color;
        ctx.fillText(label, xEnd, legendY);
      };

      drawDashedLegend('Theo. Thr', 'rgba(34, 197, 94, 0.7)', w - pad.right - 120);
      drawDashedLegend('Theo. Brk', 'rgba(255, 42, 42, 0.7)', w - pad.right - 50);
      drawDashedLegend('Theo. Str', 'rgba(240, 237, 229, 0.5)', w - pad.right + 14);
    }
  }, [selectedLap, theoreticalInputs]);

  // -- Redraw when data changes ------------------------------------------
  useEffect(() => {
    if (!loading) draw();
  }, [loading, draw]);

  // -- Resize observer ---------------------------------------------------
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const ro = new ResizeObserver(() => draw());
    ro.observe(container);
    return () => ro.disconnect();
  }, [draw]);

  // -- Hover sync: subscribe to external hover events --------------------
  useEffect(() => {
    const unsubscribe = useChartHoverStore.subscribe((state) => {
      if (state.hoverSource === 'pedal-chart') return;
      draw(state.hoverDistance);
    });
    return unsubscribe;
  }, [draw]);

  // -- Hover sync: publish hover events from this chart ------------------
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
      setHover(dist, 'pedal-chart');
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

  // -- Render -------------------------------------------------------------
  if (!gpsLaps.length) {
    return (
      <div className={`text-steel text-sm text-center p-4 ${className}`}>
        No laps with GPS data available.
      </div>
    );
  }

  return (
    <div ref={containerRef} className={className} role="img" aria-label="Pedal trace chart showing throttle and brake input over distance">
      {/* Lap selector */}
      <div className="flex items-center gap-3 mb-3 flex-wrap text-sm">
        {!controlledLap && (
          <label className="flex items-center gap-1.5 text-steel">
            Lap:
            <select
              value={selectedLap}
              onChange={(e) => setSelectedLap(Number(e.target.value))}
              className="bg-concrete text-chalk text-sm rounded px-2 py-1 border border-steel/20"
            >
              {gpsLaps.map((l) => (
                <option key={l} value={l}>
                  Lap {l}{l === bestLap ? ' (Best)' : ''}
                </option>
              ))}
            </select>
          </label>
        )}
        {loading && <span className="text-xs text-steel animate-pulse">Loading...</span>}
        {error && <span className="text-xs text-safety-red">{error}</span>}
      </div>

      {/* Chart canvas */}
      <div className="relative" style={{ width: '100%' }}>
        <canvas ref={canvasRef} style={{ width: '100%', height: '260px', display: 'block' }} />
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
