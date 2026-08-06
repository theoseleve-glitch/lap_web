import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import DrivingEventsPanel from '@/components/app/DrivingEventsPanel';

vi.mock('@/lib/driving-events', async (orig) => {
  const actual = await orig<typeof import('@/lib/driving-events')>();
  return { ...actual, fetchDrivingEvents: vi.fn() };
});
import { fetchDrivingEvents } from '@/lib/driving-events';

const CLEAN_CAP = {
  over_slowing: 'not_triggered', late_throttle: 'not_triggered',
  re_braking: 'not_triggered', envelope_under_use: 'not_triggered',
} as const;

beforeEach(() => vi.mocked(fetchDrivingEvents).mockReset());

describe('DrivingEventsPanel distinguishes the empty states', () => {
  it('says nothing to fix when every detector looked and found nothing', async () => {
    vi.mocked(fetchDrivingEvents).mockResolvedValue({
      events: [], available: false, capability: { ...CLEAN_CAP }, capability_available: true,
    });
    render(<DrivingEventsPanel sessionId="s1" />);
    await waitFor(() => expect(screen.getByTestId('events-empty-clean')).toBeTruthy());
    expect(screen.queryByTestId('events-empty-degraded')).toBeNull();
  });

  it('says it could not measure when a detector reported insufficient', async () => {
    vi.mocked(fetchDrivingEvents).mockResolvedValue({
      events: [], available: false,
      capability: { ...CLEAN_CAP, over_slowing: 'insufficient' }, capability_available: true,
    });
    render(<DrivingEventsPanel sessionId="s1" />);
    await waitFor(() => expect(screen.getByTestId('events-empty-degraded')).toBeTruthy());
    expect(screen.queryByTestId('events-empty-clean')).toBeNull();
  });

  it('names which detectors could not look', async () => {
    vi.mocked(fetchDrivingEvents).mockResolvedValue({
      events: [], available: false,
      capability: { ...CLEAN_CAP, re_braking: 'insufficient' }, capability_available: true,
    });
    render(<DrivingEventsPanel sessionId="s1" />);
    await waitFor(() =>
      expect(screen.getByTestId('events-empty-degraded').textContent).toContain('re_braking'));
  });

  // Regression: describeCapability is an allow-list (only 'detected' and
  // 'not_triggered' are healthy), so ANY other string -- including one this
  // build has never seen, like a future backend's 'timed_out' -- makes the
  // session degraded. The naming logic must inherit that same allow-list,
  // not re-derive its own deny-list of just 'insufficient', or an
  // unrecognised value renders degraded with nothing named.
  it('names a detector reporting an unrecognised capability value, not just "insufficient"', async () => {
    vi.mocked(fetchDrivingEvents).mockResolvedValue({
      events: [], available: false,
      // Deliberately a value this build's CapabilityValue union does not
      // include -- that's the point of the test. Matches the `as never`
      // convention already used for the same purpose in driving-events.test.ts.
      capability: { ...CLEAN_CAP, over_slowing: 'timed_out' as never }, capability_available: true,
    });
    render(<DrivingEventsPanel sessionId="s1" />);
    const el = await waitFor(() => screen.getByTestId('events-empty-degraded'));
    expect(el.textContent).toContain('over_slowing');
    // The old bug: an unnamed blind list left a bare "here: ." trailing
    // punctuation artifact that reads as a rendering bug, not a message.
    expect(el.textContent).not.toMatch(/here:\s*\.$/);
  });
});

