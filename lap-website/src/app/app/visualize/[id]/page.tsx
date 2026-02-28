'use client';

import { useQuery } from '@tanstack/react-query';
import { useParams } from 'next/navigation';
import { useState, useCallback, useMemo, useRef } from 'react';
import { api } from '@/lib/api-client';
import { useInteractiveCanvas, type HoverPoint, type TooltipData } from '@/hooks/useInteractiveCanvas';
import { ChartTooltip } from '@/components/app/ChartTooltip';
import { useEntitlements } from '@/hooks/useEntitlements';
import { UpgradeBanner } from '@/components/billing/UpgradeBanner';

/* ---------- types ---------- */

interface GpsPoint { lat: number; lng: number; speed: number }
interface GgPoint { lat_g: number; lon_g: number }
interface SpeedPoint { distance: number; speed: number }

interface LapData {
  lap_number: number;
  gps: GpsPoint[];
  gg: GgPoint[];
  speed_trace: SpeedPoint[];
}

interface VisualizeResponse { laps: LapData[] }

/* ---------- color helpers ---------- */

const LAP_COLORS = [
  '#B6FF2E', '#FF6A00', '#FFD400', '#FF2A2A', '#2AA5FF',
  '#A855F7', '#22D3EE', '#F472B6', '#34D399', '#FCD34D',
];

function speedToColor(speed: number, min: number, max: number): string {
  const t = Math.max(0, Math.min(1, (speed - min) / (max - min || 1)));
  const r = Math.round(t < 0.5 ? 0 : (t - 0.5) * 2 * 255);
  const g = Math.round(t < 0.5 ? t * 2 * 255 : (1 - t) * 2 * 255);
  const b = Math.round(t < 0.5 ? (1 - t * 2) * 255 : 0);
  return `rgb(${r},${g},${b})`;
}

function lapColor(lapNum: number, idx: Map<number, number>): string {
  return LAP_COLORS[(idx.get(lapNum) ?? 0) % LAP_COLORS.length];
}

/* ---------- GPS Map Panel ---------- */

const GPS_PAD = { top: 10, right: 10, bottom: 40, left: 10 };

