/**
 * CornerPicker.tsx — Canvas-based track map for mid-analysis corner selection.
 *
 * Uses the same 2.5D isometric speed-colored rendering as TrackMap.tsx —
 * no Leaflet, no tile loading. User clicks corner markers to toggle selection.
 */
'use client';

import { useEffect, useRef, useState, useCallback } from 'react';

/* ── Types ──────────────────────────────────────────── */

interface Corner {
  corner_id: number;
  direction: string;
  lat: number;
  lon: number;
  dist_m: number;
  s_start: number | null;
  s_end: number | null;
  s_apex: number | null;
}

export interface TrackLayout {
  latitudes: number[];
  longitudes: number[];
  distances: number[];
  speeds: number[];
  corners: Corner[];
  track_id?: string;
}

interface CornerPickerProps {
  trackLayout: TrackLayout;
  onSubmit: (selectedIds: number[]) => void;
  isSubmitting: boolean;
}

/* ── Colors ──────────────────────────────────────────── */

const LEFT_COLOR = '#60a5fa';   // blue-400
const RIGHT_COLOR = '#fb923c';  // orange-400
const NEUTRAL_COLOR = '#6b7280'; // gray-500

function speedToColor(t: number): string {
  const c = Math.max(0, Math.min(1, t));
  let r: number, g: number, b: number;
  if (c < 0.25) {
    const s = c / 0.25;
    r = 0; g = Math.round(180 * s); b = 220;
  } else if (c < 0.5) {
    const s = (c - 0.25) / 0.25;
    r = 0; g = 180 + Math.round(40 * s); b = Math.round(220 * (1 - s));
  } else if (c < 0.75) {
    const s = (c - 0.5) / 0.25;
    r = Math.round(240 * s); g = 220; b = 0;
  } else {
    const s = (c - 0.75) / 0.25;
    r = 240; g = Math.round(220 * (1 - s)); b = 0;
  }
  return `rgb(${r},${g},${b})`;
}

function dirColor(direction: string): string {
  if (direction === 'L') return LEFT_COLOR;
  if (direction === 'R') return RIGHT_COLOR;
  return NEUTRAL_COLOR;
}

/* ── Projection (matches TrackMap.tsx) ───────────────── */

interface Projection {
  pxs: number[];
  pys: number[];
  projectPoint: (lat: number, lon: number) => [number, number];
}

