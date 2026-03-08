/**
 * TrackMap.tsx — Canvas-based speed-colored track map.
 *
 * Renders GPS trace as a colored polyline where hue = speed.
 * Dark background (#0B0C0F) — pure racing line, no map tiles.
 *
 * Dual-mode:
 *   - `sessionId` → fetches GPS data from API
 *   - `data` → renders directly from pre-fetched data
 */
'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { apiFetch } from '@/lib/api-client';
import { useChartHoverStore } from '@/lib/chart-hover-store';

/* ── Types ──────────────────────────────────────────────── */

interface TrackMapData {
  latitudes: number[];
  longitudes: number[];
  distances: number[];
  speeds?: number[];
}

interface Corner {
  corner_id: number;
  lat: number;
  lon: number;
  label?: string;
}

interface TrackMapProps {
  sessionId?: string;
  lap?: number;
  data?: TrackMapData;
  corners?: Corner[];
  markerDistance?: number;
  onHoverDistance?: (d: number) => void;
  className?: string;
  gpsLaps?: number[];
  bestLap?: number | null;
  apiBase?: string;
}

/* ── Speed → Color (blue → cyan → green → yellow → red) ── */

function speedToColor(t: number): string {
  // t is 0..1 (fraction of min→max speed)
  const clamped = Math.max(0, Math.min(1, t));

  let r: number, g: number, b: number;
  if (clamped < 0.25) {
    // blue → cyan
    const s = clamped / 0.25;
    r = 0; g = Math.round(180 * s); b = 220;
  } else if (clamped < 0.5) {
    // cyan → green
    const s = (clamped - 0.25) / 0.25;
    r = 0; g = 180 + Math.round(40 * s); b = Math.round(220 * (1 - s));
  } else if (clamped < 0.75) {
    // green → yellow
    const s = (clamped - 0.5) / 0.25;
    r = Math.round(240 * s); g = 220; b = 0;
  } else {
    // yellow → red
    const s = (clamped - 0.75) / 0.25;
    r = 240; g = Math.round(220 * (1 - s)); b = 0;
  }

  return `rgb(${r},${g},${b})`;
}

/* ── Projection: lat/lon → canvas px ──────────────────── */

interface Projection {
  toX: (lon: number) => number;
  toY: (lat: number) => number;
  /** Find closest point index to canvas coords */
  closestIndex: (cx: number, cy: number) => number;
}

function buildProjection(
  lats: number[],
  lons: number[],
  width: number,
  height: number,
  padding: number,
): Projection {
  let minLat = Infinity, maxLat = -Infinity;
  let minLon = Infinity, maxLon = -Infinity;

  for (let i = 0; i < lats.length; i++) {
    if (lats[i] < minLat) minLat = lats[i];
    if (lats[i] > maxLat) maxLat = lats[i];
    if (lons[i] < minLon) minLon = lons[i];
    if (lons[i] > maxLon) maxLon = lons[i];
  }

  // Aspect-ratio correction for latitude (Mercator-ish)
  const midLat = (minLat + maxLat) / 2;
  const cosLat = Math.cos((midLat * Math.PI) / 180);

  const spanLat = maxLat - minLat || 0.0001;
  const spanLon = (maxLon - minLon) * cosLat || 0.0001;

  const drawW = width - padding * 2;
  const drawH = height - padding * 2;

  // Fit with uniform scale
  const scale = Math.min(drawW / spanLon, drawH / spanLat);
  const offsetX = padding + (drawW - spanLon * scale) / 2;
  const offsetY = padding + (drawH - spanLat * scale) / 2;

  const toX = (lon: number) => offsetX + (lon - minLon) * cosLat * scale;
  // Flip Y: higher lat = higher on screen
  const toY = (lat: number) => offsetY + (maxLat - lat) * scale;

  // Pre-compute projected points for hit-testing
  const pxs = new Float64Array(lats.length);
  const pys = new Float64Array(lats.length);
  for (let i = 0; i < lats.length; i++) {
    pxs[i] = toX(lons[i]);
    pys[i] = toY(lats[i]);
  }

  const closestIndex = (cx: number, cy: number): number => {
    let best = 0;
    let bestDist = Infinity;
    for (let i = 0; i < pxs.length; i++) {
      const dx = pxs[i] - cx;
      const dy = pys[i] - cy;
      const d = dx * dx + dy * dy;
      if (d < bestDist) { bestDist = d; best = i; }
    }
    return best;
  };

  return { toX, toY, closestIndex };
}

