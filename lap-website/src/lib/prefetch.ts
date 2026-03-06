/**
 * Route + data prefetching with bandwidth guardrails.
 *
 * Guards:
 *  - Save-Data header (user opted into lite mode)
 *  - Slow connection (2g / slow-2g via Network Information API)
 *  - TTL dedup (same URL won't re-prefetch within 30s)
 *  - Max concurrent prefetches (2)
 */

// ── Network Information API types ─────────────────────────────────

interface NetworkInformation {
  saveData: boolean;
  effectiveType: string;
}

declare global {
  interface Navigator {
    connection?: NetworkInformation;
  }
}

// ── Config ─────────────────────────────────────────────────────────

/** Routes eligible for Next.js route-chunk prefetch on hover. */
export const PREFETCH_ALLOWLIST: readonly string[] = [
  '/app/dashboard',
  '/app/sessions',
  '/app/compare',
  '/app/compare/sessions',
  '/app/analyze',
  '/app/tracks',
  '/app/account',
  '/app/analytics',
] as const;

const DEDUP_TTL_MS = 30_000;
const MAX_CONCURRENT = 2;

// ── State ──────────────────────────────────────────────────────────

const _prefetched = new Map<string, number>();
let _inFlight = 0;

// ── Guards ─────────────────────────────────────────────────────────

export function shouldPrefetch(): boolean {
  if (typeof navigator === 'undefined') return false;

  const conn = navigator.connection;
  if (!conn) return true; // API not supported — allow

  if (conn.saveData) return false;

  const slow = conn.effectiveType === '2g' || conn.effectiveType === 'slow-2g';
  if (slow) return false;

  return true;
}

/** Check dedup + concurrency for a specific key. */
export function canPrefetch(key: string): boolean {
  if (!shouldPrefetch()) return false;
  if (_inFlight >= MAX_CONCURRENT) return false;

  const lastPrefetch = _prefetched.get(key);
  if (lastPrefetch && Date.now() - lastPrefetch < DEDUP_TTL_MS) return false;

  return true;
}

/** Mark a key as prefetched and track concurrency. */
export function markPrefetched(key: string): void {
  _prefetched.set(key, Date.now());
}

export function incrementInFlight(): void {
  _inFlight++;
}

export function decrementInFlight(): void {
  _inFlight = Math.max(0, _inFlight - 1);
}

/** Check if a path matches the route allowlist (exact or dynamic segment parent). */
export function isAllowedRoute(path: string): boolean {
  // Exact match
  if ((PREFETCH_ALLOWLIST as readonly string[]).includes(path)) return true;

  // Dynamic segment: /app/sessions/[id] is allowed if parent /app/sessions is in list
  for (const allowed of PREFETCH_ALLOWLIST) {
    if (path.startsWith(allowed + '/')) return true;
  }

  return false;
}

/** Reset internal state (for tests). */
export function _resetPrefetchState(): void {
  _prefetched.clear();
  _inFlight = 0;
}
