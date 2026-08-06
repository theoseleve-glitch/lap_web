/**
 * Phase 3 client for the driving-events API (Phase 2, Task 10).
 *
 * Two of these exports exist to enforce constraints the BACKEND states
 * per-row precisely so a renderer never has to infer them. Do not replace
 * them with a hardcoded list of event types: a fifth detector must inherit
 * the constraint automatically, and getting this wrong renders a number the
 * measurement does not support.
 */
import { api } from '@/lib/api-client';

export type CapabilityValue = 'detected' | 'not_triggered' | 'insufficient';

/**
 * The closed unit vocabulary, verbatim from `driving_events.MAGNITUDE_UNITS`.
 *
 * A runtime array first, with the type derived from it, so
 * `backend-vocabulary-contract.test.ts` can diff it against the Python that
 * produces it. A type alone is erased at runtime and could not be checked --
 * and an unchecked hand-copied vocabulary is precisely how TIER_LABEL shipped
 * a tier the backend never emits.
 *
 * `m/s2`, NOT `m/s²`: the superscript spelling is what a human writes and is
 * not a value the producer can emit (`driving_events.py:211-221`).
 */
export const MAGNITUDE_UNITS = ['m', 'm/s', 'm/s2', 'pct'] as const;
export type MagnitudeUnit = (typeof MAGNITUDE_UNITS)[number];

export interface AlsoFired {
  event_type: string;
  magnitude: number | null;
  magnitude_unit: MagnitudeUnit | null;
  validity: string | null;
  magnitude_is_standalone_quotable: boolean;
}

export interface DrivingEvent {
  lap_number: number;
  corner_id: number;
  event_type: string;
  s_norm_start: number | null;
  s_norm_end: number | null;
  magnitude: number | null;
  magnitude_unit: MagnitudeUnit | null;
  time_cost_s: number | null;
  validity: string | null;
  reason: string | null;
  n_samples_in_window: number | null;
  anchor_tier: string | null;
  anchor_reason: string | null;
  evidence: Record<string, unknown>;
  /** "caused" | "context" | "no_cost" — see driving_events.TIME_COST_ATTRIBUTION */
  time_cost_attribution: string;
  magnitude_is_standalone_quotable: boolean;
}

export interface DrivingEventsResponse {
  events: DrivingEvent[];
  available: boolean;
  capability: Record<string, CapabilityValue>;
  capability_available: boolean;
}

/** May this event's magnitude be shown on its own? */
export function canQuoteMagnitude(e: DrivingEvent): boolean {
  if (!e.magnitude_is_standalone_quotable) return false;
  return typeof e.magnitude === 'number' && Number.isFinite(e.magnitude);
}

/** May `time_cost_s` be presented as CAUSED by this event's own magnitude? */
export function canAttributeCost(e: DrivingEvent): boolean {
  // Allow-list, not deny-list: an attribution value this build does not know
  // must read as "not attributable", never as permissive.
  if (e.time_cost_attribution !== 'caused') return false;
  return typeof e.time_cost_s === 'number' && Number.isFinite(e.time_cost_s);
}

/**
 * Co-firing events attached to this one, e.g. the `late_throttle` that rode
 * along with an `over_slowing` detection. The backend (`events_repo.py`'s
 * `_dedupe_by_lap_corner`) writes this ONLY as `evidence.also_fired` -- never
 * as a top-level field on the event -- and every Python consumer reads it
 * the same nested way. `evidence` is `Record<string, unknown>`, so read it
 * through this accessor rather than hand-indexing at each call site: that
 * keeps the one place that knows where this lives from drifting out of sync
 * with the producer again.
 */
export function alsoFired(e: DrivingEvent): AlsoFired[] {
  const v = e.evidence?.also_fired;
  return Array.isArray(v) ? (v as AlsoFired[]) : [];
}

// Allow-list: only these values indicate a healthy measurement. Anything
// else -- an unrecognised status from a future backend build, a typo, a new
// 'timed_out' state nobody has named to this build yet -- must read as
// "could not measure", never as clean.
//
// Exported (not inlined into describeCapability) so any caller that needs to
// name WHICH detectors are unhealthy -- e.g. a UI listing them by name --
// reads the same set describeCapability used to decide the session is
// degraded in the first place. A second, hand-copied list in a second file
// is exactly the kind of thing that drifts: this module has already had
// that defect once (`'insufficient'` copied as the sole "bad" value instead
// of reusing the allow-list), so there is now only one place this rule
// lives.
const HEALTHY_CAPABILITY_VALUES = new Set<string>(['detected', 'not_triggered']);

export function isHealthyCapabilityValue(v: string): boolean {
  return HEALTHY_CAPABILITY_VALUES.has(v);
}

/**
 * Collapse the response into the four states a UI must tell apart.
 * `events: []` alone is ambiguous — it is both "nothing to fix" and
 * "three of four detectors could not look at anything".
 */
export function describeCapability(
  r: DrivingEventsResponse | null,
): 'clean' | 'degraded' | 'unavailable' | 'has-events' {
  if (!r) return 'unavailable';
  if (r.events.length > 0) return 'has-events';
  if (!r.capability_available || Object.keys(r.capability).length === 0) {
    return 'unavailable';
  }
  const values = Object.values(r.capability);
  // If ANY value is not recognised, treat it as degraded (the honest claim is
  // "something here we cannot interpret"), not clean. This prevents new backend
  // status values (e.g. 'timed_out') from falsely reassuring the driver that
  // all detectors ran and found nothing.
  if (values.some((v) => !isHealthyCapabilityValue(v))) return 'degraded';
  return 'clean';
}

export async function fetchDrivingEvents(
  sessionId: string,
  limit = 10,
): Promise<DrivingEventsResponse | null> {
  try {
    return await api.get<DrivingEventsResponse>(
      `/sessions/${encodeURIComponent(sessionId)}/driving-events?limit=${limit}`,
    );
  } catch {
    // Optional overlay — a 404 or a pre-086 session must not break the chart.
    return null;
  }
}
