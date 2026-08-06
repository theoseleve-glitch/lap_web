/**
 * `s_norm` is a fraction of the LAP, and stays one when the chart is zoomed.
 *
 * `makeTapeGeometry` used to set `lapLengthM = xMax - xMin` — the VISIBLE
 * WINDOW — and then spread `s_norm ∈ [0,1]` across the plot whatever the
 * crop. Three layers said the same wrong thing (the field name, its doc
 * comment, and the unit test), so the frame looked verified.
 *
 * These tests drive the SHIPPED `drawSpeedTrace` with `distRange` set, which
 * is the only way to prove the CALL SITE hands over a lap length and not a
 * window length. The unit tests on `makeTapeGeometry` cannot: they pass their
 * own arguments.
 */
import { describe, it, expect } from 'vitest';
import { drawSpeedTrace } from '@/components/shared/charts/SpeedTraceChart';
import { TAPE_HEIGHT_PX } from '@/lib/driving-events-draw';
import type { DrivingEvent } from '@/lib/driving-events';

function ev(over: Partial<DrivingEvent> = {}): DrivingEvent {
  return {
    lap_number: 3, corner_id: 4, event_type: 'over_slowing',
    s_norm_start: 0.5, s_norm_end: 0.7,
    magnitude: 1.4, magnitude_unit: 'm/s', time_cost_s: 0.31,
    validity: 'measured', reason: null, n_samples_in_window: 40,
    anchor_tier: 'session_envelope_ellipse_fitted', anchor_reason: null,
    evidence: {}, time_cost_attribution: 'caused',
    magnitude_is_standalone_quotable: true,
    ...over,
  };
}

function recorder() {
  const calls: Array<{ op: string; args: unknown[] }> = [];
  const ctx = new Proxy({} as CanvasRenderingContext2D, {
    get(_t, prop: string) {
      if (prop === 'canvas') return undefined;
      return (...args: unknown[]) => { calls.push({ op: prop, args }); };
    },
    set(_t, prop: string, value) { calls.push({ op: `set:${prop}`, args: [value] }); return true; },
  });
  return { ctx, calls };
}

// pad = {top:20,right:20,bottom:50,left:60}; W=1100 -> plotX=60, pW=1020.
const W = 1100, H = 370;
const LAP_M = 1000;
const DISTANCES = Array.from({ length: 11 }, (_, i) => i * 100);   // 0..1000 m
const SPEEDS = DISTANCES.map(() => 30);
const CROP: [number, number] = [400, 900];                          // 500 m window

function tapeRects(events: DrivingEvent[], distRange: [number, number] | null) {
  const r = recorder();
  drawSpeedTrace(r.ctx, W, H, {
    distances: DISTANCES, speeds: SPEEDS, hoverDistanceM: null,
    distRange, drivingEvents: events, drivingEventsLap: 3,
  });
  return r.calls.filter(
    (c) => c.op === 'fillRect' && (c.args as number[])[3] === TAPE_HEIGHT_PX);
}

/** metres -> pixel under the crop, computed independently of the chart. */
const px = (m: number) => 60 + ((m - CROP[0]) / (CROP[1] - CROP[0])) * 1020;

describe('the tape frame survives a distance zoom', () => {
  it('places a cropped-in event at its true lap distance', () => {
    // s_norm 0.5..0.7 of a 1000 m lap = 500..700 m, inside the 400..900 crop.
    const rects = tapeRects([ev({ s_norm_start: 0.5, s_norm_end: 0.7 })], CROP);
    expect(rects.length).toBe(1);
    const [x, , w] = rects[0]!.args as number[];
    expect(x).toBeCloseTo(px(500), 5);              // 264
    expect(w).toBeCloseTo(px(700) - px(500), 5);    // 408
    // The old window-relative frame would have put this at
    // xToPixel(400 + 0.5*500) = px(650) = 570 with width px(100)-px(0)=204.
    expect(x).not.toBeCloseTo(px(650), 1);
  });

  it('draws nothing for an event that lies before the crop', () => {
    // s_norm 0.15..0.20 = 150..200 m, outside the 400..900 window. The old
    // frame rescaled it to 475..500 m and painted it mid-plot.
    expect(tapeRects([ev({ s_norm_start: 0.15, s_norm_end: 0.20 })], CROP).length).toBe(0);
  });

  it('draws nothing for an event that lies after the crop', () => {
    expect(tapeRects([ev({ s_norm_start: 0.92, s_norm_end: 0.97 })], CROP).length).toBe(0);
  });

  it('is unchanged when there is no crop at all', () => {
    // Regression guard on the uncropped path, which was already correct
    // (xMin = 0 and xMax = lap length made the two lengths coincide — which
    // is exactly why the bug hid).
    const rects = tapeRects([ev({ s_norm_start: 0.5, s_norm_end: 0.7 })], null);
    expect(rects.length).toBe(1);
    const [x, , w] = rects[0]!.args as number[];
    expect(x).toBeCloseTo(60 + (500 / LAP_M) * 1020, 5);
    expect(w).toBeCloseTo((200 / LAP_M) * 1020, 5);
  });
});
