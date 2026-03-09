/**
 * CornerSpeedTrend.tsx — Plot minimum (apex) speed per corner across all laps.
 *
 * Fetches per-lap corner metrics from the backend and draws a line chart
 * with lap number on X-axis and apex speed (km/h) on Y-axis.
 */
'use client';

import { useEffect, useRef, useState, useMemo } from 'react';
import { BACKEND_URL } from '@/lib/api-client';

interface CornerMetric {
  lap_number: number;
  corner_id: number;
  apex_speed_mps: number | null;
  entry_speed_mps?: number | null;
  exit_speed_mps?: number | null;
}

interface CornerSpeedTrendProps {
  sessionId: string;
}

const CORNER_COLORS = [
  '#3ddc84', '#58a6ff', '#ff8c42', '#d29922', '#f472b6',
  '#a78bfa', '#34d399', '#fb923c', '#38bdf8', '#e879f9',
];

export function CornerSpeedTrend({ sessionId }: CornerSpeedTrendProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [metrics, setMetrics] = useState<CornerMetric[]>([]);
  const [available, setAvailable] = useState(true);

  useEffect(() => {
    fetch(`${BACKEND_URL}/api/v1/sessions/${sessionId}/corners/per-lap`, {
      credentials: 'include',
    })
      .then((r) => r.json())
      .then((json) => {
        const d = json.data ?? json;
        if (!d.available || !d.metrics?.length) {
          setAvailable(false);
          return;
        }
        setMetrics(d.metrics);
      })
      .catch(() => setAvailable(false));
  }, [sessionId]);

  // Group by corner_id
  const cornerSeries = useMemo(() => {
    const byCorner: Record<number, { lap: number; speed: number }[]> = {};
    for (const m of metrics) {
      if (m.apex_speed_mps == null) continue;
      if (!byCorner[m.corner_id]) byCorner[m.corner_id] = [];
      byCorner[m.corner_id].push({
        lap: m.lap_number,
        speed: m.apex_speed_mps * 3.6, // m/s → km/h
      });
    }
    // Sort each series by lap
    for (const cid of Object.keys(byCorner)) {
      byCorner[Number(cid)].sort((a, b) => a.lap - b.lap);
    }
    return byCorner;
  }, [metrics]);

  const cornerIds = useMemo(
    () => Object.keys(cornerSeries).map(Number).sort((a, b) => a - b),
    [cornerSeries],
  );

  // Draw
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || cornerIds.length === 0) return;

    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth || 400;
    const h = 200;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = `${w}px`;
    canvas.style.height = `${h}px`;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    // Background
    ctx.fillStyle = '#1a1f2e';
    ctx.fillRect(0, 0, w, h);

    // Compute global ranges
    let minLap = Infinity, maxLap = -Infinity;
    let minSpd = Infinity, maxSpd = -Infinity;
    for (const cid of cornerIds) {
      for (const pt of cornerSeries[cid]) {
        if (pt.lap < minLap) minLap = pt.lap;
        if (pt.lap > maxLap) maxLap = pt.lap;
        if (pt.speed < minSpd) minSpd = pt.speed;
        if (pt.speed > maxSpd) maxSpd = pt.speed;
      }
    }
    if (minLap === maxLap) maxLap = minLap + 1;
    const spdRange = maxSpd - minSpd || 1;
    minSpd -= spdRange * 0.05;
    maxSpd += spdRange * 0.1;

    const pad = { top: 20, right: 80, bottom: 30, left: 50 };
    const pW = w - pad.left - pad.right;
    const pH = h - pad.top - pad.bottom;

    const xToPixel = (lap: number) => pad.left + ((lap - minLap) / (maxLap - minLap)) * pW;
    const yToPixel = (spd: number) => pad.top + pH - ((spd - minSpd) / (maxSpd - minSpd)) * pH;

    // Grid
    ctx.strokeStyle = '#30363d';
    ctx.lineWidth = 0.5;
    for (let i = 0; i < 5; i++) {
      const y = pad.top + (pH / 4) * i;
      ctx.beginPath();
      ctx.moveTo(pad.left, y);
      ctx.lineTo(pad.left + pW, y);
      ctx.stroke();
    }

    // Axis labels
    ctx.fillStyle = '#8b949e';
    ctx.font = '10px -apple-system, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    for (let lap = minLap; lap <= maxLap; lap++) {
      ctx.fillText(String(lap), xToPixel(lap), pad.top + pH + 6);
    }
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    for (let i = 0; i < 5; i++) {
      const spd = minSpd + ((maxSpd - minSpd) / 4) * (4 - i);
      ctx.fillText(spd.toFixed(0), pad.left - 6, pad.top + (pH / 4) * i);
    }

    // Title labels
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillText('Lap', pad.left + pW / 2, h - 5);
    ctx.save();
    ctx.translate(12, pad.top + pH / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText('Apex Speed (km/h)', 0, 0);
    ctx.restore();

    // Draw lines per corner
    for (let ci = 0; ci < cornerIds.length; ci++) {
      const cid = cornerIds[ci];
      const pts = cornerSeries[cid];
      const color = CORNER_COLORS[ci % CORNER_COLORS.length];

      ctx.strokeStyle = color;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      for (let i = 0; i < pts.length; i++) {
        const x = xToPixel(pts[i].lap);
        const y = yToPixel(pts[i].speed);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();

      // Dots
      for (const pt of pts) {
        ctx.beginPath();
        ctx.arc(xToPixel(pt.lap), yToPixel(pt.speed), 2.5, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.fill();
      }

      // Legend label on the right
      const lastPt = pts[pts.length - 1];
      ctx.fillStyle = color;
      ctx.font = '9px -apple-system, sans-serif';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'middle';
      ctx.fillText(`T${cid}`, pad.left + pW + 6, yToPixel(lastPt.speed));
    }
  }, [cornerIds, cornerSeries]);

  if (!available || cornerIds.length === 0) {
    return (
      <div className="text-steel/60 text-sm text-center p-4">
        No per-lap corner speed data available
      </div>
    );
  }

  return (
    <canvas
      ref={canvasRef}
      className="w-full"
      style={{ height: 200 }}
      aria-label="Line chart showing apex speed per corner across laps"
    />
  );
}