function buildProjection(
  lats: number[], lons: number[], w: number, h: number, padding: number,
): Projection {
  const midLat = lats.reduce((a, b) => a + b, 0) / lats.length;
  const midLon = lons.reduce((a, b) => a + b, 0) / lons.length;
  const cosLat = Math.cos((midLat * Math.PI) / 180);

  const xs: number[] = [];
  const ys: number[] = [];
  for (let i = 0; i < lats.length; i++) {
    xs.push((lons[i]! - midLon) * cosLat);
    ys.push(lats[i]! - midLat);
  }

  // PCA for auto-rotation
  let cxx = 0, cyy = 0, cxy = 0;
  for (let i = 0; i < xs.length; i++) {
    cxx += xs[i] * xs[i]; cyy += ys[i] * ys[i]; cxy += xs[i] * ys[i];
  }
  const pcaAngle = 0.5 * Math.atan2(2 * cxy, cxx - cyy);

  const drawW = w - padding * 2;
  const drawH = h - padding * 2;
  let bestAngle = 0, bestScale = 0;

  for (const candidate of [pcaAngle, pcaAngle + Math.PI / 2]) {
    const cosA = Math.cos(candidate), sinA = Math.sin(candidate);
    let rMinX = Infinity, rMaxX = -Infinity, rMinY = Infinity, rMaxY = -Infinity;
    for (let i = 0; i < xs.length; i++) {
      const rx = xs[i] * cosA - ys[i] * sinA;
      const ry = xs[i] * sinA + ys[i] * cosA;
      if (rx < rMinX) rMinX = rx; if (rx > rMaxX) rMaxX = rx;
      if (ry < rMinY) rMinY = ry; if (ry > rMaxY) rMaxY = ry;
    }
    const s = Math.min(drawW / (rMaxX - rMinX || 0.0001), drawH / (rMaxY - rMinY || 0.0001));
    if (s > bestScale) { bestScale = s; bestAngle = candidate; }
  }

  const cosR = Math.cos(bestAngle), sinR = Math.sin(bestAngle);
  const pxs = new Array(lats.length);
  const pys = new Array(lats.length);

  const rxs = new Array(lats.length);
  const rys = new Array(lats.length);
  let rMinX = Infinity, rMaxX = -Infinity, rMinY = Infinity, rMaxY = -Infinity;
  for (let i = 0; i < xs.length; i++) {
    rxs[i] = xs[i] * cosR - ys[i] * sinR;
    rys[i] = xs[i] * sinR + ys[i] * cosR;
    if (rxs[i] < rMinX) rMinX = rxs[i]; if (rxs[i] > rMaxX) rMaxX = rxs[i];
    if (rys[i] < rMinY) rMinY = rys[i]; if (rys[i] > rMaxY) rMaxY = rys[i];
  }

  const spanX = rMaxX - rMinX || 0.0001;
  const spanY = rMaxY - rMinY || 0.0001;
  const scale = Math.min(drawW / spanX, drawH / spanY);
  const usedW = spanX * scale, usedH = spanY * scale;
  const offsetX = padding + (drawW - usedW) / 2;
  const offsetY = padding + (drawH - usedH) / 2;
  const centerY = offsetY + usedH / 2;
  const TILT_K = 0.88;

  for (let i = 0; i < lats.length; i++) {
    pxs[i] = offsetX + (rxs[i] - rMinX) * scale;
    const baseY = offsetY + (rMaxY - rys[i]) * scale;
    pys[i] = centerY + (baseY - centerY) * TILT_K;
  }

  const projectPoint = (lat: number, lon: number): [number, number] => {
    const lx = (lon - midLon) * cosLat;
    const ly = lat - midLat;
    const rx = lx * cosR - ly * sinR;
    const ry = lx * sinR + ly * cosR;
    const px = offsetX + (rx - rMinX) * scale;
    const baseY2 = offsetY + (rMaxY - ry) * scale;
    return [px, centerY + (baseY2 - centerY) * TILT_K];
  };

  return { pxs, pys, projectPoint };
}

/* ── Helpers ─────────────────────────────────────────── */

function distToIndex(distances: number[], dist: number): number {
  let lo = 0, hi = distances.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (distances[mid] < dist) lo = mid + 1; else hi = mid;
  }
  return Math.min(lo, distances.length - 1);
}

/** Hit-test: find which corner marker is within radius of click. */
function hitTestCorner(
  cx: number, cy: number,
  corners: Corner[],
  proj: Projection,
  radius: number,
): number | null {
  let bestDist = radius * radius;
  let bestId: number | null = null;
  for (const c of corners) {
    const [px, py] = proj.projectPoint(c.lat, c.lon);
    const d = (px - cx) ** 2 + (py - cy) ** 2;
    if (d < bestDist) { bestDist = d; bestId = c.corner_id; }
  }
  return bestId;
}

/**
 * Hit-test via track-point snapping: find the nearest point on the track,
 * then check if it falls within any corner's s_start..s_end range.
 * This lets users click anywhere on a highlighted corner segment.
 */
function hitTestTrackSnap(
  cx: number, cy: number,
  corners: Corner[],
  proj: Projection,
  distances: number[],
  snapRadius: number,
): number | null {
  if (distances.length < 2) return null;

  // Find nearest track point to click
  let bestDist = snapRadius * snapRadius;
  let bestIdx = -1;
  for (let i = 0; i < proj.pxs.length; i++) {
    const d = (proj.pxs[i] - cx) ** 2 + (proj.pys[i] - cy) ** 2;
    if (d < bestDist) { bestDist = d; bestIdx = i; }
  }
  if (bestIdx < 0) return null;

  // Check which corner segment contains this track point
  const clickDist = distances[bestIdx];
  if (clickDist == null) return null;

  for (const c of corners) {
    if (c.s_start == null || c.s_end == null) continue;
    if (clickDist >= c.s_start && clickDist <= c.s_end) {
      return c.corner_id;
    }
  }
  return null;
}

