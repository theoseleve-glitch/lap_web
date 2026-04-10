/**
 * TrackMap.tsx — 2.5D isometric speed-colored track map.
 *
 * Renders GPS trace as a speed-colored polyline with an isometric
 * camera tilt (~25°) giving a racing-game overhead view.
 * Dark background (#000000) — pure racing line, no map tiles.
 * Depth cues: shadow underneath, line width varies with depth,
 * subtle ground grid for spatial reference.
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
  controlledLap?: boolean;
  /** Distance zoom range [startM, endM] — segments outside are dimmed. */
  distRange?: [number, number] | null;
  /** When set, fetches and draws a second lap trace for comparison. */
  compareLap?: number | null;
  /** Color mode: "speed" (default), "grip" (headroom heatmap), or "ribbon" (filled 2.5D width). */
  colorMode?: "speed" | "grip" | "ribbon";
}

/* ── Speed → Color (blue → cyan → green → yellow → red) ── */

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

/* ── Grip headroom → Color (red → gold → green) ────────── */

function gripHeadroomColor(headroom_pct: number): string {
  if (headroom_pct > 15) return '#22C55E';
  if (headroom_pct > 5) {
    const t = (headroom_pct - 5) / 10;
    const r = Math.round(201 * (1 - t) + 34 * t);
    const g = Math.round(168 * (1 - t) + 197 * t);
    const b = Math.round(76 * (1 - t) + 94 * t);
    return `rgb(${r},${g},${b})`;
  }
  if (headroom_pct > 0) {
    const t = headroom_pct / 5;
    const r = Math.round(255 * (1 - t) + 201 * t);
    const g = Math.round(42 * (1 - t) + 168 * t);
    const b = Math.round(42 * (1 - t) + 76 * t);
    return `rgb(${r},${g},${b})`;
  }
  return '#FF2A2A';
}

/* ── 2.5D Isometric projection ──────────────────────────── */

const TILT = 0.42; // ~25° tilt angle (radians)
const COS_TILT = Math.cos(TILT);
const SIN_TILT = Math.sin(TILT);

interface Projection {
  toX: (lon: number) => number;
  toY: (lat: number) => number;
  toShadowY: (lat: number) => number;
  /** Project a (lat, lon) pair to screen coords */
  toXY?: (lat: number, lon: number) => [number, number];
  closestIndex: (cx: number, cy: number) => number;
  pxs: Float64Array;
  pys: Float64Array;
}

