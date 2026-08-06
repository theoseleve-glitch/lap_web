import { describe, it, expect } from 'vitest';
import {
  canQuoteMagnitude,
  canAttributeCost,
  describeCapability,
  type DrivingEvent,
  type DrivingEventsResponse,
} from '@/lib/driving-events';

function ev(over: Partial<DrivingEvent> = {}): DrivingEvent {
  return {
    lap_number: 3,
    corner_id: 4,
    event_type: 'over_slowing',
    s_norm_start: 0.21,
    s_norm_end: 0.30,
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

describe('rendering constraints come from the payload, not a hardcoded list', () => {
  it('lets a caused, quotable event be quoted and attributed', () => {
    const e = ev();
    expect(canQuoteMagnitude(e)).toBe(true);
    expect(canAttributeCost(e)).toBe(true);
  });

  it('refuses to quote or attribute a context event', () => {
    const e = ev({
      event_type: 'late_throttle',
      magnitude: 12.4,
      magnitude_unit: 'm',
      time_cost_attribution: 'context',
      magnitude_is_standalone_quotable: false,
    });
    expect(canQuoteMagnitude(e)).toBe(false);
    expect(canAttributeCost(e)).toBe(false);
  });

  it('treats the two axes as independent: no cost but a quotable magnitude', () => {
    const e = ev({
      event_type: 're_braking',
      magnitude: 9.8,
      magnitude_unit: 'm/s2',
      time_cost_s: null,
      time_cost_attribution: 'no_cost',
      magnitude_is_standalone_quotable: true,
    });
    expect(canQuoteMagnitude(e)).toBe(true);
    expect(canAttributeCost(e)).toBe(false);
  });

  it('refuses an unknown attribution rather than defaulting to permissive', () => {
    const e = ev({ time_cost_attribution: 'something_new' as never });
    expect(canAttributeCost(e)).toBe(false);
  });

  it('never quotes a non-finite magnitude even when the flag allows it', () => {
    expect(canQuoteMagnitude(ev({ magnitude: NaN }))).toBe(false);
    expect(canQuoteMagnitude(ev({ magnitude: null }))).toBe(false);
  });
});

describe('an empty event list is not one state', () => {
  function res(over: Partial<DrivingEventsResponse> = {}): DrivingEventsResponse {
    return {
      events: [], available: false,
      capability: {
        over_slowing: 'not_triggered', late_throttle: 'not_triggered',
        re_braking: 'not_triggered', envelope_under_use: 'not_triggered',
      },
      capability_available: true,
      ...over,
    };
  }

  it('calls a session with events has-events', () => {
    expect(describeCapability(res({ events: [ev()], available: true }))).toBe('has-events');
  });

  it('calls all-not_triggered clean', () => {
    expect(describeCapability(res())).toBe('clean');
  });

  it('calls any insufficient detector degraded, NOT clean', () => {
    const r = res();
    r.capability.over_slowing = 'insufficient';
    expect(describeCapability(r)).toBe('degraded');
  });

  it('calls a missing capability record unavailable, distinct from clean', () => {
    expect(describeCapability(res({ capability: {}, capability_available: false })))
      .toBe('unavailable');
  });

  it('calls a null response unavailable', () => {
    expect(describeCapability(null)).toBe('unavailable');
  });

  it('treats an unrecognised capability value as degraded, not clean', () => {
    const r = res();
    r.capability.over_slowing = 'timed_out' as never;
    expect(describeCapability(r)).toBe('degraded');
  });

  it('treats a mix of recognised and unrecognised values as degraded', () => {
    const r = res();
    r.capability.over_slowing = 'timed_out' as never;
    r.capability.late_throttle = 'not_triggered';
    expect(describeCapability(r)).toBe('degraded');
  });
});

import {
  drawMistakeTape, drawCornerShade, eventColor, TAPE_HEIGHT_PX,
  type TapeGeometry,
} from '@/lib/driving-events-draw';

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

const GEO: TapeGeometry = {
  xToPixel: (m) => 100 + m,     // 1 px per metre, origin at 100
  plotX: 100, plotY: 20, plotW: 1000, plotH: 300, lapLengthM: 1000,
};

describe('drawMistakeTape', () => {
  it('places a segment at the event span converted from s_norm', () => {
    const r = recorder();
    drawMistakeTape(r.ctx, [ev({ s_norm_start: 0.2, s_norm_end: 0.3 })], GEO);
    const rects = r.rects();
    expect(rects.length).toBe(1);
    const [x, , w, h] = rects[0]!.args as number[];
    expect(x).toBeCloseTo(300, 5);   // 100 + 0.2*1000
    expect(w).toBeCloseTo(100, 5);   // (0.3-0.2)*1000
    expect(h).toBe(TAPE_HEIGHT_PX);
  });

  it('draws nothing for an event with no span', () => {
    const r = recorder();
    drawMistakeTape(r.ctx, [ev({ s_norm_start: null, s_norm_end: null })], GEO);
    expect(r.rects().length).toBe(0);
  });

  it('draws nothing for a non-finite or inverted span', () => {
    const r = recorder();
    drawMistakeTape(r.ctx, [
      ev({ s_norm_start: NaN, s_norm_end: 0.3 }),
      ev({ s_norm_start: 0.5, s_norm_end: 0.4 }),
    ], GEO);
    expect(r.rects().length).toBe(0);
  });

  it('clips a segment to the plot area instead of painting outside it', () => {
    const r = recorder();
    drawMistakeTape(r.ctx, [ev({ s_norm_start: -0.5, s_norm_end: 1.5 })], GEO);
    const [x, , w] = r.rects()[0]!.args as number[];
    expect(x).toBeGreaterThanOrEqual(GEO.plotX);
    expect(x + w).toBeLessThanOrEqual(GEO.plotX + GEO.plotW);
  });

  it('gives a zero-width span a minimum visible width', () => {
    const r = recorder();
    drawMistakeTape(r.ctx, [ev({ s_norm_start: 0.4, s_norm_end: 0.4 })], GEO);
    const [, , w] = r.rects()[0]!.args as number[];
    expect(w).toBeGreaterThanOrEqual(1);
  });

  it('draws one segment per event', () => {
    const r = recorder();
    drawMistakeTape(r.ctx, [
      ev({ s_norm_start: 0.1, s_norm_end: 0.2 }),
      ev({ s_norm_start: 0.5, s_norm_end: 0.6 }),
    ], GEO);
    expect(r.rects().length).toBe(2);
  });
});

describe('eventColor', () => {
  it('distinguishes a costed event from a context one', () => {
    const caused = ev();
    const context = ev({ event_type: 'late_throttle', time_cost_attribution: 'context',
                         magnitude_is_standalone_quotable: false });
    expect(eventColor(caused)).not.toBe(eventColor(context));
  });

  it('returns a parseable rgba string for every event type', () => {
    for (const t of ['over_slowing', 'late_throttle', 're_braking', 'envelope_under_use', 'unknown']) {
      expect(eventColor(ev({ event_type: t }))).toMatch(/^rgba?\(/);
    }
  });
});

describe('drawCornerShade', () => {
  it('shades the full plot height over the event span', () => {
    const r = recorder();
    drawCornerShade(r.ctx, [ev({ s_norm_start: 0.2, s_norm_end: 0.3 })], GEO);
    const [, y, , h] = r.rects()[0]!.args as number[];
    expect(y).toBe(GEO.plotY);
    expect(h).toBe(GEO.plotH);
  });
});
