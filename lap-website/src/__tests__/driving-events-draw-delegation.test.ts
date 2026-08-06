import { describe, it, expect, vi } from 'vitest';

/**
 * Delegation test for eventLabel.
 *
 * This test verifies that eventLabel CALLS canQuoteMagnitude rather than
 * inlining its rule. A behavioural test alone cannot catch drift: if the rule
 * is inlined, the test passes even after the shared rule is updated (e.g., a
 * new validity state, a unit that must not be printed). This test uses vi.mock
 * to prove eventLabel is calling the shared function, not a copy.
 */

vi.mock('@/lib/driving-events', async () => {
  const actual = await vi.importActual('@/lib/driving-events');
  return {
    ...actual,
    canQuoteMagnitude: () => false,  // Always reject, regardless of event payload
  };
});

// Import AFTER the mock is set up
import { eventLabel, type TapeGeometry } from '@/lib/driving-events-draw';

function ev(over: Record<string, unknown> = {}) {
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
    magnitude_is_standalone_quotable: true,  // Flag says yes, but mock overrides it
    also_fired: [],
    ...over,
  };
}

describe('eventLabel delegation to canQuoteMagnitude', () => {
  it('stops printing magnitude when canQuoteMagnitude returns false, even if event flags allow it', () => {
    // This event's own fields would normally make it quotable:
    // - magnitude: finite (1.4)
    // - magnitude_unit: present ('m/s')
    // - magnitude_is_standalone_quotable: true
    //
    // But the mocked canQuoteMagnitude always returns false, so if eventLabel
    // calls the real function (not an inlined copy), it must NOT print the magnitude.
    const e = ev({ magnitude: 1.4, magnitude_unit: 'm/s', magnitude_is_standalone_quotable: true });
    const label = eventLabel(e);

    // If eventLabel inlined the rule, it would check e.magnitude_is_standalone_quotable
    // and print "1.4". But since it calls the mocked function, it must not.
    expect(label).not.toContain('1.4');
    expect(label).not.toContain('m/s');
    expect(label).toContain('over_slowing');  // event type is still present
  });

  it('prints event type even when no magnitude is allowed', () => {
    const label = eventLabel(ev());
    expect(label).toMatch(/C\d+ L\d+ · over_slowing$/);
  });
});
