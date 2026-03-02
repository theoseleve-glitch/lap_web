'use client';

import { useEffect, useState, useRef, useCallback } from 'react';
import { api } from '@/lib/api-client';

interface HeatmapResponse {
  available: boolean;
  reason_code?: string;
  laps: number[];
  corners: number[];
  values: (number | null)[][];
  corner_stats: {
    corner_id: number;
    mean_ms: number | null;
    std_ms: number | null;
    max_ms: number | null;
  }[];
}

interface ConsistencyHeatmapProps {
  sessionId: string;
}

function lossColor(ms: number | null): string {
  if (ms === null) return 'rgba(138,143,152,0.1)';
  if (ms <= 10) return '#4ade80';     // green — consistent
  if (ms <= 30) return '#a3e635';     // lime
  if (ms <= 50) return '#facc15';     // yellow — variable
  if (ms <= 100) return '#fb923c';    // orange
  return '#f87171';                    // red — erratic
}

function drawHeatmap(
  canvas: HTMLCanvasElement,
  laps: number[],
  corners: number[],
  values: (number | null)[][],
) {
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  ctx.scale(dpr, dpr);

  const W = rect.width;
  const H = rect.height;
  const labelLeft = 32;
  const topPad = 24;
  const rightPad = 8;
  const bottomPad = 8;
  const chartW = W - labelLeft - rightPad;
  const chartH = H - topPad - bottomPad;
  const nLaps = laps.length;
  const nCorners = corners.length;
  if (nLaps === 0 || nCorners === 0) return;

  const cellW = chartW / nCorners;
  const cellH = Math.min(chartH / nLaps, 20);
  const actualH = cellH * nLaps;

  // Background
  ctx.fillStyle = '#0B0C0F';
  ctx.fillRect(0, 0, W, H);

  // Column headers (corner IDs)
  ctx.fillStyle = 'rgba(138,143,152,0.6)';
  ctx.font = '9px monospace';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'bottom';
  corners.forEach((cid, ci) => {
    ctx.fillText(`C${cid}`, labelLeft + ci * cellW + cellW / 2, topPad - 4);
  });

  // Draw cells
  laps.forEach((lap, li) => {
    const y = topPad + li * cellH;

    // Row label (lap number)
    ctx.fillStyle = 'rgba(243,240,232,0.5)';
    ctx.font = '9px monospace';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    ctx.fillText(`L${lap}`, labelLeft - 4, y + cellH / 2);

    corners.forEach((_cid, ci) => {
      const x = labelLeft + ci * cellW;
      const val = values[li]?.[ci] ?? null;

      // Cell fill
      ctx.fillStyle = lossColor(val);
      ctx.fillRect(x + 1, y + 1, cellW - 2, cellH - 2);

      // Value text (only if cells are big enough)
      if (cellW >= 28 && cellH >= 14 && val !== null) {
        ctx.fillStyle = val > 50 ? 'rgba(255,255,255,0.9)' : 'rgba(0,0,0,0.7)';
        ctx.font = '8px monospace';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(
          val < 1000 ? `${Math.round(val)}` : `${(val / 1000).toFixed(1)}s`,
          x + cellW / 2,
          y + cellH / 2,
        );
      }
    });
  });

  // Legend bar at right edge if space
  if (rightPad < 8) return;
  const legendX = labelLeft + nCorners * cellW + 4;
  const legendH = Math.min(actualH, 80);
  const legendY = topPad;
  const stops = [0, 10, 30, 50, 100, 200];
  stops.forEach((s, i) => {
    const y2 = legendY + (i / (stops.length - 1)) * legendH;
    ctx.fillStyle = lossColor(s);
    ctx.fillRect(legendX, y2, 6, legendH / (stops.length - 1));
  });
}

export function ConsistencyHeatmap({ sessionId }: ConsistencyHeatmapProps) {
  const [response, setResponse] = useState<HeatmapResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .get<HeatmapResponse>(`/sessions/${sessionId}/consistency-heatmap`)
      .then((res) => {
        if (!cancelled) setResponse(res);
      })
      .catch((err) => {
        if (!cancelled) setError((err as Error)?.message ?? 'Failed to load');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [sessionId]);

  const draw = useCallback(() => {
    if (canvasRef.current && response?.available && response.laps.length > 0) {
      drawHeatmap(canvasRef.current, response.laps, response.corners, response.values);
    }
  }, [response]);

  useEffect(() => { draw(); }, [draw]);

  useEffect(() => {
    const observer = new ResizeObserver(() => draw());
    if (canvasRef.current) observer.observe(canvasRef.current);
    return () => observer.disconnect();
  }, [draw]);

  if (loading) {
    return (
      <div className="bg-concrete rounded-lg border border-steel/10 p-4 animate-pulse">
        <div className="h-4 bg-asphalt rounded w-36 mb-3" />
        <div className="h-48 bg-asphalt rounded" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-concrete rounded-lg border border-steel/10 p-4">
        <h3 className="text-sm text-chalk font-telemetry mb-2">Consistency</h3>
        <p className="text-xs text-steel">{error}</p>
      </div>
    );
  }

  if (!response?.available || response.laps.length === 0) {
    return (
      <div className="bg-concrete rounded-lg border border-steel/10 p-4">
        <h3 className="text-sm text-chalk font-telemetry mb-2">Consistency</h3>
        <p className="text-xs text-steel">No consistency data available.</p>
      </div>
    );
  }

  const canvasHeight = Math.max(response.laps.length * 18 + 32, 120);

  return (
    <div className="bg-concrete rounded-lg border border-steel/10 p-4">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm text-chalk font-telemetry">Consistency</h3>
        <span className="text-[9px] text-steel/40 font-body">
          Time loss (ms) per corner per lap
        </span>
      </div>
      <canvas
        ref={canvasRef}
        className="w-full"
        style={{ height: canvasHeight }}
      />
    </div>
  );
}
