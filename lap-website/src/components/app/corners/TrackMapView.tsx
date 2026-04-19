'use client';

import { useEffect, useRef, useState, useCallback, useMemo } from 'react';
import type { CornerData, GpsTrace, TheoreticalData } from './useCornerData';
import { useChartHoverStore } from '@/lib/chart-hover-store';

/* ── Props ──────────────────────────────────────────── */

interface TrackMapViewProps {
  corners: CornerData[];
  gpsTrace: GpsTrace | null;
  theoretical: TheoreticalData | null;
  onSelectCorner: (id: number) => void;
}

/* ── Derived corner position (interpolated from GPS trace) ─ */

interface DerivedCornerPos {
  corner_id: number;
  lat: number;
  lon: number;
  direction?: 'L' | 'R';
  time_loss_total_s?: number | null;
}

/* ── Interpolate corner GPS positions from trace distances ─ */

function interpolateCornerPositions(
  corners: CornerData[],
  gps: GpsTrace,
): DerivedCornerPos[] {
  const { distances, latitudes, longitudes } = gps;
  if (!distances?.length || !latitudes?.length || !longitudes?.length) return [];

  const n = distances.length;
  const result: DerivedCornerPos[] = [];

  // Compute per-lap distance range for normalizing session-cumulative s_apex values
  const dMin = distances[0];
  const dMax = distances[n - 1];
  const lapLen = dMax - dMin;

  for (const c of corners) {
    let apex = c.s_apex ?? (c.s_start != null && c.s_end != null ? (c.s_start + c.s_end) / 2 : null);
    if (apex == null) continue;

    // Normalize session-cumulative distance to per-lap range
    // s_apex values may be multi-lap cumulative (e.g., 5608m for a 1200m lap)
    if (lapLen > 0 && apex > dMax) {
      apex = dMin + ((apex - dMin) % lapLen);
    }

    // Binary search for the closest distance index
    let lo = 0;
    let hi = n - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (distances[mid] < apex) lo = mid + 1;
      else hi = mid;
    }

    // Linear interpolation between adjacent points for precision
    let lat: number;
    let lon: number;
    if (lo === 0 || lo >= n) {
      const idx = Math.min(lo, n - 1);
      lat = latitudes[idx];
      lon = longitudes[idx];
    } else {
      const d0 = distances[lo - 1];
      const d1 = distances[lo];
      const range = d1 - d0;
      if (range < 0.001) {
        lat = latitudes[lo];
        lon = longitudes[lo];
      } else {
        const t = (apex - d0) / range;
        lat = latitudes[lo - 1] + t * (latitudes[lo] - latitudes[lo - 1]);
        lon = longitudes[lo - 1] + t * (longitudes[lo] - longitudes[lo - 1]);
      }
    }

    result.push({
      corner_id: c.corner_id,
      lat,
      lon,
      direction: c.direction,
      time_loss_total_s: c.time_loss_total_s,
    });
  }

  return result;
}

/* ── Time-loss color coding ─────────────────────────── */

function timeLossColor(tl: number | null | undefined): string {
  if (tl == null) return '#949494';
  if (tl < 0.05) return '#C6F135';
  if (tl < 0.15) return '#F5C518';
  if (tl < 0.3) return '#FF6B2B';
  return '#FF2A2A';
}

/* ── Equirectangular projection ─────────────────────── */

interface Projected {
  xs: number[];
  ys: number[];
  project: (lat: number, lon: number) => [number, number];
}

