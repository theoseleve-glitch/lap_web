/**
 * CornerEditor.tsx — Canvas-based corner zone editor.
 *
 * Replaces CornerPicker. Users click the track to place corners (entry/apex/exit),
 * drag handles to adjust zones, click apex to delete. Auto-detected corners load
 * as defaults; 15s timer auto-proceeds if user doesn't interact.
 */
'use client';

import { useEffect, useRef, useState, useCallback } from 'react';

/* ── Types ──────────────────────────────────────────── */

export interface TrackLayout {
  latitudes: number[];
  longitudes: number[];
  distances: number[];
  speeds: number[];
  corners: {
    corner_id: number;
    direction: string;
    lat: number;
    lon: number;
    dist_m: number;
    s_start: number | null;
    s_end: number | null;
    s_apex: number | null;
  }[];
  track_id?: string;
}

export interface EditorCorner {
  id: string;
  s_start: number;
  s_apex: number;
  s_end: number;
  idxStart: number;
  idxApex: number;
  idxEnd: number;
}

interface CornerEditorProps {
  trackLayout: TrackLayout;
  onSubmit: (corners: { s_start: number; s_apex: number; s_end: number }[]) => void;
  isSubmitting: boolean;
}

type EditorMode = 'timer' | 'editing';
type DragTarget = { cornerId: string; handle: 'start' | 'end' } | null;

/* ── Constants ──────────────────────────────────────── */

const TIMER_DURATION_MS = 15_000;
const DEFAULT_ZONE_M = 30;
const MIN_ZONE_M = 10;
const HANDLE_RADIUS = 6;
const APEX_RADIUS = 9;
const HIT_RADIUS_HANDLE = 14;
const HIT_RADIUS_APEX = 16;
const SNAP_RADIUS = 20;

const CORNER_COLORS = [
  '#f97316', '#60a5fa', '#a78bfa', '#34d399',
  '#f472b6', '#fbbf24', '#38bdf8', '#fb7185',
];

