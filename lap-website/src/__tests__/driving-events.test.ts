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
  drawMistakeTape, drawCornerShade, eventColor, eventLabel, TAPE_HEIGHT_PX,
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

  it('draws nothing when plotW is zero or negative (transient resize state)', () => {
    const r = recorder();
    const zeroWidthGeo: TapeGeometry = { ...GEO, plotW: 0 };
    drawMistakeTape(r.ctx, [ev({ s_norm_start: 0.2, s_norm_end: 0.3 })], zeroWidthGeo);
    expect(r.rects().length).toBe(0);

    const r2 = recorder();
    const negWidthGeo: TapeGeometry = { ...GEO, plotW: -100 };
    drawMistakeTape(r2.ctx, [ev({ s_norm_start: 0.2, s_norm_end: 0.3 })], negWidthGeo);
    expect(r2.rects().length).toBe(0);
  });

  it('draws nothing when plotH is zero or negative', () => {
    const r = recorder();
    const zeroHeightGeo: TapeGeometry = { ...GEO, plotH: 0 };
    drawMistakeTape(r.ctx, [ev({ s_norm_start: 0.2, s_norm_end: 0.3 })], zeroHeightGeo);
    expect(r.rects().length).toBe(0);
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

describe('spanPx edge cases', () => {
  it('draws nothing for an event entirely left of the window', () => {
    const r = recorder();
    // s_norm -0.5 to -0.1: lap is 1000m (0..1000), so this is -500 to -100m
    // xToPixel(-500) = 100 + (-500) = -400, xToPixel(-100) = 0, both left of plotX=100
    drawMistakeTape(r.ctx, [ev({ s_norm_start: -0.5, s_norm_end: -0.1 })], GEO);
    expect(r.rects().length).toBe(0);
  });

  it('draws nothing for an event entirely right of the window', () => {
    const r = recorder();
    // s_norm 1.2 to 1.8: lap is 1000m, so this is 1200 to 1800m
    // xToPixel(1200) = 100 + 1200 = 1300, xToPixel(1800) = 1900, both right of plotX+plotW=1100
    drawMistakeTape(r.ctx, [ev({ s_norm_start: 1.2, s_norm_end: 1.8 })], GEO);
    expect(r.rects().length).toBe(0);
  });

  it('clips and draws a segment that straddles the left edge', () => {
    const r = recorder();
    drawMistakeTape(r.ctx, [ev({ s_norm_start: -0.1, s_norm_end: 0.2 })], GEO);
    const [x, , w] = r.rects()[0]!.args as number[];
    expect(x).toBe(GEO.plotX);  // clipped to left edge
    expect(x + w).toBeGreaterThan(GEO.plotX);  // has non-zero width
  });

  it('clips and draws a segment that straddles the right edge, staying within bounds', () => {
    const r = recorder();
    drawMistakeTape(r.ctx, [ev({ s_norm_start: 0.8, s_norm_end: 1.2 })], GEO);
    const [x, , w] = r.rects()[0]!.args as number[];
    expect(x).toBeGreaterThanOrEqual(GEO.plotX);
    expect(x + w).toBeLessThanOrEqual(GEO.plotX + GEO.plotW);  // never paints outside right boundary
  });
});

describe('eventLabel', () => {
  it('does not print magnitude for a non-quotable event', () => {
    const label = eventLabel(ev({
      magnitude: 12.4,
      magnitude_unit: 'm',
      magnitude_is_standalone_quotable: false,
    }));
    expect(label).not.toContain('12.4');
    expect(label).not.toContain('12');
    expect(label).toContain('over_slowing');  // event type is present
  });

  it('prints magnitude and unit for a quotable event', () => {
    const label = eventLabel(ev({
      magnitude: 9.8,
      magnitude_unit: 'm/s²',
      magnitude_is_standalone_quotable: true,
    }));
    expect(label).toContain('9.8');
    expect(label).toContain('m/s²');
  });

  it('respects null or non-finite magnitudes', () => {
    const nullMag = eventLabel(ev({ magnitude: null }));
    expect(nullMag).not.toContain('null');

    const nanMag = eventLabel(ev({ magnitude: NaN }));
    expect(nanMag).not.toContain('NaN');

    const infMag = eventLabel(ev({ magnitude: Infinity }));
    expect(infMag).not.toContain('Infinity');
  });
});

import { makeTapeGeometry } from '@/lib/driving-events-draw';

describe('makeTapeGeometry — the one place a frame bug can re-enter', () => {
  // A chart cropped to 400..900 m at 2 px per metre. This is the SHIPPED
  // helper, not a copy: mutating it in the source must turn these red.
  const build = () => makeTapeGeometry({
    xMin: 400, xMax: 900,
    xToPixel: (m: number) => (m - 400) * 2,
    plotX: 0, plotY: 0, plotW: 1000, plotH: 300,
  });

  it('anchors s_norm to xMin, not to zero, when the chart is zoomed', () => {
    const geo = build()!;
    const r = recorder();
    drawMistakeTape(r.ctx, [ev({ s_norm_start: 0.2, s_norm_end: 0.4 })], geo);
    // Assert the rect exists BEFORE destructuring it: with the offset
    // dropped, this fixture's mislocated span falls fully outside the plot
    // and Task 2's reject-before-clip guard discards it, so zero rects are
    // emitted. Destructuring straight into `.args` would then throw
    // TypeError on undefined — a crash that a future, unrelated regression
    // in that reject-before-clip guard would also produce, and could be
    // misread as "the xMin bug is back". This assertion names the actual
    // failure (wrong rect count) instead.
    expect(r.rects().length).toBe(1);
    const [x, , w] = r.rects()[0]!.args as number[];
    // s_norm 0.2 of the 500 m window = 500 m absolute = (500-400)*2 = 200 px.
    // Anchoring to zero instead would give (0.2*500 - 400)*2 = -600 px,
    // which clips to plotX and silently mislocates every event.
    expect(x).toBeCloseTo(200, 5);
    expect(w).toBeCloseTo(200, 5);   // 0.2 * 500 m * 2 px/m
  });

  it('derives lapLengthM from the visible window', () => {
    expect(build()!.lapLengthM).toBe(500);
  });

  it('refuses a degenerate or inverted window instead of dividing by it', () => {
    const bad = (xMin: number, xMax: number) => makeTapeGeometry({
      xMin, xMax, xToPixel: (m) => m,
      plotX: 0, plotY: 0, plotW: 100, plotH: 100,
    });
    expect(bad(400, 400)).toBeNull();
    expect(bad(900, 400)).toBeNull();
    expect(bad(NaN, 900)).toBeNull();
  });
});

import {
  resolveEnvelope, aggregateAnchor,
  type AnchorSummary, type CornerAnchorRow,
} from '@/lib/driving-events-draw';

describe('resolveEnvelope — never a boundary drawn from its own data', () => {
  it('uses the anchored baseline and names the tier', () => {
    const d = resolveEnvelope(
      { baseline_g: 1.02, tier: 'session_envelope_ellipse_fitted', reason: null }, 1.30);
    expect(d.draw).toBe(true);
    expect(d.radiusG).toBeCloseTo(1.02, 6);
    expect(d.label).toContain('1.02');
    expect(d.label.toLowerCase()).toContain('fitted');
  });

  it('still draws on the weaker driver-best tier, but says so', () => {
    const d = resolveEnvelope(
      { baseline_g: 0.94, tier: 'driver_best_session', reason: null }, 1.10);
    expect(d.draw).toBe(true);
    expect(d.label.toLowerCase()).toContain('your best');
  });

  it('DRAWS NOTHING when the anchor refused, and never falls back to maxG', () => {
    const d = resolveEnvelope(
      { baseline_g: null, tier: 'refused', reason: 'channel_untrusted' }, 1.30);
    expect(d.draw).toBe(false);
    expect(d.radiusG).toBeNull();
    expect(d.label.toLowerCase()).toContain('not measured');
    // The old defect: 1.30 * 0.95 = 1.235. It must appear nowhere.
    expect(d.label).not.toContain('1.23');
  });

  it('draws nothing when there is no anchor at all (pre-085 session)', () => {
    const d = resolveEnvelope(null, 1.30);
    expect(d.draw).toBe(false);
    expect(d.radiusG).toBeNull();
  });

  it('draws nothing for a non-finite or non-positive baseline', () => {
    for (const g of [NaN, Infinity, 0, -1]) {
      const d = resolveEnvelope(
        { baseline_g: g, tier: 'session_envelope_default_p2', reason: null }, 1.3);
      expect(d.draw).toBe(false);
    }
  });

  it('carries the refusal reason so the UI can explain itself', () => {
    const d = resolveEnvelope(
      { baseline_g: null, tier: 'refused', reason: 'channel_untrusted' }, 1.0);
    expect(d.reason).toBe('channel_untrusted');
  });
});

describe('resolveEnvelope — tier is an ALLOW-list, not a deny-list', () => {
  it('draws for each of the three tiers this build recognises', () => {
    for (const tier of [
      'session_envelope_ellipse_fitted', 'session_envelope_default_p2', 'driver_best_session',
    ]) {
      const d = resolveEnvelope({ baseline_g: 1.0, tier, reason: null }, 1.3);
      expect(d.draw).toBe(true);
    }
  });

  it('refuses the explicit refused tier', () => {
    const d = resolveEnvelope({ baseline_g: 1.0, tier: 'refused', reason: null }, 1.3);
    expect(d.draw).toBe(false);
  });

  it('refuses an unrecognised tier string even with a finite positive baseline -- ' +
     'the exact bug: an upstream rename/typo must not draw a confident circle', () => {
    const d = resolveEnvelope({ baseline_g: 1.02, tier: 'not_a_real_tier', reason: null }, 1.3);
    expect(d.draw).toBe(false);
    expect(d.radiusG).toBeNull();
    expect(d.label.toLowerCase()).toContain('not measured');
    expect(d.label).not.toContain('not_a_real_tier');
  });

  it('refuses a null tier', () => {
    expect(resolveEnvelope({ baseline_g: 1.02, tier: null, reason: null }, 1.3).draw).toBe(false);
  });

  it('refuses an undefined tier', () => {
    const anchor = { baseline_g: 1.02, reason: null } as unknown as AnchorSummary;
    expect(resolveEnvelope(anchor, 1.3).draw).toBe(false);
  });

  it('refuses an empty-string tier', () => {
    expect(resolveEnvelope({ baseline_g: 1.02, tier: '', reason: null }, 1.3).draw).toBe(false);
  });
});

describe('aggregateAnchor — per-corner anchors collapse to one session-level answer', () => {
  function row(over: Partial<CornerAnchorRow> = {}): CornerAnchorRow {
    return {
      grip_anchor_tier: 'session_envelope_ellipse_fitted',
      grip_anchor_reason: null,
      grip_anchor_baseline_g: 1.0,
      ...over,
    };
  }

  it('returns null for an empty list', () => {
    expect(aggregateAnchor([])).toBeNull();
    expect(aggregateAnchor(null)).toBeNull();
    expect(aggregateAnchor(undefined)).toBeNull();
  });

  it('takes the shared tier when every corner agrees', () => {
    const a = aggregateAnchor([row(), row(), row()]);
    expect(a?.tier).toBe('session_envelope_ellipse_fitted');
    expect(a?.baseline_g).toBe(1.0);
  });

  it('takes the modal tier across mixed tiers with no refusal', () => {
    const a = aggregateAnchor([
      row({ grip_anchor_tier: 'driver_best_session', grip_anchor_baseline_g: 0.9 }),
      row({ grip_anchor_tier: 'driver_best_session', grip_anchor_baseline_g: 0.9 }),
      row({ grip_anchor_tier: 'session_envelope_default_p2', grip_anchor_baseline_g: 1.1 }),
    ]);
    expect(a?.tier).toBe('driver_best_session');
    expect(a?.baseline_g).toBe(0.9);
  });

  it('prefers refused when ONE corner refuses among many good ones -- ' +
     'degrading loudly is the point, not averaging a refusal away', () => {
    const a = aggregateAnchor([
      row(), row(), row(), row(),
      row({ grip_anchor_tier: 'refused', grip_anchor_reason: 'channel_untrusted', grip_anchor_baseline_g: null }),
    ]);
    expect(a?.tier).toBe('refused');
    expect(a?.baseline_g).toBeNull();
    expect(a?.reason).toBe('channel_untrusted');
  });

  it('returns refused when every corner refused', () => {
    const a = aggregateAnchor([
      row({ grip_anchor_tier: 'refused', grip_anchor_baseline_g: null }),
      row({ grip_anchor_tier: 'refused', grip_anchor_baseline_g: null }),
    ]);
    expect(a?.tier).toBe('refused');
  });

  it('folds a null/absent per-corner tier into the refused vote rather than ' +
     'dropping it -- a corner with no anchor recorded is not evidence of grip', () => {
    // 2 corners recorded nothing, 1 recorded a good tier: absence outvotes it.
    const a = aggregateAnchor([
      row({ grip_anchor_tier: null }),
      row({ grip_anchor_tier: null }),
      row({ grip_anchor_tier: 'driver_best_session' }),
    ]);
    expect(a?.tier).toBe('refused');
  });

  it('a minority null/absent tier does not overrule a good majority', () => {
    const a = aggregateAnchor([
      row({ grip_anchor_tier: 'driver_best_session' }),
      row({ grip_anchor_tier: 'driver_best_session' }),
      row({ grip_anchor_tier: null }),
    ]);
    expect(a?.tier).toBe('driver_best_session');
  });

  it('aggregates an unrecognised tier string as-is -- drawability is ' +
     'resolveEnvelope\'s job, not aggregateAnchor\'s', () => {
    const a = aggregateAnchor([
      row({ grip_anchor_tier: 'not_a_real_tier' }),
      row({ grip_anchor_tier: 'not_a_real_tier' }),
    ]);
    expect(a?.tier).toBe('not_a_real_tier');
    // But it must still refuse to draw once resolved -- the allow-list catches it.
    expect(resolveEnvelope(a, 1.3).draw).toBe(false);
  });

  it('prefers refused when an unrecognised tier and an explicit refusal both appear', () => {
    const a = aggregateAnchor([
      row({ grip_anchor_tier: 'not_a_real_tier' }),
      row({ grip_anchor_tier: 'refused', grip_anchor_reason: 'channel_untrusted', grip_anchor_baseline_g: null }),
    ]);
    expect(a?.tier).toBe('refused');
    expect(a?.reason).toBe('channel_untrusted');
  });

  describe('an exact tie refuses regardless of row order', () => {
    const nullRows = [row({ grip_anchor_tier: null }), row({ grip_anchor_tier: null }),
                       row({ grip_anchor_tier: null }), row({ grip_anchor_tier: null })];
    const goodRows = [row({ grip_anchor_tier: 'driver_best_session' }), row({ grip_anchor_tier: 'driver_best_session' }),
                       row({ grip_anchor_tier: 'driver_best_session' }), row({ grip_anchor_tier: 'driver_best_session' })];

    // THIS is the test the coordinator asked for: one ordering alone would
    // have passed by luck under the old `>` scan (whichever tier's first
    // row came first in the array won). Both orders must agree, or the
    // fix isn't order-independent.
    it('null-tier rows first, then good rows (4 vs 4) -> refuses', () => {
      const a = aggregateAnchor([...nullRows, ...goodRows]);
      expect(a?.tier).toBe('refused');
      expect(a?.baseline_g).toBeNull();
    });

    it('good rows first, then null-tier rows (4 vs 4) -> refuses, SAME result', () => {
      const a = aggregateAnchor([...goodRows, ...nullRows]);
      expect(a?.tier).toBe('refused');
      expect(a?.baseline_g).toBeNull();
    });

    it('interleaved order (4 vs 4) -> refuses, SAME result', () => {
      const interleaved = [
        goodRows[0], nullRows[0], goodRows[1], nullRows[1],
        goodRows[2], nullRows[2], goodRows[3], nullRows[3],
      ];
      const a = aggregateAnchor(interleaved);
      expect(a?.tier).toBe('refused');
    });
  });

  it('refuses on a 3-way tie between three distinct good tiers', () => {
    const a = aggregateAnchor([
      row({ grip_anchor_tier: 'session_envelope_ellipse_fitted' }),
      row({ grip_anchor_tier: 'session_envelope_ellipse_fitted' }),
      row({ grip_anchor_tier: 'session_envelope_default_p2' }),
      row({ grip_anchor_tier: 'session_envelope_default_p2' }),
      row({ grip_anchor_tier: 'driver_best_session' }),
      row({ grip_anchor_tier: 'driver_best_session' }),
    ]);
    expect(a?.tier).toBe('refused');
  });

  it('a clear majority (not a tie) still wins outright, either direction', () => {
    // 5 good vs 3 null: good has a real plurality, no tie -> draws.
    const goodWins = aggregateAnchor([
      row({ grip_anchor_tier: 'driver_best_session' }), row({ grip_anchor_tier: 'driver_best_session' }),
      row({ grip_anchor_tier: 'driver_best_session' }), row({ grip_anchor_tier: 'driver_best_session' }),
      row({ grip_anchor_tier: 'driver_best_session' }),
      row({ grip_anchor_tier: null }), row({ grip_anchor_tier: null }), row({ grip_anchor_tier: null }),
    ]);
    expect(goodWins?.tier).toBe('driver_best_session');

    // 5 null vs 3 good: absence has a real plurality, no tie -> refuses.
    const nullWins = aggregateAnchor([
      row({ grip_anchor_tier: null }), row({ grip_anchor_tier: null }), row({ grip_anchor_tier: null }),
      row({ grip_anchor_tier: null }), row({ grip_anchor_tier: null }),
      row({ grip_anchor_tier: 'driver_best_session' }), row({ grip_anchor_tier: 'driver_best_session' }),
      row({ grip_anchor_tier: 'driver_best_session' }),
    ]);
    expect(nullWins?.tier).toBe('refused');
  });
});
