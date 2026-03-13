/**
 * LiveFrictionCircle.tsx — Enhanced G-G diagram with driver-input coloring.
 *
 * Scatter dots are colored by driver input:
 *   - Green: throttle > 20%
 *   - Red: brake > 5%
 *   - Yellow: throttle+brake overlap (left-foot braking)
 *   - Blue: coast (neither throttle nor brake)
 *
 * Hover sync: when hovering another chart at distance D, the corresponding
 * dot on this diagram is highlighted with a larger marker.
 */
'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { apiFetch } from '@/lib/api-client';
import { useChartHoverStore } from '@/lib/chart-hover-store';

interface GGData {
  distances: number[];
  accel_lat: number[];
  accel_long: number[];
}

interface PedalData {
  distances: number[];
  throttle: number[];
  brake: number[];
}

interface LiveFrictionCircleProps {
  sessionId: string;
  gpsLaps: number[];
  bestLap: number | null;
  className?: string;
  controlledLap?: boolean;
}

const COLORS = {
  throttle: '#22c55e',  // green
  brake: '#ef4444',     // red
  overlap: '#eab308',   // yellow
  coast: '#3b82f6',     // blue
  bg: '#1a1a2e',
  grid: 'rgba(255,255,255,0.08)',
  text: '#e0e0e0',
  textDim: 'rgba(255,255,255,0.4)',
  circle: 'rgba(255,255,255,0.15)',
  highlight: '#ffffff',
};