/* ── Projection ─────────────────────────────────────── */

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

  let cxx = 0, cyy = 0, cxy = 0;
  for (let i = 0; i < xs.length; i++) {
    cxx += xs[i]! * xs[i]!; cyy += ys[i]! * ys[i]!; cxy += xs[i]! * ys[i]!;
  }
  const pcaAngle = 0.5 * Math.atan2(2 * cxy, cxx - cyy);

  const drawW = w - padding * 2;
  const drawH = h - padding * 2;
  let bestAngle = 0, bestScale = 0;

  for (const candidate of [pcaAngle, pcaAngle + Math.PI / 2]) {
    const cosA = Math.cos(candidate), sinA = Math.sin(candidate);
    let rMinX = Infinity, rMaxX = -Infinity, rMinY = Infinity, rMaxY = -Infinity;
    for (let i = 0; i < xs.length; i++) {
      const rx = xs[i]! * cosA - ys[i]! * sinA;
      const ry = xs[i]! * sinA + ys[i]! * cosA;
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
    rxs[i] = xs[i]! * cosR - ys[i]! * sinR;
    rys[i] = xs[i]! * sinR + ys[i]! * cosR;
    if (rxs[i]! < rMinX) rMinX = rxs[i]!; if (rxs[i]! > rMaxX) rMaxX = rxs[i]!;
    if (rys[i]! < rMinY) rMinY = rys[i]!; if (rys[i]! > rMaxY) rMaxY = rys[i]!;
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
    pxs[i] = offsetX + (rxs[i]! - rMinX) * scale;
    const baseY = offsetY + (rMaxY - rys[i]!) * scale;
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

function speedToColor(t: number): string {
  const c = Math.max(0, Math.min(1, t));
  let r: number, g: number, b: number;
  if (c < 0.25) { const s = c / 0.25; r = 0; g = Math.round(180 * s); b = 220; }
  else if (c < 0.5) { const s = (c - 0.25) / 0.25; r = 0; g = 180 + Math.round(40 * s); b = Math.round(220 * (1 - s)); }
  else if (c < 0.75) { const s = (c - 0.5) / 0.25; r = Math.round(240 * s); g = 220; b = 0; }
  else { const s = (c - 0.75) / 0.25; r = 240; g = Math.round(220 * (1 - s)); b = 0; }
  return `rgb(${r},${g},${b})`;
}

/* ── Track helpers ──────────────────────────────────── */

function distToIndex(distances: number[], dist: number): number {
  let lo = 0, hi = distances.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (distances[mid]! < dist) lo = mid + 1; else hi = mid;
  }
  return Math.min(lo, distances.length - 1);
}

function nearestTrackPoint(
  cx: number, cy: number, proj: Projection, radius: number,
): number {
  let best = radius * radius;
  let bestIdx = -1;
  for (let i = 0; i < proj.pxs.length; i++) {
    const d = (proj.pxs[i]! - cx) ** 2 + (proj.pys[i]! - cy) ** 2;
    if (d < best) { best = d; bestIdx = i; }
  }
  return bestIdx;
}

/* ── Drawing ──────────────────────────────────────── */

function drawEditorMap(
  canvas: HTMLCanvasElement,
  layout: TrackLayout,
  corners: EditorCorner[],
  hoverIdx: number,
  timerPct: number,
  mode: EditorMode,
): Projection | null {
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;

  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const w = rect.width, h = rect.height;
  if (w === 0 || h === 0) return null;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  ctx.scale(dpr, dpr);

  const lats = layout.latitudes ?? [];
  const lons = layout.longitudes ?? [];
  const speeds = layout.speeds ?? [];
  if (lats.length < 2) return null;

  ctx.fillStyle = '#0B0C0F';
  ctx.fillRect(0, 0, w, h);

  const proj = buildProjection(lats, lons, w, h, 24);

  // Speed normalization
  let minSpd = Infinity, maxSpd = -Infinity;
  if (speeds.length === lats.length) {
    for (const s of speeds) { if (s < minSpd) minSpd = s; if (s > maxSpd) maxSpd = s; }
  }
  const spdRange = maxSpd - minSpd || 1;

  // Ground grid
  let pMinX = Infinity, pMaxX = -Infinity, pMinY = Infinity, pMaxY = -Infinity;
  for (let i = 0; i < proj.pxs.length; i++) {
    const px = proj.pxs[i]!, py = proj.pys[i]!;
    if (px < pMinX) pMinX = px; if (px > pMaxX) pMaxX = px;
    if (py < pMinY) pMinY = py; if (py > pMaxY) pMaxY = py;
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
    const x = proj.pxs[i]!, y = proj.pys[i]! + 5;
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }
  ctx.stroke();

  // Main track — speed-colored
  for (let i = 0; i < lats.length - 1; i++) {
    const depthT = (proj.pys[i]! - pMinY) / (pMaxY - pMinY || 1);
    ctx.lineWidth = 2 + depthT * 1.5;
    if (speeds.length === lats.length) {
      ctx.strokeStyle = speedToColor((speeds[i]! - minSpd) / spdRange);
    } else {
      ctx.strokeStyle = '#F0EDE5';
    }
    ctx.beginPath();
    ctx.moveTo(proj.pxs[i]!, proj.pys[i]!);
    ctx.lineTo(proj.pxs[i + 1]!, proj.pys[i + 1]!);
    ctx.stroke();
  }

  // Corner zones
  for (let ci = 0; ci < corners.length; ci++) {
    const cn = corners[ci]!;
    const color = CORNER_COLORS[ci % CORNER_COLORS.length]!;

    // Highlighted segment
    ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    ctx.lineWidth = 6;
    ctx.strokeStyle = color;
    ctx.globalAlpha = 0.8;
    ctx.beginPath();
    for (let i = cn.idxStart; i <= cn.idxEnd; i++) {
      if (i === cn.idxStart) ctx.moveTo(proj.pxs[i]!, proj.pys[i]!);
      else ctx.lineTo(proj.pxs[i]!, proj.pys[i]!);
    }
    ctx.stroke();
    ctx.globalAlpha = 1.0;

    // Entry handle
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(proj.pxs[cn.idxStart]!, proj.pys[cn.idxStart]!, HANDLE_RADIUS, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // Exit handle
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(proj.pxs[cn.idxEnd]!, proj.pys[cn.idxEnd]!, HANDLE_RADIUS, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // Apex marker (larger)
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(proj.pxs[cn.idxApex]!, proj.pys[cn.idxApex]!, APEX_RADIUS, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 2;
    ctx.stroke();

    // Label
    ctx.font = '600 10px "Space Mono", monospace';
    ctx.fillStyle = '#F0EDE5';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'bottom';
    ctx.fillText(`C${ci + 1}`, proj.pxs[cn.idxApex]!, proj.pys[cn.idxApex]! - 14);
  }

  // Ghost hover preview
  if (hoverIdx >= 0 && mode === 'editing') {
    ctx.setLineDash([4, 4]);
    ctx.strokeStyle = 'rgba(249, 115, 22, 0.5)';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.arc(proj.pxs[hoverIdx]!, proj.pys[hoverIdx]!, APEX_RADIUS + 4, 0, Math.PI * 2);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  // S/F marker
  ctx.fillStyle = 'rgba(240, 237, 229, 0.15)';
  ctx.beginPath(); ctx.arc(proj.pxs[0]!, proj.pys[0]!, 8, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = '#F0EDE5';
  ctx.beginPath(); ctx.arc(proj.pxs[0]!, proj.pys[0]!, 4, 0, Math.PI * 2); ctx.fill();
  ctx.font = '600 9px "Space Mono", monospace';
  ctx.fillStyle = 'rgba(240, 237, 229, 0.7)';
  ctx.textAlign = 'center'; ctx.textBaseline = 'bottom';
  ctx.fillText('S/F', proj.pxs[0]!, proj.pys[0]! - 10);

  // Timer bar
  if (mode === 'timer' && timerPct > 0) {
    const barY = h - 4;
    const barW = w * timerPct;
    ctx.fillStyle = 'rgba(107, 114, 128, 0.3)';
    ctx.fillRect(0, barY, w, 4);
    ctx.fillStyle = 'rgba(249, 115, 22, 0.6)';
    ctx.fillRect(0, barY, barW, 4);
  }

  // Instruction
  ctx.font = '11px "Space Mono", monospace';
  ctx.fillStyle = 'rgba(240, 237, 229, 0.5)';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'bottom';
  const msg = mode === 'timer'
    ? 'Click anywhere on the track to edit corners'
    : 'Click track to add corner \u00B7 Click apex to delete \u00B7 Drag handles to adjust';
  ctx.fillText(msg, w / 2, h - 10);

  return proj;
}

/* ── Auto-detect to EditorCorner conversion ────────── */

function autoDetectedToEditor(layout: TrackLayout): EditorCorner[] {
  const distances = layout.distances ?? [];
  if (distances.length < 2) return [];

  return (layout.corners ?? [])
    .filter((c) => c.s_start != null && c.s_end != null)
    .map((c, i) => {
      const s_apex = c.s_apex ?? (c.s_start! + c.s_end!) / 2;
      return {
        id: `auto-${i}`,
        s_start: c.s_start!,
        s_apex: s_apex,
        s_end: c.s_end!,
        idxStart: distToIndex(distances, c.s_start!),
        idxApex: distToIndex(distances, s_apex),
        idxEnd: distToIndex(distances, c.s_end!),
      };
    });
}

let _idCounter = 0;
function nextId(): string {
  return `corner-${++_idCounter}-${Date.now()}`;
}

/* ── Component ──────────────────────────────────────── */

export function CornerEditor({ trackLayout, onSubmit, isSubmitting }: CornerEditorProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const projRef = useRef<Projection | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startTimeRef = useRef<number>(0);

  const distances = trackLayout?.distances ?? [];

  const [corners, setCorners] = useState<EditorCorner[]>(() => autoDetectedToEditor(trackLayout));
  const [mode, setMode] = useState<EditorMode>('timer');
  const [timerPct, setTimerPct] = useState(1);
  const [hoverIdx, setHoverIdx] = useState(-1);
  const [dragTarget, setDragTarget] = useState<DragTarget>(null);

  // Stable ref for onSubmit to avoid re-triggering timer effect
  const onSubmitRef = useRef(onSubmit);
  onSubmitRef.current = onSubmit;
  const cornersRef = useRef(corners);
  cornersRef.current = corners;

  // ── Timer ────────────────────────────────────────
  useEffect(() => {
    if (mode !== 'timer') return;
    startTimeRef.current = Date.now();

    const interval = setInterval(() => {
      const elapsed = Date.now() - startTimeRef.current;
      const remaining = 1 - elapsed / TIMER_DURATION_MS;
      if (remaining <= 0) {
        clearInterval(interval);
        setTimerPct(0);
        onSubmitRef.current(
          cornersRef.current.map((c) => ({ s_start: c.s_start, s_apex: c.s_apex, s_end: c.s_end })),
        );
      } else {
        setTimerPct(remaining);
      }
    }, 50);

    timerRef.current = interval;
    return () => clearInterval(interval);
  }, [mode]);

  const cancelTimer = useCallback(() => {
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
    setMode('editing');
    setTimerPct(0);
  }, []);

  // ── Drawing ──────────────────────────────────────
  useEffect(() => {
    if (!canvasRef.current) return;
    projRef.current = drawEditorMap(canvasRef.current, trackLayout, corners, hoverIdx, timerPct, mode);
  }, [trackLayout, corners, hoverIdx, timerPct, mode]);

  useEffect(() => {
    if (!canvasRef.current) return;
    const canvas = canvasRef.current;
    const ro = new ResizeObserver(() => {
      projRef.current = drawEditorMap(canvas, trackLayout, corners, hoverIdx, timerPct, mode);
    });
    ro.observe(canvas);
    return () => ro.disconnect();
  }, [trackLayout, corners, hoverIdx, timerPct, mode]);

  // ── Hit testing ──────────────────────────────────
  const hitTest = useCallback((cx: number, cy: number): { type: 'apex' | 'handle'; cornerId: string; handle?: 'start' | 'end' } | null => {
    const proj = projRef.current;
    if (!proj) return null;

    for (const cn of corners) {
      const apxX = proj.pxs[cn.idxApex]!, apxY = proj.pys[cn.idxApex]!;
      if ((apxX - cx) ** 2 + (apxY - cy) ** 2 < HIT_RADIUS_APEX ** 2) {
        return { type: 'apex', cornerId: cn.id };
      }
      const stX = proj.pxs[cn.idxStart]!, stY = proj.pys[cn.idxStart]!;
      if ((stX - cx) ** 2 + (stY - cy) ** 2 < HIT_RADIUS_HANDLE ** 2) {
        return { type: 'handle', cornerId: cn.id, handle: 'start' };
      }
      const enX = proj.pxs[cn.idxEnd]!, enY = proj.pys[cn.idxEnd]!;
      if ((enX - cx) ** 2 + (enY - cy) ** 2 < HIT_RADIUS_HANDLE ** 2) {
        return { type: 'handle', cornerId: cn.id, handle: 'end' };
      }
    }
    return null;
  }, [corners]);

  // ── Mouse handlers ───────────────────────────────
  const getCanvasPos = useCallback((e: React.MouseEvent): [number, number] => {
    const rect = canvasRef.current!.getBoundingClientRect();
    return [e.clientX - rect.left, e.clientY - rect.top];
  }, []);

  const handleMouseDown = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!canvasRef.current || !projRef.current) return;
    if (mode === 'timer') cancelTimer();

    const [cx, cy] = getCanvasPos(e);
    const hit = hitTest(cx, cy);

    if (hit?.type === 'apex') {
      setCorners((prev) => prev.filter((c) => c.id !== hit.cornerId));
      return;
    }

    if (hit?.type === 'handle') {
      setDragTarget({ cornerId: hit.cornerId, handle: hit.handle! });
      return;
    }

    // Click on empty track → place new corner
    const trackIdx = nearestTrackPoint(cx, cy, projRef.current, SNAP_RADIUS);
    if (trackIdx < 0 || distances.length < 2) return;

    const apexDist = distances[trackIdx]!;
    const maxDist = distances[distances.length - 1]!;
    const startDist = Math.max(0, apexDist - DEFAULT_ZONE_M);
    const endDist = Math.min(maxDist, apexDist + DEFAULT_ZONE_M);

    const newCorner: EditorCorner = {
      id: nextId(),
      s_start: startDist,
      s_apex: apexDist,
      s_end: endDist,
      idxStart: distToIndex(distances, startDist),
      idxApex: trackIdx,
      idxEnd: distToIndex(distances, endDist),
    };

    setCorners((prev) => [...prev, newCorner].sort((a, b) => a.s_apex - b.s_apex));
  }, [mode, cancelTimer, hitTest, getCanvasPos, distances]);

  const handleMouseMove = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!canvasRef.current || !projRef.current) return;
    const [cx, cy] = getCanvasPos(e);

    if (dragTarget) {
      const trackIdx = nearestTrackPoint(cx, cy, projRef.current, 50);
      if (trackIdx < 0) return;
      const newDist = distances[trackIdx]!;

      setCorners((prev) => prev.map((cn) => {
        if (cn.id !== dragTarget.cornerId) return cn;
        if (dragTarget.handle === 'start') {
          const clamped = Math.min(newDist, cn.s_apex - MIN_ZONE_M);
          const clampedIdx = distToIndex(distances, Math.max(0, clamped));
          return { ...cn, s_start: Math.max(0, clamped), idxStart: clampedIdx };
        } else {
          const clamped = Math.max(newDist, cn.s_apex + MIN_ZONE_M);
          const maxDist = distances[distances.length - 1]!;
          const clampedIdx = distToIndex(distances, Math.min(maxDist, clamped));
          return { ...cn, s_end: Math.min(maxDist, clamped), idxEnd: clampedIdx };
        }
      }));
      return;
    }

    if (mode === 'editing') {
      const trackIdx = nearestTrackPoint(cx, cy, projRef.current, SNAP_RADIUS);
      if (trackIdx >= 0) {
        const dist = distances[trackIdx]!;
        const insideCorner = corners.some((cn) => dist >= cn.s_start && dist <= cn.s_end);
        setHoverIdx(insideCorner ? -1 : trackIdx);
      } else {
        setHoverIdx(-1);
      }
    }
  }, [dragTarget, distances, corners, mode, getCanvasPos]);

  const handleMouseUp = useCallback(() => {
    setDragTarget(null);
  }, []);

  const handleMouseLeave = useCallback(() => {
    setHoverIdx(-1);
    setDragTarget(null);
  }, []);

  // ── Actions ──────────────────────────────────────
  const handleSubmit = useCallback(() => {
    onSubmit(corners.map((c) => ({ s_start: c.s_start, s_apex: c.s_apex, s_end: c.s_end })));
  }, [corners, onSubmit]);

  const resetToAutoDetected = useCallback(() => {
    setCorners(autoDetectedToEditor(trackLayout));
  }, [trackLayout]);

  const clearAll = useCallback(() => setCorners([]), []);

  const cursor = dragTarget ? 'grabbing' : mode === 'editing' ? 'crosshair' : 'pointer';

  return (
    <div className="rounded-lg border border-steel/20 bg-concrete overflow-hidden">
      <canvas
        ref={canvasRef}
        className="w-full"
        style={{ display: 'block', height: '420px', cursor }}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseLeave}
        role="application"
        aria-label="Track map corner editor"
      />

      <div className="p-4 border-t border-steel/10">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            <span className="font-telemetry text-chalk text-sm">
              {corners.length} corner{corners.length !== 1 ? 's' : ''} defined
            </span>
            {mode === 'editing' && (
              <>
                <button type="button" onClick={resetToAutoDetected}
                  className="text-xs font-telemetry text-pit-orange hover:text-pit-orange/80 transition-colors">
                  Reset to Auto-detected
                </button>
                <button type="button" onClick={clearAll}
                  className="text-xs font-telemetry text-steel hover:text-chalk transition-colors">
                  Clear All
                </button>
              </>
            )}
          </div>
          {mode === 'timer' && (
            <span className="text-xs font-telemetry text-steel animate-pulse">
              Auto-proceeding in {Math.ceil(timerPct * 15)}s...
            </span>
          )}
        </div>

        {corners.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-4">
            {corners.map((cn, i) => {
              const color = CORNER_COLORS[i % CORNER_COLORS.length];
              return (
                <button
                  key={cn.id}
                  type="button"
                  onClick={() => {
                    if (mode === 'timer') cancelTimer();
                    setCorners((prev) => prev.filter((c) => c.id !== cn.id));
                  }}
                  className="inline-flex items-center gap-1.5 px-2 py-1 rounded text-[11px] font-telemetry
                    border border-chalk/40 text-chalk bg-asphalt hover:bg-safety-red/10 hover:border-safety-red/30
                    transition-all duration-150 group"
                  title="Click to remove"
                >
                  <span className="w-2 h-2 rounded-full" style={{ background: color }} />
                  C{i + 1}
                  <span className="text-steel/40 group-hover:text-safety-red transition-colors">x</span>
                </button>
              );
            })}
          </div>
        )}

        {mode === 'editing' && (
          <button
            type="button"
            onClick={handleSubmit}
            disabled={isSubmitting || corners.length === 0}
            className="w-full px-6 py-3 bg-gold text-carbon font-monument text-sm rounded-lg
              hover:bg-gold/90 transition-colors
              disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-gold"
          >
            {isSubmitting ? 'Resuming Analysis...' : `Continue Analysis (${corners.length} corners)`}
          </button>
        )}
      </div>
    </div>
  );
}
