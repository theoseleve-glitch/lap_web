'use client';

import { useCallback, useRef, useEffect } from 'react';
import type { ReplayMode, CornerReplayTrace, CornerReplayCorner, ReplayWindow } from '@/types/corner-replay';

/* ─── Design Colors ──────────────────────────────────────────────────── */

const COLORS = {
  concrete: '#141414',
  asphalt: '#000000',
  steel: '#888888',
  acidGreen: '#F0EDE5',
  safetyRed: '#EF4444',
  chalk: '#F0EDE5',
  gold: '#C9A84C',
  silver: '#C0C0C0',
  bronze: '#CD7F32',
};

const PODIUM_COLORS = [COLORS.gold, COLORS.silver, COLORS.bronze] as const;

/* ─── Props ──────────────────────────────────────────────────────────── */

interface CornerReplayMapProps {
  mode: ReplayMode;
  traces: Record<string, CornerReplayTrace>;
  corners: CornerReplayCorner[];
  cornerIndex: number;
  lapA: number;
  lapB: number;
  frame: number;
  replayWindow: ReplayWindow | null;
}

/* ─── Helpers ────────────────────────────────────────────────────────── */

function clampFrame(frame: number, trace: CornerReplayTrace): number {
  if (trace.lat.length === 0) return 0;
  return Math.max(0, Math.min(frame, trace.lat.length - 1));
}

function safeRadius(r: number): number {
  return Math.max(0, r);
}

function pickTop3Laps(traces: Record<string, CornerReplayTrace>): { key: string; color: string }[] {
  const keys = Object.keys(traces);
  const sorted = [...keys].sort((a, b) => {
    const tA = traces[a];
    const tB = traces[b];
    return tA.lat.length - tB.lat.length;
  });
  return sorted.slice(0, 3).map((key, i) => ({
    key,
    color: PODIUM_COLORS[i] ?? COLORS.steel,
  }));
}

/* ─── Component ──────────────────────────────────────────────────────── */