describe('DrivingEventsPanel obeys the attribution constraint', () => {
  const base = {
    lap_number: 3, corner_id: 4, s_norm_start: 0.2, s_norm_end: 0.3,
    validity: 'measured', reason: null, n_samples_in_window: 40,
    anchor_tier: 'session_envelope_ellipse_fitted', anchor_reason: null,
    evidence: {},
  };

  it('shows the cost as attributable for a caused event', async () => {
    vi.mocked(fetchDrivingEvents).mockResolvedValue({
      events: [{ ...base, event_type: 'over_slowing', magnitude: 1.4, magnitude_unit: 'm/s',
                 time_cost_s: 0.31, time_cost_attribution: 'caused',
                 magnitude_is_standalone_quotable: true }],
      available: true, capability: { ...CLEAN_CAP, over_slowing: 'detected' },
      capability_available: true,
    });
    render(<DrivingEventsPanel sessionId="s1" />);
    await waitFor(() => expect(screen.getByTestId('event-row-0')).toBeTruthy());
    expect(screen.getByTestId('event-cost-0').textContent).toContain('0.31');
    expect(screen.queryByTestId('event-cost-context-0')).toBeNull();
  });

  it('never prints a context event magnitude as a number', async () => {
    vi.mocked(fetchDrivingEvents).mockResolvedValue({
      events: [{ ...base, event_type: 'late_throttle', magnitude: 12.4, magnitude_unit: 'm',
                 time_cost_s: 0.31, time_cost_attribution: 'context',
                 magnitude_is_standalone_quotable: false }],
      available: true, capability: { ...CLEAN_CAP, late_throttle: 'detected' },
      capability_available: true,
    });
    render(<DrivingEventsPanel sessionId="s1" />);
    await waitFor(() => expect(screen.getByTestId('event-row-0')).toBeTruthy());
    expect(screen.getByTestId('event-row-0').textContent).not.toContain('12.4');
  });
});

describe('DrivingEventsPanel renders a row a driver can read', () => {
  // Everything here was checked by reading the JSX and ruled cosmetic. It was
  // not: rendered, the row read `C4 L5 · late_throttlein a corner losing
  // 0.31s` with an invisible colour chip. These assert the RENDER.
  const base = {
    lap_number: 3, corner_id: 4, s_norm_start: 0.2, s_norm_end: 0.3,
    validity: 'measured', reason: null, n_samples_in_window: 40,
    anchor_tier: 'session_envelope_ellipse_fitted', anchor_reason: null,
    evidence: {},
  };

  async function renderRow(over: Record<string, unknown>) {
    vi.mocked(fetchDrivingEvents).mockResolvedValue({
      events: [{ ...base, ...over } as never],
      available: true, capability: { ...CLEAN_CAP, over_slowing: 'detected' },
      capability_available: true,
    });
    render(<DrivingEventsPanel sessionId="s1" />);
    return waitFor(() => screen.getByTestId('event-row-0'));
  }

  it('separates the label from the cost instead of gluing them', async () => {
    const row = await renderRow({
      event_type: 'late_throttle', magnitude: 12.4, magnitude_unit: 'm',
      time_cost_s: 0.31, time_cost_attribution: 'context',
      magnitude_is_standalone_quotable: false,
    });
    // The defect, exactly: "late_throttlein a corner losing".
    expect(row.textContent).not.toMatch(/late_throttlein/);
    expect(row.textContent).toMatch(/late_throttle\s+in a corner losing/);
  });

  it('separates the label from an attributed cost too', async () => {
    const row = await renderRow({
      event_type: 'over_slowing', magnitude: 1.4, magnitude_unit: 'm/s',
      time_cost_s: 0.31, time_cost_attribution: 'caused',
      magnitude_is_standalone_quotable: true,
    });
    expect(row.textContent).not.toMatch(/m\/scosts/);
    expect(row.textContent).toMatch(/1\.4 m\/s\s+costs 0\.31s/);
  });

  it('gives the colour swatch real dimensions so it actually paints', async () => {
    await renderRow({
      event_type: 'over_slowing', magnitude: 1.4, magnitude_unit: 'm/s',
      time_cost_s: 0.31, time_cost_attribution: 'caused',
      magnitude_is_standalone_quotable: true,
    });
    const chip = screen.getByTestId('event-swatch-0') as HTMLElement;
    // A bare <span style={{background}}/> is an empty inline box: zero width,
    // zero height, nothing on screen — and it is the only link between this
    // row and its band on the tape.
    expect(chip.style.width).not.toBe('');
    expect(parseFloat(chip.style.width)).toBeGreaterThan(0);
    expect(parseFloat(chip.style.height)).toBeGreaterThan(0);
    expect(chip.style.display).toBe('inline-block');
    // and it carries the same colour the tape paints for this event type
    expect(chip.style.background || chip.style.backgroundColor).toContain('255, 42, 42');
  });

  it('never shows a magnitude with no unit', async () => {
    const row = await renderRow({
      event_type: 're_braking', magnitude: 9.8, magnitude_unit: null,
      time_cost_s: null, time_cost_attribution: 'no_cost',
      magnitude_is_standalone_quotable: true,
    });
    // "C4 L3 · re_braking 9.8" — 9.8 of what?
    expect(row.textContent).not.toContain('9.8');
    expect(row.textContent).toContain('re_braking');
  });
});

