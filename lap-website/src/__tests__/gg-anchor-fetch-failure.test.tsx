/**
 * A failing corner-metrics fetch must not become a claim about the driver.
 *
 * WHY THIS FILE EXISTS SEPARATELY FROM gg-anchor-load-state.test.ts. That
 * file drives `drawGG` with a hand-made `{status:'error'}` and proves the
 * DRAW path. It proves nothing about the `catch` that produces that value.
 * Mutating `setFetchedAnchor({ status: 'error' })` back to
 * `{ status: 'loaded', anchor: null }` -- literally reintroducing the bug --
 * left all 558 tests green.
 *
 * That is this branch's signature failure once more: a correct, unguarded
 * fix. The next refactor of that catch would silently restore "Grip limit
 * not measured for this session" on every network failure, and nothing would
 * go red. So this test mounts the REAL component with `api.get` rejecting
 * and asserts what actually reaches the canvas.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, waitFor, cleanup } from '@testing-library/react';
import { GGExplorer } from '@/components/shared/charts/GGExplorer';

vi.mock('@/lib/api-client', async (orig) => {
  const actual = await orig<typeof import('@/lib/api-client')>();
  return { ...actual, api: { ...actual.api, get: vi.fn() }, apiFetch: vi.fn() };
});
import { api } from '@/lib/api-client';

const GG = {
  accel_lat: [0.1, -0.4, 0.9, -0.8, 0.3],
  accel_long: [0.2, 0.5, -0.3, 0.1, -0.6],
};

/**
 * jsdom has no 2D context, so drawGG would bail at `if (!ctx) return` and
 * this test would pass without drawing anything. Install a recorder instead
 * and capture every fillText the component paints.
 */
let painted: string[] = [];
let restoreCtx: (() => void) | null = null;
let restoreRect: (() => void) | null = null;

beforeEach(() => {
  painted = [];
  vi.mocked(api.get).mockReset();

  // jsdom has no ResizeObserver; the component attaches one to redraw on
  // resize. A no-op stub is enough — the draws under test are triggered by
  // state, not by resize.
  if (!('ResizeObserver' in globalThis)) {
    (globalThis as unknown as Record<string, unknown>).ResizeObserver = class {
      observe() {} unobserve() {} disconnect() {}
    };
  }

  const ctx = new Proxy({} as CanvasRenderingContext2D, {
    get(_t, prop: string) {
      if (prop === 'measureText') return (t: string) => ({ width: t.length * 5 });
      if (prop === 'canvas') return undefined;
      return (...args: unknown[]) => {
        if (prop === 'fillText') painted.push(String(args[0]));
      };
    },
    set() { return true; },
  });

  const origCtx = HTMLCanvasElement.prototype.getContext;
  HTMLCanvasElement.prototype.getContext = (() => ctx) as unknown as typeof origCtx;
  restoreCtx = () => { HTMLCanvasElement.prototype.getContext = origCtx; };

  const origRect = HTMLCanvasElement.prototype.getBoundingClientRect;
  HTMLCanvasElement.prototype.getBoundingClientRect =
    (() => ({ width: 600, height: 400, top: 0, left: 0, right: 600, bottom: 400,
              x: 0, y: 0, toJSON: () => ({}) })) as typeof origRect;
  restoreRect = () => { HTMLCanvasElement.prototype.getBoundingClientRect = origRect; };
});

afterEach(() => {
  cleanup();
  restoreCtx?.();
  restoreRect?.();
});

/** Everything the mounted component wrote to the canvas, joined. */
const text = () => painted.join(' | ');

describe('GGExplorer, mounted, when corner-metrics fails', () => {
  it('says the lookup failed — it does NOT say grip was not measured', async () => {
    vi.mocked(api.get).mockRejectedValue(new Error('500 Internal Server Error'));

    render(<GGExplorer sessionId="s1" data={GG} />);

    await waitFor(() => expect(text()).toContain('could not load'));
    // THE ASSERTION THAT MATTERS: a transport failure is not evidence about
    // this driver's grip, and must never be worded as if it were.
    expect(text()).not.toContain('not measured');
  });

  it('says the same for a 404 on a pre-085 session', async () => {
    vi.mocked(api.get).mockRejectedValue(
      Object.assign(new Error('Not Found'), { status: 404 }));

    render(<GGExplorer sessionId="s1" data={GG} />);

    await waitFor(() => expect(text()).toContain('could not load'));
    expect(text()).not.toContain('not measured');
  });

  it('DOES say grip was not measured when the fetch SUCCEEDS and the producer refused', async () => {
    // The control: the same component, the same canvas, a working fetch.
    // Without this, a test asserting only "never says not measured" would
    // pass against a build that deleted the refusal sentence entirely.
    vi.mocked(api.get).mockResolvedValue({
      available: true,
      corners: [{ grip_anchor_tier: 'refused', grip_anchor_reason: 'channel_untrusted',
                  grip_anchor_baseline_g: null }],
    });

    render(<GGExplorer sessionId="s1" data={GG} />);

    await waitFor(() => expect(text()).toContain('not measured'));
    expect(text()).not.toContain('could not load');
  });

  it('draws the measured boundary when the fetch succeeds and the anchor holds', async () => {
    vi.mocked(api.get).mockResolvedValue({
      available: true,
      corners: [
        { grip_anchor_tier: 'session_envelope_ellipse_default_p2', grip_anchor_reason: null,
          grip_anchor_baseline_g: 1.02 },
        { grip_anchor_tier: 'session_envelope_ellipse_default_p2', grip_anchor_reason: null,
          grip_anchor_baseline_g: 1.02 },
      ],
    });

    render(<GGExplorer sessionId="s1" data={GG} />);

    // Also the end-to-end proof of CRITICAL 1: this is the tier the backend
    // selects by default, through the real component, from a real payload.
    await waitFor(() => expect(text()).toContain('1.02'));
    expect(text()).toContain('default p=2');
    expect(text()).not.toContain('not measured');
    expect(text()).not.toContain('could not load');
  });
});
