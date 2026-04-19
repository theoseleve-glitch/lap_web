/**
 * GGExplorer.tsx — Pure React canvas G-G diagram.
 *
 * Plots lateral vs longitudinal acceleration as a density-colored
 * scatter with friction circle, grid, quadrant labels, and hover sync.
 *
 * Dual-mode:
 *   - `sessionId` → fetches from API
 *   - `data` → renders directly from pre-fetched data
 */
'use client';

import { useEffect, useRef, useState, useCallback, useMemo } from 'react';
import { apiFetch } from '@/lib/api-client';
import { useChartHoverStore } from '@/lib/chart-hover-store';
import { chartColor } from '@/components/shared/chart-kit';
import { useReferenceOverlay } from '@/components/app/reference';

/* ── Types ──────────────────────────────────────────────── */

interface GGData {
  accel_lat: number[];
  accel_long: number[];
  distances?: number[];
}

interface GGExplorerProps {
  sessionId?: string;
  data?: GGData;
  apiBase?: string;
  className?: string;
  gpsLaps?: number[];
  bestLap?: number | null;
  controlledLap?: boolean;
}

/* ── Density color (blue → cyan → green → yellow → red) ── */

function densityColor(t: number): string {
  const c = Math.max(0, Math.min(1, t));
  let r: number, g: number, b: number;
  if (c < 0.25) {
    r = 0; g = Math.round(100 + 155 * (c / 0.25)); b = 255;
  } else if (c < 0.5) {
    r = 0; g = 255; b = Math.round(255 * (1 - (c - 0.25) / 0.25));
  } else if (c < 0.75) {
    r = Math.round(255 * ((c - 0.5) / 0.25)); g = 255; b = 0;
  } else {
    r = 255; g = Math.round(255 * (1 - (c - 0.75) / 0.25)); b = 0;
  }
  return `rgb(${r},${g},${b})`;
}

/* ── Drawing ──────────────────────────────────────────── */

const PAD = { top: 30, right: 20, bottom: 45, left: 55 };

interface CrossRefGG {
  accel_lat: number[];
  accel_long: number[];
  distances: number[];
}