/* ── Drawing ──────────────────────────────────────────── */

function drawTrack(
  canvas: HTMLCanvasElement,
  trace: TrackMapData,
  corners?: Corner[],
  hoverIndex?: number,
) {
  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const w = rect.width;
  const h = rect.height;

  canvas.width = w * dpr;
  canvas.height = h * dpr;
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, w, h);

  // Dark background — pure racing line, no map tiles
  ctx.fillStyle = '#0B0C0F';
  ctx.fillRect(0, 0, w, h);

  const { latitudes: lats, longitudes: lons, speeds } = trace;
  if (lats.length < 2) return;

  const proj = buildProjection(lats, lons, w, h, 24);

  // Speed normalization
  let minSpd = Infinity, maxSpd = -Infinity;
  if (speeds && speeds.length === lats.length) {
    for (let i = 0; i < speeds.length; i++) {
      if (speeds[i] < minSpd) minSpd = speeds[i];
      if (speeds[i] > maxSpd) maxSpd = speeds[i];
    }
  }
  const spdRange = maxSpd - minSpd || 1;

  // Draw speed-colored segments
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  ctx.lineWidth = 2.5;

  for (let i = 0; i < lats.length - 1; i++) {
    const x0 = proj.toX(lons[i]);
    const y0 = proj.toY(lats[i]);
    const x1 = proj.toX(lons[i + 1]);
    const y1 = proj.toY(lats[i + 1]);

    if (speeds && speeds.length === lats.length) {
      const t = (speeds[i] - minSpd) / spdRange;
      ctx.strokeStyle = speedToColor(t);
    } else {
      ctx.strokeStyle = '#F0EDE5'; // off-white fallback
    }

    ctx.beginPath();
    ctx.moveTo(x0, y0);
    ctx.lineTo(x1, y1);
    ctx.stroke();
  }

  // Draw start/finish marker (small circle at first point)
  const sx = proj.toX(lons[0]);
  const sy = proj.toY(lats[0]);
  ctx.fillStyle = '#F0EDE5';
  ctx.beginPath();
  ctx.arc(sx, sy, 4, 0, Math.PI * 2);
  ctx.fill();
  ctx.strokeStyle = 'rgba(243,240,232,0.4)';
  ctx.lineWidth = 1;
  ctx.stroke();

  // Corner labels
  if (corners && corners.length > 0) {
    ctx.font = '600 10px "Space Mono", "IBM Plex Mono", monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';

    for (const c of corners) {
      const cx = proj.toX(c.lon);
      const cy = proj.toY(c.lat);

      // Small dot
      ctx.fillStyle = 'rgba(201,168,76,0.6)';
      ctx.beginPath();
      ctx.arc(cx, cy, 3, 0, Math.PI * 2);
      ctx.fill();

      // Label
      ctx.fillStyle = 'rgba(201,168,76,0.9)';
      ctx.fillText(c.label || `C${c.corner_id}`, cx, cy - 10);
    }
  }

  // Hover marker
  if (hoverIndex != null && hoverIndex >= 0 && hoverIndex < lats.length) {
    const hx = proj.toX(lons[hoverIndex]);
    const hy = proj.toY(lats[hoverIndex]);

    // Outer glow
    ctx.fillStyle = 'rgba(201,168,76,0.3)';
    ctx.beginPath();
    ctx.arc(hx, hy, 8, 0, Math.PI * 2);
    ctx.fill();

    // Inner dot
    ctx.fillStyle = '#C9A84C';
    ctx.beginPath();
    ctx.arc(hx, hy, 4, 0, Math.PI * 2);
    ctx.fill();
  }

  // Store projection on canvas for hit-testing
  (canvas as unknown as Record<string, unknown>)._proj = proj;
}

