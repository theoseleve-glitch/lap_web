'use client';

import { useCallback, useRef, useState, useEffect } from 'react';
import { ChartTooltip } from '@/components/app/ChartTooltip';
import { useInteractiveCanvas, type HoverPoint, type TooltipData } from '@/hooks/useInteractiveCanvas';
import type { ReplayMode, CornerReplayTrace, CornerReplayCorner, ReplayWindow } from '@/types/corner-replay';

/* ─── Design Colors ──────────────────────────────────────────────────── */

const COLORS = {
  concrete: '#1A1A1A',
  asphalt: '#0D0D0D',
  steel: '#8A8F98',
  acidGreen: '#BFFF00',
  safetyRed: '#EF4444',
  chalk: '#F3F0E8',
  gold: '#FFD700',
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

/* ─── Padding ────────────────────────────────────────────────────────── */

const PAD = { top: 24, right: 24, bottom: 24, left: 24 };

/* ─── Helpers ────────────────────────────────────────────────────────── */

/** Clamp a frame index safely into trace length range */
function clampFrame(frame: number, trace: CornerReplayTrace): number {
  if (trace.lat.length === 0) return 0;
  return Math.max(0, Math.min(frame, trace.lat.length - 1));
}

/** Safe positive radius for ctx.arc */
function safeRadius(r: number): number {
  return Math.max(0, r);
}

/** Pick the top-3 laps by fastest lap time (smallest key as proxy when no explicit time) */
function pickTop3Laps(traces: Record<string, CornerReplayTrace>): { key: string; color: string }[] {
  const keys = Object.keys(traces);
  // Sort by key numerically (lap number) — fastest laps by convention are first
  // In the data model, each key IS the lap number. We pick the three with the shortest traces
  // (fewest data points, i.e., least time at the given sample rate).
  // If traces have speed data, we use a heuristic: fewer samples = faster lap.
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
  /* ── Zoom / Pan state ──────────────────────────────────────────────── */
  const [zoom, setZoom] = useState(1);
  const [panX, setPanX] = useState(0);
  const [panY, setPanY] = useState(0);

  /* Drag tracking for pan */
  const dragRef = useRef<{ dragging: boolean; lastX: number; lastY: number }>({
    dragging: false,
    lastX: 0,
    lastY: 0,
  });

  /* Screen-point cache for tooltip lookup */
  const screenPtsRef = useRef<{ x: number; y: number; lat: number; lon: number; idx: number }[]>([]);

  /* ── Main draw callback ────────────────────────────────────────────── */
  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number, hover: HoverPoint | null) => {
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = COLORS.concrete;
      ctx.fillRect(0, 0, w, h);

      /* Safety: skip draw if canvas too small */
      if (w < 10 || h < 10) {
        screenPtsRef.current = [];
        return;
      }

      /* Resolve primary trace (lap A) */
      const traceA = traces[String(lapA)];
      if (!traceA || traceA.lat.length < 2) {
        ctx.fillStyle = COLORS.steel;
        ctx.font = '12px "IBM Plex Mono", monospace';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText('No GPS data', w / 2, h / 2);
        screenPtsRef.current = [];
        return;
      }

      /* ── Coordinate system ─────────────────────────────────────────── */

      // Gather all lat/lon across all relevant traces to compute bounds
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

      // Always include lap A
      pushTrace(traceA);

      // Include lap B if split mode
      if (mode === 'split') {
        const traceB = traces[String(lapB)];
        if (traceB) pushTrace(traceB);
      }

      // Include top 3 if top3 mode
      if (mode === 'top3') {
        const top3 = pickTop3Laps(traces);
        for (const { key } of top3) {
          const t = traces[key];
          if (t) pushTrace(t);
        }
      }

      if (allLats.length === 0) {
        screenPtsRef.current = [];
        return;
      }

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

      /* Apply zoom + pan to coordinate transforms */
      const toX = (lon: number): number => {
        const val = (offsetX + (lon - minLon) * scale) * zoom + panX;
        return Number.isFinite(val) ? val : 0;
      };
      const toY = (lat: number): number => {
        const val = (h - offsetY - (lat - minLat) * scale) * zoom + panY;
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

        // Glow
        const glow = ctx.createRadialGradient(cx, cy, 0, cx, cy, safeRadius(radius * 2.5));
        glow.addColorStop(0, color + '66');
        glow.addColorStop(1, color + '00');
        ctx.fillStyle = glow;
        ctx.beginPath();
        ctx.arc(cx, cy, safeRadius(radius * 2.5), 0, Math.PI * 2);
        ctx.fill();

        // Solid dot
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
        ctx.font = '10px "IBM Plex Mono", monospace';
        ctx.textAlign = 'left';
        ctx.textBaseline = 'middle';
        ctx.fillStyle = COLORS.asphalt;
        ctx.fillRect(x + offsetXPx - 1, y + offsetYPx - 7, ctx.measureText(text).width + 4, 14);
        ctx.fillStyle = color;
        ctx.fillText(text, x + offsetXPx + 1, y + offsetYPx);
      };

      /* ── Cache screen points for trace A (for tooltip) ─────────────── */
      const computedPts = traceA.lat.map((lat, i) => ({
        x: toX(traceA.lon[i]),
        y: toY(lat),
        lat,
        lon: traceA.lon[i],
        idx: i,
      }));
      screenPtsRef.current = computedPts;

      /* ── REVIEW MODE ───────────────────────────────────────────────── */
      if (mode === 'review') {
        // Full track outline (gray)
        drawPath(traceA, 'rgba(138, 143, 152, 0.25)', 2);

        // Highlighted replay window section (acid-green)
        if (replayWindow) {
          drawPath(traceA, COLORS.acidGreen, 2.5, replayWindow.start_idx, replayWindow.end_idx);
        }

        // Corner marker dots
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

          // Label
          drawLabel(cx, cy, c.label || `C${ci + 1}`, isActive ? COLORS.acidGreen : COLORS.steel);
        }

        // Current frame position dot
        drawPositionDot(traceA, frame, COLORS.acidGreen, 6);
      }

      /* ── SPLIT MODE ────────────────────────────────────────────────── */
      if (mode === 'split') {
        const traceB = traces[String(lapB)];

        // Full track outline (gray) — use trace A
        drawPath(traceA, 'rgba(138, 143, 152, 0.25)', 2);

        // Lap A replay window (acid-green)
        if (replayWindow) {
          drawPath(traceA, COLORS.acidGreen, 2.5, replayWindow.start_idx, replayWindow.end_idx);
        }

        // Lap B replay window (red)
        if (traceB && replayWindow) {
          // Use same window indices, clamped to trace B length
          const startB = Math.min(replayWindow.start_idx, traceB.lat.length - 1);
          const endB = Math.min(replayWindow.end_idx, traceB.lat.length - 1);
          drawPath(traceB, COLORS.safetyRed, 2.5, startB, endB);
        }

        // Position dots
        drawPositionDot(traceA, frame, COLORS.acidGreen, 6);
        if (traceB) {
          drawPositionDot(traceB, frame, COLORS.safetyRed, 6);
        }

        // Delta badge
        if (traceB && replayWindow) {
          const fiA = clampFrame(frame, traceA);
          const fiB = clampFrame(frame, traceB);

          // Compute time delta heuristic: difference in distance covered at same frame
          // Positive = B ahead, Negative = A ahead
          const distA = fiA < traceA.dist_m.length ? traceA.dist_m[fiA] : 0;
          const distB = fiB < traceB.dist_m.length ? traceB.dist_m[fiB] : 0;
          const speedA = fiA < traceA.speed_mps.length ? traceA.speed_mps[fiA] : 1;
          const avgSpeed = Math.max(speedA, 0.1);
          const deltaDist = distA - distB;
          const deltaTime = deltaDist / avgSpeed;

          const cx = toX(traceA.lon[fiA]);
          const cy = toY(traceA.lat[fiA]);

          if (Number.isFinite(cx) && Number.isFinite(cy) && Number.isFinite(deltaTime)) {
            const sign = deltaTime > 0 ? '+' : '';
            const label = `${sign}${deltaTime.toFixed(2)}s`;
            const tw = ctx.measureText(label).width;

            ctx.font = 'bold 11px "IBM Plex Mono", monospace';
            const badgeW = tw + 16;
            const badgeH = 20;
            const bx = cx + 14;
            const by = cy - 20;

            // Badge background
            ctx.fillStyle = COLORS.asphalt + 'DD';
            ctx.beginPath();
            const r = 4;
            ctx.moveTo(bx + r, by);
            ctx.lineTo(bx + badgeW - r, by);
            ctx.arcTo(bx + badgeW, by, bx + badgeW, by + r, safeRadius(r));
            ctx.lineTo(bx + badgeW, by + badgeH - r);
            ctx.arcTo(bx + badgeW, by + badgeH, bx + badgeW - r, by + badgeH, safeRadius(r));
            ctx.lineTo(bx + r, by + badgeH);
            ctx.arcTo(bx, by + badgeH, bx, by + badgeH - r, safeRadius(r));
            ctx.lineTo(bx, by + r);
            ctx.arcTo(bx, by, bx + r, by, safeRadius(r));
            ctx.closePath();
            ctx.fill();
            ctx.strokeStyle = deltaTime > 0 ? COLORS.safetyRed : COLORS.acidGreen;
            ctx.lineWidth = 1;
            ctx.stroke();

            // Badge text
            ctx.fillStyle = deltaTime > 0 ? COLORS.safetyRed : COLORS.acidGreen;
            ctx.font = 'bold 11px "IBM Plex Mono", monospace';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(label, bx + badgeW / 2, by + badgeH / 2);
          }
        }
      }

      /* ── TOP 3 MODE ────────────────────────────────────────────────── */
      if (mode === 'top3') {
        // Full track outline (gray) — use trace A
        drawPath(traceA, 'rgba(138, 143, 152, 0.25)', 2);

        const top3 = pickTop3Laps(traces);

        for (const { key, color } of top3) {
          const t = traces[key];
          if (!t || t.lat.length < 2) continue;

          // Draw trace path
          drawPath(t, color, 2);

          // Position dot
          drawPositionDot(t, frame, color, 5);

          // Label
          const fi = clampFrame(frame, t);
          const px = toX(t.lon[fi]);
          const py = toY(t.lat[fi]);
          drawLabel(px, py, `L${key}`, color, 10, -16);
        }
      }

      /* ── Hover point highlight ─────────────────────────────────────── */
      if (hover) {
        const pts = screenPtsRef.current;
        let nearest = -1;
        let bestDist = Infinity;
        for (let i = 0; i < pts.length; i++) {
          const d = (pts[i].x - hover.x) ** 2 + (pts[i].y - hover.y) ** 2;
          if (d < bestDist) {
            bestDist = d;
            nearest = i;
          }
        }
        if (nearest >= 0 && bestDist < 625) {
          const pt = pts[nearest];
          if (Number.isFinite(pt.x) && Number.isFinite(pt.y)) {
            ctx.beginPath();
            ctx.arc(pt.x, pt.y, safeRadius(6), 0, Math.PI * 2);
            ctx.fillStyle = COLORS.chalk + '88';
            ctx.fill();
            ctx.strokeStyle = COLORS.chalk;
            ctx.lineWidth = 1.5;
            ctx.stroke();
          }
        }
      }

      /* ── Scale indicator ───────────────────────────────────────────── */
      const metersPerPx = (latRange * 111_320) / (latRange * scale);
      const scaleBarLen = 50;
      const scaleMeters = Math.round(scaleBarLen * metersPerPx);
      if (Number.isFinite(scaleMeters) && Number.isFinite(metersPerPx)) {
        ctx.strokeStyle = COLORS.steel;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(w - pad - scaleBarLen, h - 10);
        ctx.lineTo(w - pad, h - 10);
        ctx.stroke();
        // Tick marks
        ctx.beginPath();
        ctx.moveTo(w - pad - scaleBarLen, h - 13);
        ctx.lineTo(w - pad - scaleBarLen, h - 7);
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(w - pad, h - 13);
        ctx.lineTo(w - pad, h - 7);
        ctx.stroke();
        // Label
        ctx.fillStyle = COLORS.steel;
        ctx.font = '9px "IBM Plex Mono", monospace';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'bottom';
        ctx.fillText(`~${scaleMeters}m`, w - pad - scaleBarLen / 2, h - 14);
      }

      /* ── Zoom indicator ────────────────────────────────────────────── */
      if (zoom !== 1) {
        ctx.fillStyle = COLORS.steel;
        ctx.font = '9px "IBM Plex Mono", monospace';
        ctx.textAlign = 'left';
        ctx.textBaseline = 'top';
        ctx.fillText(`${zoom.toFixed(1)}x`, pad + 4, h - pad + 4);
      }
    },
    [traces, corners, cornerIndex, lapA, lapB, frame, mode, replayWindow, zoom, panX, panY],
  );

  /* ── Tooltip data callback ─────────────────────────────────────────── */
  const getTooltipData = useCallback(
    (hover: HoverPoint): TooltipData | null => {
      const pts = screenPtsRef.current;
      if (pts.length === 0) return null;
      let nearest = -1;
      let bestDist = Infinity;
      for (let i = 0; i < pts.length; i++) {
        const d = (pts[i].x - hover.x) ** 2 + (pts[i].y - hover.y) ** 2;
        if (d < bestDist) {
          bestDist = d;
          nearest = i;
        }
      }
      if (nearest < 0 || bestDist > 625) return null;
      const pt = pts[nearest];
      const traceA = traces[String(lapA)];
      const speed = traceA && nearest < traceA.speed_mps.length
        ? (traceA.speed_mps[nearest] * 3.6).toFixed(1) + ' km/h'
        : '—';
      return {
        header: `Point ${nearest + 1} / ${pts.length}`,
        lines: [
          { label: 'Lat', value: pt.lat.toFixed(6), color: COLORS.chalk },
          { label: 'Lon', value: pt.lon.toFixed(6), color: COLORS.chalk },
          { label: 'Speed', value: speed, color: COLORS.acidGreen },
        ],
      };
    },
    [traces, lapA],
  );

  /* ── Interactive canvas hook ───────────────────────────────────────── */
  const { canvasRef, containerRef, tooltip } = useInteractiveCanvas({
    draw,
    deps: [traces, corners, cornerIndex, lapA, lapB, frame, mode, replayWindow, zoom, panX, panY],
    padding: PAD,
    getTooltipData,
  });

  /* ── Wheel event for zoom ──────────────────────────────────────────── */
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const handleWheel = (e: WheelEvent) => {
      e.preventDefault();
      setZoom((prev) => {
        const factor = e.deltaY < 0 ? 1.1 : 0.9;
        return Math.max(0.5, Math.min(5, prev * factor));
      });
    };

    canvas.addEventListener('wheel', handleWheel, { passive: false });
    return () => canvas.removeEventListener('wheel', handleWheel);
  }, [canvasRef]);

  /* ── Double-click to reset zoom/pan ────────────────────────────────── */
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const handleDblClick = () => {
      setZoom(1);
      setPanX(0);
      setPanY(0);
    };

    canvas.addEventListener('dblclick', handleDblClick);
    return () => canvas.removeEventListener('dblclick', handleDblClick);
  }, [canvasRef]);

  /* ── Mouse drag for pan ────────────────────────────────────────────── */
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const handleMouseDown = (e: MouseEvent) => {
      // Only pan on middle-click or when shift is held for left-click
      if (e.button === 1 || (e.button === 0 && e.shiftKey)) {
        e.preventDefault();
        dragRef.current = { dragging: true, lastX: e.clientX, lastY: e.clientY };
      }
    };

    const handleMouseMove = (e: MouseEvent) => {
      if (!dragRef.current.dragging) return;
      const dx = e.clientX - dragRef.current.lastX;
      const dy = e.clientY - dragRef.current.lastY;
      dragRef.current.lastX = e.clientX;
      dragRef.current.lastY = e.clientY;
      setPanX((prev) => prev + dx);
      setPanY((prev) => prev + dy);
    };

    const handleMouseUp = () => {
      dragRef.current.dragging = false;
    };

    canvas.addEventListener('mousedown', handleMouseDown);
    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);

    return () => {
      canvas.removeEventListener('mousedown', handleMouseDown);
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [canvasRef]);

  /* ── Mode label ────────────────────────────────────────────────────── */
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
      {zoom !== 1 && (
        <div className="absolute top-3 right-3 z-10 pointer-events-none">
          <span className="text-steel/60 font-telemetry text-[9px]">
            dbl-click to reset
          </span>
        </div>
      )}
      <canvas ref={canvasRef} className="w-full h-full" />
      <ChartTooltip tooltip={tooltip} />
    </div>
  );
}
