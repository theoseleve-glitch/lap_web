'use client';

import { useQuery } from '@tanstack/react-query';
import { useParams } from 'next/navigation';
import { useState, useCallback } from 'react';
import { api } from '@/lib/api-client';
import { useCanvas } from '@/hooks/useCanvas';

/* ---------- types ---------- */

interface GpsPoint {
  lat: number;
  lng: number;
  speed: number;
}

interface GgPoint {
  lat_g: number;
  lon_g: number;
}

interface SpeedPoint {
  distance: number;
  speed: number;
}

interface LapData {
  lap_number: number;
  gps: GpsPoint[];
  gg: GgPoint[];
  speed_trace: SpeedPoint[];
}

interface VisualizeResponse {
  laps: LapData[];
}

/* ---------- color helpers ---------- */

const LAP_COLORS = [
  '#B6FF2E', // acid green
  '#FF6A00', // pit orange
  '#FFD400', // marshal yellow
  '#FF2A2A', // safety red
  '#2AA5FF', // blue
  '#A855F7', // purple
  '#22D3EE', // cyan
  '#F472B6', // pink
  '#34D399', // emerald
  '#FCD34D', // amber
];

function speedToColor(speed: number, min: number, max: number): string {
  const range = max - min || 1;
  const t = Math.max(0, Math.min(1, (speed - min) / range));
  // Blue (slow) -> Green (mid) -> Red (fast)
  const r = Math.round(t < 0.5 ? 0 : (t - 0.5) * 2 * 255);
  const g = Math.round(t < 0.5 ? t * 2 * 255 : (1 - t) * 2 * 255);
  const b = Math.round(t < 0.5 ? (1 - t * 2) * 255 : 0);
  return `rgb(${r},${g},${b})`;
}

/* ---------- component ---------- */