/* ── Speed legend ─────────────────────────────────────── */

function SpeedLegend({ min, max }: { min: number; max: number }) {
  const stops = [0, 0.25, 0.5, 0.75, 1].map((t) => speedToColor(t));
  const gradient = `linear-gradient(to right, ${stops.join(', ')})`;

  return (
    <div className="flex items-center gap-2 mt-2">
      <span className="font-telemetry text-[10px] text-steel tabular-nums">
        {min.toFixed(0)}
      </span>
      <div
        className="flex-1 h-1.5 rounded-full"
        style={{ background: gradient }}
      />
      <span className="font-telemetry text-[10px] text-steel tabular-nums">
        {max.toFixed(0)} km/h
      </span>
    </div>
  );
}

/* ── Component ────────────────────────────────────────── */

export function TrackMap(props: TrackMapProps) {
  const {
    sessionId,
    data: preFetchedData,
    corners,
    onHoverDistance,
    className = '',
    gpsLaps = [],
    bestLap = null,
    apiBase,
  } = props;

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [trace, setTrace] = useState<TrackMapData | null>(preFetchedData ?? null);
  const [selectedLap, setSelectedLap] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  // Effective lap (selected or best)
  const activeLap = selectedLap ?? bestLap ?? gpsLaps[0] ?? null;

  // ── Fetch GPS data ──────────────────────────────────────
  useEffect(() => {
    if (preFetchedData) {
      setTrace(preFetchedData);
      return;
    }
    if (!sessionId) return;

    let cancelled = false;
    setLoading(true);
    setError(null);

    const lapParam = activeLap != null ? `?lap=${activeLap}` : '';

    (async () => {
      try {
        const result = await apiFetch<TrackMapData & { available?: boolean }>(
          `/sessions/${sessionId}/gps-trace${lapParam}`,
        );
        if (cancelled) return;

        if (result.available === false) {
          setTrace(null);
          setError('No GPS data available');
        } else {
          setTrace(result);
        }
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : 'Failed to load GPS data');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => { cancelled = true; };
  }, [sessionId, preFetchedData, activeLap]);

  // ── Draw on canvas ──────────────────────────────────────
  useEffect(() => {
    if (!trace || !canvasRef.current) return;
    drawTrack(canvasRef.current, trace, corners, hoverIdx ?? undefined);
  }, [trace, corners, hoverIdx]);

  // Redraw on resize
  useEffect(() => {
    if (!trace || !canvasRef.current) return;
    const canvas = canvasRef.current;
    const ro = new ResizeObserver(() => {
      drawTrack(canvas, trace, corners, hoverIdx ?? undefined);
    });
    ro.observe(canvas);
    return () => ro.disconnect();
  }, [trace, corners, hoverIdx]);

  // ── Hover handling ──────────────────────────────────────
  const handleCanvasMove = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      if (!trace || !canvasRef.current) return;
      const canvas = canvasRef.current;
      const proj = (canvas as unknown as Record<string, unknown>)._proj as Projection | undefined;
      if (!proj) return;

      const rect = canvas.getBoundingClientRect();
      const cx = e.clientX - rect.left;
      const cy = e.clientY - rect.top;
      const idx = proj.closestIndex(cx, cy);

      setHoverIdx(idx);

      if (trace.distances && trace.distances[idx] != null) {
        const d = trace.distances[idx];
        useChartHoverStore.getState().setHover(d, 'track-map');
        onHoverDistance?.(d);
      }
    },
    [trace, onHoverDistance],
  );

  const handleCanvasLeave = useCallback(() => {
    setHoverIdx(null);
    useChartHoverStore.getState().clearHover();
  }, []);

  // ── External hover sync (from other charts) ─────────────
  useEffect(() => {
    if (!trace || !trace.distances) return;

    const unsub = useChartHoverStore.subscribe((state) => {
      if (state.hoverSource === 'track-map') return;

      if (state.hoverDistance !== null) {
        // Binary search for closest distance index
        const dists = trace.distances;
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
  }, [trace]);

  // ── Speed stats for legend ──────────────────────────────
  let minSpd = 0, maxSpd = 0;
  if (trace?.speeds && trace.speeds.length > 0) {
    minSpd = Infinity;
    maxSpd = -Infinity;
    for (const s of trace.speeds) {
      if (s < minSpd) minSpd = s;
      if (s > maxSpd) maxSpd = s;
    }
    // Convert m/s → km/h if values look like m/s (< 100)
    if (maxSpd < 100) {
      minSpd *= 3.6;
      maxSpd *= 3.6;
    }
  }

  // ── Render ──────────────────────────────────────────────
  return (
    <div className={className}>
      <div
        className="relative rounded-lg border border-steel/10"
        style={{ width: '100%', height: '400px', background: '#0B0C0F' }}
      >
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="w-5 h-5 border-2 border-steel/30 border-t-chalk rounded-full animate-spin" />
          </div>
        )}

        {error && !trace && (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="text-center">
              <p className="font-telemetry text-chalk text-sm mb-1">No GPS Data</p>
              <p className="text-steel/60 text-xs max-w-[280px]">
                No GPS trace data available for this lap. Ensure your CSV contains
                latitude and longitude columns.
              </p>
            </div>
          </div>
        )}

        <canvas
          ref={canvasRef}
          role="img"
          aria-label="Track map showing GPS trace colored by speed"
          className="w-full h-full cursor-crosshair"
          onMouseMove={handleCanvasMove}
          onMouseLeave={handleCanvasLeave}
        />

        {/* Hover tooltip */}
        {hoverIdx != null && trace?.speeds && trace.speeds[hoverIdx] != null && (
          <div
            className="absolute top-2 right-2 bg-concrete/90 border border-steel/20 px-2 py-1 pointer-events-none"
          >
            <span className="font-telemetry text-[11px] text-chalk tabular-nums">
              {(trace.speeds[hoverIdx] < 100
                ? trace.speeds[hoverIdx] * 3.6
                : trace.speeds[hoverIdx]
              ).toFixed(1)} km/h
            </span>
            {trace.distances && (
              <span className="font-telemetry text-[10px] text-steel ml-2 tabular-nums">
                {trace.distances[hoverIdx].toFixed(0)}m
              </span>
            )}
          </div>
        )}
      </div>

      {/* Lap selector + speed legend */}
      <div className="flex items-center gap-3 mt-2 flex-wrap">
        {gpsLaps.length > 0 && (
          <>
            <label className="font-telemetry text-[10px] text-steel uppercase tracking-wider">Lap</label>
            <select
              value={activeLap ?? ''}
              onChange={(e) => setSelectedLap(Number(e.target.value))}
              className="bg-concrete text-chalk text-sm font-telemetry rounded px-2 py-1 border border-steel/20 focus:border-[#C9A84C] focus:outline-none"
            >
              {gpsLaps.map((l) => (
                <option key={l} value={l}>
                  {l}{l === bestLap ? ' (Best)' : ''}
                </option>
              ))}
            </select>
          </>
        )}
        {trace?.speeds && trace.speeds.length > 0 && (
          <div className="flex-1 min-w-[120px]">
            <SpeedLegend min={minSpd} max={maxSpd} />
          </div>
        )}
      </div>
    </div>
  );
}
