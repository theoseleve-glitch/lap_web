/**
 * useVanillaChart.ts — Shared hook for loading Old Tool vanilla JS chart modules.
 *
 * Handles:
 *  - Loading infrastructure scripts (module_manager, lifecycle_helpers, theme, fetch_helper)
 *  - Patching FetchHelper to prepend the API base URL
 *  - Setting up window.TELEMETRY globals
 *  - Loading a chart module script and returning ready state
 *  - Cleanup on unmount (script removal, ModuleManager.deactivateAll)
 */
'use client';

import { useEffect, useRef, useState, useCallback } from 'react';

/* ── Global type augmentation for the Old Tool's window globals ── */
declare global {
  interface Window {
    ModuleManager?: {
      register: (name: string, mod: { init: () => void; destroy: () => void }) => void;
      activate: (names: string[]) => void;
      deactivateAll: () => void;
      isActive: (name: string) => boolean;
      getActive: () => string[];
      getRegistered: () => string[];
    };
    LifecycleHelpers?: {
      create: () => {
        addListener: (el: EventTarget, evt: string, fn: EventListener, opts?: AddEventListenerOptions) => void;
        removeListener: (el: EventTarget, evt: string, fn: EventListener, opts?: EventListenerOptions) => void;
        addTimer: (fn: () => void, ms: number) => number;
        clearTimer: (id: number) => void;
        addInterval: (fn: () => void, ms: number) => number;
        clearInterval: (id: number) => void;
        addRaf: (fn: FrameRequestCallback) => number;
        cancelRaf: (id: number) => void;
        destroyAll: () => void;
      };
    };
    Theme?: {
      colors: Record<string, string>;
      lapColor: (index: number) => string;
      heatColor: (t: number) => string;
      speedColor: (t: number) => string;
      hydrate: () => void;
    };
    FetchHelper?: {
      load: (container: HTMLElement, url: string, onSuccess: (data: unknown) => void, opts?: Record<string, unknown>) => void;
      fetch: (url: string, opts?: RequestInit & { timeout?: number }) => Promise<unknown>;
      lazyInit: (containerId: string, initFn: () => void) => void;
    };
    TELEMETRY?: {
      sessionId: string;
      gpsLaps: number[];
      bestLap: number | null;
    };
    sizeCanvas?: (canvas: HTMLCanvasElement, w: number, h: number) => CanvasRenderingContext2D;
    ChartSync?: Record<string, unknown>;
    GpsTrace?: Record<string, unknown>;
    TrackMap?: Record<string, unknown>;
    SpeedTraceZoom?: Record<string, unknown>;
    GGExplorer?: Record<string, unknown>;
    Toast?: { error: (title: string, msg: string) => void };
  }
}

/** Infrastructure scripts that must be loaded before any chart module. */
const INFRA_SCRIPTS = [
  '/js/module_manager.js',
  '/js/lifecycle_helpers.js',
  '/js/theme.js',
  '/js/fetch_helper.js',
];

/** Track which scripts have been loaded globally (across all instances). */
const loadedScripts = new Set<string>();
let infraReady = false;
let infraPromise: Promise<void> | null = null;

/**
 * Load a single script by appending a <script> tag.
 * Returns a promise that resolves when the script has loaded.
 */