function GpsMapPanel({ activeLaps }: { activeLaps: LapData[] }) {
  const screenRef = useRef<{ x: number; y: number; speed: number; lat: number; lng: number; lap: number }[]>([]);

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number, hover: HoverPoint | null) => {
      ctx.fillStyle = '#0B0C0F';
      ctx.fillRect(0, 0, w, h);

      if (activeLaps.length === 0) {
        ctx.fillStyle = '#8A8F98';
        ctx.font = '12px "IBM Plex Mono", monospace';
        ctx.textAlign = 'center';
        ctx.fillText('Select laps to display', w / 2, h / 2);
        screenRef.current = [];
        return;
      }

      const allGps = activeLaps.flatMap((l) => l.gps);
      if (allGps.length === 0) {
        ctx.fillStyle = '#8A8F98';
        ctx.font = '12px "IBM Plex Mono", monospace';
        ctx.textAlign = 'center';
        ctx.fillText('No GPS data', w / 2, h / 2);
        screenRef.current = [];
        return;
      }

      const lats = allGps.map((p) => p.lat);
      const lngs = allGps.map((p) => p.lng);
      const minLat = Math.min(...lats), maxLat = Math.max(...lats);
      const minLng = Math.min(...lngs), maxLng = Math.max(...lngs);
      const pad = 30;
      const drawW = w - pad * 2, drawH = h - pad * 2;
      const latR = maxLat - minLat || 0.001, lngR = maxLng - minLng || 0.001;
      const scale = Math.min(drawW / lngR, drawH / latR);

      const toX = (lng: number) => pad + (lng - minLng) * scale + (drawW - lngR * scale) / 2;
      const toY = (lat: number) => pad + (maxLat - lat) * scale + (drawH - latR * scale) / 2;

      const speeds = allGps.map((p) => p.speed);
      const minSpd = Math.min(...speeds), maxSpd = Math.max(...speeds);

      // Store screen positions for tooltip lookup
      const pts: typeof screenRef.current = [];
      for (const lap of activeLaps) {
        for (const pt of lap.gps) {
          pts.push({ x: toX(pt.lng), y: toY(pt.lat), speed: pt.speed, lat: pt.lat, lng: pt.lng, lap: lap.lap_number });
        }
      }
      screenRef.current = pts;

      // Find nearest point for hover
      let nearIdx = -1;
      if (hover) {
        let nearDist = Infinity;
        for (let i = 0; i < pts.length; i++) {
          const dx = pts[i].x - hover.x, dy = pts[i].y - hover.y;
          const d = dx * dx + dy * dy;
          if (d < nearDist) { nearDist = d; nearIdx = i; }
        }
        if (nearDist > 400) nearIdx = -1;
      }

      // Draw track lines colored by speed
      for (const lap of activeLaps) {
        if (lap.gps.length < 2) continue;
        for (let i = 1; i < lap.gps.length; i++) {
          const prev = lap.gps[i - 1], curr = lap.gps[i];
          ctx.beginPath();
          ctx.moveTo(toX(prev.lng), toY(prev.lat));
          ctx.lineTo(toX(curr.lng), toY(curr.lat));
          ctx.strokeStyle = speedToColor(curr.speed, minSpd, maxSpd);
          ctx.lineWidth = 2;
          ctx.stroke();
        }
      }

      // Hover highlight
      if (nearIdx >= 0) {
        const p = pts[nearIdx];
        ctx.beginPath();
        ctx.arc(p.x, p.y, 7, 0, Math.PI * 2);
        ctx.fillStyle = '#F3F0E8';
        ctx.fill();
        ctx.strokeStyle = '#F3F0E8';
        ctx.lineWidth = 2;
        ctx.stroke();
      }

      // Speed legend
      const lW = 120, lH = 10, lX = w - lW - 16, lY = h - 32;
      for (let i = 0; i < lW; i++) {
        ctx.fillStyle = speedToColor(minSpd + (i / lW) * (maxSpd - minSpd), minSpd, maxSpd);
        ctx.fillRect(lX + i, lY, 1, lH);
      }
      ctx.fillStyle = '#8A8F98';
      ctx.font = '9px "IBM Plex Mono", monospace';
      ctx.textAlign = 'left';
      ctx.fillText(`${minSpd.toFixed(0)}`, lX, lY + lH + 12);
      ctx.textAlign = 'right';
      ctx.fillText(`${maxSpd.toFixed(0)} m/s`, lX + lW, lY + lH + 12);
    },
    [activeLaps],
  );

  const getTooltipData = useCallback(
    (hover: HoverPoint): TooltipData | null => {
      const pts = screenRef.current;
      if (pts.length === 0) return null;
      let nearest = 0, nearDist = Infinity;
      for (let i = 0; i < pts.length; i++) {
        const dx = pts[i].x - hover.x, dy = pts[i].y - hover.y;
        const d = dx * dx + dy * dy;
        if (d < nearDist) { nearDist = d; nearest = i; }
      }
      if (nearDist > 400) return null;
      const p = pts[nearest];
      return {
        header: `Lap ${p.lap}`,
        lines: [
          { label: 'Speed', value: `${p.speed.toFixed(1)} m/s`, color: '#B6FF2E' },
          { label: 'Position', value: `${p.lat.toFixed(5)}, ${p.lng.toFixed(5)}` },
        ],
      };
    },
    [],
  );

  const { canvasRef, containerRef, tooltip } = useInteractiveCanvas({
    draw,
    deps: [activeLaps],
    padding: GPS_PAD,
    getTooltipData,
  });

  return (
    <div ref={containerRef} className="relative w-full h-full">
      <canvas ref={canvasRef} className="w-full h-full" />
      <ChartTooltip tooltip={tooltip} />
    </div>
  );
}

/* ---------- Speed Trace Panel ---------- */

