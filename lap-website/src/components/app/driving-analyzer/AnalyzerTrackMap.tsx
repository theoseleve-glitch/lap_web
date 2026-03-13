'use client';

import { useRef, useEffect, useCallback } from 'react';
import type { AnalyzerTrace, SectionDef } from './types';

interface AnalyzerTrackMapProps {
  trace: AnalyzerTrace | null;
  overlayTrace: AnalyzerTrace | null;
  currentDistance: number;
  activeSection: SectionDef | null;
  sections: SectionDef[];
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

/* ── Projection ───────────────────────────────────────────── */

function buildProjection(lats: number[], lons: number[], w: number, h: number, padding: number) {
  let minLat = Infinity, maxLat = -Infinity;
  let minLon = Infinity, maxLon = -Infinity;
  for (let i = 0; i < lats.length; i++) {
    if (lats[i] < minLat) minLat = lats[i];
    if (lats[i] > maxLat) maxLat = lats[i];
    if (lons[i] < minLon) minLon = lons[i];
    if (lons[i] > maxLon) maxLon = lons[i];
  }
  const midLat = (minLat + maxLat) / 2;
  const cosLat = Math.cos((midLat * Math.PI) / 180);
  const spanLat = maxLat - minLat || 0.0001;
  const spanLon = (maxLon - minLon) * cosLat || 0.0001;
  const drawW = w - padding * 2;
  const drawH = h - padding * 2;
  const scale = Math.min(drawW / spanLon, drawH / spanLat);
  const offsetX = padding + (drawW - spanLon * scale) / 2;
  const offsetY = padding + (drawH - spanLat * scale) / 2;

  return {
    toX: (lon: number) => offsetX + (lon - minLon) * cosLat * scale,
    toY: (lat: number) => offsetY + (maxLat - lat) * scale,
  };
}

/* ── Binary search ────────────────────────────────────────── */

function closestIdx(arr: number[], target: number): number {
  let lo = 0, hi = arr.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (arr[mid] < target) lo = mid + 1;
    else hi = mid;
  }
  if (lo > 0 && Math.abs(arr[lo - 1] - target) < Math.abs(arr[lo] - target)) return lo - 1;
  return lo;
}

/* ── Component ────────────────────────────────────────────── */

