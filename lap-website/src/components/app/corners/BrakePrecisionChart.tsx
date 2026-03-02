'use client';

import { useEffect, useState, useRef, useCallback } from 'react';
import { api } from '@/lib/api-client';

interface BrakeData {
  corner_id: number;
  braking_point_delta_m: number;
  direction?: 'L' | 'R';
}

interface BrakePrecisionResponse {
  brake_data: BrakeData[];
}

interface BrakePrecisionChartProps {
  sessionId: string;
}

function deltaColor(absVal: number): string {
  if (absVal < 2) return '#4ade80';   // green-400
  if (absVal <= 5) return '#facc15';  // yellow-400
  return '#f87171';                    // red-400
}

function drawBrakeChart(canvas: HTMLCanvasElement, brakeData: BrakeData[]) {
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
  const rightPad = 40;
  const topPad = 24;
  const bottomPad = 24;
  const chartW = W - labelWidth - rightPad;
  const chartH = H - topPad - bottomPad;
  const n = brakeData.length;
  if (n === 0) return;

  // Background
  ctx.fillStyle = '#0B0C0F';
  ctx.fillRect(0, 0, W, H);

  // Find max absolute delta for scale
  const maxAbs = Math.max(
    ...brakeData.map((d) => Math.abs(d.braking_point_delta_m)),
    1,
  );
  const scale = (chartW / 2) / maxAbs;
  const cx = labelWidth + chartW / 2;
  const barH = Math.min(chartH / n - 2, 18);

  // Center line
  ctx.strokeStyle = 'rgba(255,255,255,0.15)';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(cx, topPad);
  ctx.lineTo(cx, topPad + chartH);
  ctx.stroke();

  // Axis labels
  ctx.fillStyle = 'rgba(138,143,152,0.5)';
  ctx.font = '9px system-ui, sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText('Early', labelWidth + chartW * 0.25, topPad - 6);
  ctx.fillText('Late', labelWidth + chartW * 0.75, topPad - 6);

  // Draw bars
  brakeData.forEach((d, i) => {
    const y = topPad + (i * chartH) / n + (chartH / n - barH) / 2;
    const delta = d.braking_point_delta_m;
    const barW = Math.abs(delta) * scale;
    const color = deltaColor(Math.abs(delta));

    // Bar
    ctx.fillStyle = color;
    if (delta < 0) {
      // Early = left of center
      ctx.fillRect(cx - barW, y, barW, barH);
    } else {
      // Late = right of center
      ctx.fillRect(cx, y, barW, barH);
    }

    // Corner label on left
    ctx.fillStyle = 'rgba(243,240,232,0.7)';
    ctx.font = '10px monospace';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    ctx.fillText(`C${d.corner_id}`, labelWidth - 6, y + barH / 2);

    // Delta value at bar end
    ctx.fillStyle = color;
    ctx.font = '9px monospace';
    ctx.textAlign = delta < 0 ? 'right' : 'left';
    const valX = delta < 0 ? cx - barW - 4 : cx + barW + 4;
    ctx.fillText(`${delta > 0 ? '+' : ''}${delta.toFixed(1)}m`, valX, y + barH / 2);
  });
}

export function BrakePrecisionChart({ sessionId }: BrakePrecisionChartProps) {
  const [data, setData] = useState<BrakeData[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .get<BrakePrecisionResponse>(`/sessions/${sessionId}/brake-precision`)
      .then((res) => {
        if (!cancelled) setData(res.brake_data);
      })
      .catch((err) => {
        if (!cancelled) setError((err as Error)?.message ?? 'Failed to load');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  const draw = useCallback(() => {
    if (canvasRef.current && data && data.length > 0) {
      drawBrakeChart(canvasRef.current, data);
    }
  }, [data]);

  // Draw on data change
  useEffect(() => {
    draw();
  }, [draw]);

  // Redraw on resize
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
        <h3 className="text-sm text-chalk font-telemetry mb-2">Brake Precision</h3>
        <p className="text-xs text-steel">{error}</p>
      </div>
    );
  }

  if (!data || data.length === 0) {
    return (
      <div className="bg-concrete rounded-lg border border-steel/10 p-4">
        <h3 className="text-sm text-chalk font-telemetry mb-2">Brake Precision</h3>
        <p className="text-xs text-steel">No braking data available.</p>
      </div>
    );
  }

  return (
    <div className="bg-concrete rounded-lg border border-steel/10 p-4">
      <h3 className="text-sm text-chalk font-telemetry mb-2">Brake Precision</h3>
      <canvas
        ref={canvasRef}
        className="w-full"
        style={{ height: Math.max(data.length * 28 + 48, 120) }}
      />
    </div>
  );
}
