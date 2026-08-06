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

export interface AlsoFired {
  event_type: string;
  magnitude: number | null;
  magnitude_unit: string | null;
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
  magnitude_unit: string | null;
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
  also_fired?: AlsoFired[];
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
  // Allow-list: only these values indicate a healthy measurement.
  // If ANY value is not recognised, treat it as degraded (the honest claim is
  // "something here we cannot interpret"), not clean. This prevents new backend
  // status values (e.g. 'timed_out') from falsely reassuring the driver that
  // all detectors ran and found nothing.
  const goodValues = new Set<string>(['detected', 'not_triggered']);
  if (values.some((v) => !goodValues.has(v))) return 'degraded';
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
