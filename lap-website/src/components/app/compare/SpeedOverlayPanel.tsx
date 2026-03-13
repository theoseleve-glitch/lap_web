'use client';

import { useEffect, useState, useRef, useCallback } from 'react';
import { api } from '@/lib/api-client';
import { useChartHoverStore } from '@/lib/chart-hover-store';

interface SpeedOverlayData {
  distances: number[];
  speeds_a: number[];
  speeds_b: number[];
  delta_s: number[];
  session_a: { session_id: string; best_time_s: number | null; lap_number: number };
  session_b: { session_id: string; best_time_s: number | null; lap_number: number };
}

export default function SpeedOverlayPanel({
  sessionAId,
  sessionBId,
  colorA,
  colorB,
}: {
  sessionAId: string;
  sessionBId: string;
  colorA: string;
  colorB: string;
}) {
  const speedCanvasRef = useRef<HTMLCanvasElement>(null);
  const deltaCanvasRef = useRef<HTMLCanvasElement>(null);
  const [overlay, setOverlay] = useState<SpeedOverlayData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const setHover = useChartHoverStore((s) => s.setHover);
  const clearHover = useChartHoverStore((s) => s.clearHover);

  // Keep a ref to the overlay data for mousemove calculations without re-binding
  const overlayRef = useRef<SpeedOverlayData | null>(null);
  overlayRef.current = overlay;

  // Fetch overlay data
  useEffect(() => {
    if (!sessionAId || !sessionBId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);

    api
      .get<SpeedOverlayData>(
        `/sessions/${encodeURIComponent(sessionAId)}/compare?sessionKeyB=${encodeURIComponent(sessionBId)}`,
      )
      .then((data) => {
        if (!cancelled) setOverlay(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load speed overlay');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [sessionAId, sessionBId]);

  // Draw speed traces
  const drawCharts = useCallback(() => {
    if (!overlay || !speedCanvasRef.current || !deltaCanvasRef.current) return;

    const { distances, speeds_a, speeds_b, delta_s } = overlay;
    if (distances.length === 0) return;

    drawSpeedCanvas(speedCanvasRef.current, distances, speeds_a, speeds_b, colorA, colorB);
    drawDeltaCanvas(deltaCanvasRef.current, distances, delta_s, colorA, colorB);
  }, [overlay, colorA, colorB]);

  useEffect(() => { drawCharts(); }, [drawCharts]);

  useEffect(() => {
    const s = speedCanvasRef.current;
    const d = deltaCanvasRef.current;
    if (!s || !d) return;
    const ro = new ResizeObserver(() => drawCharts());
    ro.observe(s);
    ro.observe(d);
    return () => ro.disconnect();
  }, [drawCharts]);

  // Hover handlers
  const handleMouseMove = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = speedCanvasRef.current;
    const data = overlayRef.current;
    if (!canvas || !data || data.distances.length === 0) return;

    const rect = canvas.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const pad = { left: 50, right: 15 };
    const cW = rect.width - pad.left - pad.right;
    const maxDist = data.distances[data.distances.length - 1];

    const fraction = (mouseX - pad.left) / cW;
    if (fraction < 0 || fraction > 1) return;

    const distance = fraction * maxDist;
    setHover(distance, 'speed-overlay');
  }, [setHover]);

  const handleMouseLeave = useCallback(() => {
    clearHover();
  }, [clearHover]);

  if (loading) {
    return (
      <div className="bg-zinc-900 rounded-lg p-4 flex items-center justify-center py-12">
        <div className="w-5 h-5 border-2 border-acid-green border-t-transparent rounded-full animate-spin mr-3" />
        <p className="text-zinc-500 text-sm">Loading speed overlay...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-zinc-900 rounded-lg p-4">
        <h3 className="text-sm font-medium text-zinc-300 mb-2">Speed Overlay</h3>
        <p className="text-zinc-500 text-sm">{error}</p>
      </div>
    );
  }

  if (!overlay) return null;

  return (
    <div className="bg-zinc-900 rounded-lg p-4">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-medium text-zinc-300">Speed Overlay</h3>
        <div className="flex items-center gap-4 text-xs font-body">
          <span className="flex items-center gap-1.5">
            <span className="w-3 h-0.5 rounded" style={{ backgroundColor: colorA }} />
            <span style={{ color: colorA }}>Session A (Lap {overlay.session_a.lap_number})</span>
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-3 h-0.5 rounded" style={{ backgroundColor: colorB }} />
            <span style={{ color: colorB }}>Session B (Lap {overlay.session_b.lap_number})</span>
          </span>
        </div>
      </div>

      {/* Speed chart */}
      <div className="relative rounded-lg overflow-hidden bg-asphalt">
        <canvas
          ref={speedCanvasRef}
          onMouseMove={handleMouseMove}
          onMouseLeave={handleMouseLeave}
          style={{ width: '100%', height: '220px', display: 'block' }}
        />
      </div>

      {/* Delta chart */}
      <div className="mt-2 relative rounded-lg overflow-hidden bg-asphalt">
        <canvas
          ref={deltaCanvasRef}
          style={{ width: '100%', height: '80px', display: 'block' }}
        />
      </div>

      <p className="text-xs text-steel/50 font-body mt-2 text-center">
        Distance (m) -- Delta: negative = Session A faster, positive = Session B faster
      </p>
    </div>
  );
}

// Loop-based min/max — Math.min(...arr) overflows the call stack with 5000+ GPS points
function minOf(arr: number[]): number {
  let v = Infinity;
  for (let i = 0; i < arr.length; i++) if (arr[i] < v) v = arr[i];
  return v;
}
function maxOf(arr: number[]): number {
  let v = -Infinity;
  for (let i = 0; i < arr.length; i++) if (arr[i] > v) v = arr[i];
  return v;
}

/** Draw overlaid speed traces on canvas */
function drawSpeedCanvas(
  canvas: HTMLCanvasElement,
  distances: number[],
  speedsA: number[],
  speedsB: number[],
  colorA: string,
  colorB: string,
) {
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  if (rect.width === 0 || rect.height === 0) return;
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  ctx.scale(dpr, dpr);
  const W = rect.width;
  const H = rect.height;

  ctx.clearRect(0, 0, W, H);

  const pad = { top: 20, right: 15, bottom: 30, left: 50 };
  const cW = W - pad.left - pad.right;
  const cH = H - pad.top - pad.bottom;

  const maxDist = distances[distances.length - 1] || 1;
  const allSpeeds = [...speedsA, ...speedsB];
  const maxSpeed = maxOf(allSpeeds) * 3.6;
  const minSpeed = Math.max(0, minOf(allSpeeds) * 3.6 - 5);
  const speedRange = maxSpeed - minSpeed || 1;

  const xScale = (d: number) => pad.left + (d / maxDist) * cW;
  const yScale = (s: number) => pad.top + cH - ((s * 3.6 - minSpeed) / speedRange) * cH;

  // Grid
  ctx.strokeStyle = 'rgba(255,255,255,0.06)';
  ctx.lineWidth = 1;
  const nGridY = 5;
  for (let i = 0; i <= nGridY; i++) {
    const y = pad.top + (i / nGridY) * cH;
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(W - pad.right, y);
    ctx.stroke();
  }

  // Y-axis labels
  ctx.fillStyle = 'rgba(255,255,255,0.4)';
  ctx.font = '10px monospace';
  ctx.textAlign = 'right';
  for (let i = 0; i <= nGridY; i++) {
    const val = maxSpeed - (i / nGridY) * speedRange;
    const y = pad.top + (i / nGridY) * cH;
    ctx.fillText(`${val.toFixed(0)}`, pad.left - 5, y + 3);
  }

  // X-axis labels
  ctx.textAlign = 'center';
  const nGridX = 5;
  for (let i = 0; i <= nGridX; i++) {
    const d = (i / nGridX) * maxDist;
    ctx.fillText(`${d.toFixed(0)}`, xScale(d), H - pad.bottom + 18);
  }

  // Y-axis title
  ctx.save();
  ctx.translate(12, pad.top + cH / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.textAlign = 'center';
  ctx.fillStyle = 'rgba(255,255,255,0.3)';
  ctx.font = '10px sans-serif';
  ctx.fillText('km/h', 0, 0);
  ctx.restore();

  // Speed trace A
  ctx.strokeStyle = colorA;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  for (let i = 0; i < distances.length; i++) {
    const x = xScale(distances[i]);
    const y = yScale(speedsA[i]);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }
  ctx.stroke();

  // Speed trace B
  ctx.strokeStyle = colorB;
  ctx.beginPath();
  for (let i = 0; i < distances.length; i++) {
    const x = xScale(distances[i]);
    const y = yScale(speedsB[i]);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }
  ctx.stroke();
}

/** Draw cumulative time delta on canvas */
function drawDeltaCanvas(
  canvas: HTMLCanvasElement,
  distances: number[],
  delta: number[],
  colorA: string,
  colorB: string,
) {
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  if (rect.width === 0 || rect.height === 0) return;
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  ctx.scale(dpr, dpr);
  const W = rect.width;
  const H = rect.height;

  ctx.clearRect(0, 0, W, H);

  const pad = { top: 5, right: 15, bottom: 15, left: 50 };
  const cW = W - pad.left - pad.right;
  const cH = H - pad.top - pad.bottom;

  const maxDist = distances[distances.length - 1];
  let absMax = 0.01;
  for (let i = 0; i < delta.length; i++) {
    const a = Math.abs(delta[i]);
    if (a > absMax) absMax = a;
  }

  const xScale = (d: number) => pad.left + (d / maxDist) * cW;
  const yScale = (d: number) => pad.top + cH / 2 - (d / absMax) * (cH / 2);

  // Zero line
  ctx.strokeStyle = 'rgba(255,255,255,0.15)';
  ctx.lineWidth = 1;
  ctx.beginPath();
  const zeroY = pad.top + cH / 2;
  ctx.moveTo(pad.left, zeroY);
  ctx.lineTo(W - pad.right, zeroY);
  ctx.stroke();

  // Delta fill -- green below zero (A faster), red above (B faster)
  for (let i = 1; i < distances.length; i++) {
    const x0 = xScale(distances[i - 1]);
    const x1 = xScale(distances[i]);
    const y0 = yScale(delta[i - 1]);
    const y1 = yScale(delta[i]);
    const isAbove = delta[i] >= 0;
    ctx.fillStyle = isAbove ? colorB + '30' : colorA + '30';
    ctx.beginPath();
    ctx.moveTo(x0, zeroY);
    ctx.lineTo(x0, y0);
    ctx.lineTo(x1, y1);
    ctx.lineTo(x1, zeroY);
    ctx.closePath();
    ctx.fill();
  }

  // Delta line
  ctx.strokeStyle = '#e6edf3';
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let i = 0; i < distances.length; i++) {
    const x = xScale(distances[i]);
    const y = yScale(delta[i]);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }
  ctx.stroke();

  // Y-axis labels
  ctx.fillStyle = 'rgba(255,255,255,0.4)';
  ctx.font = '9px monospace';
  ctx.textAlign = 'right';
  ctx.fillText(`+${absMax.toFixed(2)}s`, pad.left - 5, pad.top + 8);
  ctx.fillText(`-${absMax.toFixed(2)}s`, pad.left - 5, H - pad.bottom);
  ctx.fillText('0', pad.left - 5, zeroY + 3);
}