export default function VisualizePage() {
  const { id } = useParams<{ id: string }>();
  const [visibleLaps, setVisibleLaps] = useState<Set<number>>(new Set());

  const { data, isLoading, error } = useQuery({
    queryKey: ['visualize', id],
    queryFn: () => api.get<VisualizeResponse>(`/sessions/${id}/visualize`),
  });

  // Initialize visible laps once data loads
  const laps = data?.laps ?? [];
  if (laps.length > 0 && visibleLaps.size === 0) {
    const initial = new Set(laps.map((l) => l.lap_number));
    if (initial.size !== visibleLaps.size) {
      setVisibleLaps(initial);
    }
  }

  const toggleLap = (lapNum: number) => {
    setVisibleLaps((prev) => {
      const next = new Set(prev);
      if (next.has(lapNum)) {
        next.delete(lapNum);
      } else {
        next.add(lapNum);
      }
      return next;
    });
  };

  const activeLaps = laps.filter((l) => visibleLaps.has(l.lap_number));

  /* ---------- GPS Track Map ---------- */
  const drawGpsMap = useCallback(
    (ctx: CanvasRenderingContext2D, width: number, height: number) => {
      ctx.fillStyle = '#0B0C0F';
      ctx.fillRect(0, 0, width, height);

      if (activeLaps.length === 0) {
        ctx.fillStyle = '#8A8F98';
        ctx.font = '12px "IBM Plex Mono", monospace';
        ctx.textAlign = 'center';
        ctx.fillText('Select laps to display', width / 2, height / 2);
        return;
      }

      // Gather all GPS points to compute bounds
      const allGps = activeLaps.flatMap((l) => l.gps);
      if (allGps.length === 0) {
        ctx.fillStyle = '#8A8F98';
        ctx.font = '12px "IBM Plex Mono", monospace';
        ctx.textAlign = 'center';
        ctx.fillText('No GPS data', width / 2, height / 2);
        return;
      }

      const lats = allGps.map((p) => p.lat);
      const lngs = allGps.map((p) => p.lng);
      const minLat = Math.min(...lats);
      const maxLat = Math.max(...lats);
      const minLng = Math.min(...lngs);
      const maxLng = Math.max(...lngs);

      const padding = 30;
      const drawW = width - padding * 2;
      const drawH = height - padding * 2;
      const latRange = maxLat - minLat || 0.001;
      const lngRange = maxLng - minLng || 0.001;
      const scale = Math.min(drawW / lngRange, drawH / latRange);

      const toX = (lng: number) => padding + (lng - minLng) * scale + (drawW - lngRange * scale) / 2;
      const toY = (lat: number) => padding + (maxLat - lat) * scale + (drawH - latRange * scale) / 2;

      const allSpeeds = allGps.map((p) => p.speed);
      const minSpd = Math.min(...allSpeeds);
      const maxSpd = Math.max(...allSpeeds);

      for (const lap of activeLaps) {
        if (lap.gps.length < 2) continue;
        for (let i = 1; i < lap.gps.length; i++) {
          const prev = lap.gps[i - 1];
          const curr = lap.gps[i];
          ctx.beginPath();
          ctx.moveTo(toX(prev.lng), toY(prev.lat));
          ctx.lineTo(toX(curr.lng), toY(curr.lat));
          ctx.strokeStyle = speedToColor(curr.speed, minSpd, maxSpd);
          ctx.lineWidth = 2;
          ctx.stroke();
        }
      }

      // Speed legend
      const legendW = 120;
      const legendH = 10;
      const legendX = width - legendW - 16;
      const legendY = height - 32;
      for (let i = 0; i < legendW; i++) {
        ctx.fillStyle = speedToColor(minSpd + (i / legendW) * (maxSpd - minSpd), minSpd, maxSpd);
        ctx.fillRect(legendX + i, legendY, 1, legendH);
      }
      ctx.fillStyle = '#8A8F98';
      ctx.font = '9px "IBM Plex Mono", monospace';
      ctx.textAlign = 'left';
      ctx.fillText(`${minSpd.toFixed(0)}`, legendX, legendY + legendH + 12);
      ctx.textAlign = 'right';
      ctx.fillText(`${maxSpd.toFixed(0)} m/s`, legendX + legendW, legendY + legendH + 12);
    },
    [activeLaps],
  );

  /* ---------- Speed Trace Chart ---------- */
  const drawSpeedTrace = useCallback(
    (ctx: CanvasRenderingContext2D, width: number, height: number) => {
      ctx.fillStyle = '#0B0C0F';
      ctx.fillRect(0, 0, width, height);

      if (activeLaps.length === 0) {
        ctx.fillStyle = '#8A8F98';
        ctx.font = '12px "IBM Plex Mono", monospace';
        ctx.textAlign = 'center';
        ctx.fillText('Select laps to display', width / 2, height / 2);
        return;
      }

      const allTraces = activeLaps.flatMap((l) => l.speed_trace);
      if (allTraces.length === 0) {
        ctx.fillStyle = '#8A8F98';
        ctx.font = '12px "IBM Plex Mono", monospace';
        ctx.textAlign = 'center';
        ctx.fillText('No speed data', width / 2, height / 2);
        return;
      }

      const allDist = allTraces.map((p) => p.distance);
      const allSpd = allTraces.map((p) => p.speed);
      const minD = Math.min(...allDist);
      const maxD = Math.max(...allDist);
      const minS = Math.min(...allSpd) * 0.95;
      const maxS = Math.max(...allSpd) * 1.05;

      const pad = { top: 20, right: 16, bottom: 32, left: 48 };
      const drawW = width - pad.left - pad.right;
      const drawH = height - pad.top - pad.bottom;
      const distRange = maxD - minD || 1;
      const spdRange = maxS - minS || 1;

      const toX = (d: number) => pad.left + ((d - minD) / distRange) * drawW;
      const toY = (s: number) => pad.top + drawH - ((s - minS) / spdRange) * drawH;

      // Grid lines
      ctx.strokeStyle = '#8A8F9820';
      ctx.lineWidth = 1;
      for (let i = 0; i <= 4; i++) {
        const y = pad.top + (i / 4) * drawH;
        ctx.beginPath();
        ctx.moveTo(pad.left, y);
        ctx.lineTo(width - pad.right, y);
        ctx.stroke();
      }

      // Draw traces
      activeLaps.forEach((lap, idx) => {
        if (lap.speed_trace.length < 2) return;
        ctx.beginPath();
        ctx.moveTo(toX(lap.speed_trace[0].distance), toY(lap.speed_trace[0].speed));
        for (let i = 1; i < lap.speed_trace.length; i++) {
          ctx.lineTo(toX(lap.speed_trace[i].distance), toY(lap.speed_trace[i].speed));
        }
        ctx.strokeStyle = LAP_COLORS[idx % LAP_COLORS.length];
        ctx.lineWidth = 1.5;
        ctx.stroke();
      });

      // Axis labels
      ctx.fillStyle = '#8A8F98';
      ctx.font = '9px "IBM Plex Mono", monospace';
      ctx.textAlign = 'center';
      ctx.fillText('Distance (m)', width / 2, height - 6);
      ctx.save();
      ctx.translate(12, height / 2);
      ctx.rotate(-Math.PI / 2);
      ctx.fillText('Speed (m/s)', 0, 0);
      ctx.restore();

      // Axis tick labels
      ctx.textAlign = 'center';
      for (let i = 0; i <= 4; i++) {
        const d = minD + (i / 4) * distRange;
        ctx.fillText(`${d.toFixed(0)}`, toX(d), height - pad.bottom + 14);
      }
      ctx.textAlign = 'right';
      for (let i = 0; i <= 4; i++) {
        const s = minS + (i / 4) * spdRange;
        const y = pad.top + drawH - (i / 4) * drawH;
        ctx.fillText(`${s.toFixed(0)}`, pad.left - 6, y + 3);
      }
    },
    [activeLaps],
  );

  /* ---------- GG Scatter Diagram ---------- */
  const drawGgDiagram = useCallback(
    (ctx: CanvasRenderingContext2D, width: number, height: number) => {
      ctx.fillStyle = '#0B0C0F';
      ctx.fillRect(0, 0, width, height);

      if (activeLaps.length === 0) {
        ctx.fillStyle = '#8A8F98';
        ctx.font = '12px "IBM Plex Mono", monospace';
        ctx.textAlign = 'center';
        ctx.fillText('Select laps to display', width / 2, height / 2);
        return;
      }

      const allGg = activeLaps.flatMap((l) => l.gg);
      if (allGg.length === 0) {
        ctx.fillStyle = '#8A8F98';
        ctx.font = '12px "IBM Plex Mono", monospace';
        ctx.textAlign = 'center';
        ctx.fillText('No GG data', width / 2, height / 2);
        return;
      }

      const latGs = allGg.map((p) => Math.abs(p.lat_g));
      const lonGs = allGg.map((p) => Math.abs(p.lon_g));
      const maxG = Math.max(Math.max(...latGs), Math.max(...lonGs), 0.5) * 1.15;

      const pad = { top: 20, right: 16, bottom: 32, left: 48 };
      const drawW = width - pad.left - pad.right;
      const drawH = height - pad.top - pad.bottom;
      const cx = pad.left + drawW / 2;
      const cy = pad.top + drawH / 2;
      const scaleX = drawW / (2 * maxG);
      const scaleY = drawH / (2 * maxG);

      // Cross-hairs
      ctx.strokeStyle = '#8A8F9830';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(pad.left, cy);
      ctx.lineTo(width - pad.right, cy);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(cx, pad.top);
      ctx.lineTo(cx, height - pad.bottom);
      ctx.stroke();

      // Circle guides
      const gSteps = [0.5, 1.0, 1.5, 2.0].filter((g) => g <= maxG);
      ctx.strokeStyle = '#8A8F9818';
      for (const g of gSteps) {
        ctx.beginPath();
        ctx.ellipse(cx, cy, g * scaleX, g * scaleY, 0, 0, Math.PI * 2);
        ctx.stroke();
        ctx.fillStyle = '#8A8F9860';
        ctx.font = '8px "IBM Plex Mono", monospace';
        ctx.textAlign = 'left';
        ctx.fillText(`${g}G`, cx + g * scaleX + 2, cy - 2);
      }

      // Plot points per lap
      activeLaps.forEach((lap, idx) => {
        const color = LAP_COLORS[idx % LAP_COLORS.length];
        ctx.fillStyle = color + '80'; // semi-transparent
        for (const pt of lap.gg) {
          const x = cx + pt.lat_g * scaleX;
          const y = cy - pt.lon_g * scaleY;
          ctx.beginPath();
          ctx.arc(x, y, 2, 0, Math.PI * 2);
          ctx.fill();
        }
      });

      // Axis labels
      ctx.fillStyle = '#8A8F98';
      ctx.font = '9px "IBM Plex Mono", monospace';
      ctx.textAlign = 'center';
      ctx.fillText('Lateral G', width / 2, height - 6);
      ctx.save();
      ctx.translate(12, height / 2);
      ctx.rotate(-Math.PI / 2);
      ctx.fillText('Longitudinal G', 0, 0);
      ctx.restore();
    },
    [activeLaps],
  );

  /* ---------- canvas refs ---------- */
  const gpsCanvasRef = useCanvas(drawGpsMap, [drawGpsMap]);
  const speedCanvasRef = useCanvas(drawSpeedTrace, [drawSpeedTrace]);
  const ggCanvasRef = useCanvas(drawGgDiagram, [drawGgDiagram]);

  /* ---------- render ---------- */
  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-6rem)]">
        <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-6rem)]">
        <p className="text-safety-red font-telemetry text-sm">Failed to load visualization data</p>
      </div>
    );
  }

  return (
    <div className="flex h-[calc(100vh-6rem)] -mx-6 -my-6">
      {/* Sidebar - lap selector */}
      <aside className="w-48 bg-concrete border-r border-steel/20 overflow-y-auto p-3 shrink-0">
        <h2 className="font-monument text-sm text-chalk mb-3 tracking-tight">Laps</h2>
        {laps.length === 0 ? (
          <p className="text-steel font-telemetry text-xs">No laps available</p>
        ) : (
          <div className="space-y-1">
            {laps.map((lap, idx) => (
              <label
                key={lap.lap_number}
                className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-asphalt/50 transition-colors cursor-pointer"
              >
                <input
                  type="checkbox"
                  checked={visibleLaps.has(lap.lap_number)}
                  onChange={() => toggleLap(lap.lap_number)}
                  className="accent-acid-green w-3.5 h-3.5"
                />
                <span
                  className="w-2.5 h-2.5 rounded-full shrink-0"
                  style={{ backgroundColor: LAP_COLORS[idx % LAP_COLORS.length] }}
                />
                <span className="font-telemetry text-xs text-chalk">
                  Lap {lap.lap_number}
                </span>
              </label>
            ))}
          </div>
        )}

        {laps.length > 1 && (
          <div className="mt-4 pt-3 border-t border-steel/20 space-y-1">
            <button
              onClick={() => setVisibleLaps(new Set(laps.map((l) => l.lap_number)))}
              className="w-full text-left px-2 py-1 text-xs font-telemetry text-steel hover:text-chalk transition-colors"
            >
              Select All
            </button>
            <button
              onClick={() => setVisibleLaps(new Set())}
              className="w-full text-left px-2 py-1 text-xs font-telemetry text-steel hover:text-chalk transition-colors"
            >
              Deselect All
            </button>
          </div>
        )}
      </aside>

      {/* Main panels */}
      <div className="flex-1 grid grid-cols-2 grid-rows-2 gap-2 p-2 min-w-0">
        {/* GPS Map - spans both rows in left column */}
        <div className="row-span-2 bg-concrete rounded-lg border border-steel/20 overflow-hidden flex flex-col">
          <div className="px-3 py-2 border-b border-steel/10">
            <h3 className="text-chalk font-body text-sm font-medium">GPS Track Map</h3>
            <p className="text-steel font-telemetry text-xs mt-0.5">Colored by speed</p>
          </div>
          <div className="flex-1 relative">
            <canvas ref={gpsCanvasRef} className="absolute inset-0 w-full h-full" />
          </div>
        </div>

        {/* Speed trace - top right */}
        <div className="bg-concrete rounded-lg border border-steel/20 overflow-hidden flex flex-col">
          <div className="px-3 py-2 border-b border-steel/10">
            <h3 className="text-chalk font-body text-sm font-medium">Speed Trace</h3>
            <p className="text-steel font-telemetry text-xs mt-0.5">Speed vs distance</p>
          </div>
          <div className="flex-1 relative">
            <canvas ref={speedCanvasRef} className="absolute inset-0 w-full h-full" />
          </div>
        </div>

        {/* GG diagram - bottom right */}
        <div className="bg-concrete rounded-lg border border-steel/20 overflow-hidden flex flex-col">
          <div className="px-3 py-2 border-b border-steel/10">
            <h3 className="text-chalk font-body text-sm font-medium">GG Diagram</h3>
            <p className="text-steel font-telemetry text-xs mt-0.5">Lateral vs longitudinal G</p>
          </div>
          <div className="flex-1 relative">
            <canvas ref={ggCanvasRef} className="absolute inset-0 w-full h-full" />
          </div>
        </div>
      </div>
    </div>
  );
}