function buildProjection(
  lats: number[],
  lons: number[],
  width: number,
  height: number,
  padding: number,
): Projection {
  // Convert to metric-ish local coordinates first
  const midLat = (lats.reduce((a, b) => a + b, 0)) / lats.length;
  const midLon = (lons.reduce((a, b) => a + b, 0)) / lons.length;
  const cosLat = Math.cos((midLat * Math.PI) / 180);

  // Local X/Y in approximate metres (for PCA + rotation)
  const xs = new Float64Array(lats.length);
  const ys = new Float64Array(lats.length);
  for (let i = 0; i < lats.length; i++) {
    xs[i] = (lons[i] - midLon) * cosLat;
    ys[i] = lats[i] - midLat;
  }

  // PCA: find principal axis angle to auto-rotate track for best fit
  let cxx = 0, cyy = 0, cxy = 0;
  for (let i = 0; i < xs.length; i++) {
    cxx += xs[i] * xs[i];
    cyy += ys[i] * ys[i];
    cxy += xs[i] * ys[i];
  }
  // Angle of principal axis
  const pcaAngle = 0.5 * Math.atan2(2 * cxy, cxx - cyy);

  // Try PCA angle + 90° to find best natural orientation.
  // Compute fit using UN-TILTED bounding box; tilt applied visually afterward.
  const drawW = width - padding * 2;
  const drawH = height - padding * 2;

  let bestAngle = 0;
  let bestScale = 0;

  for (const candidate of [pcaAngle, pcaAngle + Math.PI / 2]) {
    const cosA = Math.cos(candidate);
    const sinA = Math.sin(candidate);

    let rMinX = Infinity, rMaxX = -Infinity;
    let rMinY = Infinity, rMaxY = -Infinity;
    for (let i = 0; i < xs.length; i++) {
      const rx = xs[i] * cosA - ys[i] * sinA;
      const ry = xs[i] * sinA + ys[i] * cosA; // NO tilt during fit
      if (rx < rMinX) rMinX = rx;
      if (rx > rMaxX) rMaxX = rx;
      if (ry < rMinY) rMinY = ry;
      if (ry > rMaxY) rMaxY = ry;
    }

    const spanX = rMaxX - rMinX || 0.0001;
    const spanY = rMaxY - rMinY || 0.0001;
    const s = Math.min(drawW / spanX, drawH / spanY);
    if (s > bestScale) {
      bestScale = s;
      bestAngle = candidate;
    }
  }

  // Apply best rotation — use uniform scale from un-tilted fit,
  // then apply COS_TILT only to Y for the isometric visual effect.
  const cosR = Math.cos(bestAngle);
  const sinR = Math.sin(bestAngle);

  const pxs = new Float64Array(lats.length);
  const pys = new Float64Array(lats.length);

  // First pass: compute rotated (un-tilted) to get bounding box for centering
  const rxs = new Float64Array(lats.length);
  const rys = new Float64Array(lats.length);
  let rMinX = Infinity, rMaxX = -Infinity;
  let rMinY = Infinity, rMaxY = -Infinity;

  for (let i = 0; i < xs.length; i++) {
    rxs[i] = xs[i] * cosR - ys[i] * sinR;
    rys[i] = xs[i] * sinR + ys[i] * cosR; // un-tilted for fit
    if (rxs[i] < rMinX) rMinX = rxs[i];
    if (rxs[i] > rMaxX) rMaxX = rxs[i];
    if (rys[i] < rMinY) rMinY = rys[i];
    if (rys[i] > rMaxY) rMaxY = rys[i];
  }

  const spanX = rMaxX - rMinX || 0.0001;
  const spanY = rMaxY - rMinY || 0.0001;
  const scale = Math.min(drawW / spanX, drawH / spanY);

  // Center in canvas using the un-tilted span
  const usedW = spanX * scale;
  const usedH = spanY * scale;
  const offsetX = padding + (drawW - usedW) / 2;
  const offsetY = padding + (drawH - usedH) / 2;

  // Map to screen coords with subtle Y foreshortening (2.5D effect)
  const centerY = offsetY + usedH / 2;
  const TILT_K = 0.88; // subtle Y compression for isometric feel

  for (let i = 0; i < lats.length; i++) {
    pxs[i] = offsetX + (rxs[i] - rMinX) * scale;
    const baseY = offsetY + (rMaxY - rys[i]) * scale; // flip Y: north=up
    pys[i] = centerY + (baseY - centerY) * TILT_K;
  }

  // Project an arbitrary (lat, lon) → screen coords
  const projectPoint = (lat: number, lon: number): [number, number] => {
    const lx = (lon - midLon) * cosLat;
    const ly = lat - midLat;
    const rx = lx * cosR - ly * sinR;
    const ry = lx * sinR + ly * cosR;
    const px = offsetX + (rx - rMinX) * scale;
    const baseY = offsetY + (rMaxY - ry) * scale;
    return [px, centerY + (baseY - centerY) * TILT_K];
  };

  const toX = (lon: number) => projectPoint(0, lon)[0]; // approx
  const toY = (lat: number) => projectPoint(lat, midLon)[1]; // approx
  const toXY = projectPoint;
  const toShadowY = (lat: number) => toY(lat) + 6;

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

  return { toX, toY, toShadowY, closestIndex, pxs, pys, toXY } as Projection & { toXY: (lat: number, lon: number) => [number, number] };
}

/* ── Drawing ──────────────────────────────────────────── */

