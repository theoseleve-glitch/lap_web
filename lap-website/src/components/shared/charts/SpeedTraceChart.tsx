/**
 * SpeedTraceChart.tsx — Pure React speed-vs-distance chart.
 *
 * Architecture mirrors CornerReplayCockpit: useRef<canvas>, pure draw function,
 * useEffect for rendering, ResizeObserver for responsiveness. No vanilla JS
 * modules, no DOMContentLoaded, no window globals.
 *
 * Fetches data from:
 *   GET /api/v1/sessions/{id}/speed-trace?lap=N     (distances, speeds)
 *   GET /api/v1/sessions/{id}/speed-trace?lap=N&avg=1 (avg_speeds overlay)
 */
'use client';

import { useEffect, useRef, useState, useCallback, useMemo } from 'react';
import { api } from '@/lib/api-client';
import { useChartHoverStore } from '@/lib/chart-hover-store';
import { useReferenceOverlay } from '@/components/app/reference';
import { chartColor } from '@/components/shared/chart-kit';
import { fetchDrivingEvents, type DrivingEvent, type DrivingEventsResponse } from '@/lib/driving-events';
import { makeTapeGeometry, drawMistakeTape, drawCornerShade } from '@/lib/driving-events-draw';

// ── Types ────────────────────────────────────────────────────────
interface SpeedTraceData {
  distances: number[];
  speeds: number[];
  ref_speeds?: number[];
  avg_speeds?: number[];
  available?: boolean;
}

interface SpeedTraceChartProps {
  sessionId?: string;
  data?: SpeedTraceData;
  onHoverDistance?: (d: number) => void;
  className?: string;
  gpsLaps?: number[];
  bestLap?: number | null;
  apiBase?: string;
  /** When set, fetches ref lap and draws delta time sub-chart */
  compareLap?: number | null;
  /** Actual lap time of the primary lap (seconds) */
  primaryLapTime?: number | null;
  /** Actual lap time of the compare lap (seconds) */
  compareLapTime?: number | null;
  /** When true, lap selection is controlled by parent (hides per-chart selector) */
  controlledLap?: boolean;
  /** Distance zoom range [startM, endM]. When set, x-axis crops to this window. */
  distRange?: [number, number] | null;
  /** Callback when user drag-selects a distance range on the chart. */
  onDistRangeChange?: (range: [number, number] | null) => void;
  /** When true, fetches and overlays the theoretical optimal speed profile */
  showTheoretical?: boolean;
  /** When true, fetches and overlays the aggregate physics ceiling */
  showPhysicsCeiling?: boolean;
  /** When true, fetches Phase 2 driving events and overlays the mistake tape */
  showDrivingEvents?: boolean;
}

// ── Helpers ──────────────────────────────────────────────────────
function speedColor(speed: number, min: number, max: number): string {
  let t = max > min ? (speed - min) / (max - min) : 0.5;
  t = Math.max(0, Math.min(1, t));
  let r: number, g: number, b: number;
  if (t < 0.25) {
    r = 0; g = Math.round(255 * (t / 0.25)); b = 255;
  } else if (t < 0.5) {
    r = 0; g = 255; b = Math.round(255 * (1 - (t - 0.25) / 0.25));
  } else if (t < 0.75) {
    r = Math.round(255 * ((t - 0.5) / 0.25)); g = 255; b = 0;
  } else {
    r = 255; g = Math.round(255 * (1 - (t - 0.75) / 0.25)); b = 0;
  }
  return `rgb(${r},${g},${b})`;
}

function niceRange(lo: number, hi: number, count: number): number[] {
  const range = hi - lo;
  if (range <= 0) return [lo];
  const step = range / count;
  const mag = Math.pow(10, Math.floor(Math.log10(step)));
  const residual = step / mag;
  let niceStep: number;
  if (residual <= 1.5) niceStep = 1;
  else if (residual <= 3) niceStep = 2;
  else if (residual <= 7) niceStep = 5;
  else niceStep = 10;
  niceStep *= mag;

  const ticks: number[] = [];
  const start = Math.ceil(lo / niceStep) * niceStep;
  for (let v = start; v <= hi; v += niceStep) {
    ticks.push(v);
  }
  return ticks;
}

function closestIndex(arr: number[], target: number): number {
  if (!arr || arr.length === 0) return -1;
  let lo = 0, hi = arr.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if ((arr[mid] ?? 0) < target) lo = mid + 1;
    else hi = mid;
  }
  if (lo > 0 && Math.abs((arr[lo - 1] ?? 0) - target) < Math.abs((arr[lo] ?? 0) - target)) {
    return lo - 1;
  }
  return lo;
}

// ── Pure draw function ───────────────────────────────────────────
interface DrawOptions {
  distances: number[];
  speeds: number[];       // m/s
  avgSpeeds?: number[];   // m/s
  refSpeeds?: number[];   // m/s
  theoreticalSpeeds?: { distances: number[]; speeds: number[] } | null; // kph, own distance axis
  ceilingSpeeds?: { distances: number[]; speeds: number[]; sessions: number } | null;
  hoverDistanceM: number | null;
  /** When set, ref line legend shows "Lap N" instead of "Theoretical" */
  refLapLabel?: string | null;
  /** Primary lap label shown in legend */
  primaryLapLabel?: string | null;
  /** Distance zoom override [startM, endM] */
  distRange?: [number, number] | null;
  /** Pixel range of active drag selection [startPx, endPx] */
  dragSelection?: [number, number] | null;
  /** Cross-session reference overlay data */
  crossRefDistances?: number[] | null;
  crossRefSpeeds?: number[] | null;   // m/s
  crossRefDeltaS?: number[] | null;   // delta_s: positive = ref slower = primary faster
  crossRefLabel?: string | null;
  /** Phase 2 driving events to overlay as a tape. Null = not requested or unavailable. */
  drivingEvents?: DrivingEvent[] | null;
  /**
   * The lap number the speed curve below the tape belongs to. REQUIRED
   * whenever `drivingEvents` is set; without it no tape is drawn.
   *
   * `GET /driving-events` returns the session's top-N ranked corner-laps
   * across EVERY lap, while `GET /speed-trace?lap=` returns exactly one.
   * Painting the former over the latter puts another lap's mistake on this
   * lap's curve: a red band at turn 3 with nothing wrong in the speed trace
   * underneath it, because the event was lap 2. The ranked panel discloses
   * the lap ("C3 L1"); the tape is a pixel-level claim about THIS trace and
   * cannot. Spec §2 line 27 and §5 line 214 both say per-lap.
   */
  drivingEventsLap?: number | null;
}