/* ── Drawing ─────────────────────────────────────────── */

function drawPickerMap(
  canvas: HTMLCanvasElement,
  layout: TrackLayout,
  selected: Set<number>,
  enrichedCorners: Corner[],
): Projection | null {
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;

  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const w = rect.width, h = rect.height;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  ctx.scale(dpr, dpr);

  // Background
  ctx.fillStyle = '#0B0C0F';
  ctx.fillRect(0, 0, w, h);

  const lats = layout.latitudes ?? [];
  const lons = layout.longitudes ?? [];
  const distances = layout.distances ?? [];
  const speeds = layout.speeds ?? [];
  const corners = enrichedCorners;
  if (lats.length < 2) return null;

  const proj = buildProjection(lats, lons, w, h, 24);

  // Speed normalization
  let minSpd = Infinity, maxSpd = -Infinity;
  if (speeds?.length === lats.length) {
    for (const s of speeds) { if (s < minSpd) minSpd = s; if (s > maxSpd) maxSpd = s; }
  }
  const spdRange = maxSpd - minSpd || 1;

  // Ground grid
  let pMinX = Infinity, pMaxX = -Infinity, pMinY = Infinity, pMaxY = -Infinity;
  for (let i = 0; i < proj.pxs.length; i++) {
    if (proj.pxs[i] < pMinX) pMinX = proj.pxs[i]; if (proj.pxs[i] > pMaxX) pMaxX = proj.pxs[i];
    if (proj.pys[i] < pMinY) pMinY = proj.pys[i]; if (proj.pys[i] > pMaxY) pMaxY = proj.pys[i];
  }
  ctx.strokeStyle = 'rgba(240, 237, 229, 0.06)';
  ctx.lineWidth = 0.5;
  const gridStep = Math.max(20, (pMaxX - pMinX) / 12);
  for (let x = pMinX - 8; x <= pMaxX + 8; x += gridStep) {
    ctx.beginPath(); ctx.moveTo(x, pMinY - 8); ctx.lineTo(x, pMaxY + 8); ctx.stroke();
  }
  for (let y = pMinY - 8; y <= pMaxY + 8; y += gridStep) {
    ctx.beginPath(); ctx.moveTo(pMinX - 8, y); ctx.lineTo(pMaxX + 8, y); ctx.stroke();
  }

  // Shadow pass
  ctx.lineCap = 'round'; ctx.lineJoin = 'round';
  ctx.lineWidth = 5; ctx.strokeStyle = 'rgba(0, 0, 0, 0.35)';
  ctx.beginPath();
  for (let i = 0; i < lats.length; i++) {
    const x = proj.pxs[i], y = proj.pys[i] + 5;
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }
  ctx.stroke();

  // Main track — speed-colored with corner highlight
  for (let i = 0; i < lats.length - 1; i++) {
    const depthT = (proj.pys[i] - pMinY) / (pMaxY - pMinY || 1);
    ctx.lineWidth = 2 + depthT * 1.5;

    if (speeds?.length === lats.length) {
      ctx.strokeStyle = speedToColor((speeds[i] - minSpd) / spdRange);
    } else {
      ctx.strokeStyle = '#F0EDE5';
    }

    ctx.beginPath();
    ctx.moveTo(proj.pxs[i], proj.pys[i]);
    ctx.lineTo(proj.pxs[i + 1], proj.pys[i + 1]);
    ctx.stroke();
  }

  // Corner segment highlights
  for (const cn of corners) {
    if (cn.s_start == null || cn.s_end == null || !distances.length) continue;
    const isSelected = selected.has(cn.corner_id);
    const color = dirColor(cn.direction);
    const startIdx = distToIndex(distances, cn.s_start);
    const endIdx = distToIndex(distances, cn.s_end);

    ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    ctx.lineWidth = isSelected ? 6 : 3;
    ctx.strokeStyle = isSelected ? color : `${color}40`;
    ctx.globalAlpha = isSelected ? 1.0 : 0.4;
    ctx.beginPath();
    for (let i = startIdx; i <= endIdx; i++) {
      if (i === startIdx) ctx.moveTo(proj.pxs[i], proj.pys[i]);
      else ctx.lineTo(proj.pxs[i], proj.pys[i]);
    }
    ctx.stroke();
    ctx.globalAlpha = 1.0;
  }

  // S/F marker
  ctx.fillStyle = 'rgba(240, 237, 229, 0.15)';
  ctx.beginPath(); ctx.arc(proj.pxs[0], proj.pys[0], 8, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = '#F0EDE5';
  ctx.beginPath(); ctx.arc(proj.pxs[0], proj.pys[0], 4, 0, Math.PI * 2); ctx.fill();
  ctx.font = '600 9px "Space Mono", monospace';
  ctx.fillStyle = 'rgba(240, 237, 229, 0.7)';
  ctx.textAlign = 'center'; ctx.textBaseline = 'bottom';
  ctx.fillText('S/F', proj.pxs[0], proj.pys[0] - 10);

  // Corner markers
  ctx.font = '600 10px "Space Mono", monospace';
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';

  for (const cn of corners) {
    const [cx, cy] = proj.projectPoint(cn.lat, cn.lon);
    const isSelected = selected.has(cn.corner_id);
    const color = dirColor(cn.direction);

    // Outer ring (selection indicator)
    if (isSelected) {
      ctx.fillStyle = `${color}30`;
      ctx.beginPath(); ctx.arc(cx, cy, 14, 0, Math.PI * 2); ctx.fill();
    }

    // Marker dot
    ctx.fillStyle = isSelected ? color : `${color}60`;
    ctx.beginPath(); ctx.arc(cx, cy, isSelected ? 7 : 5, 0, Math.PI * 2); ctx.fill();
    ctx.strokeStyle = isSelected ? '#fff' : `${color}80`;
    ctx.lineWidth = isSelected ? 2 : 1;
    ctx.stroke();

    // Label
    const dirArrow = cn.direction === 'L' ? '\u21B0' : cn.direction === 'R' ? '\u21B1' : '';
    ctx.fillStyle = isSelected ? '#F0EDE5' : 'rgba(240,237,229,0.4)';
    ctx.fillText(`C${cn.corner_id + 1} ${dirArrow}`, cx, cy - 16);
  }

  // Instruction banner
  ctx.font = '11px "Space Mono", monospace';
  ctx.fillStyle = 'rgba(240, 237, 229, 0.5)';
  ctx.textBaseline = 'bottom';
  ctx.fillText('Click corners on the map to select/deselect', w / 2, h - 6);

  return proj;
}

/* ── Enrich corners with lat/lon from track data ──── */

function enrichCorners(corners: Corner[], layout: TrackLayout): Corner[] {
  const lats = layout.latitudes ?? [];
  const lons = layout.longitudes ?? [];
  const dists = layout.distances ?? [];
  if (lats.length < 2 || dists.length < 2) return corners;

  return corners.map((c) => {
    // Already has valid lat/lon — skip
    if (c.lat && c.lon && c.lat !== 0 && c.lon !== 0) return c;

    // Derive from apex distance (or midpoint of s_start/s_end)
    const dist = c.s_apex ?? c.dist_m ?? (
      c.s_start != null && c.s_end != null ? (c.s_start + c.s_end) / 2 : null
    );
    if (dist == null) return c;

    const idx = distToIndex(dists, dist);
    return { ...c, lat: lats[idx] ?? 0, lon: lons[idx] ?? 0, dist_m: dists[idx] ?? dist };
  });
}

/* ── Component ──────────────────────────────────────── */

export function CornerPicker({ trackLayout, onSubmit, isSubmitting }: CornerPickerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const projRef = useRef<Projection | null>(null);

  const rawCorners = trackLayout?.corners ?? [];
  const corners = enrichCorners(rawCorners, trackLayout);
  const allIds = corners.map((c) => c.corner_id);
  const [selected, setSelected] = useState<Set<number>>(() => new Set(allIds));

  const toggle = useCallback((id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  const selectAll = useCallback(() => setSelected(new Set(allIds)), [allIds]);
  const clearAll = useCallback(() => setSelected(new Set()), []);

  // Draw
  useEffect(() => {
    if (!canvasRef.current) return;
    projRef.current = drawPickerMap(canvasRef.current, trackLayout, selected, corners);
  }, [trackLayout, selected]);

  // Resize
  useEffect(() => {
    if (!canvasRef.current) return;
    const canvas = canvasRef.current;
    const ro = new ResizeObserver(() => {
      projRef.current = drawPickerMap(canvas, trackLayout, selected, corners);
    });
    ro.observe(canvas);
    return () => ro.disconnect();
  }, [trackLayout, selected]);

  // Click handler — toggle nearest corner (marker dot first, then track segment snap)
  const handleClick = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    const proj = projRef.current;
    if (!canvas || !proj) return;

    const rect = canvas.getBoundingClientRect();
    const cx = e.clientX - rect.left;
    const cy = e.clientY - rect.top;

    // Try marker dot hit first (generous 30px radius)
    const markerHit = hitTestCorner(cx, cy, corners, proj, 30);
    if (markerHit !== null) { toggle(markerHit); return; }

    // Fall back to track-point snapping (click on the track segment itself)
    const distances = trackLayout?.distances ?? [];
    const snapHit = hitTestTrackSnap(cx, cy, corners, proj, distances, 15);
    if (snapHit !== null) toggle(snapHit);
  }, [corners, toggle, trackLayout]);

  const handleSubmit = () => onSubmit(Array.from(selected));

  const totalCorners = corners.length;
  const selectedCount = selected.size;

  return (
    <div className="rounded-lg border border-steel/20 bg-concrete overflow-hidden">
      {/* Canvas map */}
      <canvas
        ref={canvasRef}
        className="w-full cursor-pointer"
        style={{ display: 'block', height: '400px' }}
        onClick={handleClick}
        role="img"
        aria-label="Track map for corner selection"
      />

      {/* Controls */}
      <div className="p-4 border-t border-steel/10">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            <span className="font-telemetry text-chalk text-sm">
              {selectedCount} / {totalCorners} corners selected
            </span>
            <button
              type="button"
              onClick={selectedCount === totalCorners ? clearAll : selectAll}
              className="text-xs font-telemetry text-pit-orange hover:text-pit-orange/80 transition-colors"
            >
              {selectedCount === totalCorners ? 'Clear All' : 'Select All'}
            </button>
          </div>

          {/* Direction legend */}
          <div className="flex items-center gap-4 text-xs font-telemetry text-steel">
            <span className="flex items-center gap-1.5">
              <span className="w-3 h-1.5 rounded-full" style={{ background: LEFT_COLOR }} />
              Left
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-3 h-1.5 rounded-full" style={{ background: RIGHT_COLOR }} />
              Right
            </span>
          </div>
        </div>

        {/* Corner chips */}
        <div className="flex flex-wrap gap-2 mb-4">
          {corners.map((cn) => {
            const isSelected = selected.has(cn.corner_id);
            const color = dirColor(cn.direction);
            const dirArrow = cn.direction === 'L' ? '\u21B0' : cn.direction === 'R' ? '\u21B1' : '';
            return (
              <button
                key={cn.corner_id}
                type="button"
                onClick={() => toggle(cn.corner_id)}
                className={`
                  inline-flex items-center gap-1 px-2 py-1 rounded text-[11px] font-telemetry
                  border transition-all duration-150
                  ${isSelected
                    ? 'border-chalk/40 text-chalk bg-asphalt'
                    : 'border-steel/20 text-steel/50 bg-concrete'
                  }
                `}
              >
                <span
                  className="w-2 h-2 rounded-full"
                  style={{ background: isSelected ? color : `${color}40` }}
                />
                C{cn.corner_id + 1} {dirArrow}
              </button>
            );
          })}
        </div>

        {/* Submit */}
        <button
          type="button"
          onClick={handleSubmit}
          disabled={isSubmitting || selectedCount === 0}
          className="w-full px-6 py-3 bg-gold text-carbon font-monument text-sm rounded-lg
            hover:bg-gold/90 transition-colors
            disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-gold"
        >
          {isSubmitting ? 'Resuming Analysis...' : `Continue Analysis (${selectedCount} corners)`}
        </button>
      </div>
    </div>
  );
}
