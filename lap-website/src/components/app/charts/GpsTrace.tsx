/**
 * GpsTrace.tsx — React wrapper for the Old Tool's gps_trace.js.
 *
 * This module renders a Leaflet GPS map with speed-colored polylines,
 * corner markers, reference line and best lap overlays, and hover sync.
 *
 * The vanilla JS expects:
 *  - Leaflet (L) global loaded via CDN
 *  - #gps-map element
 *  - window.TELEMETRY
 *  - window.FetchHelper
 *
 * Hover events are bridged to the Zustand chart-hover-store:
 *  - Map hover → setHover (distance)
 *  - External hover → updateMarkerByDistance
 */
'use client';

import { useEffect, useRef, useMemo } from 'react';
import { useVanillaChart } from './useVanillaChart';
import { useChartHoverStore } from '@/lib/chart-hover-store';

interface GpsTraceProps {
  sessionId: string;
  apiBase?: string;
  className?: string;
  gpsLaps?: number[];
  bestLap?: number | null;
}

/** Load Leaflet CSS + JS from CDN (only once). */
let leafletLoaded = false;
let leafletPromise: Promise<void> | null = null;

function ensureLeaflet(): Promise<void> {
  if (leafletLoaded) return Promise.resolve();
  if (leafletPromise) return leafletPromise;

  leafletPromise = new Promise<void>((resolve, reject) => {
    // CSS
    if (!document.querySelector('link[href*="leaflet"]')) {
      const link = document.createElement('link');
      link.rel = 'stylesheet';
      link.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
      link.crossOrigin = '';
      document.head.appendChild(link);
    }

    // JS
    if ('L' in window) {
      leafletLoaded = true;
      resolve();
      return;
    }

    const script = document.createElement('script');
    script.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
    script.crossOrigin = '';
    script.onload = () => {
      leafletLoaded = true;
      resolve();
    };
    script.onerror = () => reject(new Error('Failed to load Leaflet'));
    document.head.appendChild(script);
  });

  return leafletPromise;
}

export function GpsTrace({
  sessionId,
  apiBase,
  className = '',
  gpsLaps = [],
  bestLap = null,
}: GpsTraceProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const leafletReadyRef = useRef(false);
  const cleanedUpRef = useRef(false);

  const scripts = useMemo(() => ['/js/gps_trace.js'], []);

  const { ready, error } = useVanillaChart({
    sessionId,
    apiBase,
    scripts,
    gpsLaps,
    bestLap,
  });

  // Load Leaflet and initialize the map module
  useEffect(() => {
    if (!ready || !containerRef.current) return;
    cleanedUpRef.current = false;
    const container = containerRef.current;

    let cancelled = false;

    (async () => {
      try {
        await ensureLeaflet();
        if (cancelled) return;
        leafletReadyRef.current = true;

        // The gps_trace.js auto-inits on DOMContentLoaded, which has
        // already fired. We need to manually trigger its load path.
        // It creates a Leaflet map on #gps-map and loads the default lap.
        if (window.GpsTrace) {
          const loadLap = (window.GpsTrace as Record<string, unknown>).loadLap as
            | ((lapNum: number) => void)
            | undefined;
          if (loadLap) {
            const defaultLap = bestLap || (gpsLaps.length > 0 ? gpsLaps[0] : null);
            if (defaultLap) loadLap(defaultLap);
          }
        }
      } catch (err) {
        console.error('Failed to load Leaflet for GpsTrace:', err);
      }
    })();

    return () => {
      cancelled = true;
      if (cleanedUpRef.current) return;
      cleanedUpRef.current = true;

      // Clean container DOM (don't call deactivateAll — it destroys sibling charts)
      if (container) {
        while (container.firstChild) {
          container.removeChild(container.firstChild);
        }
      }
    };
  }, [ready, bestLap, gpsLaps]);

  // Bridge hover events: GpsTrace map hover → Zustand store
  useEffect(() => {
    if (!ready) return;

    const setHover = useChartHoverStore.getState().setHover;
    const clearHover = useChartHoverStore.getState().clearHover;

    // gps_trace.js has a callback setter: GpsTrace.onMapHover = fn
    if (window.GpsTrace) {
      Object.defineProperty(window.GpsTrace, 'onMapHover', {
        set(fn: ((distance: number, speed: number, idx: number) => void) | null) {
          // Store the original callback
          (window.GpsTrace as Record<string, unknown>)._originalOnMapHover = fn;
        },
        get() {
          return (window.GpsTrace as Record<string, unknown>)._originalOnMapHover || null;
        },
        configurable: true,
      });

      // Set our bridge callback
      (window.GpsTrace as Record<string, unknown>)._originalOnMapHover = (
        distance: number,
      ) => {
        if (distance != null && isFinite(distance)) {
          setHover(distance, 'gps-trace');
        }
      };
    }

    // Subscribe to external hover (from other charts) → update map marker
    const unsubscribe = useChartHoverStore.subscribe((state) => {
      if (state.hoverSource === 'gps-trace') return; // ignore own events
      if (state.hoverDistance !== null && window.GpsTrace) {
        const updateMarker = (window.GpsTrace as Record<string, unknown>)
          .updateMarkerByDistance as ((d: number) => void) | undefined;
        if (updateMarker) updateMarker(state.hoverDistance);
      }
    });

    // Listen for mouseleave on the map container
    const mapEl = document.getElementById('gps-map');
    const handleLeave = () => clearHover();
    if (mapEl) {
      mapEl.addEventListener('mouseleave', handleLeave);
    }

    return () => {
      unsubscribe();
      if (mapEl) {
        mapEl.removeEventListener('mouseleave', handleLeave);
      }
    };
  }, [ready]);

  if (error) {
    return (
      <div className={`text-red-400 p-4 ${className}`}>
        Failed to load GPS trace: {error}
      </div>
    );
  }

  return (
    <div ref={containerRef} className={className}>
      {/* Map container — used by gps_trace.js */}
      <div
        id="gps-map"
        style={{ width: '100%', height: '400px', position: 'relative' }}
      />

      {/* Controls */}
      <div className="flex items-center gap-3 mt-2 text-sm flex-wrap">
        <label className="text-gray-400">Lap:</label>
        <select
          id="lap-select"
          className="bg-gray-800 text-white text-sm rounded px-2 py-1 border border-gray-700"
        >
          {gpsLaps.map((lap) => (
            <option key={lap} value={lap}>
              Lap {lap}
              {lap === bestLap ? ' (Best)' : ''}
            </option>
          ))}
        </select>

        <label className="inline-flex items-center gap-1 text-gray-400 ml-3">
          <input type="checkbox" id="toggle-reference-line" className="accent-orange-500" />
          Reference
        </label>

        <label className="inline-flex items-center gap-1 text-gray-400">
          <input type="checkbox" id="toggle-best-lap" className="accent-orange-500" />
          Best Lap
        </label>

        <label className="inline-flex items-center gap-1 text-gray-400">
          <input type="checkbox" id="toggle-all-laps" className="accent-orange-500" />
          All Laps
        </label>
      </div>
    </div>
  );
}