// Height of the cross-session delta bar strip (see "Cross-session delta bar"
// below). Shared with the driving-event tape's stacking offset so the two
// can never drift apart — the tape sits directly above this band instead of
// under it, rather than each side hardcoding its own copy of "10".
// Exported so the stacking test shares this ONE source of truth. It used
// to keep its own literal 10, which is the same drift risk the constant
// exists to remove -- just pushed one layer out into the test.
export const CROSS_SESSION_BAR_H = 10;

// Exported for direct testing of layering/stacking behaviour (e.g. the
// mistake tape vs. the cross-session delta bar) with a canvas-recorder
// stub, mirroring how driving-events-draw.ts's pure draw functions are
// tested — no DOM, no real canvas.
export function drawSpeedTrace(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  opts: DrawOptions,
): { xMin: number; xMax: number; yMin: number; yMax: number; plotX: number; plotY: number; plotW: number; plotH: number } | null {
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = chartColor.surface;
  ctx.fillRect(0, 0, w, h);

  const { distances, speeds, avgSpeeds, refSpeeds, hoverDistanceM } = opts;
  if (!distances || distances.length < 2) {
    ctx.fillStyle = chartColor.textSecondary;
    ctx.font = '13px "Space Mono", monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('No speed trace data', w / 2, h / 2);
    return null;
  }

  const pad = { top: 20, right: 20, bottom: 50, left: 60 };
  const pW = w - pad.left - pad.right;
  const pH = h - pad.top - pad.bottom;

  // Data ranges — use loop-based max to avoid stack overflow on large arrays
  const safeMax = (arr: number[]): number => {
    let m = -Infinity;
    for (const v of arr) { if (v != null && isFinite(v) && v > m) m = v; }
    return m === -Infinity ? 0 : m;
  };
  const safeMin = (arr: number[]): number => {
    let m = Infinity;
    for (const v of arr) { if (v != null && isFinite(v) && v < m) m = v; }
    return m === Infinity ? 0 : m;
  };
  const validSpeeds = speeds.filter((s): s is number => s != null && isFinite(s));
  const xMin = opts.distRange ? opts.distRange[0] : 0;
  const xMax = opts.distRange ? opts.distRange[1] : (safeMax(distances) || 1);

  // When zoomed, compute yMin/yMax from visible speeds only
  let visibleSpeeds = validSpeeds;
  if (opts.distRange) {
    visibleSpeeds = [];
    for (let i = 0; i < distances.length; i++) {
      if (distances[i] >= xMin && distances[i] <= xMax && speeds[i] != null && isFinite(speeds[i])) {
        visibleSpeeds.push(speeds[i]);
      }
    }
  }
  const yMin = 0;
  let yMax = (visibleSpeeds.length > 0 ? safeMax(visibleSpeeds) : 1) * 3.6 * 1.1;

  // Extend yMax for reference/avg overlays
  if (refSpeeds && refSpeeds.length > 0) {
    const refMax = safeMax(refSpeeds) * 3.6 * 1.1;
    if (refMax > yMax) yMax = refMax;
  }
  if (avgSpeeds && avgSpeeds.length > 0) {
    const avgMax = safeMax(avgSpeeds) * 3.6 * 1.1;
    if (avgMax > yMax) yMax = avgMax;
  }
  if (opts.theoreticalSpeeds && opts.theoreticalSpeeds.speeds.length > 0) {
    const theoMax = safeMax(opts.theoreticalSpeeds.speeds) * 1.1; // already kph
    if (theoMax > yMax) yMax = theoMax;
  }
  if (opts.ceilingSpeeds && opts.ceilingSpeeds.speeds.length > 0) {
    const ceilMax = safeMax(opts.ceilingSpeeds.speeds) * 1.1;
    if (ceilMax > yMax) yMax = ceilMax;
  }
  if (opts.crossRefSpeeds && opts.crossRefSpeeds.length > 0) {
    const xRefMax = safeMax(opts.crossRefSpeeds) * 3.6 * 1.1;
    if (xRefMax > yMax) yMax = xRefMax;
  }
  if (yMax <= yMin) yMax = yMin + 1;

  const bounds = { xMin, xMax, yMin, yMax, plotX: pad.left, plotY: pad.top, plotW: pW, plotH: pH };

  const xToPixel = (v: number) => pad.left + (v - xMin) / (xMax - xMin) * pW;
  const yToPixel = (v: number) => pad.top + pH - (v - yMin) / (yMax - yMin) * pH;

  // Grid lines
  ctx.strokeStyle = chartColor.grid;
  ctx.lineWidth = 0.5;
  const yTicks = niceRange(yMin, yMax, 5);
  for (const tick of yTicks) {
    const y = yToPixel(tick);
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(w - pad.right, y);
    ctx.stroke();
  }
  const xTicks = niceRange(xMin, xMax, 6);
  for (const tick of xTicks) {
    const x = xToPixel(tick);
    ctx.beginPath();
    ctx.moveTo(x, pad.top);
    ctx.lineTo(x, pad.top + pH);
    ctx.stroke();
  }

  // Y-axis labels
  ctx.fillStyle = chartColor.textSecondary;
  ctx.font = '11px "Space Mono", monospace';
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  for (const tick of yTicks) {
    ctx.fillText(tick.toFixed(0), pad.left - 8, yToPixel(tick));
  }

  // X-axis labels
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  for (const tick of xTicks) {
    ctx.fillText(`${tick.toFixed(0)}m`, xToPixel(tick), pad.top + pH + 8);
  }

  // Axis titles
  ctx.fillStyle = chartColor.textSecondary;
  ctx.font = '12px "Space Mono", monospace';
  ctx.textAlign = 'center';
  // Compact unit labels — no full axis titles (tick labels are self-explanatory)
  ctx.font = '10px "Space Mono", monospace';
  ctx.fillStyle = chartColor.textSecondary;
  ctx.textAlign = 'left';
  ctx.fillText('km/h', pad.left + 2, pad.top - 4);
  ctx.textAlign = 'right';
  ctx.fillText('m', pad.left + pW, pad.top + pH + 26);

  // Legend y-offset tracker
  let legendY = pad.top + 4;

  // Clip all trace lines to the plot area (inside axes)
  ctx.save();
  ctx.beginPath();
  ctx.rect(pad.left, pad.top, pW, pH);
  ctx.clip();

  // Theoretical optimal speed (dashed chalk — drawn first so it sits behind actual)
  if (opts.theoreticalSpeeds && opts.theoreticalSpeeds.distances.length > 0) {
    const td = opts.theoreticalSpeeds.distances;
    const ts = opts.theoreticalSpeeds.speeds; // already kph
    ctx.save();
    ctx.setLineDash([6, 4]);
    ctx.strokeStyle = 'rgba(240, 237, 229, 0.6)'; // chalk at 60%
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    let started = false;
    for (let i = 0; i < td.length; i++) {
      const x = xToPixel(td[i]);
      const y = yToPixel(ts[i]);
      if (x < pad.left || x > pad.left + pW) continue;
      if (!started) { ctx.moveTo(x, y); started = true; } else { ctx.lineTo(x, y); }
    }
    ctx.stroke();
    ctx.restore();
    ctx.fillStyle = chartColor.text;
    ctx.globalAlpha = 0.6;
    ctx.font = '10px "Space Mono", monospace';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    ctx.fillText('- - Theoretical', pad.left + 8, legendY);
    ctx.globalAlpha = 1.0;
    legendY += 12;
  }

  // Physics ceiling from aggregate track surface (dashed gold, filled area)
  if (opts.ceilingSpeeds && opts.ceilingSpeeds.distances.length > 0) {
    const cd = opts.ceilingSpeeds.distances;
    const cs = opts.ceilingSpeeds.speeds;

    // Fill area between actual speed and ceiling
    ctx.save();
    ctx.globalAlpha = 0.08;
    ctx.fillStyle = chartColor.series.primary;
    ctx.beginPath();
    let fillStarted = false;
    for (let i = 0; i < cd.length; i++) {
      const x = xToPixel(cd[i]);
      if (x < pad.left || x > pad.left + pW) continue;
      const y = yToPixel(cs[i]);
      if (!fillStarted) { ctx.moveTo(x, y); fillStarted = true; } else { ctx.lineTo(x, y); }
    }
    if (fillStarted && distances.length > 0) {
      for (let i = cd.length - 1; i >= 0; i--) {
        const x = xToPixel(cd[i]);
        if (x < pad.left || x > pad.left + pW) continue;
        const idx = closestIndex(distances, cd[i]);
        const actualKph = (speeds[idx] ?? 0) * 3.6;
        const y = yToPixel(actualKph);
        ctx.lineTo(x, y);
      }
    }
    ctx.closePath();
    ctx.fill();
    ctx.restore();

    // Dashed gold ceiling line
    ctx.save();
    ctx.setLineDash([8, 4]);
    ctx.strokeStyle = chartColor.series.primary;
    ctx.lineWidth = 1.5;
    ctx.globalAlpha = 0.7;
    ctx.beginPath();
    let ceilStarted = false;
    for (let i = 0; i < cd.length; i++) {
      const x = xToPixel(cd[i]);
      if (x < pad.left || x > pad.left + pW) continue;
      const y = yToPixel(cs[i]);
      if (!ceilStarted) { ctx.moveTo(x, y); ceilStarted = true; } else { ctx.lineTo(x, y); }
    }
    ctx.stroke();
    ctx.restore();

    // Legend
    ctx.fillStyle = chartColor.series.primary;
    ctx.globalAlpha = 0.7;
    ctx.font = '10px "Space Mono", monospace';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    ctx.fillText(`- - Track Limit (${opts.ceilingSpeeds.sessions} sessions)`, pad.left + 8, legendY);
    ctx.globalAlpha = 1.0;
    legendY += 12;
  }

  // Reference line (dashed marshal-yellow)
  if (refSpeeds && refSpeeds.length > 0) {
    ctx.strokeStyle = chartColor.series.warning;
    ctx.lineWidth = 2;
    ctx.setLineDash([8, 4]);
    ctx.beginPath();
    let started = false;
    for (let i = 0; i < Math.min(distances.length, refSpeeds.length); i++) {
      const d = distances[i]!, rs = refSpeeds[i]!;
      if (d == null || rs == null || !isFinite(rs)) continue;
      const x = xToPixel(d);
      const y = yToPixel(rs * 3.6);
      if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
    }
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = chartColor.series.warning;
    ctx.font = '10px "Space Mono", monospace';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    ctx.fillText(opts.refLapLabel ? `--- ${opts.refLapLabel}` : '--- Theoretical', pad.left + 8, legendY);
    legendY += 12;
  }

  // Average pace (dotted blue)
  if (avgSpeeds && avgSpeeds.length > 0) {
    ctx.strokeStyle = chartColor.palette[3];
    ctx.lineWidth = 1.5;
    ctx.setLineDash([4, 4]);
    ctx.globalAlpha = 0.6;
    ctx.beginPath();
    let started = false;
    for (let i = 0; i < Math.min(distances.length, avgSpeeds.length); i++) {
      const d = distances[i]!, as_ = avgSpeeds[i]!;
      if (d == null || as_ == null || !isFinite(as_)) continue;
      const x = xToPixel(d);
      const y = yToPixel(as_ * 3.6);
      if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
    }
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.globalAlpha = 1.0;
    ctx.fillStyle = chartColor.palette[3];
    ctx.font = '10px "Space Mono", monospace';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    ctx.fillText('... Avg Pace', pad.left + 8, legendY);
    legendY += 12;
  }

  // Primary lap label
  if (opts.primaryLapLabel) {
    ctx.fillStyle = chartColor.series.primary;
    ctx.font = '10px "Space Mono", monospace';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    ctx.fillText(`── ${opts.primaryLapLabel}`, pad.left + 8, legendY);
    legendY += 12;
  }

  // Main speed trace (color gradient)
  const sMin = validSpeeds.length > 0 ? safeMin(validSpeeds) : 0;
  const sMax = validSpeeds.length > 0 ? safeMax(validSpeeds) : 1;
  ctx.lineWidth = 2;
  for (let i = 0; i < distances.length - 1; i++) {
    const d0 = distances[i]!, s0 = speeds[i]!;
    const d1 = distances[i + 1]!, s1 = speeds[i + 1]!;
    if (d0 == null || s0 == null || d1 == null || s1 == null) continue;
    ctx.strokeStyle = speedColor(s0, sMin, sMax);
    ctx.beginPath();
    ctx.moveTo(xToPixel(d0), yToPixel(s0 * 3.6));
    ctx.lineTo(xToPixel(d1), yToPixel(s1 * 3.6));
    ctx.stroke();
  }

  // Cross-session reference speed line (dashed racing-purple)
  if (opts.crossRefDistances && opts.crossRefSpeeds && opts.crossRefDistances.length > 1) {
    ctx.save();
    ctx.strokeStyle = chartColor.series.reference;
    ctx.lineWidth = 1.5;
    ctx.setLineDash([6, 4]);
    ctx.globalAlpha = 0.7;
    ctx.beginPath();
    let xRefStarted = false;
    const xRefDist = opts.crossRefDistances;
    const xRefSpd = opts.crossRefSpeeds;
    for (let i = 0; i < Math.min(xRefDist.length, xRefSpd.length); i++) {
      const d = xRefDist[i]!, rs = xRefSpd[i]!;
      if (d == null || rs == null || !isFinite(rs)) continue;
      const x = xToPixel(d);
      const y = yToPixel(rs * 3.6);
      if (!xRefStarted) { ctx.moveTo(x, y); xRefStarted = true; } else { ctx.lineTo(x, y); }
    }
    ctx.stroke();
    ctx.restore();
    // Legend entry
    ctx.fillStyle = chartColor.series.reference;
    ctx.globalAlpha = 0.9;
    ctx.font = '10px "Space Mono", monospace';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    ctx.fillText(opts.crossRefLabel ? `- - ${opts.crossRefLabel}` : '- - Ref Session', pad.left + 8, legendY);
    ctx.globalAlpha = 1.0;
    legendY += 12;
  }

  // End plot-area clip
  ctx.restore();

  // Hover crosshair
  if (hoverDistanceM !== null && hoverDistanceM >= xMin && hoverDistanceM <= xMax) {
    const hx = xToPixel(hoverDistanceM);
    ctx.strokeStyle = chartColor.crosshair;
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 3]);
    ctx.beginPath();
    ctx.moveTo(hx, pad.top);
    ctx.lineTo(hx, pad.top + pH);
    ctx.stroke();
    ctx.setLineDash([]);

    // Tooltip at hover position
    const idx = closestIndex(distances, hoverDistanceM);
    if (idx >= 0 && idx < speeds.length && speeds[idx] != null && isFinite(speeds[idx])) {
      const kmh = (speeds[idx] * 3.6).toFixed(0);
      const label = `${kmh} km/h @ ${hoverDistanceM.toFixed(0)}m`;
      const speedY = yToPixel(speeds[idx] * 3.6);

      // Speed dot
      ctx.beginPath();
      ctx.arc(hx, speedY, 4, 0, Math.PI * 2);
      ctx.fillStyle = chartColor.series.primary;
      ctx.fill();

      // Tooltip background
      ctx.font = '11px "Space Mono", monospace';
      const tw = ctx.measureText(label).width + 12;
      const tx = Math.min(hx + 8, w - pad.right - tw);
      const ty = Math.max(pad.top, speedY - 24);
      ctx.fillStyle = chartColor.tooltipBg;
      ctx.beginPath();
      ctx.roundRect(tx, ty, tw, 20, 4);
      ctx.fill();
      ctx.fillStyle = chartColor.text;
      ctx.textAlign = 'left';
      ctx.textBaseline = 'middle';
      ctx.fillText(label, tx + 6, ty + 10);
    }
  }

  // ── Driving-event tape ────────────────────────────────────
  // The cross-session delta bar (below) is a bottom-anchored strip painted
  // LATER in this same pass, so if the tape used the full plot height it
  // would paint the tape and then immediately cover it. When that bar will
  // render, shrink the geometry handed to the tape by its height so
  // drawMistakeTape's own "bottom of the plot" math lands one band higher —
  // directly above the delta bar instead of under it.
  //
  // The event list spans the whole session, the curve is ONE lap: keep only
  // the events belonging to the lap being drawn. When the caller did not say
  // which lap that is, draw nothing — an unverifiable claim about which lap
  // a band belongs to is exactly the kind this surface must not make.
  if (opts.drivingEvents && opts.drivingEvents.length > 0
      && typeof opts.drivingEventsLap === 'number'
      && Number.isFinite(opts.drivingEventsLap)) {
    const lap = opts.drivingEventsLap;
    const thisLap = opts.drivingEvents.filter((e) => e.lap_number === lap);
    const hasCrossSessionDeltaBar = !!(
      opts.crossRefDistances && opts.crossRefDeltaS && opts.crossRefDistances.length > 1
    );
    const geo = thisLap.length > 0 ? makeTapeGeometry({
      // The LAP's length, not the window's: xMax is the crop end when
      // distRange is set, and s_norm is a fraction of the lap.
      lapLengthM: safeMax(distances) || 1,
      xMin, xMax, xToPixel,
      plotX: pad.left, plotY: pad.top, plotW: pW,
      plotH: pH - (hasCrossSessionDeltaBar ? CROSS_SESSION_BAR_H : 0),
    }) : null;
    if (geo) {
      drawCornerShade(ctx, thisLap, geo);
      drawMistakeTape(ctx, thisLap, geo);
    }
  }

  // ── Drag selection overlay ────────────────────────────────
  if (opts.dragSelection) {
    const [sx, ex] = opts.dragSelection;
    const left = Math.max(pad.left, Math.min(sx, ex));
    const right = Math.min(pad.left + pW, Math.max(sx, ex));
    if (right > left) {
      ctx.fillStyle = 'rgba(34, 197, 94, 0.08)';
      ctx.fillRect(left, pad.top, right - left, pH);
      ctx.strokeStyle = 'rgba(34, 197, 94, 0.5)';
      ctx.lineWidth = 1;
      ctx.strokeRect(left, pad.top, right - left, pH);
    }
  }

  // ── Cross-session delta bar ───────────────────────────────
  if (opts.crossRefDistances && opts.crossRefDeltaS && opts.crossRefDistances.length > 1) {
    const barH = CROSS_SESSION_BAR_H;
    const barY = pad.top + pH - barH; // sits at the very bottom of the plot area
    const xRefDist = opts.crossRefDistances;
    const deltaS = opts.crossRefDeltaS;
    ctx.save();
    for (let i = 0; i < Math.min(xRefDist.length, deltaS.length) - 1; i++) {
      const d0 = xRefDist[i]!, d1 = xRefDist[i + 1]!;
      const dv = deltaS[i]!;
      if (d0 == null || d1 == null || dv == null) continue;
      const x0 = xToPixel(d0);
      const x1 = xToPixel(d1);
      if (x1 < pad.left || x0 > pad.left + pW) continue;
      // delta_s > 0 means ref is slower → primary is faster → green
      ctx.fillStyle = dv > 0 ? 'rgba(34,197,94,0.3)' : 'rgba(255,42,42,0.3)';
      ctx.fillRect(Math.max(pad.left, x0), barY, Math.min(x1, pad.left + pW) - Math.max(pad.left, x0), barH);
    }
    ctx.restore();
  }

  // ── Cross-session hover marker ────────────────────────────
  if (
    hoverDistanceM !== null &&
    hoverDistanceM >= xMin &&
    hoverDistanceM <= xMax &&
    opts.crossRefDistances &&
    opts.crossRefSpeeds &&
    opts.crossRefDistances.length > 0
  ) {
    const xRefIdx = closestIndex(opts.crossRefDistances, hoverDistanceM);
    if (xRefIdx >= 0 && xRefIdx < opts.crossRefSpeeds.length) {
      const rs = opts.crossRefSpeeds[xRefIdx];
      if (rs != null && isFinite(rs)) {
        const hx = xToPixel(hoverDistanceM);
        const hy = yToPixel(rs * 3.6);
        ctx.save();
        ctx.strokeStyle = chartColor.series.reference;
        ctx.lineWidth = 2;
        ctx.globalAlpha = 0.9;
        ctx.beginPath();
        ctx.arc(hx, hy, 5, 0, Math.PI * 2);
        ctx.stroke();
        ctx.restore();
      }
    }
  }

  return bounds;
}

