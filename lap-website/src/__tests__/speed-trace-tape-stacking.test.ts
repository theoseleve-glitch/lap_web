/**
 * Fix round 1: the mistake tape and the cross-session delta bar are both
 * bottom-anchored strips in drawSpeedTrace, and the delta bar paints LATER
 * in the same pass — so without stacking, the delta bar silently covers
 * the tape exactly when a driver is comparing two laps (the situation
 * where the tape matters most).
 *
 * These tests exercise the SHIPPED `drawSpeedTrace` (exported from
 * SpeedTraceChart.tsx for this purpose) with a canvas-recorder stub, the
 * same no-DOM technique driving-events-draw.ts's pure functions are
 * tested with in driving-events.test.ts.
 */
import { describe, it, expect } from 'vitest';
import { drawSpeedTrace } from '@/components/shared/charts/SpeedTraceChart';
import { TAPE_HEIGHT_PX } from '@/lib/driving-events-draw';
import type { DrivingEvent } from '@/lib/driving-events';

function ev(over: Partial<DrivingEvent> = {}): DrivingEvent {
  return {
    lap_number: 3,
    corner_id: 4,
    event_type: 'over_slowing',
    s_norm_start: 0.2,
    s_norm_end: 0.3,
    magnitude: 1.4,
    magnitude_unit: 'm/s',
    time_cost_s: 0.31,
    validity: 'measured',
    reason: null,
    n_samples_in_window: 40,
    anchor_tier: 'session_envelope_ellipse_fitted',
    anchor_reason: null,
    evidence: {},
    time_cost_attribution: 'caused',
    magnitude_is_standalone_quotable: true,
    also_fired: [],
    ...over,
  };
}

/** Records every call instead of painting. No DOM, no canvas mock. */
function recorder() {
  const calls: Array<{ op: string; args: unknown[] }> = [];
  const ctx = new Proxy({} as CanvasRenderingContext2D, {
    get(_t, prop: string) {
      if (prop === 'canvas') return undefined;
      return (...args: unknown[]) => { calls.push({ op: prop, args }); };
    },
    set(_t, prop: string, value) { calls.push({ op: `set:${prop}`, args: [value] }); return true; },
  });
  return { ctx, calls, rects: () => calls.filter((c) => c.op === 'fillRect') };
}

// 11 evenly spaced points over 0..1000m. w/h chosen so pad math (top:20,
// right:20, bottom:50, left:60) gives round plot dimensions: pW=1020, pH=300.
const W = 1100;
const H = 370;
const DISTANCES = Array.from({ length: 11 }, (_, i) => i * 100);
const SPEEDS = DISTANCES.map(() => 30);
const PAD_TOP = 20;
const PLOT_H = 300; // H - top(20) - bottom(50)

function baseOpts() {
  return {
    distances: DISTANCES,
    speeds: SPEEDS,
    hoverDistanceM: null,
    drivingEvents: [ev({ s_norm_start: 0.2, s_norm_end: 0.3 })],
  };
}

/** The tape's own fillRect is the only one with height === TAPE_HEIGHT_PX;
 *  the delta bar, corner shade, and background fills all use other heights. */
function tapeRectY(calls: ReturnType<typeof recorder>['calls']): number {
  const tapeRects = calls.filter(
    (c) => c.op === 'fillRect' && (c.args as number[])[3] === TAPE_HEIGHT_PX,
  );
  expect(tapeRects.length).toBe(1);
  return (tapeRects[0]!.args as number[])[1]!;
}

describe('driving-event tape vs. cross-session delta bar stacking', () => {
  it('leaves the tape at the bottom of the plot when no cross-session data is present', () => {
    const r = recorder();
    drawSpeedTrace(r.ctx, W, H, baseOpts());
    const y = tapeRectY(r.calls);
    expect(y).toBeCloseTo(PAD_TOP + PLOT_H - TAPE_HEIGHT_PX, 5); // unchanged: 312
  });

  it('stacks the tape directly above the delta bar band when cross-session data is present', () => {
    const r = recorder();
    drawSpeedTrace(r.ctx, W, H, {
      ...baseOpts(),
      crossRefDistances: DISTANCES,
      crossRefDeltaS: DISTANCES.map(() => 0.1),
    });
    const tapeY = tapeRectY(r.calls);

    const barRects = r.calls.filter((c) => c.op === 'fillRect' && (c.args as number[])[3] === 10);
    expect(barRects.length).toBeGreaterThan(0);
    const barY = (barRects[0]!.args as number[])[1]!;

    // The tape must clear the bar's band: its bottom edge must not exceed
    // the bar's top edge. A plain reorder (tape drawn after) would instead
    // hide the delta bar — this asserts NEITHER is covered by the other.
    expect(tapeY + TAPE_HEIGHT_PX).toBeLessThanOrEqual(barY);
    // And it should be exactly one bar-height higher than the unstacked case.
    expect(tapeY).toBeCloseTo(PAD_TOP + PLOT_H - 10 - TAPE_HEIGHT_PX, 5); // 302
  });
});