function drawTrack(
  canvas: HTMLCanvasElement,
  trace: TrackMapData,
  corners?: Corner[],
  hoverIndex?: number,
  distRange?: [number, number] | null,
  compareTrace?: TrackMapData | null,
  colorMode: "speed" | "grip" | "ribbon" = "speed",
  gripDelta?: { distance_m: number; headroom_pct: number }[] | null,
  ribbonData?: { points: { lat: number; lon: number; nx: number; ny: number; width_m: number; mu_p95: number | null; speed_mps?: number }[]; aggregate_sessions: number } | null,
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

  // Dark background
  ctx.fillStyle = '#000000';
  ctx.fillRect(0, 0, w, h);

  const { latitudes: lats, longitudes: lons, speeds } = trace;
  if (lats.length < 2) return;

  const proj = buildProjection(lats, lons, w, h, 12);

  // Speed normalization
  let minSpd = Infinity, maxSpd = -Infinity;
  if (speeds && speeds.length === lats.length) {
    for (let i = 0; i < speeds.length; i++) {
      if (speeds[i] < minSpd) minSpd = speeds[i];
      if (speeds[i] > maxSpd) maxSpd = speeds[i];
    }
  }
  const spdRange = maxSpd - minSpd || 1;

  // ── Ground grid for spatial reference ──
  const gridAlpha = 0.06;
  ctx.strokeStyle = `rgba(240, 237, 229, ${gridAlpha})`;
  ctx.lineWidth = 0.5;

  // Find grid bounds from projected points
  let pMinX = Infinity, pMaxX = -Infinity;
  let pMinY = Infinity, pMaxY = -Infinity;
  for (let i = 0; i < proj.pxs.length; i++) {
    if (proj.pxs[i] < pMinX) pMinX = proj.pxs[i];
    if (proj.pxs[i] > pMaxX) pMaxX = proj.pxs[i];
    if (proj.pys[i] < pMinY) pMinY = proj.pys[i];
    if (proj.pys[i] > pMaxY) pMaxY = proj.pys[i];
  }
  const gridPad = 8;
  const gx0 = pMinX - gridPad, gx1 = pMaxX + gridPad;
  const gy0 = pMinY - gridPad, gy1 = pMaxY + gridPad;
  const gridStep = Math.max(20, (gx1 - gx0) / 12);

  for (let x = gx0; x <= gx1; x += gridStep) {
    ctx.beginPath();
    ctx.moveTo(x, gy0);
    ctx.lineTo(x, gy1);
    ctx.stroke();
  }
  for (let y = gy0; y <= gy1; y += gridStep) {
    ctx.beginPath();
    ctx.moveTo(gx0, y);
    ctx.lineTo(gx1, y);
    ctx.stroke();
  }

  // ── Compare trace (dashed, drawn underneath primary) ──
  if (compareTrace && compareTrace.latitudes && compareTrace.latitudes.length > 1) {
    const cLats = compareTrace.latitudes;
    const cLons = compareTrace.longitudes;
    const cProj = buildProjection(cLats, cLons, w, h, 12);
    const cSpeeds = compareTrace.speeds;

    // Speed normalization for compare trace
    let cMinSpd = Infinity, cMaxSpd = -Infinity;
    if (cSpeeds && cSpeeds.length === cLats.length) {
      for (let i = 0; i < cSpeeds.length; i++) {
        if (cSpeeds[i] < cMinSpd) cMinSpd = cSpeeds[i];
        if (cSpeeds[i] > cMaxSpd) cMaxSpd = cSpeeds[i];
      }
    }
    const cSpdRange = cMaxSpd - cMinSpd || 1;

    // Draw compare trace — speed-colored but semi-transparent
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.globalAlpha = 0.35;
    ctx.setLineDash([6, 4]);
    for (let i = 0; i < cLats.length - 1; i++) {
      ctx.lineWidth = 1.5;
      if (cSpeeds && cSpeeds.length === cLats.length) {
        const t = (cSpeeds[i] - cMinSpd) / cSpdRange;
        ctx.strokeStyle = speedToColor(t);
      } else {
        ctx.strokeStyle = '#F0EDE5';
      }
      ctx.beginPath();
      ctx.moveTo(cProj.pxs[i], cProj.pys[i]);
      ctx.lineTo(cProj.pxs[i + 1], cProj.pys[i + 1]);
      ctx.stroke();
    }
    ctx.setLineDash([]);
    ctx.globalAlpha = 1.0;
  }

  // ── Shadow pass (dark, blurred, offset below track) ──
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  ctx.lineWidth = 3;
  ctx.strokeStyle = 'rgba(0, 0, 0, 0.25)';
  ctx.beginPath();
  for (let i = 0; i < lats.length; i++) {
    const x = proj.pxs[i];
    const y = proj.pys[i] + 5; // shadow offset
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();

  // ── Ribbon mode: filled quads with width ──
  if (colorMode === 'ribbon' && ribbonData && ribbonData.points.length > 2) {
    // Project ribbon points and compute edges
    const rPts = ribbonData.points;
    const rProj = buildProjection(
      rPts.map(p => p.lat),
      rPts.map(p => p.lon),
      w, h, 30,
    );

    // Compute screen-space normals and edge points
    const leftXs: number[] = [];
    const leftYs: number[] = [];
    const rightXs: number[] = [];
    const rightYs: number[] = [];

    for (let i = 0; i < rPts.length; i++) {
      const cx = rProj.pxs[i];
      const cy = rProj.pys[i];

      // Compute screen-space tangent from projected points
      let tx: number, ty: number;
      if (i === 0) {
        tx = rProj.pxs[1] - rProj.pxs[0];
        ty = rProj.pys[1] - rProj.pys[0];
      } else if (i === rPts.length - 1) {
        tx = rProj.pxs[i] - rProj.pxs[i - 1];
        ty = rProj.pys[i] - rProj.pys[i - 1];
      } else {
        tx = rProj.pxs[i + 1] - rProj.pxs[i - 1];
        ty = rProj.pys[i + 1] - rProj.pys[i - 1];
      }
      const tMag = Math.sqrt(tx * tx + ty * ty) || 1;
      // Normal = 90 deg rotation of tangent
      const nnx = -ty / tMag;
      const nny = tx / tMag;

      // Width in pixels: approximate by using the projection scale
      // Use half-width of 4px as base, scale with actual track width
      const halfW = Math.max(3, Math.min(20, rPts[i].width_m * 0.4));

      leftXs.push(cx + nnx * halfW);
      leftYs.push(cy + nny * halfW);
      rightXs.push(cx - nnx * halfW);
      rightYs.push(cy - nny * halfW);
    }

    // Draw shadow first
    ctx.save();
    ctx.globalAlpha = 0.15;
    ctx.fillStyle = '#000000';
    ctx.beginPath();
    ctx.moveTo(leftXs[0], leftYs[0] + 4);
    for (let i = 1; i < leftXs.length; i++) ctx.lineTo(leftXs[i], leftYs[i] + 4);
    for (let i = rightXs.length - 1; i >= 0; i--) ctx.lineTo(rightXs[i], rightYs[i] + 4);
    ctx.closePath();
    ctx.fill();
    ctx.restore();

    // Draw filled ribbon — per-segment quads with grip coloring
    for (let i = 0; i < rPts.length - 1; i++) {
      const mu = rPts[i].mu_p95;
      let color: string;
      if (mu != null && mu > 0) {
        // Map mu to color: low grip (red) -> medium (gold) -> high grip (green)
        if (mu > 1.2) color = '#22C55E';
        else if (mu > 0.9) {
          const t = (mu - 0.9) / 0.3;
          const r = Math.round(201 * (1 - t) + 34 * t);
          const g = Math.round(168 * (1 - t) + 197 * t);
          const b = Math.round(76 * (1 - t) + 94 * t);
          color = `rgb(${r},${g},${b})`;
        } else {
          const t = Math.max(0, mu / 0.9);
          const r = Math.round(255 * (1 - t) + 201 * t);
          const g = Math.round(42 * (1 - t) + 168 * t);
          const b = Math.round(42 * (1 - t) + 76 * t);
          color = `rgb(${r},${g},${b})`;
        }
      } else {
        // No aggregate data — use speed coloring or neutral
        const spd = rPts[i].speed_mps;
        if (spd != null) {
          const maxSpd2 = 40; // rough max for karts
          const t = Math.min(1, spd / maxSpd2);
          color = speedToColor(t);
        } else {
          color = '#F0EDE5';
        }
      }

      ctx.fillStyle = color;
      ctx.globalAlpha = 0.85;
      ctx.beginPath();
      ctx.moveTo(leftXs[i], leftYs[i]);
      ctx.lineTo(leftXs[i + 1], leftYs[i + 1]);
      ctx.lineTo(rightXs[i + 1], rightYs[i + 1]);
      ctx.lineTo(rightXs[i], rightYs[i]);
      ctx.closePath();
      ctx.fill();
    }

    // Draw edge lines (subtle border)
    ctx.globalAlpha = 0.3;
    ctx.strokeStyle = '#F0EDE5';
    ctx.lineWidth = 0.5;
    ctx.beginPath();
    ctx.moveTo(leftXs[0], leftYs[0]);
    for (let i = 1; i < leftXs.length; i++) ctx.lineTo(leftXs[i], leftYs[i]);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(rightXs[0], rightYs[0]);
    for (let i = 1; i < rightXs.length; i++) ctx.lineTo(rightXs[i], rightYs[i]);
    ctx.stroke();

    // Centerline (thin dashed chalk)
    ctx.globalAlpha = 0.2;
    ctx.strokeStyle = '#F0EDE5';
    ctx.lineWidth = 0.5;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    for (let i = 0; i < rPts.length; i++) {
      if (i === 0) ctx.moveTo(rProj.pxs[i], rProj.pys[i]);
      else ctx.lineTo(rProj.pxs[i], rProj.pys[i]);
    }
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.globalAlpha = 1.0;

    // Grip legend
    const legX = w - 20;
    const legY = 16;
    const legH = 60;
    const legW = 8;
    const grad = ctx.createLinearGradient(legX, legY, legX, legY + legH);
    grad.addColorStop(0, '#22C55E');
    grad.addColorStop(0.5, '#C9A84C');
    grad.addColorStop(1, '#FF2A2A');
    ctx.fillStyle = grad;
    ctx.fillRect(legX - legW, legY, legW, legH);
    ctx.fillStyle = '#949494';
    ctx.font = '8px "Space Mono", monospace';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'top';
    ctx.fillText('Grip', legX - legW - 4, legY);
    ctx.fillText('High', legX - legW - 4, legY + 12);
    ctx.textBaseline = 'bottom';
    ctx.fillText('Low', legX - legW - 4, legY + legH);

    // Session count badge
    if (ribbonData.aggregate_sessions > 0) {
      ctx.fillStyle = '#949494';
      ctx.font = '8px "Space Mono", monospace';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'top';
      ctx.fillText(`${ribbonData.aggregate_sessions} sessions`, 8, h - 16);
    }
  }

  if (colorMode !== 'ribbon' || !ribbonData) {
  // ── Main track (speed-colored segments) ──
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';

  const dists = trace.distances;
  for (let i = 0; i < lats.length - 1; i++) {
    const x0 = proj.pxs[i];
    const y0 = proj.pys[i];
    const x1 = proj.pxs[i + 1];
    const y1 = proj.pys[i + 1];

    // Depth-varying line width: thicker when "closer" (higher Y)
    const depthT = (y0 - gy0) / (gy1 - gy0 || 1);

    // Dim segments outside zoom range
    const inRange = !distRange || !dists || (dists[i] >= distRange[0] && dists[i] <= distRange[1]);
    ctx.lineWidth = inRange ? 1.5 : 0.5;
    ctx.globalAlpha = inRange ? 1.0 : 0.15;

    if (colorMode === 'grip' && gripDelta && dists) {
      let bestIdx = 0;
      let bestDist = Infinity;
      for (let j = 0; j < gripDelta.length; j++) {
        const dd = Math.abs(gripDelta[j].distance_m - (dists[i] ?? 0));
        if (dd < bestDist) { bestDist = dd; bestIdx = j; }
      }
      ctx.strokeStyle = inRange ? gripHeadroomColor(gripDelta[bestIdx].headroom_pct) : '#444';
    } else if (speeds && speeds.length === lats.length) {
      const t = (speeds[i] - minSpd) / spdRange;
      ctx.strokeStyle = inRange ? speedToColor(t) : '#444';
    } else {
      ctx.strokeStyle = inRange ? '#F0EDE5' : '#333';
    }

    ctx.beginPath();
    ctx.moveTo(x0, y0);
    ctx.lineTo(x1, y1);
    ctx.stroke();
  }
  ctx.globalAlpha = 1.0;
  } // end non-ribbon track draw

  // ── Start/finish marker ──
  const sx = proj.pxs[0];
  const sy = proj.pys[0];
  // Outer glow
  ctx.fillStyle = 'rgba(240, 237, 229, 0.15)';
  ctx.beginPath();
  ctx.arc(sx, sy, 8, 0, Math.PI * 2);
  ctx.fill();
  // Inner dot
  ctx.fillStyle = '#F0EDE5';
  ctx.beginPath();
  ctx.arc(sx, sy, 4, 0, Math.PI * 2);
  ctx.fill();
  ctx.strokeStyle = 'rgba(243,240,232,0.4)';
  ctx.lineWidth = 1;
  ctx.stroke();
  // "S/F" label
  ctx.font = '600 9px "Space Mono", monospace';
  ctx.fillStyle = 'rgba(240, 237, 229, 0.7)';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'bottom';
  ctx.fillText('S/F', sx, sy - 10);

  // ── Corner labels ──
  if (corners && corners.length > 0) {
    ctx.font = '600 10px "Space Mono", monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';

    for (const c of corners) {
      const [cx, cy] = proj.toXY ? proj.toXY(c.lat, c.lon) : [proj.toX(c.lon), proj.toY(c.lat)];

      // Small dot
      ctx.fillStyle = 'rgba(201,168,76,0.6)';
      ctx.beginPath();
      ctx.arc(cx, cy, 3, 0, Math.PI * 2);
      ctx.fill();

      // Find min speed near this corner
      let cornerSpeed: number | null = null;
      if (speeds && speeds.length === lats.length) {
        let minDist = Infinity;
        let nearIdx = 0;
        for (let i = 0; i < lats.length; i++) {
          const dLat = lats[i] - c.lat;
          const dLon = lons[i] - c.lon;
          const d = dLat * dLat + dLon * dLon;
          if (d < minDist) { minDist = d; nearIdx = i; }
        }
        let localMin = speeds[nearIdx];
        const lo = Math.max(0, nearIdx - 10);
        const hi = Math.min(speeds.length - 1, nearIdx + 10);
        for (let i = lo; i <= hi; i++) {
          if (speeds[i] < localMin) localMin = speeds[i];
        }
        cornerSpeed = localMin;
      }

      const labelText = c.label || `C${c.corner_id}`;
      ctx.fillStyle = 'rgba(201,168,76,0.9)';
      ctx.fillText(labelText, cx, cy - 10);

      if (cornerSpeed != null) {
        const spdKmh = Math.round(cornerSpeed * 3.6);
        ctx.font = '500 8px "Space Mono", monospace';
        ctx.fillStyle = 'rgba(240,237,229,0.6)';
        ctx.fillText(`${spdKmh}`, cx, cy - 20);
        ctx.font = '600 10px "Space Mono", monospace';
      }
    }
  }

  // ── Hover marker ──
  if (hoverIndex != null && hoverIndex >= 0 && hoverIndex < lats.length) {
    const hx = proj.pxs[hoverIndex];
    const hy = proj.pys[hoverIndex];

    // Vertical "pin" line from shadow to point
    ctx.strokeStyle = 'rgba(201,168,76,0.25)';
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(hx, hy);
    ctx.lineTo(hx, hy + 5);
    ctx.stroke();
    ctx.setLineDash([]);

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

  // ── Grip headroom legend ──
  if (colorMode === 'grip') {
    const legX = w - 20;
    const legY = 16;
    const legH = 60;
    const legW = 8;
    const grad = ctx.createLinearGradient(legX, legY, legX, legY + legH);
    grad.addColorStop(0, '#22C55E');
    grad.addColorStop(0.5, '#C9A84C');
    grad.addColorStop(1, '#FF2A2A');
    ctx.fillStyle = grad;
    ctx.fillRect(legX - legW, legY, legW, legH);
    ctx.fillStyle = '#949494';
    ctx.font = '8px "Space Mono", monospace';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'top';
    ctx.fillText('Headroom', legX - legW - 4, legY);
    ctx.fillText('+15%', legX - legW - 4, legY + 12);
    ctx.textBaseline = 'bottom';
    ctx.fillText('0%', legX - legW - 4, legY + legH);
  }

  // Store projection on canvas for hit-testing
  (canvas as unknown as Record<string, unknown>)._proj = proj;
}

/* ── Speed legend ─────────────────────────────────────── */

function SpeedLegend({ min, max }: { min: number; max: number }) {
  const stops = [0, 0.25, 0.5, 0.75, 1].map((t) => speedToColor(t));
  const gradient = `linear-gradient(to right, ${stops.join(', ')})`;

  return (
    <div className="flex items-center gap-2">
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
    controlledLap = false,
    distRange,
    compareLap = null,
    colorMode = 'speed',
  } = props;

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [trace, setTrace] = useState<TrackMapData | null>(preFetchedData ?? null);
  const [compareTrace, setCompareTrace] = useState<TrackMapData | null>(null);
  const [selectedLap, setSelectedLap] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  const [gripDelta, setGripDelta] = useState<{ distance_m: number; headroom_pct: number }[] | null>(null);
  const [ribbonData, setRibbonData] = useState<{
    points: { lat: number; lon: number; distance_m: number; nx: number; ny: number; width_m: number; mu_p95: number | null; speed_mps?: number }[];
    aggregate_sessions: number;
  } | null>(null);

  useEffect(() => {
    if (controlledLap && bestLap != null) setSelectedLap(bestLap);
  }, [controlledLap, bestLap]);

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

  // ── Fetch compare lap GPS data ─────────────────────────
  useEffect(() => {
    if (!sessionId || compareLap == null) { setCompareTrace(null); return; }
    let cancelled = false;
    (async () => {
      try {
        const result = await apiFetch<TrackMapData & { available?: boolean }>(
          `/sessions/${sessionId}/gps-trace?lap=${compareLap}`,
        );
        if (cancelled) return;
        if (result.available === false) setCompareTrace(null);
        else setCompareTrace(result);
      } catch {
        if (!cancelled) setCompareTrace(null);
      }
    })();
    return () => { cancelled = true; };
  }, [sessionId, compareLap]);

  // ── Fetch grip delta data ─────────────────────────────────
  useEffect(() => {
    if (colorMode !== 'grip' || !sessionId) {
      setGripDelta(null);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const res = await apiFetch<{ bins: { distance_m: number; headroom_pct: number }[] }>(
          `/sessions/${encodeURIComponent(sessionId)}/track-delta`,
        );
        if (!cancelled && res?.bins) setGripDelta(res.bins);
      } catch {
        if (!cancelled) setGripDelta(null);
      }
    })();
    return () => { cancelled = true; };
  }, [colorMode, sessionId]);

  // ── Fetch ribbon data ───────────────────────────────────
  useEffect(() => {
    if (colorMode !== 'ribbon' || !sessionId) {
      setRibbonData(null);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const res = await apiFetch<{ points: { lat: number; lon: number; distance_m: number; nx: number; ny: number; width_m: number; mu_p95: number | null; speed_mps?: number }[]; aggregate_sessions: number }>(
          `/sessions/${encodeURIComponent(sessionId)}/track-ribbon`,
        );
        if (!cancelled && res?.points) setRibbonData(res);
      } catch {
        if (!cancelled) setRibbonData(null);
      }
    })();
    return () => { cancelled = true; };
  }, [colorMode, sessionId]);

  // ── Draw on canvas ──────────────────────────────────────
  const draw = useCallback(() => {
    if (!trace || !canvasRef.current) return;
    drawTrack(canvasRef.current, trace, corners, hoverIdx ?? undefined, distRange, compareTrace, colorMode, gripDelta, ribbonData);
  }, [trace, compareTrace, corners, hoverIdx, distRange, colorMode, gripDelta, ribbonData]);

  useEffect(() => { draw(); }, [draw]);

  // Stable ref for ResizeObserver — avoids re-attaching on every hover
  const drawRef = useRef(draw);
  drawRef.current = draw;

  // Redraw on resize — attached once per trace/corners change, not per hover
  useEffect(() => {
    if (!trace || !canvasRef.current) return;
    const canvas = canvasRef.current;
    const ro = new ResizeObserver(() => drawRef.current());
    ro.observe(canvas);
    return () => ro.disconnect();
  }, [trace, corners]);

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
        const dists = trace.distances;
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
    if (maxSpd < 100) {
      minSpd *= 3.6;
      maxSpd *= 3.6;
    }
  }

  // ── Render ──────────────────────────────────────────────
  return (
    <div className={`flex flex-col ${className}`}>
      <div
        className="relative flex-1 min-h-0 rounded-lg border border-steel/10"
        style={{ width: '100%', background: 'var(--asphalt)', ...(!className.includes('h-full') ? { minHeight: '300px' } : {}) }}
      >
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center z-10">
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
            className="absolute top-2 right-2 bg-concrete/90 border border-steel/20 rounded px-2.5 py-1.5 pointer-events-none"
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
        {trace?.speeds && trace.speeds.length > 0 && (
          <div className="flex-1 min-w-[120px]">
            <SpeedLegend min={minSpd} max={maxSpd} />
          </div>
        )}
      </div>
    </div>
  );
}