const SPEED_PAD = { top: 20, right: 16, bottom: 32, left: 48 };

function SpeedTracePanel({ activeLaps, lapIdx }: { activeLaps: LapData[]; lapIdx: Map<number, number> }) {
  const bounds = useMemo(() => {
    const all = activeLaps.flatMap((l) => l.speed_trace);
    if (all.length === 0) return { minD: 0, maxD: 1, dR: 1, minS: 0, maxS: 1, sR: 1 };
    const ds = all.map((p) => p.distance), ss = all.map((p) => p.speed);
    const minD = Math.min(...ds), maxD = Math.max(...ds);
    const minS = Math.min(...ss) * 0.95, maxS = Math.max(...ss) * 1.05;
    return { minD, maxD, dR: maxD - minD || 1, minS, maxS, sR: maxS - minS || 1 };
  }, [activeLaps]);

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number, hover: HoverPoint | null) => {
      ctx.fillStyle = '#0B0C0F';
      ctx.fillRect(0, 0, w, h);

      if (activeLaps.length === 0) {
        ctx.fillStyle = '#8A8F98';
        ctx.font = '12px "IBM Plex Mono", monospace';
        ctx.textAlign = 'center';
        ctx.fillText('Select laps to display', w / 2, h / 2);
        return;
      }

      const { minD, dR, minS, sR } = bounds;
      const plotW = w - SPEED_PAD.left - SPEED_PAD.right;
      const plotH = h - SPEED_PAD.top - SPEED_PAD.bottom;
      const toX = (d: number) => SPEED_PAD.left + ((d - minD) / dR) * plotW;
      const toY = (s: number) => SPEED_PAD.top + plotH - ((s - minS) / sR) * plotH;

      // Grid
      ctx.strokeStyle = '#8A8F9820';
      ctx.lineWidth = 1;
      for (let i = 0; i <= 4; i++) {
        const y = SPEED_PAD.top + (i / 4) * plotH;
        ctx.beginPath();
        ctx.moveTo(SPEED_PAD.left, y);
        ctx.lineTo(w - SPEED_PAD.right, y);
        ctx.stroke();
      }

      // Draw traces
      for (const lap of activeLaps) {
        if (lap.speed_trace.length < 2) continue;
        const color = lapColor(lap.lap_number, lapIdx);
        ctx.beginPath();
        ctx.moveTo(toX(lap.speed_trace[0].distance), toY(lap.speed_trace[0].speed));
        for (let i = 1; i < lap.speed_trace.length; i++) {
          ctx.lineTo(toX(lap.speed_trace[i].distance), toY(lap.speed_trace[i].speed));
        }
        ctx.strokeStyle = color;
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }

      // Hover dots on traces at crosshair distance
      if (hover) {
        const hoverDist = minD + hover.nx * dR;
        for (const lap of activeLaps) {
          if (lap.speed_trace.length === 0) continue;
          let best = 0, bestDiff = Infinity;
          for (let i = 0; i < lap.speed_trace.length; i++) {
            const diff = Math.abs(lap.speed_trace[i].distance - hoverDist);
            if (diff < bestDiff) { bestDiff = diff; best = i; }
          }
          const pt = lap.speed_trace[best];
          ctx.beginPath();
          ctx.arc(toX(pt.distance), toY(pt.speed), 4, 0, Math.PI * 2);
          ctx.fillStyle = lapColor(lap.lap_number, lapIdx);
          ctx.fill();
          ctx.strokeStyle = '#F3F0E8';
          ctx.lineWidth = 1.5;
          ctx.stroke();
        }
      }

      // Axis labels
      ctx.fillStyle = '#8A8F98';
      ctx.font = '9px "IBM Plex Mono", monospace';
      ctx.textAlign = 'center';
      ctx.fillText('Distance (m)', w / 2, h - 6);
      ctx.save();
      ctx.translate(12, h / 2);
      ctx.rotate(-Math.PI / 2);
      ctx.fillText('Speed (m/s)', 0, 0);
      ctx.restore();

      // Tick labels
      ctx.textAlign = 'center';
      for (let i = 0; i <= 4; i++) {
        ctx.fillText(`${(minD + (i / 4) * dR).toFixed(0)}`, toX(minD + (i / 4) * dR), h - SPEED_PAD.bottom + 14);
      }
      ctx.textAlign = 'right';
      for (let i = 0; i <= 4; i++) {
        const s = minS + (i / 4) * sR;
        ctx.fillText(`${s.toFixed(0)}`, SPEED_PAD.left - 6, SPEED_PAD.top + plotH - (i / 4) * plotH + 3);
      }
    },
    [activeLaps, bounds, lapIdx],
  );

  const getTooltipData = useCallback(
    (hover: HoverPoint): TooltipData | null => {
      if (activeLaps.length === 0) return null;
      const hoverDist = bounds.minD + hover.nx * bounds.dR;
      const lines: TooltipData['lines'] = [];
      for (const lap of activeLaps) {
        if (lap.speed_trace.length === 0) continue;
        let best = 0, bestDiff = Infinity;
        for (let i = 0; i < lap.speed_trace.length; i++) {
          const diff = Math.abs(lap.speed_trace[i].distance - hoverDist);
          if (diff < bestDiff) { bestDiff = diff; best = i; }
        }
        lines.push({
          label: `Lap ${lap.lap_number}`,
          value: `${lap.speed_trace[best].speed.toFixed(1)} m/s`,
          color: lapColor(lap.lap_number, lapIdx),
        });
      }
      return { header: `${hoverDist.toFixed(0)} m`, lines };
    },
    [activeLaps, bounds, lapIdx],
  );

  const { canvasRef, containerRef, tooltip } = useInteractiveCanvas({
    draw,
    deps: [activeLaps],
    padding: SPEED_PAD,
    getTooltipData,
    crosshair: true,
  });

  return (
    <div ref={containerRef} className="relative w-full h-full">
      <canvas ref={canvasRef} className="w-full h-full" />
      <ChartTooltip tooltip={tooltip} />
    </div>
  );
}