export function LiveFrictionCircle({
  sessionId,
  gpsLaps,
  bestLap,
  className = '',
  controlledLap = false,
}: LiveFrictionCircleProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const ggRef = useRef<GGData | null>(null);
  const pedalRef = useRef<PedalData | null>(null);

  const [selectedLap, setSelectedLap] = useState(bestLap ?? gpsLaps[0] ?? 0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (controlledLap && bestLap != null) setSelectedLap(bestLap);
  }, [controlledLap, bestLap]);

  // ── Fetch data ──────────────────────────────────────────────
  const fetchData = useCallback(async () => {
    if (!selectedLap) return;
    setLoading(true);
    setError(null);
    try {
      const [gg, pedals] = await Promise.all([
        apiFetch<(GGData & { available: boolean }) | { available: false }>(
          `/sessions/${encodeURIComponent(sessionId)}/gg-data?lap=${selectedLap}`,
        ),
        apiFetch<(PedalData & { available: boolean }) | { available: false }>(
          `/sessions/${encodeURIComponent(sessionId)}/pedals?lap=${selectedLap}`,
        ).catch(() => ({ available: false as const })),
      ]);

      if ('accel_lat' in gg && gg.available !== false) {
        ggRef.current = gg as GGData;
      } else {
        ggRef.current = null;
        setError('No G-G data available');
      }

      if ('throttle' in pedals && pedals.available !== false) {
        pedalRef.current = pedals as PedalData;
      } else {
        pedalRef.current = null;
      }
    } catch (err) {
      ggRef.current = null;
      pedalRef.current = null;
      setError(err instanceof Error ? err.message : 'Failed to load data');
    } finally {
      setLoading(false);
    }
  }, [sessionId, selectedLap]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // ── Classify point input ────────────────────────────────────
  const classifyInput = useCallback(
    (idx: number): string => {
      const pedals = pedalRef.current;
      if (!pedals) return COLORS.coast;
      const t = pedals.throttle[idx] ?? 0;
      const b = pedals.brake[idx] ?? 0;
      if (t > 20 && b > 5) return COLORS.overlap;
      if (b > 5) return COLORS.brake;
      if (t > 20) return COLORS.throttle;
      return COLORS.coast;
    },
    [],
  );

  // ── Draw ────────────────────────────────────────────────────
  const draw = useCallback(
    (hoverDist: number | null = null) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const gg = ggRef.current;
      const ctx = canvas.getContext('2d');
      if (!ctx) return;

      const container = containerRef.current;
      const w = container?.clientWidth ?? 400;
      const h = Math.min(w, 400);
      const dpr = window.devicePixelRatio || 1;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      ctx.scale(dpr, dpr);

      // Background
      ctx.fillStyle = COLORS.bg;
      ctx.fillRect(0, 0, w, h);

      if (!gg || gg.accel_lat.length === 0) {
        ctx.fillStyle = COLORS.textDim;
        ctx.font = '14px monospace';
        ctx.textAlign = 'center';
        ctx.fillText('No G-G data', w / 2, h / 2);
        return;
      }

      // Plot area (square, centered)
      const pad = 50;
      const plotSize = Math.min(w - pad * 2, h - pad * 2);
      const cx = w / 2;
      const cy = h / 2;

      // Compute data bounds (symmetric)
      let maxLat = 0.1;
      for (let i = 0; i < gg.accel_lat.length; i++) { const a = Math.abs(gg.accel_lat[i]); if (a > maxLat) maxLat = a; }
      let maxLong = 0.1;
      for (let i = 0; i < gg.accel_long.length; i++) { const a = Math.abs(gg.accel_long[i]); if (a > maxLong) maxLong = a; }
      const maxG = Math.ceil(Math.max(maxLat, maxLong) * 2) / 2;

      const scale = plotSize / 2 / maxG;

      // Grid circles
      ctx.strokeStyle = COLORS.circle;
      ctx.lineWidth = 1;
      for (let g = 0.5; g <= maxG; g += 0.5) {
        const r = g * scale;
        ctx.beginPath();
        ctx.arc(cx, cy, r, 0, Math.PI * 2);
        ctx.stroke();
        // Label
        ctx.fillStyle = COLORS.textDim;
        ctx.font = '10px monospace';
        ctx.textAlign = 'left';
        ctx.fillText(`${g.toFixed(1)}G`, cx + r + 2, cy - 2);
      }

      // Axes
      ctx.strokeStyle = COLORS.grid;
      ctx.beginPath();
      ctx.moveTo(cx - plotSize / 2, cy);
      ctx.lineTo(cx + plotSize / 2, cy);
      ctx.moveTo(cx, cy - plotSize / 2);
      ctx.lineTo(cx, cy + plotSize / 2);
      ctx.stroke();

      // Axis labels
      ctx.fillStyle = COLORS.text;
      ctx.font = '11px monospace';
      ctx.textAlign = 'center';
      ctx.fillText('Lateral (G)', cx, h - 8);
      ctx.save();
      ctx.translate(12, cy);
      ctx.rotate(-Math.PI / 2);
      ctx.fillText('Longitudinal (G)', 0, 0);
      ctx.restore();

      // Find closest index to hover distance
      let highlightIdx = -1;
      if (hoverDist !== null && gg.distances) {
        let bestDiff = Infinity;
        for (let i = 0; i < gg.distances.length; i++) {
          const diff = Math.abs(gg.distances[i] - hoverDist);
          if (diff < bestDiff) {
            bestDiff = diff;
            highlightIdx = i;
          }
        }
      }

      // Scatter dots
      const n = Math.min(gg.accel_lat.length, gg.accel_long.length);
      for (let i = 0; i < n; i++) {
        const lat = gg.accel_lat[i];
        const lng = gg.accel_long[i];
        if (lat == null || lng == null || isNaN(lat) || isNaN(lng)) continue;

        const x = cx + lat * scale;
        const y = cy - lng * scale; // flip Y: positive accel = up

        const isHighlight = i === highlightIdx;
        const color = classifyInput(i);

        ctx.fillStyle = color;
        ctx.globalAlpha = isHighlight ? 1.0 : 0.4;
        ctx.beginPath();
        ctx.arc(x, y, isHighlight ? 6 : 2, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.globalAlpha = 1.0;

      // Highlight tooltip
      if (highlightIdx >= 0) {
        const lat = gg.accel_lat[highlightIdx];
        const lng = gg.accel_long[highlightIdx];
        if (lat != null && lng != null) {
          ctx.fillStyle = 'rgba(0,0,0,0.8)';
          const txt = `Lat: ${lat.toFixed(2)}G  Long: ${lng.toFixed(2)}G`;
          ctx.font = '11px monospace';
          const tw = ctx.measureText(txt).width;
          const tx = Math.min(w - tw - 12, cx + lat * scale + 10);
          const ty = Math.max(20, cy - lng * scale - 10);
          ctx.fillRect(tx - 4, ty - 12, tw + 8, 16);
          ctx.fillStyle = COLORS.highlight;
          ctx.fillText(txt, tx, ty);
        }
      }

      // Legend
      const legend = [
        { color: COLORS.throttle, label: 'Throttle' },
        { color: COLORS.brake, label: 'Brake' },
        { color: COLORS.overlap, label: 'Overlap' },
        { color: COLORS.coast, label: 'Coast' },
      ];
      ctx.font = '10px monospace';
      let lx = w - 90;
      let ly = 16;
      for (const { color, label } of legend) {
        ctx.fillStyle = color;
        ctx.fillRect(lx, ly - 6, 8, 8);
        ctx.fillStyle = COLORS.text;
        ctx.textAlign = 'left';
        ctx.fillText(label, lx + 12, ly);
        ly += 14;
      }
    },
    [classifyInput],
  );

  // ── Effect: redraw on data change ───────────────────────────
  useEffect(() => {
    if (!loading) draw(null);
  }, [loading, draw]);

  // ── Hover sync subscription ─────────────────────────────────
  useEffect(() => {
    const unsubscribe = useChartHoverStore.subscribe((state) => {
      if (state.hoverSource !== 'friction-circle') {
        draw(state.hoverDistance);
      }
    });
    return () => unsubscribe();
  }, [draw]);

  // ── Resize observer ─────────────────────────────────────────
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const ro = new ResizeObserver(() => draw(useChartHoverStore.getState().hoverDistance));
    ro.observe(container);
    return () => ro.disconnect();
  }, [draw]);

  // ── Mouse interaction ───────────────────────────────────────
  const handleMouseMove = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const canvas = canvasRef.current;
      const gg = ggRef.current;
      if (!canvas || !gg || !gg.distances) return;

      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;

      // Find closest point to mouse
      const w = rect.width;
      const h = rect.height;
      const cx = w / 2;
      const cy = h / 2;
      const pad = 50;
      const plotSize = Math.min(w - pad * 2, h - pad * 2);
      let maxLat = 0.1;
      for (let i = 0; i < gg.accel_lat.length; i++) { const a = Math.abs(gg.accel_lat[i]); if (a > maxLat) maxLat = a; }
      let maxLong = 0.1;
      for (let i = 0; i < gg.accel_long.length; i++) { const a = Math.abs(gg.accel_long[i]); if (a > maxLong) maxLong = a; }
      const maxG = Math.ceil(Math.max(maxLat, maxLong) * 2) / 2;
      const scale = plotSize / 2 / maxG;

      let bestDist = Infinity;
      let bestIdx = -1;
      const n = Math.min(gg.accel_lat.length, gg.accel_long.length);
      for (let i = 0; i < n; i++) {
        const x = cx + gg.accel_lat[i] * scale;
        const y = cy - gg.accel_long[i] * scale;
        const d = Math.hypot(mx - x, my - y);
        if (d < bestDist) {
          bestDist = d;
          bestIdx = i;
        }
      }

      if (bestIdx >= 0 && bestDist < 20) {
        const dist = gg.distances[bestIdx];
        useChartHoverStore.getState().setHover(dist, 'friction-circle');
        draw(dist);
      }
    },
    [draw],
  );

  const handleMouseLeave = useCallback(() => {
    useChartHoverStore.getState().clearHover();
    draw(null);
  }, [draw]);

  return (
    <div ref={containerRef} className={className} role="img" aria-label="Live friction circle showing real-time G-force utilization">
      <div className="flex items-center gap-3 mb-2">
        {!controlledLap && <select
          value={selectedLap}
          onChange={(e) => setSelectedLap(Number(e.target.value))}
          className="bg-concrete border border-steel/20 text-chalk text-xs rounded px-2 py-1"
        >
          {gpsLaps.map((lap) => (
            <option key={lap} value={lap}>
              Lap {lap}
              {lap === bestLap ? ' (best)' : ''}
            </option>
          ))}
        </select>}
        {loading && <span className="text-xs text-steel/60">Loading...</span>}
      </div>
      {error ? (
        <div className="text-steel/60 text-sm text-center p-6">
          <p>{error}</p>
        </div>
      ) : (
        <canvas
          ref={canvasRef}
          onMouseMove={handleMouseMove}
          onMouseLeave={handleMouseLeave}
          className="w-full cursor-crosshair"
        />
      )}
    </div>
  );
}
