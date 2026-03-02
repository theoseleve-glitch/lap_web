/**
 * TrackMap.tsx — Shared Leaflet track map component.
 *
 * Dual-mode:
 *   - `sessionId` → delegates to vanilla JS gps_trace.js (full feature set)
 *   - `data` → renders Leaflet polyline directly (for Compare/Analytics pages)
 */
'use client';

import { useEffect, useRef, useMemo } from 'react';
import 'leaflet/dist/leaflet.css';
import { useVanillaChart } from './useVanillaChart';
import { useChartHoverStore } from '@/lib/chart-hover-store';

interface TrackMapData {
  latitudes: number[];
  longitudes: number[];
  distances: number[];
  speeds?: number[];
}

interface Corner {
  corner_id: number;
  lat: number;
  lon: number;
  label?: string;
}

interface TrackMapProps {
  /** Session ID — enables vanilla JS mode with full feature set */
  sessionId?: string;
  /** Lap number to display (vanilla mode) */
  lap?: number;
  /** Pre-fetched data — enables direct Leaflet mode */
  data?: TrackMapData;
  /** Corner markers to overlay */
  corners?: Corner[];
  /** External hover control: distance in meters */
  markerDistance?: number;
  /** Emit distance on polyline hover */
  onHoverDistance?: (d: number) => void;
  className?: string;
  /** Available lap numbers (vanilla mode) */
  gpsLaps?: number[];
  /** Best lap number (vanilla mode) */
  bestLap?: number | null;
  /** API base URL override */
  apiBase?: string;
}

/** Load Leaflet via npm dynamic import (only once). */
let leafletLoaded = false;
let leafletPromise: Promise<void> | null = null;

function ensureLeaflet(): Promise<void> {
  if (leafletLoaded) return Promise.resolve();
  if (leafletPromise) return leafletPromise;

  leafletPromise = (async () => {
    const L = (await import('leaflet')).default;
    L.Icon.Default.imagePath = '/images/leaflet/';
    (window as unknown as Record<string, unknown>).L = L;
    leafletLoaded = true;
  })();

  return leafletPromise;
}

export function TrackMap(props: TrackMapProps) {
  const {
    sessionId,
    lap,
    data,
    corners,
    onHoverDistance,
    className = '',
    gpsLaps = [],
    bestLap = null,
    apiBase,
  } = props;
  const containerRef = useRef<HTMLDivElement>(null);
  const cleanedUpRef = useRef(false);

  const scripts = useMemo(() => ['/js/gps_trace.js'], []);

  // Only use vanilla chart hook in sessionId mode (no data prop)
  const shouldUseVanilla = !!sessionId && !data;

  const { ready, error } = useVanillaChart({
    sessionId: sessionId || '__skip__',
    apiBase,
    scripts: shouldUseVanilla ? scripts : [],
    gpsLaps,
    bestLap,
  });

  // ── Vanilla JS mode ──────────────────────────────────────────
  useEffect(() => {
    if (!shouldUseVanilla || !ready || !containerRef.current) return;
    cleanedUpRef.current = false;
    const container = containerRef.current;
    let cancelled = false;

    (async () => {
      try {
        await ensureLeaflet();
        if (cancelled) return;

        // Re-fire DOMContentLoaded so the vanilla JS modules' init handlers
        // execute now that Leaflet is available and DOM elements are rendered.
        if (window.ModuleShim) {
          window.ModuleShim.fireDOMContentLoaded();
        }
      } catch (err) {
        console.error('Failed to load Leaflet for TrackMap:', err);
      }
    })();

    return () => {
      cancelled = true;
      if (cleanedUpRef.current) return;
      cleanedUpRef.current = true;
      if (container) {
        while (container.firstChild) {
          container.removeChild(container.firstChild);
        }
      }
    };
  }, [shouldUseVanilla, ready, bestLap, gpsLaps, lap]);

  // ── Hover bridge (vanilla mode) ──────────────────────────────
  useEffect(() => {
    if (!shouldUseVanilla || !ready) return;

    const setHover = useChartHoverStore.getState().setHover;
    const clearHover = useChartHoverStore.getState().clearHover;

    if (window.GpsTrace) {
      (window.GpsTrace as Record<string, unknown>)._originalOnMapHover = (
        distance: number,
      ) => {
        if (distance != null && isFinite(distance)) {
          setHover(distance, 'track-map');
          onHoverDistance?.(distance);
        }
      };
    }

    const unsubscribe = useChartHoverStore.subscribe((state) => {
      if (state.hoverSource === 'track-map') return;
      if (state.hoverDistance !== null && window.GpsTrace) {
        const updateMarker = (window.GpsTrace as Record<string, unknown>)
          .updateMarkerByDistance as ((d: number) => void) | undefined;
        if (updateMarker) updateMarker(state.hoverDistance);
      }
    });

    const mapEl = document.getElementById('gps-map');
    const handleLeave = () => clearHover();
    if (mapEl) mapEl.addEventListener('mouseleave', handleLeave);

    return () => {
      unsubscribe();
      if (mapEl) mapEl.removeEventListener('mouseleave', handleLeave);
    };
  }, [shouldUseVanilla, ready, onHoverDistance]);

  // ── Error state ──────────────────────────────────────────────
  if (error && shouldUseVanilla) {
    return (
      <div className={`text-red-400 p-4 ${className}`}>
        Failed to load track map: {error}
      </div>
    );
  }

  // ── Vanilla JS render ────────────────────────────────────────
  if (shouldUseVanilla) {
    return (
      <div ref={containerRef} className={className}>
        <div
          id="gps-map"
          style={{ width: '100%', height: '400px', position: 'relative' }}
        />
        <div className="flex items-center gap-3 mt-2 text-sm flex-wrap">
          <label className="text-gray-400">Lap:</label>
          <select
            id="lap-select"
            className="bg-gray-800 text-white text-sm rounded px-2 py-1 border border-gray-700"
          >
            {gpsLaps.map((l) => (
              <option key={l} value={l}>
                Lap {l}{l === bestLap ? ' (Best)' : ''}
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

  // ── Data mode (pre-fetched) ──────────────────────────────────
  return (
    <div ref={containerRef} className={className}>
      <div
        className="flex items-center justify-center rounded-lg border border-steel/10"
        style={{ width: '100%', height: '400px', position: 'relative', background: '#1a1a2e' }}
      >
        {data && data.latitudes.length > 0 ? (
          <div className="text-steel p-4 text-sm text-center">
            <p className="font-telemetry text-chalk mb-1">Track Map</p>
            <p>{data.latitudes.length} GPS points
              {corners ? `, ${corners.length} corners` : ''}
            </p>
          </div>
        ) : (
          <div className="text-steel p-4 text-sm text-center">
            <p className="font-telemetry text-chalk mb-1">No GPS Data</p>
            <p className="text-steel/60 text-xs max-w-[280px]">
              No GPS trace data available for this lap. Ensure your CSV contains
              latitude and longitude columns.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
