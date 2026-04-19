/**
 * SurfaceProfileChart.tsx — Track surface property visualization.
 *
 * Shows elevation profile, slope, camber, and roughness as stacked
 * mini-charts synced by distance. Integrates with useChartHoverStore.
 */
'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { apiFetch } from '@/lib/api-client';
import { useChartHoverStore } from '@/lib/chart-hover-store';
import { chartColor } from '@/components/shared/chart-kit';

interface SurfaceProfileData {
  distance_m?: number[];
  elevation_m?: number[];
  slope_pct?: number[];
  camber_deg?: number[];
  roughness_mu_delta?: number[];
  roughness_distance_m?: number[];
  available_layers: string[];
  n_laps: number;
}

interface SurfaceProfileChartProps {
  sessionId: string;
  className?: string;
}

const COLORS = {
  bg: chartColor.surface,
  grid: chartColor.grid,
  text: chartColor.textSecondary,
  chalk: chartColor.text,
  elevation: chartColor.palette[3],     // blue
  slope: chartColor.series.primary,     // gold
  camber: chartColor.series.reference,  // racing-purple
  roughness: chartColor.series.negative,// safety-red
};

function drawProfile(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  data: SurfaceProfileData,
  hoverDist: number | null,
) {
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = COLORS.bg;
  ctx.fillRect(0, 0, w, h);

  const layers = data.available_layers.filter(l =>
    l === 'elevation' || l === 'slope' || l === 'camber' || l === 'roughness'
  );
  if (layers.length === 0 || !data.distance_m || data.distance_m.length < 2) {
    ctx.fillStyle = COLORS.text;
    ctx.font = '13px "Space Mono", monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('No surface profile data', w / 2, h / 2);
    return;
  }

  const pad = { top: 8, right: 16, bottom: 24, left: 50 };
  const plotW = w - pad.left - pad.right;
  const chartH = Math.floor((h - pad.top - pad.bottom) / layers.length);

  const dist = data.distance_m;
  const xMin = dist[0];
  const xMax = dist[dist.length - 1];
  const xToPixel = (d: number) => pad.left + (d - xMin) / (xMax - xMin) * plotW;

  const layerConfigs: { key: string; label: string; unit: string; color: string; values: number[]; dists: number[] }[] = [];

  if (layers.includes('elevation') && data.elevation_m) {
    layerConfigs.push({ key: 'elevation', label: 'Elevation', unit: 'm', color: COLORS.elevation, values: data.elevation_m, dists: dist });
  }
  if (layers.includes('slope') && data.slope_pct) {
    layerConfigs.push({ key: 'slope', label: 'Slope', unit: '%', color: COLORS.slope, values: data.slope_pct, dists: dist });
  }
  if (layers.includes('camber') && data.camber_deg) {
    layerConfigs.push({ key: 'camber', label: 'Camber', unit: '\u00B0', color: COLORS.camber, values: data.camber_deg.map(v => v ?? 0), dists: dist });
  }
  if (layers.includes('roughness') && data.roughness_mu_delta && data.roughness_distance_m) {
    layerConfigs.push({ key: 'roughness', label: 'Roughness', unit: '\u0394\u03BC', color: COLORS.roughness, values: data.roughness_mu_delta, dists: data.roughness_distance_m });
  }

  for (let li = 0; li < layerConfigs.length; li++) {
    const cfg = layerConfigs[li];
    const yOffset = pad.top + li * chartH;
    const pH = chartH - 4;

    // Compute y range
    let yMin = Infinity, yMax = -Infinity;
    for (const v of cfg.values) {
      if (isFinite(v)) {
        if (v < yMin) yMin = v;
        if (v > yMax) yMax = v;
      }
    }
    if (yMin === yMax) { yMin -= 1; yMax += 1; }
    const yPad = (yMax - yMin) * 0.1;
    yMin -= yPad;
    yMax += yPad;

    const yToPixel = (v: number) => yOffset + pH - (v - yMin) / (yMax - yMin) * pH;

    // Grid line at zero (if in range)
    if (yMin < 0 && yMax > 0) {
      ctx.strokeStyle = COLORS.grid;
      ctx.lineWidth = 0.5;
      ctx.setLineDash([4, 4]);
      const zy = yToPixel(0);
      ctx.beginPath();
      ctx.moveTo(pad.left, zy);
      ctx.lineTo(pad.left + plotW, zy);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // Filled area
    ctx.save();
    ctx.globalAlpha = 0.15;
    ctx.fillStyle = cfg.color;
    ctx.beginPath();
    let started = false;
    for (let i = 0; i < cfg.values.length; i++) {
      const x = xToPixel(cfg.dists[i]);
      const y = yToPixel(cfg.values[i]);
      if (!started) { ctx.moveTo(x, y); started = true; } else { ctx.lineTo(x, y); }
    }
    // Close to baseline
    const baseline = yToPixel(cfg.key === 'elevation' ? yMin : 0);
    ctx.lineTo(xToPixel(cfg.dists[cfg.dists.length - 1]), baseline);
    ctx.lineTo(xToPixel(cfg.dists[0]), baseline);
    ctx.closePath();
    ctx.fill();
    ctx.restore();

    // Line
    ctx.strokeStyle = cfg.color;
    ctx.lineWidth = 1.5;
    ctx.globalAlpha = 0.8;
    ctx.beginPath();
    started = false;
    for (let i = 0; i < cfg.values.length; i++) {
      const x = xToPixel(cfg.dists[i]);
      const y = yToPixel(cfg.values[i]);
      if (!started) { ctx.moveTo(x, y); started = true; } else { ctx.lineTo(x, y); }
    }
    ctx.stroke();
    ctx.globalAlpha = 1.0;

    // Label
    ctx.fillStyle = cfg.color;
    ctx.font = '10px "Space Mono", monospace';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    ctx.fillText(`${cfg.label} (${cfg.unit})`, pad.left + 4, yOffset + 2);

    // Y-axis range
    ctx.fillStyle = COLORS.text;
    ctx.font = '8px "Space Mono", monospace';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'top';
    ctx.fillText(yMax.toFixed(1), pad.left - 4, yOffset + 2);
    ctx.textBaseline = 'bottom';
    ctx.fillText(yMin.toFixed(1), pad.left - 4, yOffset + pH);
  }

  // Hover line
  if (hoverDist != null && hoverDist >= xMin && hoverDist <= xMax) {
    const hx = xToPixel(hoverDist);
    ctx.strokeStyle = chartColor.series.primary;
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(hx, pad.top);
    ctx.lineTo(hx, h - pad.bottom);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  // X-axis labels
  ctx.fillStyle = COLORS.text;
  ctx.font = '9px "Space Mono", monospace';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  const xLabels = [0, 0.25, 0.5, 0.75, 1].map(t => xMin + t * (xMax - xMin));
  for (const d of xLabels) {
    ctx.fillText(`${Math.round(d)}m`, xToPixel(d), h - pad.bottom + 4);
  }
}

export function SurfaceProfileChart({ sessionId, className = '' }: SurfaceProfileChartProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [data, setData] = useState<SurfaceProfileData | null>(null);
  const [notAvailable, setNotAvailable] = useState(false);
  const fetchRef = useRef(0);
  const hoverDistance = useChartHoverStore((s) => s.hoverDistance);

  useEffect(() => {
    const ver = ++fetchRef.current;
    setNotAvailable(false);
    setData(null);
    (async () => {
      try {
        const res = await apiFetch<SurfaceProfileData>(
          `/sessions/${encodeURIComponent(sessionId)}/surface-profile`,
        );
        if (fetchRef.current !== ver) return;
        if (res?.available_layers?.length) setData(res);
        else setNotAvailable(true);
      } catch {
        if (fetchRef.current === ver) setNotAvailable(true);
      }
    })();
  }, [sessionId]);

  const render = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas || !data) return;
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.scale(dpr, dpr);
    drawProfile(ctx, rect.width, rect.height, data, hoverDistance);
  }, [data, hoverDistance]);

  useEffect(() => { render(); }, [render]);
  useEffect(() => {
    const obs = new ResizeObserver(() => render());
    if (canvasRef.current) obs.observe(canvasRef.current);
    return () => obs.disconnect();
  }, [render]);

  if (notAvailable) {
    return (
      <div className={`rounded-lg border border-steel/20 bg-concrete p-4 ${className}`}>
        <p className="text-sm text-steel font-telemetry">
          Surface profile not available — requires position data + multiple laps.
        </p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className={`rounded-lg border border-steel/20 bg-concrete p-4 animate-pulse ${className}`}>
        <div className="h-4 bg-steel/20 rounded w-2/3 mb-2" />
        <div className="h-20 bg-steel/10 rounded" />
      </div>
    );
  }

  return (
    <div className={`rounded-lg border border-steel/20 bg-concrete overflow-hidden ${className}`}>
      <div className="flex items-center justify-between px-3 py-2 border-b border-steel/10">
        <h3 className="text-xs font-monument text-chalk">Surface Profile</h3>
        <span className="text-[10px] font-telemetry text-steel">
          {data.available_layers.length} layers &middot; {data.n_laps} laps
        </span>
      </div>
      <canvas
        ref={canvasRef}
        className="w-full"
        style={{ height: `${Math.max(120, data.available_layers.length * 60)}px` }}
      />
    </div>
  );
}
