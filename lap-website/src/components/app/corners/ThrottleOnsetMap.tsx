'use client';

import { useEffect, useState, useRef, useCallback } from 'react';
import { api } from '@/lib/api-client';

interface ThrottleCorner {
  corner_id: number;
  mean_m: number;
  std_m: number;
  n_laps: number;
}

interface ThrottleOnsetResponse {
  corners: ThrottleCorner[];
  available: boolean;
  reason_code?: string;
}

interface ThrottleOnsetMapProps {
  sessionId: string;
}

function onsetColor(meanM: number): string {
  if (meanM < 3) return '#4ade80';    // green — early onset (good)
  if (meanM <= 8) return '#facc15';   // yellow — moderate
  return '#f87171';                    // red — late onset
}

function drawThrottleChart(canvas: HTMLCanvasElement, corners: ThrottleCorner[]) {
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  ctx.scale(dpr, dpr);

  const W = rect.width;
  const H = rect.height;
  const labelWidth = 40;
  const rightPad = 50;
  const topPad = 24;
  const bottomPad = 24;
  const chartW = W - labelWidth - rightPad;
  const chartH = H - topPad - bottomPad;
  const n = corners.length;
  if (n === 0) return;

  // Background
  ctx.fillStyle = '#0B0C0F';
  ctx.fillRect(0, 0, W, H);

  const maxVal = Math.max(...corners.map((c) => c.mean_m + c.std_m), 1);
  const scale = chartW / maxVal;
  const barH = Math.min(chartH / n - 2, 18);

  // Header
  ctx.fillStyle = 'rgba(138,143,152,0.5)';
  ctx.font = '9px system-ui, sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText('Distance from apex (m)', labelWidth + chartW / 2, topPad - 6);

  // Draw bars
  corners.forEach((c, i) => {
    const y = topPad + (i * chartH) / n + (chartH / n - barH) / 2;
    const barW = c.mean_m * scale;
    const color = onsetColor(c.mean_m);

    // Bar
    ctx.fillStyle = color;
    ctx.fillRect(labelWidth, y, barW, barH);

    // Std dev whisker
    if (c.std_m > 0) {
      const whiskerStart = labelWidth + (c.mean_m - c.std_m) * scale;
      const whiskerEnd = labelWidth + (c.mean_m + c.std_m) * scale;
      ctx.strokeStyle = 'rgba(243,240,232,0.4)';
      ctx.lineWidth = 1;
      const midY = y + barH / 2;
      ctx.beginPath();
      ctx.moveTo(Math.max(whiskerStart, labelWidth), midY);
      ctx.lineTo(whiskerEnd, midY);
      ctx.stroke();
      // Caps
      ctx.beginPath();
      ctx.moveTo(whiskerEnd, midY - 3);
      ctx.lineTo(whiskerEnd, midY + 3);
      ctx.stroke();
    }

    // Corner label
    ctx.fillStyle = 'rgba(243,240,232,0.7)';
    ctx.font = '10px monospace';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    ctx.fillText(`C${c.corner_id}`, labelWidth - 6, y + barH / 2);

    // Value
    ctx.fillStyle = color;
    ctx.font = '9px monospace';
    ctx.textAlign = 'left';
    ctx.fillText(`${c.mean_m.toFixed(1)}m`, labelWidth + barW + 4, y + barH / 2);
  });
}

export function ThrottleOnsetMap({ sessionId }: ThrottleOnsetMapProps) {
  const [data, setData] = useState<ThrottleCorner[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .get<ThrottleOnsetResponse>(`/sessions/${sessionId}/throttle-onset`)
      .then((res) => {
        if (!cancelled) {
          if (res.available === false) {
            setData([]);
          } else {
            setData(res.corners);
          }
        }
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
    if (canvasRef.current && data && data.length > 0) {
      drawThrottleChart(canvasRef.current, data);
    }
  }, [data]);

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
        <h3 className="text-sm text-chalk font-telemetry mb-2">Throttle Onset</h3>
        <p className="text-xs text-steel">{error}</p>
      </div>
    );
  }

  if (!data || data.length === 0) {
    return (
      <div className="bg-concrete rounded-lg border border-steel/10 p-4">
        <h3 className="text-sm text-chalk font-telemetry mb-2">Throttle Onset</h3>
        <p className="text-xs text-steel">No throttle onset data available.</p>
      </div>
    );
  }

  const earlyOnset = data.filter((c) => c.mean_m < 3).length;

  return (
    <div className="bg-concrete rounded-lg border border-steel/10 p-4">
      <div className="flex items-start justify-between mb-3">
        <div>
          <h3 className="text-sm text-chalk font-telemetry">Throttle Onset</h3>
          <p className="text-[10px] text-steel/60 font-telemetry mt-0.5">
            Distance from apex before throttle application (m)
          </p>
        </div>
        <div className="flex items-center gap-2 text-[9px] font-telemetry">
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-green-400" />
            <span className="text-steel/60">Early (&lt;3m)</span>
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-red-400" />
            <span className="text-steel/60">Late (&gt;8m)</span>
          </span>
        </div>
      </div>
      <canvas
        ref={canvasRef}
        className="w-full"
        style={{ height: Math.max(data.length * 28 + 48, 120) }}
      />
      {earlyOnset > 0 && (
        <p className="text-[10px] text-steel/60 font-telemetry mt-2">
          {earlyOnset} corner{earlyOnset > 1 ? 's' : ''} with early throttle onset — good exit discipline.
        </p>
      )}
    </div>
  );
}