/* ---------- GG Diagram Panel ---------- */

const GG_PAD = { top: 20, right: 16, bottom: 32, left: 48 };

function GgDiagramPanel({ activeLaps, lapIdx }: { activeLaps: LapData[]; lapIdx: Map<number, number> }) {
  const screenRef = useRef<{ x: number; y: number; lat_g: number; lon_g: number; lap: number }[]>([]);

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number, hover: HoverPoint | null) => {
      ctx.fillStyle = '#0B0C0F';
      ctx.fillRect(0, 0, w, h);

      if (activeLaps.length === 0) {
        ctx.fillStyle = '#8A8F98';
        ctx.font = '12px "IBM Plex Mono", monospace';
        ctx.textAlign = 'center';
        ctx.fillText('Select laps to display', w / 2, h / 2);
        screenRef.current = [];
        return;
      }

      const allGg = activeLaps.flatMap((l) => l.gg);
      if (allGg.length === 0) {
        ctx.fillStyle = '#8A8F98';
        ctx.font = '12px "IBM Plex Mono", monospace';
        ctx.textAlign = 'center';
        ctx.fillText('No GG data', w / 2, h / 2);
        screenRef.current = [];
        return;
      }

      const latGs = allGg.map((p) => Math.abs(p.lat_g));
      const lonGs = allGg.map((p) => Math.abs(p.lon_g));
      const maxG = Math.max(Math.max(...latGs), Math.max(...lonGs), 0.5) * 1.15;

      const drawW = w - GG_PAD.left - GG_PAD.right;
      const drawH = h - GG_PAD.top - GG_PAD.bottom;
      const cx = GG_PAD.left + drawW / 2;
      const cy = GG_PAD.top + drawH / 2;
      const scaleX = drawW / (2 * maxG);
      const scaleY = drawH / (2 * maxG);

      // Store screen positions
      const pts: typeof screenRef.current = [];
      for (const lap of activeLaps) {
        for (const pt of lap.gg) {
          pts.push({
            x: cx + pt.lat_g * scaleX,
            y: cy - pt.lon_g * scaleY,
            lat_g: pt.lat_g,
            lon_g: pt.lon_g,
            lap: lap.lap_number,
          });
        }
      }
      screenRef.current = pts;

      // Find nearest point for hover
      let nearIdx = -1;
      if (hover) {
        let nearDist = Infinity;
        for (let i = 0; i < pts.length; i++) {
          const dx = pts[i].x - hover.x, dy = pts[i].y - hover.y;
          const d = dx * dx + dy * dy;
          if (d < nearDist) { nearDist = d; nearIdx = i; }
        }
        if (nearDist > 400) nearIdx = -1;
      }

      // Cross-hairs
      ctx.strokeStyle = '#8A8F9830';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(GG_PAD.left, cy);
      ctx.lineTo(w - GG_PAD.right, cy);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(cx, GG_PAD.top);
      ctx.lineTo(cx, h - GG_PAD.bottom);
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
      for (const lap of activeLaps) {
        const color = lapColor(lap.lap_number, lapIdx);
        ctx.fillStyle = color + '80';
        for (const pt of lap.gg) {
          const x = cx + pt.lat_g * scaleX;
          const y = cy - pt.lon_g * scaleY;
          ctx.beginPath();
          ctx.arc(x, y, 2, 0, Math.PI * 2);
          ctx.fill();
        }
      }

      // Hover highlight
      if (nearIdx >= 0) {
        const p = pts[nearIdx];
        ctx.beginPath();
        ctx.arc(p.x, p.y, 6, 0, Math.PI * 2);
        ctx.fillStyle = lapColor(p.lap, lapIdx);
        ctx.fill();
        ctx.strokeStyle = '#F3F0E8';
        ctx.lineWidth = 2;
        ctx.stroke();
      }

      // Axis labels
      ctx.fillStyle = '#8A8F98';
      ctx.font = '9px "IBM Plex Mono", monospace';
      ctx.textAlign = 'center';
      ctx.fillText('Lateral G', w / 2, h - 6);
      ctx.save();
      ctx.translate(12, h / 2);
      ctx.rotate(-Math.PI / 2);
      ctx.fillText('Longitudinal G', 0, 0);
      ctx.restore();
    },
    [activeLaps, lapIdx],
  );

  const getTooltipData = useCallback(
    (hover: HoverPoint): TooltipData | null => {
      const pts = screenRef.current;
      if (pts.length === 0) return null;
      let nearest = 0, nearDist = Infinity;
      for (let i = 0; i < pts.length; i++) {
        const dx = pts[i].x - hover.x, dy = pts[i].y - hover.y;
        const d = dx * dx + dy * dy;
        if (d < nearDist) { nearDist = d; nearest = i; }
      }
      if (nearDist > 400) return null;
      const p = pts[nearest];
      return {
        header: `Lap ${p.lap}`,
        lines: [
          { label: 'Lateral G', value: `${p.lat_g.toFixed(2)}G`, color: lapColor(p.lap, lapIdx) },
          { label: 'Longitudinal G', value: `${p.lon_g.toFixed(2)}G` },
        ],
      };
    },
    [lapIdx],
  );

  const { canvasRef, containerRef, tooltip } = useInteractiveCanvas({
    draw,
    deps: [activeLaps],
    padding: GG_PAD,
    getTooltipData,
  });

  return (
    <div ref={containerRef} className="relative w-full h-full">
      <canvas ref={canvasRef} className="w-full h-full" />
      <ChartTooltip tooltip={tooltip} />
    </div>
  );
}

