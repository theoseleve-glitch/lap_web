'use client';

import { useRef, useEffect, useCallback, useMemo } from 'react';
import type { TheoreticalData, GpsTrace } from './useCornerData';
import { useChartHoverStore } from '@/lib/chart-hover-store';

interface FullLapTraceProps {
  theoretical: TheoreticalData | null;
  gpsTrace: GpsTrace | null;
}

const CHART_H = 160;
const PAD = { top: 20, right: 16, bottom: 28, left: 48 };

export function FullLapTrace({ theoretical, gpsTrace }: FullLapTraceProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  const hasTheo = !!(theoretical && theoretical.speeds?.length > 1 && theoretical.distances?.length > 1);
  const hasGps = !!(gpsTrace && gpsTrace.speeds?.length > 1 && gpsTrace.distances?.length > 1);

  // Debug — remove after confirming
  if (typeof window !== 'undefined') {
    console.log('[FullLapTrace]', { hasTheo, hasGps, theoSpeeds: theoretical?.speeds?.length, theoDists: theoretical?.distances?.length, gpsSpeeds: gpsTrace?.speeds?.length });
  }

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap || (!hasTheo && !hasGps)) return;

    const dpr = window.devicePixelRatio || 1;
    const w = wrap.clientWidth;
    const h = CHART_H;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = `${w}px`;
    canvas.style.height = `${h}px`;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const plotW = w - PAD.left - PAD.right;
    const plotH = h - PAD.top - PAD.bottom;

    // Gather all speeds to compute Y range
    const allSpeeds: number[] = [];
    if (hasGps) {
      for (const s of gpsTrace!.speeds) allSpeeds.push(s * 3.6);
    }
    if (hasTheo) {
      for (const s of theoretical!.speeds) allSpeeds.push(s * 3.6);
    }
    if (allSpeeds.length === 0) return;

    const yMin = Math.floor(Math.min(...allSpeeds) / 5) * 5;
    const yMax = Math.ceil(Math.max(...allSpeeds) / 5) * 5;
    const ySpan = yMax - yMin || 1;

    // Determine X range — use GPS distance range as primary
    let xMin = 0;
    let xMax = 1000;
    if (hasGps) {
      xMin = gpsTrace!.distances[0];
      xMax = gpsTrace!.distances[gpsTrace!.distances.length - 1];
    } else if (hasTheo) {
      xMin = theoretical!.distances[0];
      xMax = theoretical!.distances[theoretical!.distances.length - 1];
    }
    const xSpan = xMax - xMin || 1;

    const toX = (d: number) => PAD.left + ((d - xMin) / xSpan) * plotW;
    const toY = (s: number) => PAD.top + (1 - (s - yMin) / ySpan) * plotH;

    // Background
    ctx.fillStyle = '#1a1a1a';
    ctx.fillRect(0, 0, w, h);

    // Grid lines
    ctx.strokeStyle = 'rgba(136, 136, 136, 0.15)';
    ctx.lineWidth = 1;
    const ySteps = 5;
    for (let i = 0; i <= ySteps; i++) {
      const yVal = yMin + (ySpan / ySteps) * i;
      const py = toY(yVal);
      ctx.beginPath();
      ctx.moveTo(PAD.left, py);
      ctx.lineTo(w - PAD.right, py);
      ctx.stroke();
    }

    // Y-axis labels
    ctx.fillStyle = '#888';
    ctx.font = '10px monospace';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    for (let i = 0; i <= ySteps; i++) {
      const yVal = yMin + (ySpan / ySteps) * i;
      ctx.fillText(`${Math.round(yVal)}`, PAD.left - 6, toY(yVal));
    }

    // X-axis labels
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    const xSteps = 5;
    for (let i = 0; i <= xSteps; i++) {
      const xVal = xMin + (xSpan / xSteps) * i;
      ctx.fillText(`${Math.round(xVal)}m`, toX(xVal), h - PAD.bottom + 8);
    }

    // Draw actual trace (white solid)
    if (hasGps) {
      ctx.beginPath();
      const gd = gpsTrace!.distances;
      const gs = gpsTrace!.speeds;
      ctx.moveTo(toX(gd[0]), toY(gs[0] * 3.6));
      for (let i = 1; i < gd.length; i++) {
        ctx.lineTo(toX(gd[i]), toY(gs[i] * 3.6));
      }
      ctx.strokeStyle = 'rgba(240, 237, 229, 0.8)';
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }

    // Draw theoretical trace (green dashed) — distances are 0-based, same as GPS
    if (hasTheo) {
      const td = theoretical!.distances;
      const ts = theoretical!.speeds;

      ctx.beginPath();
      ctx.setLineDash([6, 4]);
      ctx.moveTo(toX(td[0]), toY(ts[0] * 3.6));
      for (let i = 1; i < td.length; i++) {
        ctx.lineTo(toX(td[i]), toY(ts[i] * 3.6));
      }
      ctx.strokeStyle = '#C6F135';
      ctx.lineWidth = 1.5;
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // Legend
    const legendY = PAD.top - 12;
    ctx.font = '10px monospace';
    ctx.textAlign = 'left';

    if (hasGps) {
      ctx.strokeStyle = 'rgba(240, 237, 229, 0.8)';
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(PAD.left, legendY);
      ctx.lineTo(PAD.left + 20, legendY);
      ctx.stroke();
      ctx.fillStyle = '#888';
      ctx.fillText('Best lap', PAD.left + 26, legendY + 3);
    }

    if (hasTheo) {
      const lx = hasGps ? PAD.left + 90 : PAD.left;
      ctx.strokeStyle = '#C6F135';
      ctx.lineWidth = 1.5;
      ctx.setLineDash([4, 3]);
      ctx.beginPath();
      ctx.moveTo(lx, legendY);
      ctx.lineTo(lx + 20, legendY);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = '#888';
      ctx.fillText('Theoretical', lx + 26, legendY + 3);
    }
  }, [theoretical, gpsTrace, hasTheo, hasGps]);

  useEffect(() => { draw(); }, [draw]);

  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap) return;
    const ro = new ResizeObserver(() => draw());
    ro.observe(wrap);
    return () => ro.disconnect();
  }, [draw]);

  // ── Hover sync ─────────────────────────────────────
  const SYNC_ID = 'corners-speed-trace';
  const { hoverDistance, hoverSource, setHover, clearHover } = useChartHoverStore();
  const overlayRef = useRef<HTMLCanvasElement>(null);

  // Compute x-axis mapping for hover (reuse same xMin/xMax logic)
  const xRange = useMemo(() => {
    if (hasGps) return { min: gpsTrace!.distances[0], max: gpsTrace!.distances[gpsTrace!.distances.length - 1] };
    if (hasTheo) return { min: theoretical!.distances[0], max: theoretical!.distances[theoretical!.distances.length - 1] };
    return { min: 0, max: 1000 };
  }, [gpsTrace, theoretical, hasGps, hasTheo]);

  const handleChartMouseMove = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const wrap = wrapRef.current;
      if (!wrap) return;
      const rect = wrap.getBoundingClientRect();
      const cx = e.clientX - rect.left;
      const plotW = rect.width - PAD.left - PAD.right;
      const frac = (cx - PAD.left) / plotW;
      if (frac >= 0 && frac <= 1) {
        const dist = xRange.min + frac * (xRange.max - xRange.min);
        setHover(dist, SYNC_ID);
      }
    },
    [xRange, setHover],
  );

  const handleChartMouseLeave = useCallback(() => clearHover(), [clearHover]);

  // Draw crosshair overlay from sync
  useEffect(() => {
    const oc = overlayRef.current;
    const wrap = wrapRef.current;
    if (!oc || !wrap) return;
    const dpr = window.devicePixelRatio || 1;
    const w = wrap.clientWidth;
    const h = CHART_H;
    oc.width = w * dpr;
    oc.height = h * dpr;
    oc.style.width = `${w}px`;
    oc.style.height = `${h}px`;
    const ctx = oc.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    if (hoverDistance == null) return;

    const plotW = w - PAD.left - PAD.right;
    const frac = (hoverDistance - xRange.min) / (xRange.max - xRange.min);
    if (frac < 0 || frac > 1) return;
    const px = PAD.left + frac * plotW;

    // Vertical crosshair line
    ctx.beginPath();
    ctx.moveTo(px, PAD.top);
    ctx.lineTo(px, h - PAD.bottom);
    ctx.strokeStyle = 'rgba(198, 241, 53, 0.6)';
    ctx.lineWidth = 1;
    ctx.stroke();

    // Distance label
    ctx.fillStyle = '#C6F135';
    ctx.font = '10px monospace';
    ctx.textAlign = 'center';
    ctx.fillText(`${Math.round(hoverDistance)}m`, px, h - PAD.bottom + 8);
  }, [hoverDistance, xRange]);

  if (!hasTheo && !hasGps) return null;

  return (
    <div className="mt-4 border-b border-steel/10 pb-4">
      <p className="text-[10px] text-steel font-telemetry uppercase tracking-wider mb-2">
        Full Lap Speed Profile — Best vs Theoretical
      </p>
      <div ref={wrapRef} className="w-full relative">
        <canvas ref={canvasRef} style={{ display: 'block' }} />
        <canvas
          ref={overlayRef}
          className="absolute inset-0 cursor-crosshair"
          style={{ display: 'block' }}
          onMouseMove={handleChartMouseMove}
          onMouseLeave={handleChartMouseLeave}
        />
      </div>
    </div>
  );
}
