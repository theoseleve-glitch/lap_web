/**
 * RPMGearChart.tsx — RPM trace colored by gear, with speed overlay.
 *
 * Renders:
 *   - RPM line colored by gear (each gear a distinct color)
 *   - Vertical tick marks at shift points (gear changes)
 *   - Left Y axis: RPM (0 to max)
 *   - Right Y axis: speed (thin gray line)
 *   - X axis = distance (m)
 *
 * Integrates with useChartHoverStore for cross-chart hover sync.
 */
'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { apiFetch } from '@/lib/api-client';
import { useChartHoverStore } from '@/lib/chart-hover-store';

interface RPMGearData {
  distances: number[];
  rpm: number[];
  gear: number[];
  speeds: number[];
  available: boolean;
}

interface RPMGearChartProps {
  sessionId: string;
  gpsLaps: number[];
  bestLap: number | null;
  className?: string;
}

const GEAR_COLORS: Record<number, string> = {
  0: '#9ca3af', // neutral — gray
  1: '#4488ff',
  2: '#44ddff',
  3: '#44ff88',
  4: '#ffff44',
  5: '#ff8844',
  6: '#ff4444',
  7: '#ff44ff',
};

function gearColor(g: number): string {
  return GEAR_COLORS[g] ?? '#9ca3af';
}