function loadScript(src: string): Promise<void> {
  if (loadedScripts.has(src)) return Promise.resolve();

  return new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[src="${src}"]`);
    if (existing) {
      loadedScripts.add(src);
      resolve();
      return;
    }

    const script = document.createElement('script');
    script.src = src;
    script.async = false; // preserve ordering
    script.onload = () => {
      loadedScripts.add(src);
      resolve();
    };
    script.onerror = () => reject(new Error(`Failed to load script: ${src}`));
    document.head.appendChild(script);
  });
}

/**
 * Load infrastructure scripts in order (only once globally).
 */
function ensureInfrastructure(): Promise<void> {
  if (infraReady) return Promise.resolve();
  if (infraPromise) return infraPromise;

  infraPromise = (async () => {
    for (const src of INFRA_SCRIPTS) {
      await loadScript(src);
    }
    infraReady = true;
  })();

  return infraPromise;
}

/**
 * Patch FetchHelper.fetch to prepend API base URL for relative paths.
 * This is needed because the Old Tool modules use relative URLs like
 * '/api/session/...' but in the Next.js app, the API is on a different domain.
 */
function patchFetchHelper(apiBase: string): void {
  if (!window.FetchHelper) return;

  const originalFetch = window.FetchHelper.fetch;
  // Only patch once
  if ((originalFetch as { _patched?: boolean })._patched) return;

  const patchedFetch = function (url: string, opts?: RequestInit & { timeout?: number }) {
    // Prepend base URL for relative paths
    if (url.startsWith('/api/')) {
      url = apiBase + url;
    }
    return originalFetch.call(window.FetchHelper, url, opts);
  } as typeof originalFetch & { _patched: boolean };
  patchedFetch._patched = true;

  window.FetchHelper.fetch = patchedFetch;

  // Also patch FetchHelper.load
  const originalLoad = window.FetchHelper.load;
  if (!(originalLoad as { _patched?: boolean })._patched) {
    const patchedLoad = function (
      container: HTMLElement,
      url: string,
      onSuccess: (data: unknown) => void,
      loadOpts?: Record<string, unknown>,
    ) {
      if (url.startsWith('/api/')) {
        url = apiBase + url;
      }
      return originalLoad.call(window.FetchHelper, container, url, onSuccess, loadOpts);
    } as typeof originalLoad & { _patched: boolean };
    patchedLoad._patched = true;
    window.FetchHelper.load = patchedLoad;
  }
}

interface UseVanillaChartOptions {
  /** Session ID to set on window.TELEMETRY */
  sessionId: string;
  /** API base URL (defaults to NEXT_PUBLIC_API_URL) */
  apiBase?: string;
  /** Additional script(s) to load after infrastructure */
  scripts: string[];
  /** GPS lap numbers for window.TELEMETRY */
  gpsLaps?: number[];
  /** Best lap number for window.TELEMETRY */
  bestLap?: number | null;
}

interface UseVanillaChartResult {
  /** Whether all scripts (infra + chart) are loaded and ready */
  ready: boolean;
  /** Any error that occurred during loading */
  error: string | null;
}

/**
 * Hook that loads infrastructure + chart module scripts, patches globals,
 * and sets up window.TELEMETRY. Returns { ready, error }.
 */
export function useVanillaChart(options: UseVanillaChartOptions): UseVanillaChartResult {
  const {
    sessionId,
    apiBase = process.env.NEXT_PUBLIC_API_URL || '',
    scripts,
    gpsLaps = [],
    bestLap = null,
  } = options;

  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mountedRef = useRef(true);

  // Stable reference for scripts array
  const scriptsKey = scripts.join(',');

  const loadAll = useCallback(async () => {
    try {
      // 1. Load infrastructure
      await ensureInfrastructure();

      // 2. Patch FetchHelper with API base URL
      patchFetchHelper(apiBase);

      // 3. Set up TELEMETRY globals
      window.TELEMETRY = {
        sessionId,
        gpsLaps,
        bestLap,
      };

      // 4. Load chart-specific scripts
      for (const src of scripts) {
        await loadScript(src);
      }

      if (mountedRef.current) {
        setReady(true);
      }
    } catch (err) {
      if (mountedRef.current) {
        setError(err instanceof Error ? err.message : 'Failed to load chart scripts');
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, apiBase, scriptsKey, gpsLaps.join(','), bestLap]);

  useEffect(() => {
    mountedRef.current = true;
    setReady(false);
    setError(null);
    loadAll();

    return () => {
      mountedRef.current = false;
    };
  }, [loadAll]);

  return { ready, error };
}
