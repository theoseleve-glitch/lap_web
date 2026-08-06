/**
 * Pure canvas drawing for the Phase 3 mistake tape.
 *
 * Geometry is INJECTED rather than computed here so these functions can be
 * unit-tested against a recording stub with no DOM. They mirror the shape of
 * the existing cross-session delta bar in SpeedTraceChart (a per-segment
 * strip along the bottom of the plot area), which is already proven on this
 * canvas.
 *
 * Events carry `s_norm_*` (0..1 per lap), not metres. Phase 2 moved to
 * `distance_norm` because absolute metres differenced across laps is a
 * coordinate artifact -- lap spans on real data vary by ~19 m, which is
 * larger than several detectors' firing thresholds. Convert at the drawing
 * boundary; never persist metres back onto an event.
 */
import { canQuoteMagnitude, type DrivingEvent } from '@/lib/driving-events';

export const TAPE_HEIGHT_PX = 8;

export interface TapeGeometry {
  xToPixel: (metres: number) => number;
  plotX: number;
  plotY: number;
  plotW: number;
  plotH: number;
  lapLengthM: number;
}

const COLORS: Record<string, string> = {
  over_slowing: 'rgba(255, 42, 42, 0.55)',
  late_throttle: 'rgba(250, 204, 21, 0.35)',
  re_braking: 'rgba(249, 115, 22, 0.55)',
  envelope_under_use: 'rgba(59, 130, 246, 0.45)',
};
const COLOR_UNKNOWN = 'rgba(148, 163, 184, 0.40)';

export function eventColor(e: DrivingEvent): string {
  return COLORS[e.event_type] ?? COLOR_UNKNOWN;
}

/** Pixel span of an event, or null when it has none. Clipped to the plot. */
function spanPx(e: DrivingEvent, geo: TapeGeometry): { x: number; w: number } | null {
  const a = e.s_norm_start;
  const b = e.s_norm_end;
  if (typeof a !== 'number' || typeof b !== 'number') return null;
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
  if (b < a) return null;  // inverted span is a producer bug, not something to guess at

  const rawL = geo.xToPixel(a * geo.lapLengthM);
  const rawR = geo.xToPixel(b * geo.lapLengthM);
  if (!Number.isFinite(rawL) || !Number.isFinite(rawR)) return null;

  const right = geo.plotX + geo.plotW;

  // Reject spans that do not intersect the visible window at all. This must come
  // before clipping: if we clamp both ends to the boundary, we lose the ability
  // to distinguish a span that straddles the edge from one entirely outside it.
  // An event outside the window should not mark the chart.
  if (rawR < geo.plotX || rawL > right) return null;

  // Now clip to the plot area.
  const l = Math.max(geo.plotX, Math.min(rawL, right));
  const r = Math.max(geo.plotX, Math.min(rawR, right));

  // Apply minimum width, but keep within bounds. When at the right boundary,
  // grow leftward (shift the span) rather than rightward, so a 1px indicator
  // stays inside the plot.
  let w = Math.max(1, r - l);
  let x = l;
  if (x + w > right) {
    x = Math.max(geo.plotX, right - w);
  }
  return { x, w };
}

/**
 * Build the geometry a chart hands to the tape drawers.
 *
 * The `xMin` offset is the whole point. `s_norm` is a fraction of the LAP,
 * but the chart's x-axis may be cropped by a zoom (`distRange`), so the
 * fraction must be measured from the visible window's start, not from zero.
 * Getting this wrong shifts every event by the crop offset -- silently, and
 * proportionally to how far the user has zoomed.
 *
 * Exported so a test can exercise THIS expression rather than a copy of it.
 */
export function makeTapeGeometry(a: {
  xMin: number; xMax: number;
  xToPixel: (metres: number) => number;
  plotX: number; plotY: number; plotW: number; plotH: number;
}): TapeGeometry | null {
  const lapLengthM = a.xMax - a.xMin;
  if (!Number.isFinite(lapLengthM) || lapLengthM <= 0) return null;
  return {
    xToPixel: (m: number) => a.xToPixel(a.xMin + m),
    plotX: a.plotX, plotY: a.plotY, plotW: a.plotW, plotH: a.plotH,
    lapLengthM,
  };
}

/** The tape: one coloured segment per event along the bottom of the plot. */
export function drawMistakeTape(
  ctx: CanvasRenderingContext2D,
  events: DrivingEvent[],
  geo: TapeGeometry,
): void {
  if (!events?.length) return;
  ctx.save();
  const y = geo.plotY + geo.plotH - TAPE_HEIGHT_PX;
  for (const e of events) {
    const s = spanPx(e, geo);
    if (!s) continue;
    ctx.fillStyle = eventColor(e);
    ctx.fillRect(s.x, y, s.w, TAPE_HEIGHT_PX);
  }
  ctx.restore();
}

/** Full-height wash over each event's corner window. */
export function drawCornerShade(
  ctx: CanvasRenderingContext2D,
  events: DrivingEvent[],
  geo: TapeGeometry,
): void {
  if (!events?.length) return;
  ctx.save();
  for (const e of events) {
    const s = spanPx(e, geo);
    if (!s) continue;
    ctx.fillStyle = 'rgba(255, 255, 255, 0.035)';
    ctx.fillRect(s.x, geo.plotY, s.w, geo.plotH);
  }
  ctx.restore();
}

/**
 * Label for one event. Obeys Global Constraint 1 by reading the payload's own
 * flags -- a magnitude that is not standalone-quotable is never shown as a
 * number, and a cost that is not attributable is never joined to it with
 * causal wording.
 */
export function eventLabel(e: DrivingEvent): string {
  const where = `C${e.corner_id} L${e.lap_number}`;
  if (canQuoteMagnitude(e)) {
    return `${where} · ${e.event_type} ${e.magnitude!.toFixed(1)}${e.magnitude_unit ?? ''}`;
  }
  return `${where} · ${e.event_type}`;
}