function buildProjection(
  lats: number[],
  lons: number[],
  w: number,
  h: number,
  padFraction: number,
): Projected {
  let minLat = Infinity, maxLat = -Infinity;
  let minLon = Infinity, maxLon = -Infinity;
  for (let i = 0; i < lats.length; i++) {
    if (lats[i] < minLat) minLat = lats[i];
    if (lats[i] > maxLat) maxLat = lats[i];
    if (lons[i] < minLon) minLon = lons[i];
    if (lons[i] > maxLon) maxLon = lons[i];
  }

  const latSpan = maxLat - minLat || 0.0001;
  const lonSpan = maxLon - minLon || 0.0001;
  const padX = lonSpan * padFraction;
  const padY = latSpan * padFraction;
  const bMinLon = minLon - padX;
  const bMaxLat = maxLat + padY;
  const bLonSpan = (maxLon + padX) - bMinLon;
  const bLatSpan = bMaxLat - (minLat - padY);

  const midLat = (minLat + maxLat) / 2;
  const cosLat = Math.cos((midLat * Math.PI) / 180);
  const correctedLonSpan = bLonSpan * cosLat;

  const scale = Math.min(w / correctedLonSpan, h / bLatSpan);
  const usedW = correctedLonSpan * scale;
  const usedH = bLatSpan * scale;
  const offX = (w - usedW) / 2;
  const offY = (h - usedH) / 2;

  const project = (lat: number, lon: number): [number, number] => {
    const px = offX + (lon - bMinLon) * cosLat * scale;
    const py = offY + (bMaxLat - lat) * scale;
    return [px, py];
  };

  const xs = new Array<number>(lats.length);
  const ys = new Array<number>(lats.length);
  for (let i = 0; i < lats.length; i++) {
    [xs[i], ys[i]] = project(lats[i], lons[i]);
  }

  return { xs, ys, project };
}

/* ── Tooltip state ──────────────────────────────────── */

interface TooltipInfo {
  x: number;
  y: number;
  cornerId: number;
  direction: string;
  timeLoss: number | null | undefined;
}

/* ── Drawing ────────────────────────────────────────── */

/* ── Speed-to-color helper ─────────────────────────── */

function speedToColor(speed: number, minSpd: number, maxSpd: number): string {
  const t = maxSpd > minSpd ? (speed - minSpd) / (maxSpd - minSpd) : 0.5;
  // Red (slow) → Yellow (mid) → Green (fast)
  const r = Math.round(255 * Math.max(0, Math.min(1, 1 - t)));
  const g = Math.round(255 * Math.max(0, Math.min(1, t)));
  const b = 30;
  return `rgb(${r},${g},${b})`;
}

function draw(
  canvas: HTMLCanvasElement,
  gps: GpsTrace,
  cornerPositions: DerivedCornerPos[],
  theoretical: TheoreticalData | null,
): Projected | null {
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;

  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const w = rect.width;
  const h = rect.height;
  if (w === 0 || h === 0) return null;

  canvas.width = w * dpr;
  canvas.height = h * dpr;
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, w, h);

  const lats = gps.latitudes;
  const lons = gps.longitudes;
  if (lats.length < 2) return null;

  const proj = buildProjection(lats, lons, w, h, 0.10);

  // ── Layer 1: Dim track outline (background reference) ──
  ctx.beginPath();
  ctx.moveTo(proj.xs[0], proj.ys[0]);
  for (let i = 1; i < lats.length; i++) {
    ctx.lineTo(proj.xs[i], proj.ys[i]);
  }
  ctx.strokeStyle = 'rgba(240, 237, 229, 0.12)';
  ctx.lineWidth = 4;
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  ctx.stroke();

  // ── Layer 2: Best lap speed-colored line (thin) ──
  if (gps.speeds?.length === lats.length) {
    const speeds = gps.speeds;
    let minSpd = Infinity, maxSpd = -Infinity;
    for (const s of speeds) {
      if (s < minSpd) minSpd = s;
      if (s > maxSpd) maxSpd = s;
    }

    ctx.lineWidth = 1.5;
    ctx.lineCap = 'round';
    for (let i = 1; i < lats.length; i++) {
      ctx.beginPath();
      ctx.moveTo(proj.xs[i - 1], proj.ys[i - 1]);
      ctx.lineTo(proj.xs[i], proj.ys[i]);
      ctx.strokeStyle = speedToColor(speeds[i], minSpd, maxSpd);
      ctx.stroke();
    }
  }

  // ── Layer 3: Corner dots + labels ──
  const DOT_R = 10;
  ctx.font = '600 10px monospace';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';

  for (const pos of cornerPositions) {
    const [cx, cy] = proj.project(pos.lat, pos.lon);
    const color = timeLossColor(pos.time_loss_total_s);

    ctx.beginPath();
    ctx.arc(cx, cy, DOT_R, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();

    ctx.fillStyle = '#FFFFFF';
    ctx.fillText(`${pos.corner_id}`, cx, cy + 1);
  }

  return proj;
}

