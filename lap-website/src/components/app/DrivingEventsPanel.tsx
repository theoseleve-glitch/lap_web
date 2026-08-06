'use client';

/**
 * "What should I fix next" — the ranked driving-event list.
 *
 * Two things here are load-bearing, not styling:
 *
 * 1. FOUR empty states, not one. `events: []` is returned both by a clean
 *    session with nothing to fix and by a session whose grip anchor failed
 *    and left three of four detectors unable to look at anything. Rendering
 *    those identically tells the driver "you were perfect" when the truth is
 *    "we could not measure you".
 * 2. The cost is only ever presented as CAUSED by an event when the payload
 *    says it may be. `late_throttle` reports the identical corner-time gap
 *    `over_slowing` reports for the same corner-lap, and its added
 *    information beyond apex speed is not distinguishable from zero — so
 *    attributing that cost to its metres would count one measurement twice.
 */
import { useEffect, useState } from 'react';
import {
  fetchDrivingEvents, describeCapability, canAttributeCost,
  type DrivingEventsResponse,
} from '@/lib/driving-events';
import { eventLabel, eventColor } from '@/lib/driving-events-draw';

export default function DrivingEventsPanel({ sessionId }: { sessionId: string }) {
  const [res, setRes] = useState<DrivingEventsResponse | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoaded(false);
    (async () => {
      const r = await fetchDrivingEvents(sessionId);
      if (cancelled) return;
      setRes(r);
      setLoaded(true);
    })();
    return () => { cancelled = true; };
  }, [sessionId]);

  if (!loaded) return <div data-testid="events-loading">Loading…</div>;

  const state = describeCapability(res);

  if (state === 'clean') {
    return (
      <div data-testid="events-empty-clean">
        Every detector ran and found nothing to flag on this session.
      </div>
    );
  }

  if (state === 'degraded') {
    const blind = Object.entries(res!.capability)
      .filter(([, v]) => v === 'insufficient')
      .map(([name]) => name);
    return (
      <div data-testid="events-empty-degraded">
        No events — but this is not a clean session. These detectors could not
        measure anything here: {blind.join(', ')}.
      </div>
    );
  }

  if (state === 'unavailable') {
    return (
      <div data-testid="events-empty-unavailable">
        Driving events were not computed for this session.
      </div>
    );
  }

  return (
    <ol data-testid="events-list">
      {res!.events.map((e, i) => (
        <li key={`${e.lap_number}-${e.corner_id}-${e.event_type}`}
            data-testid={`event-row-${i}`}>
          <span style={{ background: eventColor(e) }} aria-hidden />
          <span>{eventLabel(e)}</span>
          {canAttributeCost(e) ? (
            <span data-testid={`event-cost-${i}`}>
              costs {e.time_cost_s!.toFixed(2)}s
            </span>
          ) : typeof e.time_cost_s === 'number' && Number.isFinite(e.time_cost_s) ? (
            // Deliberately non-causal wording: the corner costs this much,
            // and this event happened in it. It did not necessarily cause it.
            <span data-testid={`event-cost-context-${i}`}>
              in a corner losing {e.time_cost_s.toFixed(2)}s
            </span>
          ) : null}
        </li>
      ))}
    </ol>
  );
}