// ── Delta time drawing ──────────────────────────────────────────
//
// Delta is computed on the backend by the canonical cumulative_delta
// engine (telemetry_tool/deltas.py) and fetched via /sessions/:id/delta.
// The client only projects that anchored curve onto this chart's x-axis
// via `linearInterp` below — no integration, no scaling, no forward-fill.

/** Piecewise-linear interpolation. Mirrors numpy.interp's clamping
 *  behaviour: values outside `xs` clamp to the boundary y. */
function linearInterp(x: number, xs: number[], ys: number[]): number {
  const n = xs.length;
  if (n === 0) return 0;
  if (x <= xs[0]) return ys[0];
  if (x >= xs[n - 1]) return ys[n - 1];
  // Binary search for the bracket
  let lo = 0;
  let hi = n - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (xs[mid] <= x) lo = mid;
    else hi = mid;
  }
  const t = (x - xs[lo]) / (xs[hi] - xs[lo]);
  return ys[lo] + t * (ys[hi] - ys[lo]);
}

function drawDeltaChart(
  ctx: CanvasRenderingContext2D,
  x0: number,
  y0: number,
  w: number,
  h: number,
  distances: number[],
  deltaSeconds: number[],
  hoverDistanceM: number | null,
  primaryLapNum: number,
  compareLapNum: number,
) {
  const pad = { top: 6, right: 20, bottom: 22, left: 60 };
  const pW = w - pad.left - pad.right;
  const pH = h - pad.top - pad.bottom;
  const ox = x0 + pad.left;
  const oy = y0 + pad.top;

  // Separator line
  ctx.strokeStyle = chartColor.grid;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(x0, y0);
  ctx.lineTo(x0 + w, y0);
  ctx.stroke();

  // Background
  ctx.fillStyle = chartColor.surfaceMuted;
  ctx.fillRect(x0, y0, w, h);

  if (distances.length < 2 || deltaSeconds.length < 2) return;

  const n = Math.min(distances.length, deltaSeconds.length);
  const xMin = 0;
  const xMax = distances[distances.length - 1] || 1;

  // Y range — symmetric around zero
  let maxAbs = 0;
  for (let i = 0; i < n; i++) {
    const a = Math.abs(deltaSeconds[i]);
    if (a > maxAbs) maxAbs = a;
  }
  if (maxAbs < 0.1) maxAbs = 0.1;
  const yMax = maxAbs * 1.15;
  const yMin = -yMax;

  const xToPixel = (v: number) => ox + (v - xMin) / (xMax - xMin) * pW;
  const yToPixel = (v: number) => oy + pH - (v - yMin) / (yMax - yMin) * pH;

  // Zero line
  const zeroY = yToPixel(0);
  ctx.strokeStyle = chartColor.axis;
  ctx.lineWidth = 0.5;
  ctx.setLineDash([4, 3]);
  ctx.beginPath();
  ctx.moveTo(ox, zeroY);
  ctx.lineTo(ox + pW, zeroY);
  ctx.stroke();
  ctx.setLineDash([]);

  // Y-axis ticks
  ctx.fillStyle = chartColor.textSecondary;
  ctx.font = '10px "Space Mono", monospace';
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  const yTicks = niceRange(yMin, yMax, 3);
  for (const tick of yTicks) {
    const ty = yToPixel(tick);
    ctx.fillText(`${tick > 0 ? '+' : ''}${tick.toFixed(1)}s`, ox - 6, ty);
    if (tick !== 0) {
      ctx.strokeStyle = chartColor.grid;
      ctx.lineWidth = 0.3;
      ctx.beginPath();
      ctx.moveTo(ox, ty);
      ctx.lineTo(ox + pW, ty);
      ctx.stroke();
    }
  }

  // Delta area fill + line
  ctx.beginPath();
  ctx.moveTo(xToPixel(distances[0]), zeroY);
  for (let i = 0; i < n; i++) {
    ctx.lineTo(xToPixel(distances[i]), yToPixel(deltaSeconds[i]));
  }
  ctx.lineTo(xToPixel(distances[n - 1]), zeroY);
  ctx.closePath();

  // Fill: green when faster (negative delta), red when slower (positive)
  // Use gradient from the actual data
  const lastDelta = deltaSeconds[n - 1];
  ctx.fillStyle = lastDelta <= 0 ? 'rgba(0,255,100,0.12)' : 'rgba(255,60,60,0.12)';
  ctx.fill();

  // Line colored by sign
  for (let i = 0; i < n - 1; i++) {
    const d = deltaSeconds[i];
    ctx.strokeStyle = d <= 0 ? chartColor.series.positive : chartColor.series.negative;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(xToPixel(distances[i]), yToPixel(deltaSeconds[i]));
    ctx.lineTo(xToPixel(distances[i + 1]), yToPixel(deltaSeconds[i + 1]));
    ctx.stroke();
  }

  // Label
  ctx.fillStyle = chartColor.textSecondary;
  ctx.font = '9px "Space Mono", monospace';
  ctx.textAlign = 'left';
  ctx.textBaseline = 'top';
  ctx.fillText(`\u0394t Lap ${primaryLapNum} vs ${compareLapNum}`, ox + 4, oy + 2);

  // Final delta value
  const finalDelta = deltaSeconds[n - 1];
  const sign = finalDelta <= 0 ? '' : '+';
  ctx.fillStyle = finalDelta <= 0 ? chartColor.series.positive : chartColor.series.negative;
  ctx.font = '11px "Space Mono", monospace';
  ctx.textAlign = 'right';
  ctx.fillText(`${sign}${finalDelta.toFixed(3)}s`, ox + pW - 4, oy + 2);

  // Hover crosshair
  if (hoverDistanceM !== null && hoverDistanceM >= xMin && hoverDistanceM <= xMax) {
    const hx = xToPixel(hoverDistanceM);
    ctx.strokeStyle = chartColor.crosshair;
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 3]);
    ctx.beginPath();
    ctx.moveTo(hx, oy);
    ctx.lineTo(hx, oy + pH);
    ctx.stroke();
    ctx.setLineDash([]);

    // Find closest delta value
    const idx = closestIndex(distances, hoverDistanceM);
    if (idx >= 0 && idx < deltaSeconds.length) {
      const dt = deltaSeconds[idx];
      const dtSign = dt <= 0 ? '' : '+';
      const label = `${dtSign}${dt.toFixed(3)}s`;
      ctx.font = '10px "Space Mono", monospace';
      const tw = ctx.measureText(label).width + 8;
      const tx = Math.min(hx + 6, x0 + w - pad.right - tw);
      const ty = Math.max(oy, yToPixel(dt) - 14);
      ctx.fillStyle = chartColor.tooltipBg;
      ctx.beginPath();
      ctx.roundRect(tx, ty, tw, 16, 3);
      ctx.fill();
      ctx.fillStyle = dt <= 0 ? chartColor.series.positive : chartColor.series.negative;
      ctx.textAlign = 'left';
      ctx.textBaseline = 'middle';
      ctx.fillText(label, tx + 4, ty + 8);
    }
  }
}

