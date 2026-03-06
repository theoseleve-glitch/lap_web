/**
 * Feature flag system.
 *
 * Flags are loaded from a static JSON endpoint (or baked at build time).
 * The client caches them in memory with a TTL. Each flag check is logged
 * with the build version so analytics can correlate flag state with releases.
 *
 * Kill-switch: any flag can be force-disabled by setting
 *   `NEXT_PUBLIC_FF_KILL_<FLAG_NAME>=1` at build time.
 */

/* ── Legacy flag (keep for experience layer) ───────────────────── */
export const EXPERIENCE_V2 =
  typeof process !== 'undefined'
    ? process.env.NEXT_PUBLIC_EXPERIENCE_V2 === '1'
    : false;

/* ── New flag system ───────────────────────────────────────────── */

export interface FeatureFlags {
  /** Enable offline session cache (IndexedDB). */
  offline_cache: boolean;
  /** Enable Web Vitals collection. */
  web_vitals: boolean;
  /** Enable chart CLS placeholders. */
  chart_placeholders: boolean;
  /** Enable driving analyzer on session page. */
  driving_analyzer: boolean;
  /** Enable new session expired modal (vs hard redirect). */
  session_expired_modal: boolean;
}

const DEFAULTS: FeatureFlags = {
  offline_cache: true,
  web_vitals: true,
  chart_placeholders: true,
  driving_analyzer: true,
  session_expired_modal: true,
};

let _flags: FeatureFlags = { ...DEFAULTS };
let _loadedAt = 0;
const CACHE_TTL_MS = 5 * 60 * 1000; // 5 minutes

const BUILD_VERSION = process.env.NEXT_PUBLIC_BUILD_VERSION ?? 'dev';

/**
 * Check if a flag is force-killed via env var.
 * NEXT_PUBLIC_FF_KILL_OFFLINE_CACHE=1 → offline_cache disabled.
 */
function isKilled(flag: keyof FeatureFlags): boolean {
  const envKey = `NEXT_PUBLIC_FF_KILL_${flag.toUpperCase()}`;
  return (process.env as Record<string, string | undefined>)[envKey] === '1';
}

/**
 * Load flags from remote config or return cached.
 * Falls back to defaults on any error.
 */
export async function loadFlags(): Promise<FeatureFlags> {
  if (typeof window === 'undefined') return _flags;
  if (Date.now() - _loadedAt < CACHE_TTL_MS) return _flags;

  try {
    const res = await fetch('/api/feature-flags', { cache: 'no-store' });
    if (res.ok) {
      const remote = await res.json();
      _flags = { ...DEFAULTS, ...remote };
    }
  } catch {
    // Use defaults — non-fatal
  }

  _loadedAt = Date.now();
  return _flags;
}

/**
 * Synchronous flag check — uses last cached value.
 * Returns false if the flag is kill-switched.
 */
export function getFlag(flag: keyof FeatureFlags): boolean {
  if (isKilled(flag)) return false;
  return _flags[flag] ?? DEFAULTS[flag] ?? false;
}

/**
 * Override a flag at runtime (useful for dev tools / diagnostics).
 */
export function setFlag(flag: keyof FeatureFlags, value: boolean): void {
  _flags[flag] = value;
}

/**
 * Get all current flag values (for diagnostics).
 */
export function getAllFlags(): FeatureFlags & { _version: string; _loadedAt: number } {
  return { ..._flags, _version: BUILD_VERSION, _loadedAt };
}

/**
 * Reset flags to defaults (for tests).
 */
export function resetFlags(): void {
  _flags = { ...DEFAULTS };
  _loadedAt = 0;
}
