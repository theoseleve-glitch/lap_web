'use client';

import { useEffect, useState, useRef, useCallback } from 'react';
import { api } from '@/lib/api-client';
import { useChartHoverStore } from '@/lib/chart-hover-store';

interface GpsOverlayData {
  distances: number[];
  gps_a: { latitudes: number[]; longitudes: number[] };
  gps_b: { latitudes: number[]; longitudes: number[] };
}

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

export default function GpsOverlayPanel({
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
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [data, setData] = useState<GpsOverlayData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const hoverDistance = useChartHoverStore((s) => s.hoverDistance);
  const hoverSource = useChartHoverStore((s) => s.hoverSource);

  // Keep data in a ref for draw calls driven by hover changes
  const dataRef = useRef<GpsOverlayData | null>(null);
  dataRef.current = data;

  // Fetch overlay data (reuses the same endpoint as speed overlay)
  useEffect(() => {
    if (!sessionAId || !sessionBId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);

    api
      .get<GpsOverlayData>(
        `/sessions/${encodeURIComponent(sessionAId)}/compare?sessionKeyB=${encodeURIComponent(sessionBId)}`,
      )
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load GPS overlay');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [sessionAId, sessionBId]);

  // Draw function
  const draw = useCallback(
    (activeDistance: number | null) => {
      const canvas = canvasRef.current;
      const d = dataRef.current;
      if (!canvas || !d) return;
      if (!d.gps_a || !d.gps_b) return;
      if (d.gps_a.latitudes.length === 0 && d.gps_b.latitudes.length === 0) return;

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

      const padding = 30;

      // Gather all lat/lon to compute bounds (loop instead of Math.min/max
      // spread — spread overflows the call stack with 5000+ GPS points)
      const allLat = [...d.gps_a.latitudes, ...d.gps_b.latitudes];
      const allLon = [...d.gps_a.longitudes, ...d.gps_b.longitudes];
      const minLat = minOf(allLat);
      const maxLat = maxOf(allLat);
      const minLon = minOf(allLon);
      const maxLon = maxOf(allLon);

      const latRange = maxLat - minLat || 1e-6;
      const lonRange = maxLon - minLon || 1e-6;

      // Scale to fit canvas with uniform aspect
      const drawW = W - 2 * padding;
      const drawH = H - 2 * padding;
      const scaleX = drawW / lonRange;
      const scaleY = drawH / latRange;
      const scale = Math.min(scaleX, scaleY);

      const offsetX = padding + (drawW - lonRange * scale) / 2;
      const offsetY = padding + (drawH - latRange * scale) / 2;

      const toX = (lon: number) => offsetX + (lon - minLon) * scale;
      // Invert Y so north is up
      const toY = (lat: number) => offsetY + (maxLat - lat) * scale;

      // Draw trace helper
      const drawTrace = (
        lats: number[],
        lons: number[],
        color: string,
      ) => {
        if (lats.length === 0) return;
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.globalAlpha = 0.8;
        ctx.beginPath();
        for (let i = 0; i < lats.length; i++) {
          const x = toX(lons[i]);
          const y = toY(lats[i]);
          if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.stroke();
        ctx.globalAlpha = 1;
      };

      // Draw both traces
      drawTrace(d.gps_a.latitudes, d.gps_a.longitudes, colorA);
      drawTrace(d.gps_b.latitudes, d.gps_b.longitudes, colorB);

      // Draw hover markers if we have a distance and the distances array
      if (activeDistance != null && d.distances && d.distances.length > 0) {
        // Find closest distance index
        let closestIdx = 0;
        let closestDiff = Math.abs(d.distances[0] - activeDistance);
        for (let i = 1; i < d.distances.length; i++) {
          const diff = Math.abs(d.distances[i] - activeDistance);
          if (diff < closestDiff) {
            closestDiff = diff;
            closestIdx = i;
          }
        }

        // Draw marker on trace A
        if (closestIdx < d.gps_a.latitudes.length) {
          const ax = toX(d.gps_a.longitudes[closestIdx]);
          const ay = toY(d.gps_a.latitudes[closestIdx]);
          ctx.fillStyle = colorA;
          ctx.beginPath();
          ctx.arc(ax, ay, 5, 0, Math.PI * 2);
          ctx.fill();
          ctx.strokeStyle = '#fff';
          ctx.lineWidth = 1.5;
          ctx.stroke();
        }

        // Draw marker on trace B
        if (closestIdx < d.gps_b.latitudes.length) {
          const bx = toX(d.gps_b.longitudes[closestIdx]);
          const by = toY(d.gps_b.latitudes[closestIdx]);
          ctx.fillStyle = colorB;
          ctx.beginPath();
          ctx.arc(bx, by, 5, 0, Math.PI * 2);
          ctx.fill();
          ctx.strokeStyle = '#fff';
          ctx.lineWidth = 1.5;
          ctx.stroke();
        }
      }
    },
    [colorA, colorB],
  );

  // Redraw on data or draw-function change (NOT hover — that's separate)
  useEffect(() => {
    if (data) draw(useChartHoverStore.getState().hoverDistance);
  }, [data, draw]);

  // Redraw on hover change (only when source is not us)
  useEffect(() => {
    if (data && hoverSource !== 'gps-overlay') {
      draw(hoverDistance);
    }
  }, [hoverDistance, hoverSource, data, draw]);

  // Stable resize observer — uses render ref to avoid churn on hover
  const drawRef = useRef<(d: number | null) => void>(draw);
  drawRef.current = draw;

  useEffect(() => {
    const c = canvasRef.current;
    if (!c) return;
    const ro = new ResizeObserver(() => {
      if (dataRef.current) drawRef.current(useChartHoverStore.getState().hoverDistance);
    });
    ro.observe(c);
    return () => ro.disconnect();
  }, []);

  if (loading) {
    return (
      <div className="bg-zinc-900 rounded-lg p-4 flex items-center justify-center py-12">
        <div className="w-5 h-5 border-2 border-acid-green border-t-transparent rounded-full animate-spin mr-3" />
        <p className="text-zinc-500 text-sm">Loading GPS overlay...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-zinc-900 rounded-lg p-4">
        <h3 className="text-sm font-medium text-zinc-300 mb-2">GPS Overlay</h3>
        <p className="text-zinc-500 text-sm">{error}</p>
      </div>
    );
  }

  if (!data) return null;

  const hasGpsA = data.gps_a && data.gps_a.latitudes.length > 0;
  const hasGpsB = data.gps_b && data.gps_b.latitudes.length > 0;

  if (!hasGpsA && !hasGpsB) {
    return (
      <div className="bg-zinc-900 rounded-lg p-4 text-center py-12">
        <p className="text-zinc-500 text-sm">No GPS data available for these sessions.</p>
      </div>
    );
  }

  return (
    <div className="bg-zinc-900 rounded-lg p-4">
      <h3 className="text-sm font-medium text-zinc-300 mb-4">GPS Overlay</h3>

      <div className="relative rounded-lg overflow-hidden bg-asphalt">
        <canvas
          ref={canvasRef}
          style={{ width: '100%', height: '340px', display: 'block' }}
        />
      </div>

      {/* Legend */}
      <div className="flex items-center justify-center gap-6 mt-3 text-xs font-body">
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-0.5 rounded" style={{ backgroundColor: colorA }} />
          <span style={{ color: colorA }}>Session A</span>
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-0.5 rounded" style={{ backgroundColor: colorB }} />
          <span style={{ color: colorB }}>Session B</span>
        </span>
      </div>
    </div>
  );
}