// ── Component ────────────────────────────────────────────────────
export function SpeedTraceChart({
  sessionId,
  data: externalData,
  onHoverDistance,
  className = '',
  gpsLaps = [],
  bestLap = null,
  compareLap = null,
  primaryLapTime = null,
  compareLapTime = null,
  controlledLap = false,
  distRange = null,
  onDistRangeChange,
  showTheoretical = false,
  showPhysicsCeiling = false,
  showDrivingEvents = false,
}: SpeedTraceChartProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const boundsRef = useRef<ReturnType<typeof drawSpeedTrace>>(null);

  const [traceData, setTraceData] = useState<SpeedTraceData | null>(null);
  const [avgSpeeds, setAvgSpeeds] = useState<number[] | null>(null);
  const [refSpeeds, setRefSpeeds] = useState<number[] | null>(null);
  const [activeCompareLap, setActiveCompareLap] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedLap, setSelectedLap] = useState<number | null>(null);
  const dragRef = useRef<{ startX: number; currentX: number } | null>(null);
  const [dragSelection, setDragSelection] = useState<[number, number] | null>(null);
  const [theoreticalData, setTheoreticalData] = useState<{ distances: number[]; speeds: number[] } | null>(null);
  const [ceilingData, setCeilingData] = useState<{ distances: number[]; speeds: number[]; sessions: number } | null>(null);
  const [drivingEvents, setDrivingEvents] = useState<DrivingEventsResponse | null>(null);

  const hoverDistance = useChartHoverStore((s) => s.hoverDistance);
  const setHover = useChartHoverStore((s) => s.setHover);
  const clearHover = useChartHoverStore((s) => s.clearHover);

  const { referenceData } = useReferenceOverlay();

  // Sync selectedLap when controlled externally (e.g. Focus Mode unified selector)
  useEffect(() => {
    if (controlledLap && bestLap != null) setSelectedLap(bestLap);
  }, [controlledLap, bestLap]);

  const activeLap = selectedLap ?? bestLap ?? (gpsLaps.length > 0 ? gpsLaps[0] : null);

  // Determine data source
  const chartData = externalData || traceData;

  // ── Fetch speed trace data ──────────────────────────────────
  useEffect(() => {
    if (externalData || !sessionId || activeLap == null) return;
    let cancelled = false;
    setLoading(true);
    setError(null);

    const fetchTrace = async () => {
      try {
        const data = await api.get<SpeedTraceData>(
          `/sessions/${encodeURIComponent(sessionId)}/speed-trace?lap=${activeLap}&avg=1`,
        );
        if (cancelled) return;
        if (data.available === false) {
          setError('No speed trace data available');
          setTraceData(null);
        } else {
          setTraceData(data);
          if (data.avg_speeds) setAvgSpeeds(data.avg_speeds);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load speed trace');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    fetchTrace();
    return () => { cancelled = true; };
  }, [sessionId, activeLap, externalData]);

  // ── Fetch reference lap for comparison ────────────────────────
  useEffect(() => {
    if (!sessionId || !compareLap || activeLap == null || compareLap === activeLap) {
      setRefSpeeds(null);
      setActiveCompareLap(null);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const data = await api.get<SpeedTraceData & { ref_speeds?: number[] }>(
          `/sessions/${encodeURIComponent(sessionId)}/speed-trace?lap=${activeLap}&ref=${compareLap}`,
        );
        if (cancelled) return;
        if (data.ref_speeds) {
          setRefSpeeds(data.ref_speeds);
          setActiveCompareLap(compareLap);
        }
      } catch {
        if (!cancelled) { setRefSpeeds(null); setActiveCompareLap(null); }
      }
    })();
    return () => { cancelled = true; };
  }, [sessionId, activeLap, compareLap]);

  // ── Fetch theoretical optimal speed profile ─────────────────
  useEffect(() => {
    if (!showTheoretical || !sessionId) {
      setTheoreticalData(null);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const res = await api.get<{ speed_profile?: { distance_m: number[]; speed_kph: number[] } }>(
          `/sessions/${encodeURIComponent(sessionId)}/theoretical`,
        );
        if (cancelled) return;
        if (res?.speed_profile) {
          setTheoreticalData({
            distances: res.speed_profile.distance_m,
            speeds: res.speed_profile.speed_kph,
          });
        }
      } catch {
        // Theoretical data is optional — silently skip on 404 or error
        if (!cancelled) setTheoreticalData(null);
      }
    })();
    return () => { cancelled = true; };
  }, [showTheoretical, sessionId]);

  // ── Fetch physics ceiling ────────────────────────────────────
  useEffect(() => {
    if (!showPhysicsCeiling || !sessionId) {
      setCeilingData(null);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const res = await api.get<{
          ceiling_speeds_kph: number[];
          distances: number[];
          aggregate_sessions: number;
        }>(`/sessions/${encodeURIComponent(sessionId)}/physics-ceiling`);
        if (cancelled) return;
        if (res?.ceiling_speeds_kph) {
          setCeilingData({
            distances: res.distances,
            speeds: res.ceiling_speeds_kph,
            sessions: res.aggregate_sessions,
          });
        }
      } catch {
        if (!cancelled) setCeilingData(null);
      }
    })();
    return () => { cancelled = true; };
  }, [showPhysicsCeiling, sessionId]);

  // ── Fetch driving events ─────────────────────────────────────
  useEffect(() => {
    if (!showDrivingEvents || !sessionId) {
      setDrivingEvents(null);
      return;
    }
    let cancelled = false;
    (async () => {
      const res = await fetchDrivingEvents(sessionId);
      if (!cancelled) setDrivingEvents(res);
    })();
    return () => { cancelled = true; };
  }, [showDrivingEvents, sessionId]);

  // ── Fetch canonical anchored delta from backend ───────────────
  //
  // Every delta curve in the product routes through the canonical
  // cumulative_delta engine (telemetry_tool/deltas.py). This fetch pulls
  // the anchored delta for primary vs compare laps — same path the
  // separate "Time Delta" card uses — so the two deltas agree.
  //
  // Sign from backend: positive = lap_b slower than lap_a.
  // Sign this chart expects: positive = primary slower (losing time).
  // With lap_a=primary, lap_b=compare we need to negate.
  const [backendDelta, setBackendDelta] = useState<{ distances: number[]; delta_s: number[] } | null>(null);
  useEffect(() => {
    if (!sessionId || activeCompareLap == null || activeLap == null || activeLap === activeCompareLap) {
      setBackendDelta(null);
      return;
    }
    let cancelled = false;
    api
      .get<{ distances: number[]; delta_s: number[] }>(
        `/sessions/${encodeURIComponent(sessionId)}/delta?lap_a=${activeLap}&lap_b=${activeCompareLap}`,
      )
      .then((data) => {
        if (cancelled) return;
        if (data?.distances && data?.delta_s) {
          setBackendDelta({ distances: data.distances, delta_s: data.delta_s });
        } else {
          setBackendDelta(null);
        }
      })
      .catch(() => { if (!cancelled) setBackendDelta(null); });
    return () => { cancelled = true; };
  }, [sessionId, activeLap, activeCompareLap]);

  // Project the backend delta (on its own uniform grid) onto the speed
  // trace's distance axis so the two sub-charts align vertically.
  const deltaSeconds = useMemo(() => {
    if (!chartData?.distances || !backendDelta) return null;
    const xs = backendDelta.distances;
    const ys = backendDelta.delta_s;
    if (xs.length < 2 || ys.length < 2) return null;
    return chartData.distances.map((d) => {
      // Flip sign: backend's delta_s is (compare - primary);
      // this chart's delta is (primary - compare).
      return -linearInterp(d, xs, ys);
    });
  }, [chartData, backendDelta]);

  const render = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);

    if (!chartData || !chartData.distances || chartData.distances.length < 2) {
      drawSpeedTrace(ctx, rect.width, rect.height, {
        distances: [],
        speeds: [],
        hoverDistanceM: null,
      });
      boundsRef.current = null;
      return;
    }

    // Split: if delta data, top 65% speed trace, bottom 35% delta
    const hasDelta = deltaSeconds && deltaSeconds.length > 1 && activeCompareLap != null;
    const speedH = hasDelta ? Math.round(rect.height * 0.65) : rect.height;
    const deltaH = hasDelta ? rect.height - speedH : 0;

    // Build cross-session reference label
    const crossRefLabel = referenceData
      ? `${referenceData.reference.driver_name} L${referenceData.reference.lap_number}`
      : null;

    boundsRef.current = drawSpeedTrace(ctx, rect.width, speedH, {
      distances: chartData.distances,
      speeds: chartData.speeds,
      refSpeeds: refSpeeds ?? chartData.ref_speeds,
      avgSpeeds: !refSpeeds ? (avgSpeeds ?? chartData.avg_speeds) : undefined,
      theoreticalSpeeds: theoreticalData,
      ceilingSpeeds: ceilingData,
      hoverDistanceM: hoverDistance,
      refLapLabel: activeCompareLap != null ? `Lap ${activeCompareLap}` : null,
      primaryLapLabel: activeCompareLap != null ? `Lap ${activeLap}` : null,
      distRange,
      dragSelection,
      crossRefDistances: referenceData?.distances ?? null,
      crossRefSpeeds: referenceData?.speed.reference ?? null,
      crossRefDeltaS: referenceData?.speed.delta_s ?? null,
      crossRefLabel,
      drivingEvents: drivingEvents?.events ?? null,
      // The lap the fetch at :848 asked for — the tape may only mark events
      // belonging to the curve actually drawn.
      drivingEventsLap: activeLap,
    });

    if (hasDelta && deltaSeconds) {
      drawDeltaChart(
        ctx, 0, speedH, rect.width, deltaH,
        chartData.distances, deltaSeconds,
        hoverDistance, activeLap!, activeCompareLap!,
      );
    }
  }, [chartData, avgSpeeds, refSpeeds, theoreticalData, ceilingData, deltaSeconds, activeCompareLap, hoverDistance, distRange, dragSelection, referenceData, drivingEvents, activeLap]);

  useEffect(() => {
    render();
  }, [render]);

  // Stable ref for ResizeObserver — avoids re-attaching on every hover
  const renderRef = useRef(render);
  renderRef.current = render;

  // ── ResizeObserver ──────────────────────────────────────────
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const observer = new ResizeObserver(() => renderRef.current());
    observer.observe(canvas);
    return () => observer.disconnect();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Mouse hover → emit distance ────────────────────────────
  const handleMouseMove = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const bounds = boundsRef.current;
      if (!bounds || !chartData) return;
      const canvas = canvasRef.current;
      if (!canvas) return;

      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;

      const distM = bounds.xMin + (mx - bounds.plotX) / bounds.plotW * (bounds.xMax - bounds.xMin);
      if (distM < bounds.xMin || distM > bounds.xMax) return;

      setHover(distM, 'speed-trace');
      onHoverDistance?.(distM);
    },
    [chartData, setHover, onHoverDistance],
  );

  const handleMouseLeave = useCallback(() => {
    clearHover();
    if (dragRef.current) {
      dragRef.current = null;
      setDragSelection(null);
    }
  }, [clearHover]);

  // ── Drag-to-zoom ─────────────────────────────────────────
  const handleMouseDown = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      if (!onDistRangeChange) return; // zoom only when wired up
      const bounds = boundsRef.current;
      if (!bounds) return;
      const rect = e.currentTarget.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      if (mx < bounds.plotX || mx > bounds.plotX + bounds.plotW) return;
      dragRef.current = { startX: mx, currentX: mx };
    },
    [onDistRangeChange],
  );

  const handleMouseMoveWithDrag = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      // Regular hover
      handleMouseMove(e);
      // Drag selection
      if (dragRef.current) {
        const rect = e.currentTarget.getBoundingClientRect();
        dragRef.current.currentX = e.clientX - rect.left;
        setDragSelection([dragRef.current.startX, dragRef.current.currentX]);
      }
    },
    [handleMouseMove],
  );

  const handleMouseUp = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      if (!dragRef.current || !onDistRangeChange) return;
      const bounds = boundsRef.current;
      if (!bounds) { dragRef.current = null; setDragSelection(null); return; }
      const rect = e.currentTarget.getBoundingClientRect();
      const endX = e.clientX - rect.left;
      const { startX } = dragRef.current;
      dragRef.current = null;
      setDragSelection(null);

      const pxRange = Math.abs(endX - startX);
      if (pxRange < 10) {
        // Click (not drag) — reset zoom
        onDistRangeChange(null);
        return;
      }
      const x1 = Math.max(bounds.plotX, Math.min(startX, endX));
      const x2 = Math.min(bounds.plotX + bounds.plotW, Math.max(startX, endX));
      const d1 = bounds.xMin + (x1 - bounds.plotX) / bounds.plotW * (bounds.xMax - bounds.xMin);
      const d2 = bounds.xMin + (x2 - bounds.plotX) / bounds.plotW * (bounds.xMax - bounds.xMin);
      onDistRangeChange([Math.max(0, d1), d2]);
    },
    [onDistRangeChange],
  );

  const handleDblClick = useCallback(() => {
    onDistRangeChange?.(null);
  }, [onDistRangeChange]);

  // ── Hover from ANY chart → redraw crosshair ────────────────
  // Handled by hoverDistance in the render callback — any chart
  // (including self) setting hover triggers a React re-render.

  // ── Lap selector ───────────────────────────────────────────
  const showLapSelector = !controlledLap && !!sessionId && gpsLaps.length > 1;

  // ── Render ─────────────────────────────────────────────────
  if (error && !chartData) {
    return (
      <div className={`flex items-center justify-center rounded-lg border border-steel/10 bg-concrete ${className}`} style={{ minHeight: '250px' }}>
        <div className="text-steel p-4 text-sm text-center">
          <p className="font-telemetry text-chalk mb-1">Speed Trace</p>
          <p className="text-safety-red text-xs">{error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className={`relative flex flex-col min-h-0 overflow-hidden ${className}`}>
      {/* Lap selector */}
      {showLapSelector && (
        <div className="flex items-center gap-2 mb-2">
          <span className="text-steel text-xs font-telemetry">Lap:</span>
          <div className="flex gap-1 flex-wrap">
            {gpsLaps.map((lap) => (
              <button
                key={lap}
                type="button"
                onClick={() => setSelectedLap(lap)}
                className={`px-2 py-0.5 text-xs font-telemetry rounded transition-colors ${
                  lap === activeLap
                    ? 'bg-accent/20 text-accent border border-accent/40'
                    : 'bg-asphalt text-steel border border-steel/20 hover:text-chalk hover:border-steel/40'
                }`}
              >
                {lap}
                {lap === bestLap && <span className="ml-0.5 text-[9px] text-acid-green">(B)</span>}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Loading overlay */}
      {loading && (
        <div className="absolute inset-0 flex items-center justify-center bg-concrete/80 z-10 rounded-lg">
          <div className="w-5 h-5 border-2 border-accent border-t-transparent rounded-full animate-spin" />
        </div>
      )}

      {/* Canvas */}
      <div
        className="relative w-full flex-1 min-h-0 rounded-lg bg-concrete border border-steel/10 overflow-hidden"
        style={!className.includes('h-full') ? { minHeight: '280px' } : undefined}
      >
        <canvas
          ref={canvasRef}
          className="w-full h-full cursor-crosshair"
          style={{ display: 'block' }}
          onMouseMove={onDistRangeChange ? handleMouseMoveWithDrag : handleMouseMove}
          onMouseDown={handleMouseDown}
          onMouseUp={handleMouseUp}
          onMouseLeave={handleMouseLeave}
          onDoubleClick={handleDblClick}
          role="img"
          aria-label="Speed versus distance chart — drag to zoom, double-click to reset"
        />
        {!chartData && !loading && (
          <div className="absolute inset-0 flex items-center justify-center">
            <p className="text-steel text-sm font-telemetry">No speed data</p>
          </div>
        )}
      </div>
    </div>
  );
}
