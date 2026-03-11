/**
 * SpeedTraceMiniMap.tsx — Tiny GPS track overlay for the speed trace panel.
 *
 * Shows a miniature track outline with a dot that follows the current
 * hover position (via the chart-hover-store distance value).
 */
'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { useChartHoverStore } from '@/lib/chart-hover-store';
import { api } from '@/lib/api-client';

interface GpsData {
  latitudes: number[];
  longitudes: number[];
  distances: number[];
}

interface SpeedTraceMiniMapProps {
  sessionId: string;
  bestLap?: number | null;
  /** Canvas size in CSS pixels */
  size?: number;
}

export function SpeedTraceMiniMap({
  sessionId,
  bestLap,
  size = 100,
}: SpeedTraceMiniMapProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const gpsRef = useRef<GpsData | null>(null);
  const [loaded, setLoaded] = useState(false);

  // Fetch GPS data once (uses api client for auth headers + 401 retry)
  useEffect(() => {
    let cancelled = false;
    const lap = bestLap ?? 1;

    api.get<{ available: boolean; latitudes?: number[]; longitudes?: number[]; distances?: number[] }>(
      `/sessions/${sessionId}/gps-trace?lap=${lap}`,
    )
      .then((d) => {
        if (cancelled) return;
        const lats = d.latitudes;
        const lons = d.longitudes;
        if (d.available === false || !lats?.length || !lons?.length) return;
        gpsRef.current = { latitudes: lats, longitudes: lons, distances: d.distances ?? [] };
        setLoaded(true);
      })
      .catch(() => {
        // Non-critical UI element — silent fail is acceptable
      });

    return () => { cancelled = true; };
  }, [sessionId, bestLap]);

  // Draw the track path + dot
  const draw = useCallback(
    (hoverDist: number | null) => {
      const canvas = canvasRef.current;
      const gps = gpsRef.current;
      if (!canvas || !gps) return;

      const dpr = window.devicePixelRatio || 1;
      const w = size;
      const h = size;

      if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
        canvas.width = w * dpr;
        canvas.height = h * dpr;
        canvas.style.width = `${w}px`;
        canvas.style.height = `${h}px`;
      }

      const ctx = canvas.getContext('2d');
      if (!ctx) return;

      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);

      const { latitudes: lats, longitudes: lons, distances: dists } = gps;
      const n = lats.length;
      if (n < 2) return;

      // Compute bounds with padding
      const pad = 6;
      let minLat = lats[0], maxLat = lats[0], minLon = lons[0], maxLon = lons[0];
      for (let i = 1; i < n; i++) {
        if (lats[i] < minLat) minLat = lats[i];
        if (lats[i] > maxLat) maxLat = lats[i];
        if (lons[i] < minLon) minLon = lons[i];
        if (lons[i] > maxLon) maxLon = lons[i];
      }

      const latRange = maxLat - minLat || 0.0001;
      const lonRange = maxLon - minLon || 0.0001;
      const drawW = w - pad * 2;
      const drawH = h - pad * 2;
      const scale = Math.min(drawW / lonRange, drawH / latRange);

      const toX = (lon: number) => pad + (lon - minLon) * scale + (drawW - lonRange * scale) / 2;
      const toY = (lat: number) => pad + (maxLat - lat) * scale + (drawH - latRange * scale) / 2;

      // Draw track path
      ctx.beginPath();
      ctx.moveTo(toX(lons[0]), toY(lats[0]));
      for (let i = 1; i < n; i++) {
        ctx.lineTo(toX(lons[i]), toY(lats[i]));
      }
      ctx.strokeStyle = 'rgba(240,237,229,0.25)';
      ctx.lineWidth = 1.5;
      ctx.lineJoin = 'round';
      ctx.stroke();

      // Draw position dot if hovering
      if (hoverDist !== null && dists.length === n) {
        // Find nearest index by distance
        let idx = 0;
        let bestDelta = Math.abs(dists[0] - hoverDist);
        for (let i = 1; i < n; i++) {
          const delta = Math.abs(dists[i] - hoverDist);
          if (delta < bestDelta) {
            bestDelta = delta;
            idx = i;
          }
        }

        const dx = toX(lons[idx]);
        const dy = toY(lats[idx]);

        // Glow
        ctx.beginPath();
        ctx.arc(dx, dy, 5, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(61,220,132,0.3)';
        ctx.fill();

        // Dot
        ctx.beginPath();
        ctx.arc(dx, dy, 2.5, 0, Math.PI * 2);
        ctx.fillStyle = '#3ddc84';
        ctx.fill();
      }
    },
    [size],
  );

  // Subscribe to hover store
  useEffect(() => {
    if (!loaded) return;
    // Initial draw
    draw(null);

    const unsub = useChartHoverStore.subscribe((state) => {
      draw(state.hoverDistance);
    });
    return unsub;
  }, [loaded, draw]);

  if (!loaded) return null;

  return (
    <canvas
      ref={canvasRef}
      className="absolute top-2 right-2 pointer-events-none opacity-70"
      style={{ width: size, height: size }}
      aria-label="Mini track map showing current position"
    />
  );
}
