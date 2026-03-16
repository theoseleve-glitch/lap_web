'use client';

import { useRef, useEffect, useCallback } from 'react';
import type { CornerData, TheoCorner, TheoreticalData, GpsTrace } from './useCornerData';

/* ── Helpers ───────────────────────────────────────────── */

/** Find start/end indices where distances fall within [sStart, sEnd]. */
function sliceIndices(distances: number[], sStart: number, sEnd: number): [number, number] {
  let lo = 0;
  let hi = distances.length - 1;
  while (lo < distances.length && distances[lo]! < sStart) lo++;
  while (hi >= 0 && distances[hi]! > sEnd) hi--;
  return [lo, Math.max(lo, hi)];
}

/** Linearly interpolate srcY at srcX positions onto dstX positions. */
function interpolateOnto(srcX: number[], srcY: number[], dstX: number[]): number[] {
  const out: number[] = new Array<number>(dstX.length);
  let j = 0;
  for (let i = 0; i < dstX.length; i++) {
    const x = dstX[i]!;
    while (j < srcX.length - 2 && srcX[j + 1]! < x) j++;
    if (j >= srcX.length - 1) {
      out[i] = srcY[srcY.length - 1] ?? 0;
      continue;
    }
    const x0 = srcX[j]!;
    const x1 = srcX[j + 1]!;
    const y0 = srcY[j]!;
    const y1 = srcY[j + 1]!;
    const dx = x1 - x0;
    if (dx === 0) {
      out[i] = y0;
    } else {
      const t = (x - x0) / dx;
      out[i] = y0 + t * (y1 - y0);
    }
  }
  return out;
}

/** Build a common 100-point distance axis from sStart to sEnd. */
function commonAxis(sStart: number, sEnd: number, n: number): number[] {
  const out: number[] = new Array<number>(n);
  const step = (sEnd - sStart) / (n - 1);
  for (let i = 0; i < n; i++) out[i] = sStart + i * step;
  return out;
}

const CHART_H = 200;
const PAD = { top: 12, right: 16, bottom: 28, left: 44 };
const N_POINTS = 100;

/* ── Component ─────────────────────────────────────────── */

interface TheoreticalBestPanelProps {
  corner: CornerData;
  theoCorner: TheoCorner | null;
  theoretical: TheoreticalData | null;
  gpsTrace: GpsTrace | null;
}