export function AnalyzerTrackMap({
  trace,
  overlayTrace,
  currentDistance,
  activeSection,
  sections,
}: AnalyzerTrackMapProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container || !trace) return;

    const dpr = window.devicePixelRatio || 1;
    const rect = container.getBoundingClientRect();
    const w = rect.width;
    const h = rect.height;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = w + 'px';
    canvas.style.height = h + 'px';
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    // Background
    ctx.fillStyle = '#0B0C0F';
    ctx.fillRect(0, 0, w, h);

    const { lat, lon, speed, distance } = trace;
    if (lat.length < 2) return;

    const proj = buildProjection(lat, lon, w, h, 28);

    // Speed range for coloring
    let minSpd = Infinity, maxSpd = -Infinity;
    for (let i = 0; i < speed.length; i++) {
      if (speed[i] < minSpd) minSpd = speed[i];
      if (speed[i] > maxSpd) maxSpd = speed[i];
    }
    const spdRange = maxSpd - minSpd || 1;

    // Highlight active section (dim non-active segments)
    const sectionStart = activeSection && activeSection.id !== 'full' ? activeSection.startDist : null;
    const sectionEnd = activeSection && activeSection.id !== 'full' ? activeSection.endDist : null;

    // Draw speed-colored polyline
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';

    for (let i = 0; i < lat.length - 1; i++) {
      const x0 = proj.toX(lon[i]);
      const y0 = proj.toY(lat[i]);
      const x1 = proj.toX(lon[i + 1]);
      const y1 = proj.toY(lat[i + 1]);

      // Dim segments outside active section
      const inSection = sectionStart === null || (distance[i] >= sectionStart && distance[i] <= sectionEnd!);
      const alpha = inSection ? 1.0 : 0.2;

      const t = (speed[i] - minSpd) / spdRange;
      ctx.strokeStyle = speedToColor(t);
      ctx.globalAlpha = alpha;
      ctx.lineWidth = inSection ? 3 : 1.5;

      ctx.beginPath();
      ctx.moveTo(x0, y0);
      ctx.lineTo(x1, y1);
      ctx.stroke();
    }
    ctx.globalAlpha = 1.0;

    // Draw overlay trace (if exists) with lower opacity
    if (overlayTrace && overlayTrace.lat.length > 1) {
      ctx.globalAlpha = 0.35;
      ctx.lineWidth = 2;
      ctx.strokeStyle = '#C9A84C';
      ctx.beginPath();
      for (let i = 0; i < overlayTrace.lat.length; i++) {
        const x = proj.toX(overlayTrace.lon[i]);
        const y = proj.toY(overlayTrace.lat[i]);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
      ctx.globalAlpha = 1.0;
    }

    // Section labels (corner markers)
    ctx.font = '600 9px "Space Mono", monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    for (const sec of sections) {
      if (sec.type !== 'corner') continue;
      const midDist = (sec.startDist + sec.endDist) / 2;
      const idx = closestIdx(distance, midDist);
      const cx = proj.toX(lon[idx]);
      const cy = proj.toY(lat[idx]);
      ctx.fillStyle = 'rgba(201,168,76,0.5)';
      ctx.beginPath();
      ctx.arc(cx, cy, 3, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = 'rgba(201,168,76,0.8)';
      ctx.fillText(sec.label, cx, cy - 10);
    }

    // Start/finish marker
    const sx = proj.toX(lon[0]);
    const sy = proj.toY(lat[0]);
    ctx.fillStyle = '#F0EDE5';
    ctx.beginPath();
    ctx.arc(sx, sy, 4, 0, Math.PI * 2);
    ctx.fill();

    // Cursor dot at currentDistance
    const cursorIdx = closestIdx(distance, currentDistance);
    if (cursorIdx >= 0 && cursorIdx < lat.length) {
      const cx = proj.toX(lon[cursorIdx]);
      const cy = proj.toY(lat[cursorIdx]);

      // Outer glow
      const glow = ctx.createRadialGradient(cx, cy, 0, cx, cy, 14);
      glow.addColorStop(0, 'rgba(240,237,229,0.5)');
      glow.addColorStop(1, 'rgba(240,237,229,0)');
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.arc(cx, cy, 14, 0, Math.PI * 2);
      ctx.fill();

      // Inner dot
      ctx.fillStyle = '#F0EDE5';
      ctx.beginPath();
      ctx.arc(cx, cy, 5, 0, Math.PI * 2);
      ctx.fill();
    }

    // Overlay cursor
    if (overlayTrace && overlayTrace.distance.length > 0) {
      const oIdx = closestIdx(overlayTrace.distance, currentDistance);
      if (oIdx >= 0 && oIdx < overlayTrace.lat.length) {
        const ox = proj.toX(overlayTrace.lon[oIdx]);
        const oy = proj.toY(overlayTrace.lat[oIdx]);
        ctx.fillStyle = '#C9A84C';
        ctx.beginPath();
        ctx.arc(ox, oy, 4, 0, Math.PI * 2);
        ctx.fill();
      }
    }
  }, [trace, overlayTrace, currentDistance, activeSection, sections]);

  // Stable ref for ResizeObserver — avoids re-attaching 60x/sec during playback
  const drawRef = useRef(draw);
  drawRef.current = draw;

  // Draw on every relevant change
  useEffect(() => { draw(); }, [draw]);

  // Resize observer — attached once, always calls latest draw via ref
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const ro = new ResizeObserver(() => drawRef.current());
    ro.observe(container);
    return () => ro.disconnect();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div ref={containerRef} className="relative w-full h-full min-h-[250px]" style={{ background: '#0B0C0F' }}>
      <canvas ref={canvasRef} className="w-full h-full" />
      <div className="absolute top-2 left-3">
        <span className="text-steel/50 font-telemetry text-[9px] uppercase tracking-wider">Track Map</span>
      </div>
    </div>
  );
}