/* ---------- Main Page ---------- */

export default function VisualizePage() {
  const { id } = useParams<{ id: string }>();
  const [visibleLaps, setVisibleLaps] = useState<Set<number>>(new Set());
  const { canUse } = useEntitlements();
  const visualizationAllowed = canUse('visualization');

  const { data, isLoading, error } = useQuery({
    queryKey: ['visualize', id],
    queryFn: () => api.get<VisualizeResponse>(`/sessions/${id}/visualize`),
  });

  const laps = data?.laps ?? [];

  // Initialize visible laps once data loads
  if (laps.length > 0 && visibleLaps.size === 0) {
    const initial = new Set(laps.map((l) => l.lap_number));
    if (initial.size !== visibleLaps.size) {
      setVisibleLaps(initial);
    }
  }

  const toggleLap = (lapNum: number) => {
    setVisibleLaps((prev) => {
      const next = new Set(prev);
      if (next.has(lapNum)) next.delete(lapNum);
      else next.add(lapNum);
      return next;
    });
  };

  // Stable color index: lap_number → index in full laps array
  const lapIdx = useMemo(() => {
    const m = new Map<number, number>();
    laps.forEach((l, i) => m.set(l.lap_number, i));
    return m;
  }, [laps]);

  const activeLaps = useMemo(
    () => laps.filter((l) => visibleLaps.has(l.lap_number)),
    [laps, visibleLaps],
  );

  if (!visualizationAllowed) {
    return (
      <div className="flex flex-col items-center justify-center h-[calc(100vh-6rem)] gap-6 px-4">
        <UpgradeBanner
          feature="visualization"
          context="Telemetry visualization is available on the Racer plan and above"
        />
      </div>
    );
  }

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
      {/* Sidebar — lap selector */}
      <aside className="w-48 bg-concrete border-r border-steel/20 overflow-y-auto p-3 shrink-0">
        <h2 className="font-monument text-sm text-chalk mb-3 tracking-tight">Laps</h2>
        {laps.length === 0 ? (
          <p className="text-steel font-telemetry text-xs">No laps available</p>
        ) : (
          <div className="space-y-1">
            {laps.map((lap) => {
              const ci = lapIdx.get(lap.lap_number) ?? 0;
              return (
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
                    style={{ backgroundColor: LAP_COLORS[ci % LAP_COLORS.length] }}
                  />
                  <span className="font-telemetry text-xs text-chalk">Lap {lap.lap_number}</span>
                </label>
              );
            })}
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

      {/* Main chart panels */}
      <div className="flex-1 grid grid-cols-2 grid-rows-2 gap-2 p-2 min-w-0">
        {/* GPS Map — spans both rows in left column */}
        <div className="row-span-2 bg-concrete rounded-lg border border-steel/20 overflow-hidden flex flex-col">
          <div className="px-3 py-2 border-b border-steel/10">
            <h3 className="text-chalk font-body text-sm font-medium">GPS Track Map</h3>
            <p className="text-steel font-telemetry text-xs mt-0.5">Colored by speed — hover for details</p>
          </div>
          <div className="flex-1 relative">
            <GpsMapPanel activeLaps={activeLaps} />
          </div>
        </div>

        {/* Speed trace — top right */}
        <div className="bg-concrete rounded-lg border border-steel/20 overflow-hidden flex flex-col">
          <div className="px-3 py-2 border-b border-steel/10">
            <h3 className="text-chalk font-body text-sm font-medium">Speed Trace</h3>
            <p className="text-steel font-telemetry text-xs mt-0.5">Speed vs distance — crosshair to compare</p>
          </div>
          <div className="flex-1 relative">
            <SpeedTracePanel activeLaps={activeLaps} lapIdx={lapIdx} />
          </div>
        </div>

        {/* GG diagram — bottom right */}
        <div className="bg-concrete rounded-lg border border-steel/20 overflow-hidden flex flex-col">
          <div className="px-3 py-2 border-b border-steel/10">
            <h3 className="text-chalk font-body text-sm font-medium">GG Diagram</h3>
            <p className="text-steel font-telemetry text-xs mt-0.5">Lateral vs longitudinal G — hover for values</p>
          </div>
          <div className="flex-1 relative">
            <GgDiagramPanel activeLaps={activeLaps} lapIdx={lapIdx} />
          </div>
        </div>
      </div>
    </div>
  );
}
