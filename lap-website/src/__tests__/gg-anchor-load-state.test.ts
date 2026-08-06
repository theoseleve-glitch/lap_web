/**
 * The g-g must not state a refusal before it has looked.
 *
 * `GGExplorer` held a bare `AnchorSummary | null` starting at `null`, and
 * `/gg-data` and `/corner-metrics` are independent fetches. Whenever gg-data
 * won the race the canvas painted "Grip limit not measured for this session"
 * and only later redrew with the arc. The same `null` also absorbed a network
 * failure, so a 500 rendered as a statement about the driver's data.
 *
 * Three different sentences now: "we have not looked", "we could not look",
 * "we looked and the producer refused". Asserted BOTH on the pure resolver
 * and by driving the SHIPPED `drawGG` against a canvas recorder — the pure
 * test alone would not prove the component uses it.
 */
import { describe, it, expect } from 'vitest';
import {
  resolveEnvelopeForLoad, REFUSAL_LABEL, LOADING_LABEL, LOAD_FAILED_LABEL,
  type AnchorLoad,
} from '@/lib/driving-events-draw';
import { drawGG } from '@/components/shared/charts/GGExplorer';

describe('resolveEnvelopeForLoad separates the three not-drawn cases', () => {
  const cases: Array<[string, AnchorLoad | null | undefined, string, string]> = [
    ['have not looked yet', { status: 'loading' }, 'loading', LOADING_LABEL],
    ['could not look', { status: 'error' }, 'load_failed', LOAD_FAILED_LABEL],
    ['looked, producer refused',
      { status: 'loaded', anchor: { baseline_g: null, tier: 'refused', reason: 'channel_untrusted' } },
      'refused', REFUSAL_LABEL],
    ['looked, no anchor row at all',
      { status: 'loaded', anchor: null }, 'refused', REFUSAL_LABEL],
    ['no argument at all', null, 'loading', LOADING_LABEL],
  ];

  it.each(cases)('%s -> %s', (_name, load, outcome, label) => {
    const d = resolveEnvelopeForLoad(load, 1.3);
    expect(d.draw).toBe(false);
    expect(d.radiusG).toBeNull();
    expect(d.outcome).toBe(outcome);
    expect(d.label).toBe(label);
  });

  it('the three labels are mutually distinct', () => {
    expect(new Set([LOADING_LABEL, LOAD_FAILED_LABEL, REFUSAL_LABEL]).size).toBe(3);
  });

  it('neither pending nor failed says "not measured"', () => {
    // The whole point: a fetch that has not returned, or one that 500'd, is
    // not evidence about this driver's grip.
    expect(LOADING_LABEL.toLowerCase()).not.toContain('not measured');
    expect(LOAD_FAILED_LABEL.toLowerCase()).not.toContain('not measured');
  });

  it('still draws when the anchor loaded with a usable baseline', () => {
    const d = resolveEnvelopeForLoad(
      { status: 'loaded', anchor: { baseline_g: 1.02, tier: 'session_envelope_ellipse_fitted', reason: null } },
      1.3);
    expect(d.draw).toBe(true);
    expect(d.radiusG).toBeCloseTo(1.02, 6);
  });
});

/* ── the shipped drawGG actually paints those sentences ───────────── */

function recorder() {
  const calls: Array<{ op: string; args: unknown[] }> = [];
  const ctx = new Proxy({} as CanvasRenderingContext2D, {
    get(_t, prop: string) {
      if (prop === 'measureText') return (t: string) => ({ width: t.length * 5 });
      if (prop === 'canvas') return undefined;
      return (...args: unknown[]) => { calls.push({ op: prop, args }); };
    },
    set(_t, prop: string, value) { calls.push({ op: `set:${prop}`, args: [value] }); return true; },
  });
  return { ctx, calls };
}

/** Minimal stand-in for the canvas drawGG is handed. No jsdom canvas needed. */
function fakeCanvas(ctx: CanvasRenderingContext2D) {
  return {
    getContext: () => ctx,
    getBoundingClientRect: () => ({ width: 600, height: 400 }),
    width: 0, height: 0,
  } as unknown as HTMLCanvasElement;
}

const GG = {
  accel_lat: [0.1, -0.4, 0.9, -0.8, 0.3],
  accel_long: [0.2, 0.5, -0.3, 0.1, -0.6],
};

/** Everything drawGG wrote with fillText, joined. */
function painted(load: AnchorLoad | null) {
  const r = recorder();
  drawGG(fakeCanvas(r.ctx), GG, null, null, null, load);
  return r.calls
    .filter((c) => c.op === 'fillText')
    .map((c) => String((c.args as unknown[])[0]))
    .join(' | ');
}

describe('drawGG paints the load state it was given', () => {
  it('says it is loading, not that grip was not measured', () => {
    const text = painted({ status: 'loading' });
    expect(text).toContain('loading');
    expect(text).not.toContain('not measured');
  });

  it('says the lookup failed, not that grip was not measured', () => {
    const text = painted({ status: 'error' });
    expect(text).toContain('could not load');
    expect(text).not.toContain('not measured');
  });

  it('says grip was not measured only when the producer actually refused', () => {
    const text = painted({
      status: 'loaded',
      anchor: { baseline_g: null, tier: 'refused', reason: 'channel_untrusted' },
    });
    expect(text).toContain('not measured');
  });

  it('draws the measured boundary and its tier when the anchor loaded', () => {
    const r = recorder();
    drawGG(fakeCanvas(r.ctx), GG, null, null, null, {
      status: 'loaded',
      anchor: { baseline_g: 1.02, tier: 'session_envelope_ellipse_fitted', reason: null },
    });
    const text = r.calls.filter((c) => c.op === 'fillText')
      .map((c) => String((c.args as unknown[])[0])).join(' | ');
    expect(text).toContain('1.02');
    expect(text).toContain('fitted');
    // and an actual arc was stroked for it
    expect(r.calls.some((c) => c.op === 'arc')).toBe(true);
  });

  it('draws NO arc while loading', () => {
    const r = recorder();
    drawGG(fakeCanvas(r.ctx), GG, null, null, null, { status: 'loading' });
    // The scatter dots are drawn with arc() too, so isolate the envelope by
    // its dash pattern: the envelope is the only stroked dashed circle.
    expect(r.calls.some((c) => c.op === 'setLineDash'
      && JSON.stringify((c.args as unknown[])[0]) === '[6,4]')).toBe(false);
  });
});