export function RPMGearChart({
  sessionId,
  gpsLaps,
  bestLap,
  className = '',
}: RPMGearChartProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const dataRef = useRef<RPMGearData | null>(null);
  const boundsRef = useRef<{
    xMin: number; xMax: number;
    plotX: number; plotY: number; plotW: number; plotH: number;
  } | null>(null);

  const [selectedLap, setSelectedLap] = useState<number>(bestLap ?? gpsLaps[0] ?? 0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // -- Fetch RPM/gear data -----------------------------------------------
  const fetchData = useCallback(async () => {
    if (!selectedLap) {
      dataRef.current = null;
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch<RPMGearData>(
        `/sessions/${encodeURIComponent(sessionId)}/rpm-gear?lap=${selectedLap}`,
      );
      if (!data.available) {
        dataRef.current = null;
        setError('No RPM/gear data available for this lap');
      } else {
        dataRef.current = data;
      }
    } catch (err) {
      dataRef.current = null;
      setError(err instanceof Error ? err.message : 'Failed to load RPM/gear data');
    } finally {
      setLoading(false);
    }
  }, [sessionId, selectedLap]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // -- Draw chart --------------------------------------------------------
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
    ctx.fillStyle = '#1a1f2e';
    ctx.fillRect(0, 0, w, h);

    if (!data || !data.distances || data.distances.length < 2) {
      ctx.fillStyle = '#8b949e';
      ctx.font = '13px -apple-system, sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText('No RPM/gear data available', w / 2, h / 2);
      boundsRef.current = null;
      return;
    }

    const dists = data.distances;
    const rpm = data.rpm;
    const gear = data.gear;
    const speeds = data.speeds;

    // Ranges
    const xMin = 0;
    const xMax = dists[dists.length - 1] || 1;

    let rpmMax = 0;
    for (let i = 0; i < rpm.length; i++) {
      if (rpm[i] > rpmMax) rpmMax = rpm[i];
    }
    if (rpmMax < 1000) rpmMax = 1000;
    rpmMax = Math.ceil(rpmMax / 1000) * 1000;

    let spdMax = 0;
    for (let i = 0; i < speeds.length; i++) {
      if (speeds[i] > spdMax) spdMax = speeds[i];
    }
    if (spdMax < 20) spdMax = 20;
    spdMax = Math.ceil(spdMax / 10) * 10;

    boundsRef.current = { xMin, xMax, plotX: pad.left, plotY: pad.top, plotW: pW, plotH: pH };

    const xToPixel = (v: number) => pad.left + ((v - xMin) / (xMax - xMin)) * pW;
    const rpmToPixel = (v: number) => pad.top + pH - (v / rpmMax) * pH;
    const spdToPixel = (v: number) => pad.top + pH - (v / spdMax) * pH;

    // Grid
    ctx.strokeStyle = 'rgba(255,255,255,0.08)';
    ctx.lineWidth = 0.5;

    // Y grid (RPM)
    const rpmStep = rpmMax <= 4000 ? 1000 : rpmMax <= 8000 ? 2000 : 3000;
    for (let v = 0; v <= rpmMax; v += rpmStep) {
      const y = rpmToPixel(v);
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

    // Left Y axis labels (RPM)
    ctx.fillStyle = '#8b949e';
    ctx.font = '10px -apple-system, sans-serif';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    for (let v = 0; v <= rpmMax; v += rpmStep) {
      ctx.fillText((v / 1000).toFixed(0) + 'k', pad.left - 6, rpmToPixel(v));
    }

    // Right Y axis labels (speed)
    ctx.textAlign = 'left';
    const spdStep = spdMax <= 60 ? 20 : spdMax <= 120 ? 30 : spdMax <= 200 ? 50 : 100;
    for (let v = 0; v <= spdMax; v += spdStep) {
      ctx.fillText(v.toFixed(0) + ' km/h', w - pad.right + 6, spdToPixel(v));
    }

    // X axis labels
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    for (let v = 0; v <= xMax; v += xStep) {
      ctx.fillText(v.toFixed(0) + 'm', xToPixel(v), pad.top + pH + 6);
    }

    // Axis titles
    ctx.font = '11px -apple-system, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('Distance (m)', pad.left + pW / 2, h - 4);
    ctx.save();
    ctx.translate(12, pad.top + pH / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText('RPM', 0, 0);
    ctx.restore();
    ctx.save();
    ctx.translate(w - 6, pad.top + pH / 2);
    ctx.rotate(Math.PI / 2);
    ctx.fillText('Speed (km/h)', 0, 0);
    ctx.restore();

    // -- Clip to plot area ------------------------------------------------
    ctx.save();
    ctx.beginPath();
    ctx.rect(pad.left, pad.top, pW, pH);
    ctx.clip();

    // Speed line (thin gray, drawn first so RPM sits on top)
    ctx.strokeStyle = 'rgba(156, 163, 175, 0.5)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let i = 0; i < dists.length; i++) {
      const x = xToPixel(dists[i]);
      const y = spdToPixel(speeds[i]);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();

    // RPM trace colored by gear (segment-by-segment)
    ctx.lineWidth = 2;
    let segStart = 0;
    for (let i = 1; i <= dists.length; i++) {
      // Draw segment when gear changes or at end
      if (i === dists.length || gear[i] !== gear[segStart]) {
        ctx.strokeStyle = gearColor(gear[segStart]);
        ctx.beginPath();
        ctx.moveTo(xToPixel(dists[segStart]), rpmToPixel(rpm[segStart]));
        for (let j = segStart + 1; j <= Math.min(i, dists.length - 1); j++) {
          ctx.lineTo(xToPixel(dists[j]), rpmToPixel(rpm[j]));
        }
        ctx.stroke();
        segStart = i;
      }
    }

    // Vertical tick marks at shift points
    ctx.strokeStyle = 'rgba(255,255,255,0.2)';
    ctx.lineWidth = 1;
    ctx.setLineDash([2, 2]);
    for (let i = 1; i < gear.length; i++) {
      if (gear[i] !== gear[i - 1]) {
        const x = xToPixel(dists[i]);
        ctx.beginPath();
        ctx.moveTo(x, pad.top);
        ctx.lineTo(x, pad.top + pH);
        ctx.stroke();
      }
    }
    ctx.setLineDash([]);

    ctx.restore(); // unclip

    // -- Hover crosshair --------------------------------------------------
    if (hoverDist !== null && hoverDist >= xMin && hoverDist <= xMax) {
      const hx = xToPixel(hoverDist);
      const idx = closestIdx(dists, hoverDist);

      // Vertical crosshair
      ctx.strokeStyle = 'rgba(255,255,255,0.3)';
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(hx, pad.top);
      ctx.lineTo(hx, pad.top + pH);
      ctx.stroke();
      ctx.setLineDash([]);

      if (idx >= 0 && idx < dists.length) {
        const rVal = rpm[idx];
        const gVal = gear[idx];
        const sVal = speeds[idx];

        // RPM dot
        ctx.beginPath();
        ctx.arc(hx, rpmToPixel(rVal), 4, 0, Math.PI * 2);
        ctx.fillStyle = gearColor(gVal);
        ctx.fill();
        ctx.strokeStyle = '#e6edf3';
        ctx.lineWidth = 1;
        ctx.stroke();

        // Speed dot
        ctx.beginPath();
        ctx.arc(hx, spdToPixel(sVal), 3, 0, Math.PI * 2);
        ctx.fillStyle = '#9ca3af';
        ctx.fill();
        ctx.strokeStyle = '#e6edf3';
        ctx.lineWidth = 1;
        ctx.stroke();

        // Tooltip
        const lines = [
          `RPM: ${rVal.toFixed(0)}`,
          `Gear: ${gVal === 0 ? 'N' : gVal}`,
          `Speed: ${sVal.toFixed(1)} km/h`,
          `@ ${hoverDist.toFixed(0)}m`,
        ];
        ctx.font = '11px -apple-system, sans-serif';
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

        ctx.fillStyle = 'rgba(0,0,0,0.85)';
        ctx.beginPath();
        ctx.roundRect(tipX, tipY, tipW, tipH, 4);
        ctx.fill();

        ctx.fillStyle = '#e6edf3';
        ctx.textAlign = 'left';
        ctx.textBaseline = 'top';
        for (let i = 0; i < lines.length; i++) {
          // Color the gear line with the gear color
          if (i === 1) ctx.fillStyle = gearColor(gVal);
          else ctx.fillStyle = '#e6edf3';
          ctx.fillText(lines[i], tipX + 8, tipY + 4 + i * 16);
        }
      }
    }

    // -- Legend (gear colors) ---------------------------------------------
    ctx.font = '10px -apple-system, sans-serif';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    const gearsUsed = new Set(gear);
    const sortedGears = Array.from(gearsUsed).sort((a, b) => a - b);
    let legendX = pad.left + 4;
    for (const g of sortedGears) {
      const label = g === 0 ? 'N' : String(g);
      ctx.fillStyle = gearColor(g);
      ctx.fillRect(legendX, pad.top + 2, 8, 8);
      ctx.fillText(label, legendX + 11, pad.top + 1);
      legendX += ctx.measureText(label).width + 20;
    }

    // Speed legend on the right
    ctx.textAlign = 'right';
    ctx.fillStyle = 'rgba(156, 163, 175, 0.7)';
    ctx.fillText('\u2014 Speed', w - pad.right, pad.top + 2);
  }, [selectedLap]);

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
      if (state.hoverSource === 'rpm-gear-chart') return;
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
      setHover(dist, 'rpm-gear-chart');
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
    <div ref={containerRef} className={className} role="img" aria-label="RPM and gear chart showing engine speed and gear selection">
      {/* Lap selector */}
      <div className="flex items-center gap-3 mb-3 flex-wrap text-sm">
        <label className="flex items-center gap-1.5 text-gray-400">
          Lap:
          <select
            value={selectedLap}
            onChange={(e) => setSelectedLap(Number(e.target.value))}
            className="bg-gray-800 text-white text-sm rounded px-2 py-1 border border-gray-700"
          >
            {gpsLaps.map((l) => (
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
