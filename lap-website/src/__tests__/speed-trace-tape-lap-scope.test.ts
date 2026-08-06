/**
 * The tape may only mark events belonging to the lap actually drawn.
 *
 * `GET /sessions/<id>/speed-trace?lap=N` returns ONE lap. `GET
 * /sessions/<id>/driving-events` takes no lap parameter and returns the
 * session's top-N ranked corner-laps across EVERY lap. Before this test,
 * `drawMistakeTape` never read `lap_number`, so all of them painted onto
 * whichever lap the driver happened to be looking at: a red band at turn 3
 * with a perfectly normal speed curve underneath it, because the event was
 * two laps ago. The ranked panel discloses the lap in its text ("C3 L1");
 * the tape is a pixel-level claim about THIS trace and has no way to.
 *
 * Exercises the SHIPPED `drawSpeedTrace` against a canvas recorder, so the
 * filter is asserted where it runs rather than on a copy.
 */
import { describe, it, expect } from 'vitest';
import { drawSpeedTrace } from '@/components/shared/charts/SpeedTraceChart';
import { TAPE_HEIGHT_PX } from '@/lib/driving-events-draw';
import type { DrivingEvent } from '@/lib/driving-events';

function ev(over: Partial<DrivingEvent> = {}): DrivingEvent {
  return {
    lap_number: 7,
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

const W = 1100;
const H = 370;
const DISTANCES = Array.from({ length: 11 }, (_, i) => i * 100);
const SPEEDS = DISTANCES.map(() => 30);

/** The tape's own rects are the only fillRects of exactly TAPE_HEIGHT_PX. */
function tapeRects(calls: ReturnType<typeof recorder>['calls']) {
  return calls.filter(
    (c) => c.op === 'fillRect' && (c.args as number[])[3] === TAPE_HEIGHT_PX);
}

function draw(events: DrivingEvent[], lap: number | null | undefined) {
  const r = recorder();
  drawSpeedTrace(r.ctx, W, H, {
    distances: DISTANCES, speeds: SPEEDS, hoverDistanceM: null,
    drivingEvents: events, drivingEventsLap: lap,
  });
  return tapeRects(r.calls);
}

describe('the mistake tape is scoped to the displayed lap', () => {
  it('marks an event that belongs to the displayed lap', () => {
    expect(draw([ev({ lap_number: 7 })], 7).length).toBe(1);
  });

  it('draws NOTHING for an event from another lap', () => {
    expect(draw([ev({ lap_number: 2 })], 7).length).toBe(0);
  });

  it('keeps only the displayed lap out of a mixed ranked list', () => {
    // The real shape of the payload: the top-N ranking spans the session.
    const rects = draw([
      ev({ lap_number: 2, corner_id: 1, s_norm_start: 0.05, s_norm_end: 0.10 }),
      ev({ lap_number: 5, corner_id: 2, s_norm_start: 0.30, s_norm_end: 0.35 }),
      ev({ lap_number: 7, corner_id: 3, s_norm_start: 0.60, s_norm_end: 0.65 }),
      ev({ lap_number: 7, corner_id: 4, s_norm_start: 0.80, s_norm_end: 0.85 }),
      ev({ lap_number: 9, corner_id: 5, s_norm_start: 0.90, s_norm_end: 0.95 }),
    ], 7);
    expect(rects.length).toBe(2);

    // ...and they are the RIGHT two: pW = 1100-60-20 = 1020 px over a 1000 m
    // lap starting at pad.left = 60, so s_norm 0.60 -> 60 + 612 = 672 and
    // 0.80 -> 60 + 816 = 876. A filter that kept two arbitrary events would
    // pass a bare count.
    const xs = rects.map((c) => (c.args as number[])[0]!).sort((a, b) => a - b);
    expect(xs[0]).toBeCloseTo(60 + 0.60 * 1020, 5);
    expect(xs[1]).toBeCloseTo(60 + 0.80 * 1020, 5);
  });

  it('draws nothing when the caller did not say which lap is displayed', () => {
    // Not a defensive nicety: without the lap, "does this band belong to
    // this curve" is unanswerable, and an unverifiable claim must not paint.
    expect(draw([ev({ lap_number: 7 })], null).length).toBe(0);
    expect(draw([ev({ lap_number: 7 })], undefined).length).toBe(0);
    expect(draw([ev({ lap_number: 7 })], NaN).length).toBe(0);
  });

  it('does not let an event with NO lap_number match an absent displayed lap', () => {
    // The case the equality filter alone cannot refuse: `undefined ===
    // undefined` is true, so a payload missing `lap_number` would match a
    // chart that never said which lap it is showing, and paint. This is the
    // one input that makes the explicit lap guard observable rather than
    // decorative — without it, the two unknowns agree and the band appears.
    const spanless = { ...ev(), lap_number: undefined } as unknown as DrivingEvent;
    expect(draw([spanless], undefined).length).toBe(0);
  });

  it('draws nothing when no event belongs to the displayed lap', () => {
    expect(draw([ev({ lap_number: 1 }), ev({ lap_number: 2 })], 7).length).toBe(0);
  });
});