/* ── Component ──────────────────────────────────────── */

const SYNC_ID = 'corners-track-map';

export function TrackMapView({ corners, gpsTrace, theoretical, onSelectCorner }: TrackMapViewProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const markerCanvasRef = useRef<HTMLCanvasElement>(null);
  const projRef = useRef<Projected | null>(null);
  const [tooltip, setTooltip] = useState<TooltipInfo | null>(null);
  const { hoverDistance, hoverSource, setHover, clearHover } = useChartHoverStore();

  // Derive corner GPS positions from the GPS trace distances
  const cornerPositions = useMemo(() => {
    if (!gpsTrace) return [];
    return interpolateCornerPositions(corners, gpsTrace);
  }, [corners, gpsTrace]);

  const hasData = gpsTrace != null && gpsTrace.latitudes.length > 1;

  // Render — draw track even if no corner positions (dots may be in fallback list)
  const renderRef = useRef<() => void>(() => {});
  renderRef.current = () => {
    if (!canvasRef.current || !gpsTrace) return;
    projRef.current = draw(canvasRef.current, gpsTrace, cornerPositions, theoretical);
  };

  useEffect(() => {
    renderRef.current();
  }, [gpsTrace, cornerPositions]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ro = new ResizeObserver(() => renderRef.current());
    ro.observe(canvas);
    return () => ro.disconnect();
  }, []);

  // Hit-test helper
  const findNearest = useCallback(
    (cx: number, cy: number, radius: number): DerivedCornerPos | null => {
      const proj = projRef.current;
      if (!proj) return null;
      let bestDist = radius * radius;
      let best: DerivedCornerPos | null = null;
      for (const pos of cornerPositions) {
        const [px, py] = proj.project(pos.lat, pos.lon);
        const d = (px - cx) ** 2 + (py - cy) ** 2;
        if (d < bestDist) {
          bestDist = d;
          best = pos;
        }
      }
      return best;
    },
    [cornerPositions],
  );

  const handleClick = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const rect = canvas.getBoundingClientRect();
      const hit = findNearest(e.clientX - rect.left, e.clientY - rect.top, 20);
      if (hit) onSelectCorner(hit.corner_id);
    },
    [findNearest, onSelectCorner],
  );

  // Find nearest GPS trace point to pixel position → return distance
  const findNearestTraceDistance = useCallback(
    (cx: number, cy: number): number | null => {
      const proj = projRef.current;
      if (!proj || !gpsTrace) return null;
      let bestD2 = 400; // 20px radius squared
      let bestIdx = -1;
      for (let i = 0; i < proj.xs.length; i++) {
        const d2 = (proj.xs[i] - cx) ** 2 + (proj.ys[i] - cy) ** 2;
        if (d2 < bestD2) { bestD2 = d2; bestIdx = i; }
      }
      return bestIdx >= 0 ? gpsTrace.distances[bestIdx] : null;
    },
    [gpsTrace],
  );

  const handleMouseMove = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const rect = canvas.getBoundingClientRect();
      const cx = e.clientX - rect.left;
      const cy = e.clientY - rect.top;

      // Corner tooltip
      const hit = findNearest(cx, cy, 20);
      if (hit) {
        setTooltip({ x: cx, y: cy, cornerId: hit.corner_id, direction: hit.direction ?? '', timeLoss: hit.time_loss_total_s });
      } else {
        setTooltip(null);
      }

      // Publish distance for cross-chart sync
      const dist = findNearestTraceDistance(cx, cy);
      if (dist !== null) setHover(dist, SYNC_ID);
    },
    [findNearest, findNearestTraceDistance, setHover],
  );

  const handleMouseLeave = useCallback(() => {
    setTooltip(null);
    clearHover();
  }, [clearHover]);

  // Draw sync marker from other charts
  useEffect(() => {
    const mc = markerCanvasRef.current;
    const proj = projRef.current;
    if (!mc || !proj || !gpsTrace) return;
    const ctx = mc.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const rect = mc.getBoundingClientRect();
    mc.width = rect.width * dpr;
    mc.height = rect.height * dpr;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, rect.width, rect.height);

    if (hoverDistance == null || hoverSource === SYNC_ID) return;

    // Find GPS index closest to hoverDistance
    const dists = gpsTrace.distances;
    let lo = 0, hi = dists.length - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (dists[mid] < hoverDistance) lo = mid + 1;
      else hi = mid;
    }
    if (lo >= proj.xs.length) return;

    // Interpolate position
    let px: number, py: number;
    if (lo > 0 && lo < dists.length) {
      const d0 = dists[lo - 1], d1 = dists[lo];
      const t = d1 > d0 ? (hoverDistance - d0) / (d1 - d0) : 0;
      px = proj.xs[lo - 1] + t * (proj.xs[lo] - proj.xs[lo - 1]);
      py = proj.ys[lo - 1] + t * (proj.ys[lo] - proj.ys[lo - 1]);
    } else {
      px = proj.xs[lo];
      py = proj.ys[lo];
    }

    // Draw marker
    ctx.beginPath();
    ctx.arc(px, py, 6, 0, Math.PI * 2);
    ctx.fillStyle = '#C6F135';
    ctx.fill();
    ctx.strokeStyle = '#FFFFFF';
    ctx.lineWidth = 1.5;
    ctx.stroke();
  }, [hoverDistance, hoverSource, gpsTrace]);

  if (!hasData) {
    return (
      <div className="relative w-full flex items-center justify-center" style={{ minHeight: 300 }}>
        <span className="font-telemetry text-steel text-sm">GPS data not available</span>
      </div>
    );
  }

  const fmtLoss = (v: number | null | undefined): string => {
    if (v == null) return 'n/a';
    return `${v.toFixed(3)}s`;
  };

  return (
    <div className="relative w-full" style={{ minHeight: 300 }}>
      <p className="text-steel text-xs font-body text-center mb-2">Click a corner to view coaching details</p>
      <div className="relative" style={{ height: 340 }}>
        <canvas
          ref={canvasRef}
          className="w-full cursor-pointer absolute inset-0"
          style={{ display: 'block', height: 340 }}
          onClick={handleClick}
          onMouseMove={handleMouseMove}
          onMouseLeave={handleMouseLeave}
          role="img"
          aria-label="Track map with corner markers"
        />
        <canvas
          ref={markerCanvasRef}
          className="w-full absolute inset-0 pointer-events-none"
          style={{ display: 'block', height: 340 }}
        />
      </div>
      {tooltip && (
        <div
          className="pointer-events-none absolute z-10 rounded px-2 py-1 bg-asphalt border border-steel/20 text-chalk text-xs font-telemetry"
          style={{ left: tooltip.x + 12, top: tooltip.y - 28, whiteSpace: 'nowrap' }}
        >
          <span className="font-semibold">C{tooltip.cornerId}</span>{' '}
          <span className="text-steel">{tooltip.direction === 'L' ? 'Left' : tooltip.direction === 'R' ? 'Right' : ''}</span>{' '}
          <span style={{ color: timeLossColor(tooltip.timeLoss) }}>{fmtLoss(tooltip.timeLoss)}</span>
        </div>
      )}

      {/* Fallback: corners exist but can't be positioned on the map */}
      {cornerPositions.length === 0 && corners.length > 0 && (
        <div className="mt-4">
          <p className="text-steel text-xs font-body text-center mb-3">
            Corner positions unavailable on map — select below
          </p>
          <div className="flex flex-wrap gap-2 justify-center">
            {[...corners].sort((a, b) => a.corner_id - b.corner_id).map((c) => (
              <button
                key={c.corner_id}
                onClick={() => onSelectCorner(c.corner_id)}
                className="group flex items-center gap-1.5 px-3 py-2 bg-concrete rounded border border-steel/20 hover:border-acid-green/50 transition-colors"
              >
                <span
                  className="w-2.5 h-2.5 rounded-full shrink-0"
                  style={{ backgroundColor: timeLossColor(c.time_loss_total_s) }}
                />
                <span className="text-chalk text-sm font-telemetry">C{c.corner_id}</span>
                {c.direction && (
                  <span className="text-steel text-xs font-telemetry">{c.direction}</span>
                )}
                {c.time_loss_total_s != null && (
                  <span className="text-steel text-xs font-telemetry">{fmtLoss(c.time_loss_total_s)}</span>
                )}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
