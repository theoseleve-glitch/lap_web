'use client';

import { useCallback } from 'react';
import { api } from '@/lib/api-client';
import { hasAnalyticsConsent } from '@/lib/consent';

export const FLUSH_INTERVAL_MS = 5_000;
export const FLUSH_BATCH_SIZE = 10;
export const DEDUP_WINDOW_MS = 2_000;

export interface QueuedEvent {
  event: string;
  properties: Record<string, string | number | boolean>;
  path: string;
  ts: number;
}

// Module-level state — shared across all hook instances
const _queue: QueuedEvent[] = [];
const _dedup: Map<string, number> = new Map();
let _timer: ReturnType<typeof setTimeout> | null = null;

async function _flush(): Promise<void> {
  if (!hasAnalyticsConsent()) {
    _queue.length = 0;
    return;
  }
  if (_queue.length === 0) return;

  const batch = _queue.splice(0, _queue.length);
  try {
    await api.post('/events', { events: batch });
  } catch {
    // fire-and-forget — swallow errors silently
  }
}

function _scheduleFlush(): void {
  if (_timer !== null) return;
  _timer = setTimeout(() => {
    _timer = null;
    _flush();
  }, FLUSH_INTERVAL_MS);
}

/** Exported for tests: cancels any pending timer and flushes immediately. */
export async function _flushNow(): Promise<void> {
  if (_timer !== null) {
    clearTimeout(_timer);
    _timer = null;
  }
  await _flush();
}

/** Register visibilitychange listener once (module-level). */
if (typeof window !== 'undefined') {
  window.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden' && _queue.length > 0) {
      const beaconUrl = `${process.env.NEXT_PUBLIC_API_URL ?? ''}/api/v1/events`;
      const payload = JSON.stringify({ events: _queue.splice(0, _queue.length) });
      navigator.sendBeacon(beaconUrl, new Blob([payload], { type: 'application/json' }));
    }
  });
}

/** Track an event. Safe to call from anywhere (no-ops during SSR). */
export function trackEvent(
  event: string,
  properties?: Record<string, string | number | boolean>,
  path?: string,
): void {
  if (typeof window === 'undefined') return;

  const resolvedPath = path ?? (typeof window !== 'undefined' ? window.location.pathname : '');
  const dedupKey = `${event}:${resolvedPath}`;
  const now = Date.now();
  const lastSeen = _dedup.get(dedupKey);
  if (lastSeen !== undefined && now - lastSeen < DEDUP_WINDOW_MS) return;

  _dedup.set(dedupKey, now);
  _queue.push({ event, properties: properties ?? {}, path: resolvedPath, ts: now });

  if (_queue.length >= FLUSH_BATCH_SIZE) {
    // Flush immediately — cancel any pending scheduled flush first
    if (_timer !== null) {
      clearTimeout(_timer);
      _timer = null;
    }
    _flush();
  } else {
    _scheduleFlush();
  }
}

/** React hook that returns a stable reference to trackEvent. */
export function useTrackEvent(): typeof trackEvent {
  return useCallback(trackEvent, []);
}