export function CornerReplayMap({
  mode,
  traces,
  corners,
  cornerIndex,
  lapA,
  lapB,
  frame,
  replayWindow,
}: CornerReplayMapProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const rafRef = useRef<number>(0);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;

    const rect = container.getBoundingClientRect();
    const w = rect.width;
    const h = rect.height;
    if (w < 1 || h < 1) return;

    const dpr = window.devicePixelRatio || 1;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = `${w}px`;
    canvas.style.height = `${h}px`;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.scale(dpr, dpr);

    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = COLORS.concrete;
    ctx.fillRect(0, 0, w, h);

    if (w < 10 || h < 10) return;

    const traceA = traces[String(lapA)];
    if (!traceA || traceA.lat.length < 2) {
      ctx.fillStyle = COLORS.steel;
      ctx.font = '12px "Space Mono", monospace';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText('No GPS data', w / 2, h / 2);
      return;
    }

    /* ── Coordinate system ─────────────────────────────────────────── */
    const allLats: number[] = [];
    const allLons: number[] = [];

    const pushTrace = (t: CornerReplayTrace) => {
      for (let i = 0; i < t.lat.length; i++) {
        const la = t.lat[i];
        const lo = t.lon[i];
        if (Number.isFinite(la) && Number.isFinite(lo)) {
          allLats.push(la);
          allLons.push(lo);
        }
      }
    };

    pushTrace(traceA);
    if (mode === 'split') {
      const traceB = traces[String(lapB)];
      if (traceB) pushTrace(traceB);
    }
    if (mode === 'top3') {
      for (const { key } of pickTop3Laps(traces)) {
        const t = traces[key];
        if (t) pushTrace(t);
      }
    }

    if (allLats.length === 0) return;

    const minLat = Math.min(...allLats);
    const maxLat = Math.max(...allLats);
    const minLon = Math.min(...allLons);
    const maxLon = Math.max(...allLons);
    const latRange = maxLat - minLat || 0.0001;
    const lonRange = maxLon - minLon || 0.0001;
    const pad = 24;
    const plotW = w - pad * 2;
    const plotH = h - pad * 2;
    const scaleX = plotW / lonRange;
    const scaleY = plotH / latRange;
    const scale = Math.min(scaleX, scaleY);
    const offsetX = pad + (plotW - lonRange * scale) / 2;
    const offsetY = pad + (plotH - latRange * scale) / 2;

    const toX = (lon: number): number => {
      const val = offsetX + (lon - minLon) * scale;
      return Number.isFinite(val) ? val : 0;
    };
    const toY = (lat: number): number => {
      const val = h - offsetY - (lat - minLat) * scale;
      return Number.isFinite(val) ? val : 0;
    };

    /* ── Grid ──────────────────────────────────────────────────────── */
    ctx.strokeStyle = 'rgba(138, 143, 152, 0.08)';
    ctx.lineWidth = 0.5;
    for (let i = 0; i <= 4; i++) {
      const gy = pad + (i / 4) * plotH;
      ctx.beginPath();
      ctx.moveTo(pad, gy);
      ctx.lineTo(w - pad, gy);
      ctx.stroke();
      const gx = pad + (i / 4) * plotW;
      ctx.beginPath();
      ctx.moveTo(gx, pad);
      ctx.lineTo(gx, h - pad);
      ctx.stroke();
    }

    /* ── Helper: draw a polyline from a trace ──────────────────────── */
    const drawPath = (
      trace: CornerReplayTrace,
      color: string,
      lineWidth: number,
      startIdx?: number,
      endIdx?: number,
    ) => {
      const s = startIdx ?? 0;
      const e = endIdx ?? trace.lat.length - 1;
      if (e <= s) return;
      ctx.beginPath();
      ctx.strokeStyle = color;
      ctx.lineWidth = lineWidth;
      ctx.lineJoin = 'round';
      ctx.lineCap = 'round';
      for (let i = s; i <= e; i++) {
        const x = toX(trace.lon[i]);
        const y = toY(trace.lat[i]);
        if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
        if (i === s) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
    };

    /* ── Helper: draw a position dot with glow ─────────────────────── */
    const drawPositionDot = (
      trace: CornerReplayTrace,
      frameIdx: number,
      color: string,
      radius: number,
    ) => {
      const fi = clampFrame(frameIdx, trace);
      const cx = toX(trace.lon[fi]);
      const cy = toY(trace.lat[fi]);
      if (!Number.isFinite(cx) || !Number.isFinite(cy)) return;

      const glow = ctx.createRadialGradient(cx, cy, 0, cx, cy, safeRadius(radius * 2.5));
      glow.addColorStop(0, color + '66');
      glow.addColorStop(1, color + '00');
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.arc(cx, cy, safeRadius(radius * 2.5), 0, Math.PI * 2);
      ctx.fill();

      ctx.beginPath();
      ctx.arc(cx, cy, safeRadius(radius), 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
      ctx.strokeStyle = COLORS.chalk;
      ctx.lineWidth = 1.5;
      ctx.stroke();
    };

    /* ── Helper: draw a text label near a point ────────────────────── */
    const drawLabel = (
      x: number,
      y: number,
      text: string,
      color: string,
      offsetXPx: number = 10,
      offsetYPx: number = -10,
    ) => {
      if (!Number.isFinite(x) || !Number.isFinite(y)) return;
      ctx.font = '10px "Space Mono", monospace';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'middle';
      ctx.fillStyle = COLORS.asphalt;
      ctx.fillRect(x + offsetXPx - 1, y + offsetYPx - 7, ctx.measureText(text).width + 4, 14);
      ctx.fillStyle = color;
      ctx.fillText(text, x + offsetXPx + 1, y + offsetYPx);
    };

    /* ── REVIEW MODE ───────────────────────────────────────────────── */
    if (mode === 'review') {
      drawPath(traceA, 'rgba(138, 143, 152, 0.25)', 2);
      if (replayWindow) {
        drawPath(traceA, COLORS.acidGreen, 2.5, replayWindow.start_idx, replayWindow.end_idx);
      }
      for (let ci = 0; ci < corners.length; ci++) {
        const c = corners[ci];
        const cx = toX(c.lon);
        const cy = toY(c.lat);
        if (!Number.isFinite(cx) || !Number.isFinite(cy)) continue;
        const isActive = ci === cornerIndex;
        const r = isActive ? 6 : 4;
        ctx.beginPath();
        ctx.arc(cx, cy, safeRadius(r), 0, Math.PI * 2);
        ctx.fillStyle = isActive ? COLORS.acidGreen : COLORS.steel;
        ctx.fill();
        ctx.strokeStyle = COLORS.chalk;
        ctx.lineWidth = 1;
        ctx.stroke();
        drawLabel(cx, cy, c.label || `C${ci + 1}`, isActive ? COLORS.acidGreen : COLORS.steel);
      }
      drawPositionDot(traceA, frame, COLORS.acidGreen, 6);
    }

    /* ── SPLIT MODE ────────────────────────────────────────────────── */
    if (mode === 'split') {
      const traceB = traces[String(lapB)];
      drawPath(traceA, 'rgba(138, 143, 152, 0.25)', 2);
      if (replayWindow) {
        drawPath(traceA, COLORS.acidGreen, 2.5, replayWindow.start_idx, replayWindow.end_idx);
      }
      if (traceB && replayWindow) {
        const startB = Math.min(replayWindow.start_idx, traceB.lat.length - 1);
        const endB = Math.min(replayWindow.end_idx, traceB.lat.length - 1);
        drawPath(traceB, COLORS.safetyRed, 2.5, startB, endB);
      }
      drawPositionDot(traceA, frame, COLORS.acidGreen, 6);
      if (traceB) {
        drawPositionDot(traceB, frame, COLORS.safetyRed, 6);
      }
    }

    /* ── TOP 3 MODE ────────────────────────────────────────────────── */
    if (mode === 'top3') {
      drawPath(traceA, 'rgba(138, 143, 152, 0.25)', 2);
      const top3 = pickTop3Laps(traces);
      for (const { key, color } of top3) {
        const t = traces[key];
        if (!t || t.lat.length < 2) continue;
        drawPath(t, color, 2);
        drawPositionDot(t, frame, color, 5);
        const fi = clampFrame(frame, t);
        const px = toX(t.lon[fi]);
        const py = toY(t.lat[fi]);
        drawLabel(px, py, `L${key}`, color, 10, -16);
      }
    }
  }, [traces, corners, cornerIndex, lapA, lapB, frame, mode, replayWindow]);

  /* ── Resize observer + draw ──────────────────────────────────────── */
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = requestAnimationFrame(draw);
    });
    observer.observe(container);
    rafRef.current = requestAnimationFrame(draw);

    return () => {
      observer.disconnect();
      cancelAnimationFrame(rafRef.current);
    };
  }, [draw]);

  const modeLabel = mode === 'review' ? 'Review' : mode === 'split' ? 'Split Compare' : 'Top 3';

  return (
    <div
      ref={containerRef}
      className="relative w-full h-full min-h-[200px] bg-concrete rounded-lg border border-steel/20 overflow-hidden"
    >
      <div className="absolute top-3 left-3 z-10 pointer-events-none">
        <span className="text-steel font-telemetry text-[10px] uppercase tracking-wider">
          Track Map — {modeLabel}
        </span>
      </div>
      <canvas ref={canvasRef} className="w-full h-full" />
    </div>
  );
}