export function TheoreticalBestPanel({
  corner,
  theoCorner,
  theoretical,
  gpsTrace,
}: TheoreticalBestPanelProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap || !(theoretical && theoretical.speeds?.length > 0)) return;

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

    const { s_start, s_end } = corner;

    /* ── Distance alignment ──────────────────────────────── */
    // Corner s_start/s_end are session-cumulative (e.g., 5806m).
    // Theoretical distances are also cumulative → slice directly.
    // GPS trace distances are per-lap (e.g., 0-1200m) → need modulo mapping.
    //
    // Strategy: use cumulative corner range as the common chart axis.
    // Theoretical trace slices directly. GPS trace gets mapped.

    const axis = commonAxis(s_start, s_end, N_POINTS);
    const theoDists = theoretical.distances;
    const gpsDists = gpsTrace?.distances ?? [];

    /* Slice + interpolate theoretical trace (cumulative → cumulative, direct) */
    let theoSpeeds: number[] | null = null;
    if (theoDists.length > 1 && theoretical.speeds.length > 1) {
      const [lo, hi] = sliceIndices(theoDists, s_start, s_end);
      if (hi > lo) {
        const slicedDist = theoDists.slice(lo, hi + 1);
        const slicedSpd = theoretical.speeds.slice(lo, hi + 1);
        const slicedKmh = slicedSpd.map((v) => v * 3.6);
        theoSpeeds = interpolateOnto(slicedDist, slicedKmh, axis);
      }
    }

    /* Slice + interpolate actual GPS trace (per-lap → remap to cumulative) */
    let actualSpeeds: number[] | null = null;
    if (gpsTrace && gpsDists.length > 1 && gpsTrace.speeds.length > 1) {
      const gpsMax = gpsDists[gpsDists.length - 1];
      const gpsMin = gpsDists[0];
      const lapLen = gpsMax - gpsMin;

      if (lapLen > 0) {
        // Use same lap offset for both start and end to avoid wrap-around split.
        // Compute which lap s_start falls on, subtract that offset.
        const lapOffset = Math.floor((s_start - gpsMin) / lapLen) * lapLen;
        const perLapStart = s_start - lapOffset;
        const perLapEnd = s_end - lapOffset;

        // Clamp to GPS range
        const clampedStart = Math.max(gpsMin, perLapStart);
        const clampedEnd = Math.min(gpsMax, perLapEnd);

        if (clampedEnd > clampedStart) {
          const [lo, hi] = sliceIndices(gpsDists, clampedStart, clampedEnd);
          if (hi > lo) {
            const slicedDist = gpsDists.slice(lo, hi + 1);
            const slicedSpd = gpsTrace.speeds.slice(lo, hi + 1);
            // Remap GPS distances back to cumulative for chart axis alignment
            const remappedDist = slicedDist.map((d) => d + lapOffset);
            const slicedKmh = slicedSpd.map((v) => v * 3.6);
            actualSpeeds = interpolateOnto(remappedDist, slicedKmh, axis);
          }
        }
      }
    }

    /* Y range */
    const allValues: number[] = [];
    if (actualSpeeds) allValues.push(...actualSpeeds);
    if (theoSpeeds) allValues.push(...theoSpeeds);
    if (allValues.length === 0) return;

    const yMin = Math.floor(Math.min(...allValues) / 5) * 5;
    const yMax = Math.ceil(Math.max(...allValues) / 5) * 5 || yMin + 10;

    const plotW = w - PAD.left - PAD.right;
    const plotH = h - PAD.top - PAD.bottom;
    const xOf = (d: number) => PAD.left + ((d - s_start) / (s_end - s_start)) * plotW;
    const yOf = (v: number) => PAD.top + (1 - (v - yMin) / (yMax - yMin)) * plotH;

    ctx.clearRect(0, 0, w, h);

    /* Delta shading */
    if (actualSpeeds && theoSpeeds) {
      for (let i = 0; i < N_POINTS - 1; i++) {
        const ax0 = axis[i]!;
        const ax1 = axis[i + 1]!;
        const aSpd = actualSpeeds[i]!;
        const aSpd1 = actualSpeeds[i + 1]!;
        const tSpd = theoSpeeds[i]!;
        const tSpd1 = theoSpeeds[i + 1]!;
        const faster = aSpd >= tSpd;
        ctx.fillStyle = faster ? 'rgba(0,200,100,0.15)' : 'rgba(220,50,50,0.15)';
        ctx.beginPath();
        ctx.moveTo(xOf(ax0), yOf(aSpd));
        ctx.lineTo(xOf(ax1), yOf(aSpd1));
        ctx.lineTo(xOf(ax1), yOf(tSpd1));
        ctx.lineTo(xOf(ax0), yOf(tSpd));
        ctx.closePath();
        ctx.fill();
      }
    }

    /* Axis grid + labels */
    ctx.font = '10px monospace';
    ctx.fillStyle = '#888';
    ctx.strokeStyle = 'rgba(136,136,136,0.15)';
    ctx.lineWidth = 1;

    // Y ticks
    const yStep = Math.max(1, Math.round((yMax - yMin) / 5));
    for (let v = yMin; v <= yMax; v += yStep) {
      const y = yOf(v);
      ctx.beginPath();
      ctx.moveTo(PAD.left, y);
      ctx.lineTo(w - PAD.right, y);
      ctx.stroke();
      ctx.textAlign = 'right';
      ctx.textBaseline = 'middle';
      ctx.fillText(`${v}`, PAD.left - 6, y);
    }

    // X ticks
    const xRange = s_end - s_start;
    const xStep = Math.max(1, Math.round(xRange / 5));
    for (let d = Math.ceil(s_start / xStep) * xStep; d <= s_end; d += xStep) {
      const x = xOf(d);
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      ctx.fillText(`${Math.round(d)}m`, x, h - PAD.bottom + 8);
    }

    /* Actual trace -- solid white */
    if (actualSpeeds) {
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 2;
      ctx.setLineDash([]);
      ctx.beginPath();
      for (let i = 0; i < N_POINTS; i++) {
        const x = xOf(axis[i]!);
        const y = yOf(actualSpeeds[i]!);
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      }
      ctx.stroke();
    }

    /* Theoretical trace -- dashed acid-green */
    if (theoSpeeds) {
      ctx.strokeStyle = '#b4ff39';
      ctx.lineWidth = 2;
      ctx.setLineDash([6, 4]);
      ctx.beginPath();
      for (let i = 0; i < N_POINTS; i++) {
        const x = xOf(axis[i]!);
        const y = yOf(theoSpeeds[i]!);
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      }
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }, [corner, theoretical, gpsTrace]);

  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap) return;
    draw();
    const ro = new ResizeObserver(() => draw());
    ro.observe(wrap);
    return () => ro.disconnect();
  }, [draw]);

  /* ── Empty state ─────────────────────────────────────── */

  if (!theoretical && theoretical.speeds?.length > 0) {
    return (
      <div className="py-8 text-center">
        <p className="text-steel text-sm">
          Theoretical lap not available for this session
        </p>
      </div>
    );
  }

  /* ── Metrics ─────────────────────────────────────────── */

  const apexKmh = theoCorner?.theoretical_apex_speed_mps != null
    ? (theoCorner.theoretical_apex_speed_mps * 3.6).toFixed(1)
    : null;

  const exitKmh = theoCorner?.theoretical_exit_speed_mps != null
    ? (theoCorner.theoretical_exit_speed_mps * 3.6).toFixed(1)
    : null;

  const brakePoint = corner.brake_release != null
    ? (corner.brake_release as Record<string, unknown>).brake_point_theory_m
    : null;
  const brakeStr = brakePoint != null ? `${Number(brakePoint).toFixed(1)}m` : null;

  const method = theoretical.simulation_method ?? null;

  const metrics: { label: string; value: string }[] = [
    { label: 'Theo. Apex', value: apexKmh ? `${apexKmh} km/h` : '\u2014' },
    { label: 'Brake Point', value: brakeStr ?? '\u2014' },
    { label: 'Theo. Exit', value: exitKmh ? `${exitKmh} km/h` : '\u2014' },
    { label: 'Method', value: method ?? '\u2014' },
  ];

  return (
    <div>
      <div ref={wrapRef} className="w-full" style={{ height: CHART_H }}>
        <canvas ref={canvasRef} />
      </div>
      <div className="flex gap-6 mt-3">
        {metrics.map((m) => (
          <div key={m.label}>
            <div className="text-[10px] text-steel uppercase">{m.label}</div>
            <div className="text-sm font-telemetry text-chalk">{m.value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