function drawGG(
  canvas: HTMLCanvasElement,
  ggData: GGData,
  hoverIdx: number | null,
  crossRefGG?: CrossRefGG | null,
  crossRefHoverIdx?: number | null,
) {
  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const w = rect.width;
  const h = rect.height;
  if (w === 0 || h === 0) return;

  canvas.width = w * dpr;
  canvas.height = h * dpr;
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, w, h);

  // Background
  ctx.fillStyle = chartColor.surface;
  ctx.fillRect(0, 0, w, h);

  const { accel_lat: aLat, accel_long: aLong } = ggData;
  if (aLat.length < 2) return;

  const pW = w - PAD.left - PAD.right;
  const pH = h - PAD.top - PAD.bottom;

  // Compute axis range from data
  let maxG = 0;
  for (let i = 0; i < aLat.length; i++) {
    if (aLat[i] == null || aLong[i] == null) continue;
    if (!isFinite(aLat[i]) || !isFinite(aLong[i])) continue;
    const mag = Math.sqrt(aLat[i] * aLat[i] + aLong[i] * aLong[i]);
    if (mag > maxG) maxG = mag;
  }
  let axisMax = Math.ceil(maxG * 1.15 * 10) / 10;
  if (axisMax < 0.5) axisMax = 0.5;
  const frictionR = maxG * 0.95;

  // Coordinate transforms
  const xToPixel = (v: number) => PAD.left + ((v + axisMax) / (2 * axisMax)) * pW;
  const yToPixel = (v: number) => PAD.top + pH - ((v + axisMax) / (2 * axisMax)) * pH;

  // Clip to plot area
  ctx.save();
  ctx.beginPath();
  ctx.rect(PAD.left, PAD.top, pW, pH);
  ctx.clip();

  // Grid lines
  const step = axisMax <= 0.3 ? 0.05 : axisMax <= 0.6 ? 0.1 : axisMax <= 1.2 ? 0.25 : 0.5;
  ctx.strokeStyle = 'rgba(240, 237, 229, 0.06)';
  ctx.lineWidth = 0.5;

  for (let g = -axisMax * 2; g <= axisMax * 2; g += step) {
    const yy = yToPixel(g);
    if (yy >= PAD.top && yy <= PAD.top + pH) {
      ctx.beginPath(); ctx.moveTo(PAD.left, yy); ctx.lineTo(PAD.left + pW, yy); ctx.stroke();
    }
    const xx = xToPixel(g);
    if (xx >= PAD.left && xx <= PAD.left + pW) {
      ctx.beginPath(); ctx.moveTo(xx, PAD.top); ctx.lineTo(xx, PAD.top + pH); ctx.stroke();
    }
  }

  // Axes through origin
  ctx.strokeStyle = 'rgba(240, 237, 229, 0.15)';
  ctx.lineWidth = 1;
  const ox = xToPixel(0), oy = yToPixel(0);
  ctx.beginPath(); ctx.moveTo(ox, PAD.top); ctx.lineTo(ox, PAD.top + pH); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(PAD.left, oy); ctx.lineTo(PAD.left + pW, oy); ctx.stroke();

  // Friction circle
  const rPx = (frictionR / axisMax) * (pW / 2);
  if (rPx > 0) {
    ctx.strokeStyle = 'rgba(201, 168, 76, 0.5)';
    ctx.lineWidth = 1.5;
    ctx.setLineDash([6, 4]);
    ctx.beginPath(); ctx.arc(ox, oy, rPx, 0, 2 * Math.PI); ctx.stroke();
    ctx.setLineDash([]);
  }

  // Reference scatter (drawn BEFORE density so it appears behind primary dots)
  if (crossRefGG && crossRefGG.accel_lat.length > 0) {
    ctx.save();
    ctx.strokeStyle = chartColor.series.reference;
    ctx.lineWidth = 1 * dpr;
    ctx.globalAlpha = 0.4;
    const refLat = crossRefGG.accel_lat;
    const refLong = crossRefGG.accel_long;
    for (let i = 0; i < refLat.length; i++) {
      if (refLat[i] == null || refLong[i] == null) continue;
      if (!isFinite(refLat[i]) || !isFinite(refLong[i])) continue;
      const rpx = xToPixel(refLat[i]);
      const rpy = yToPixel(refLong[i]);
      if (rpx < PAD.left || rpx > PAD.left + pW) continue;
      if (rpy < PAD.top || rpy > PAD.top + pH) continue;
      ctx.beginPath();
      ctx.arc(rpx, rpy, 3 * dpr, 0, Math.PI * 2);
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
    ctx.restore();
  }

  // Density scatter
  const GRID_SIZE = 35;
  const grid: Record<string, number> = {};
  const pts: Array<{ px: number; py: number; key: string; idx: number }> = [];

  for (let i = 0; i < aLat.length; i++) {
    if (aLat[i] == null || aLong[i] == null) continue;
    if (!isFinite(aLat[i]) || !isFinite(aLong[i])) continue;
    const px = xToPixel(aLat[i]);
    const py = yToPixel(aLong[i]);
    if (px < PAD.left || px > PAD.left + pW) continue;
    if (py < PAD.top || py > PAD.top + pH) continue;
    const gx = Math.floor(px / GRID_SIZE);
    const gy = Math.floor(py / GRID_SIZE);
    const key = `${gx},${gy}`;
    grid[key] = (grid[key] || 0) + 1;
    pts.push({ px, py, key, idx: i });
  }

  let maxDensity = 0;
  for (const k in grid) { if (grid[k] > maxDensity) maxDensity = grid[k]; }

  const dotR = pts.length > 5000 ? 1.2 : pts.length > 1000 ? 1.8 : 2.5;
  for (const p of pts) {
    const density = grid[p.key] || 1;
    const t = Math.min(1, density / Math.max(1, maxDensity * 0.6));
    ctx.fillStyle = densityColor(t);
    ctx.globalAlpha = 0.7;
    ctx.beginPath(); ctx.arc(p.px, p.py, dotR, 0, 2 * Math.PI); ctx.fill();
  }
  ctx.globalAlpha = 1;

  // Friction circle label
  ctx.fillStyle = 'rgba(201, 168, 76, 0.7)';
  ctx.font = '600 9px "Space Mono", monospace';
  ctx.textAlign = 'left';
  ctx.fillText(`${frictionR.toFixed(2)}G`, ox + rPx + 6, oy - rPx + 12);

  // Quadrant labels
  ctx.fillStyle = 'rgba(240, 237, 229, 0.15)';
  ctx.font = '700 11px "Space Grotesk", "Space Mono", monospace';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  if (oy > PAD.top + 20) {
    ctx.fillText('ACCEL', ox, Math.max(PAD.top + 16, oy - pH * 0.35));
  }
  if (oy < PAD.top + pH - 20) {
    ctx.fillText('BRAKING', ox, Math.min(PAD.top + pH - 12, oy + pH * 0.35));
  }
  if (ox > PAD.left + 30) {
    ctx.fillText('LEFT', Math.max(PAD.left + 30, ox - pW * 0.35), oy);
  }
  if (ox < PAD.left + pW - 30) {
    ctx.fillText('RIGHT', Math.min(PAD.left + pW - 30, ox + pW * 0.35), oy);
  }

  // Hover highlight
  if (hoverIdx != null && hoverIdx >= 0 && hoverIdx < aLat.length) {
    if (isFinite(aLat[hoverIdx]) && isFinite(aLong[hoverIdx])) {
      const hx = xToPixel(aLat[hoverIdx]);
      const hy = yToPixel(aLong[hoverIdx]);
      // Outer glow
      ctx.fillStyle = 'rgba(201, 168, 76, 0.3)';
      ctx.beginPath(); ctx.arc(hx, hy, 8, 0, 2 * Math.PI); ctx.fill();
      // Inner dot
      ctx.fillStyle = chartColor.series.primary;
      ctx.beginPath(); ctx.arc(hx, hy, 4, 0, 2 * Math.PI); ctx.fill();
    }
  }

  // Reference hover marker
  if (
    crossRefGG &&
    crossRefHoverIdx != null &&
    crossRefHoverIdx >= 0 &&
    crossRefHoverIdx < crossRefGG.accel_lat.length
  ) {
    const rLat = crossRefGG.accel_lat[crossRefHoverIdx];
    const rLong = crossRefGG.accel_long[crossRefHoverIdx];
    if (isFinite(rLat) && isFinite(rLong)) {
      const rhx = xToPixel(rLat);
      const rhy = yToPixel(rLong);
      ctx.save();
      ctx.strokeStyle = chartColor.series.reference;
      ctx.lineWidth = 2 * dpr;
      ctx.globalAlpha = 1;
      ctx.beginPath();
      ctx.arc(rhx, rhy, 6 * dpr, 0, Math.PI * 2);
      ctx.stroke();
      ctx.restore();
    }
  }

  ctx.restore(); // end clip

  // Axis tick labels
  ctx.fillStyle = 'rgba(240, 237, 229, 0.5)';
  ctx.font = '10px "Space Mono", monospace';

  for (let g = -axisMax * 2; g <= axisMax * 2; g += step) {
    if (Math.abs(g) < 0.001) continue;
    const xp = xToPixel(g);
    if (xp >= PAD.left && xp <= PAD.left + pW) {
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      ctx.fillText(`${g.toFixed(2)}`, xp, PAD.top + pH + 6);
    }
    const yp = yToPixel(g);
    if (yp >= PAD.top && yp <= PAD.top + pH) {
      ctx.textAlign = 'right';
      ctx.textBaseline = 'middle';
      ctx.fillText(`${g.toFixed(2)}`, PAD.left - 6, yp);
    }
  }

  // Axis titles
  ctx.fillStyle = 'rgba(240, 237, 229, 0.6)';
  ctx.font = '600 10px "Space Grotesk", "Space Mono", monospace';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  ctx.fillText('LATERAL G', PAD.left + pW / 2, h - 14);
  ctx.save();
  ctx.translate(12, PAD.top + pH / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.textBaseline = 'middle';
  ctx.fillText('LONGITUDINAL G', 0, 0);
  ctx.restore();

  // Store pixel lookup for hit-testing
  (canvas as unknown as Record<string, unknown>)._ggPts = pts;
  (canvas as unknown as Record<string, unknown>)._xToPixel = xToPixel;
  (canvas as unknown as Record<string, unknown>)._yToPixel = yToPixel;
}

/* ── Component ────────────────────────────────────────── */

export function GGExplorer({
  sessionId,
  data: preFetchedData,
  className = '',
  gpsLaps = [],
  bestLap = null,
  controlledLap = false,
}: GGExplorerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [ggData, setGgData] = useState<GGData | null>(preFetchedData ?? null);
  const [selectedLap, setSelectedLap] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  // Reference overlay
  const { referenceData } = useReferenceOverlay();
  const crossRefGG = useMemo<CrossRefGG | null>(() => {
    if (!referenceData?.gg?.reference?.accel_lat?.length) return null;
    return {
      accel_lat: referenceData.gg.reference.accel_lat,
      accel_long: referenceData.gg.reference.accel_long,
      distances: referenceData.distances,
    };
  }, [referenceData]);

  // Sync when parent controls the lap (Focus Mode)
  useEffect(() => {
    if (controlledLap && bestLap != null) setSelectedLap(bestLap);
  }, [controlledLap, bestLap]);

  const activeLap = selectedLap ?? bestLap ?? gpsLaps[0] ?? null;

  // ── Fetch GG data ──────────────────────────────────────
  useEffect(() => {
    if (preFetchedData) {
      setGgData(preFetchedData);
      return;
    }
    if (!sessionId) return;

    let cancelled = false;
    setLoading(true);
    setError(null);

    const lapParam = activeLap != null ? `?lap=${activeLap}` : '';

    (async () => {
      try {
        const result = await apiFetch<GGData & { available?: boolean; message?: string }>(
          `/sessions/${sessionId}/gg-data${lapParam}`,
        );
        if (cancelled) return;

        if (result.available === false) {
          setGgData(null);
          setError(result.message || 'No G-G data available');
        } else {
          setGgData(result);
        }
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : 'Failed to load G-G data');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => { cancelled = true; };
  }, [sessionId, preFetchedData, activeLap]);

  // Derive reference hover index from hovered distance via primary distances
  const crossRefHoverIdx = useMemo<number | null>(() => {
    if (!crossRefGG || hoverIdx == null || !ggData?.distances) return null;
    const primaryDist = ggData.distances[hoverIdx];
    if (primaryDist == null) return null;
    const refDists = crossRefGG.distances;
    if (!refDists || refDists.length === 0) return null;
    let lo = 0, hi = refDists.length - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (refDists[mid] < primaryDist) lo = mid + 1;
      else hi = mid;
    }
    return lo;
  }, [crossRefGG, hoverIdx, ggData]);

  // ── Draw on canvas ──────────────────────────────────────
  useEffect(() => {
    if (!ggData || !canvasRef.current) return;
    drawGG(canvasRef.current, ggData, hoverIdx, crossRefGG, crossRefHoverIdx);
  }, [ggData, hoverIdx, crossRefGG, crossRefHoverIdx]);

  // Stable draw ref for ResizeObserver — avoids re-attaching on every hover
  const drawRef = useRef<() => void>(() => {});
  drawRef.current = () => {
    if (ggData && canvasRef.current) drawGG(canvasRef.current, ggData, hoverIdx, crossRefGG, crossRefHoverIdx);
  };

  // Redraw on resize — attached once per data change, not per hover
  useEffect(() => {
    if (!ggData || !canvasRef.current) return;
    const canvas = canvasRef.current;
    const ro = new ResizeObserver(() => drawRef.current());
    ro.observe(canvas);
    return () => ro.disconnect();
  }, [ggData, crossRefGG]);

  // ── Hover handling ──────────────────────────────────────
  const handleCanvasMove = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      if (!ggData || !canvasRef.current) return;
      const canvas = canvasRef.current;
      const pts = (canvas as unknown as Record<string, unknown>)._ggPts as
        Array<{ px: number; py: number; idx: number }> | undefined;
      if (!pts || pts.length === 0) return;

      const rect = canvas.getBoundingClientRect();
      const cx = e.clientX - rect.left;
      const cy = e.clientY - rect.top;

      // Find closest point
      let best = 0;
      let bestDist = Infinity;
      for (let i = 0; i < pts.length; i++) {
        const dx = pts[i].px - cx;
        const dy = pts[i].py - cy;
        const d = dx * dx + dy * dy;
        if (d < bestDist) { bestDist = d; best = i; }
      }

      if (bestDist < 400) { // within ~20px
        const idx = pts[best].idx;
        setHoverIdx(idx);

        if (ggData.distances && ggData.distances[idx] != null) {
          useChartHoverStore.getState().setHover(ggData.distances[idx], 'gg-explorer');
        }
      } else {
        setHoverIdx(null);
      }
    },
    [ggData],
  );

  const handleCanvasLeave = useCallback(() => {
    setHoverIdx(null);
    useChartHoverStore.getState().clearHover();
  }, []);

  // ── External hover sync ─────────────────────────────────
  useEffect(() => {
    if (!ggData || !ggData.distances) return;

    const unsub = useChartHoverStore.subscribe((state) => {
      if (state.hoverSource === 'gg-explorer') return;

      if (state.hoverDistance !== null) {
        const dists = ggData.distances!;
        if (dists.length === 0) return;
        let lo = 0, hi = dists.length - 1;
        while (lo < hi) {
          const mid = (lo + hi) >> 1;
          if (dists[mid] < state.hoverDistance) lo = mid + 1;
          else hi = mid;
        }
        setHoverIdx(lo);
      } else {
        setHoverIdx(null);
      }
    });

    return unsub;
  }, [ggData]);

  // ── Hover tooltip data ──────────────────────────────────
  const hoverInfo = hoverIdx != null && ggData ? {
    lat: ggData.accel_lat[hoverIdx],
    long: ggData.accel_long[hoverIdx],
    dist: ggData.distances?.[hoverIdx],
  } : null;

  // ── Render ──────────────────────────────────────────────
  return (
    <div className={`flex flex-col ${className}`}>
      <div
        className="relative flex-1 min-h-0 rounded-lg border border-steel/10"
        style={{ width: '100%', background: 'var(--asphalt)', ...(!className.includes('h-full') ? { minHeight: '320px' } : {}) }}
      >
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center z-10">
            <div className="w-5 h-5 border-2 border-steel/30 border-t-chalk rounded-full animate-spin" />
          </div>
        )}

        {error && !ggData && (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="text-center">
              <p className="font-telemetry text-chalk text-sm mb-1">No G-G Data</p>
              <p className="text-steel/60 text-xs max-w-[280px]">
                G-G diagrams require lateral and longitudinal acceleration columns
                in your CSV (e.g., &quot;Acceleration X/Y&quot; or &quot;Lateral/Longitudinal G&quot;).
              </p>
            </div>
          </div>
        )}

        <canvas
          ref={canvasRef}
          role="img"
          aria-label="G-G diagram plotting lateral versus longitudinal acceleration"
          className="w-full h-full cursor-crosshair"
          onMouseMove={handleCanvasMove}
          onMouseLeave={handleCanvasLeave}
        />

        {/* Hover tooltip */}
        {hoverInfo && isFinite(hoverInfo.lat) && isFinite(hoverInfo.long) && (
          <div className="absolute top-2 right-2 bg-concrete/90 border border-steel/20 rounded px-2.5 py-1.5 pointer-events-none">
            <span className="font-telemetry text-[11px] text-chalk tabular-nums">
              Lat: {hoverInfo.lat.toFixed(2)}G
            </span>
            <span className="font-telemetry text-[11px] text-chalk tabular-nums ml-2">
              Long: {hoverInfo.long.toFixed(2)}G
            </span>
            {hoverInfo.dist != null && (
              <span className="font-telemetry text-[10px] text-steel ml-2 tabular-nums">
                {hoverInfo.dist.toFixed(0)}m
              </span>
            )}
          </div>
        )}
      </div>

      {/* Lap selector + stats */}
      <div className="flex items-center gap-3 mt-2 flex-wrap shrink-0">
        {!controlledLap && gpsLaps.length > 0 && (
          <>
            <label className="font-telemetry text-[10px] text-steel uppercase tracking-wider">Lap</label>
            <select
              value={activeLap ?? ''}
              onChange={(e) => setSelectedLap(Number(e.target.value))}
              className="bg-concrete text-chalk text-sm font-telemetry rounded px-2 py-1 border border-steel/20 focus:border-pit-orange focus:outline-none"
            >
              {gpsLaps.map((l) => (
                <option key={l} value={l}>
                  {l}{l === bestLap ? ' (Best)' : ''}
                </option>
              ))}
            </select>
          </>
        )}
        {ggData && ggData.accel_lat.length > 0 && (
          <span className="font-telemetry text-[10px] text-steel/50 tabular-nums">
            {ggData.accel_lat.length} points
          </span>
        )}
      </div>
    </div>
  );
}
