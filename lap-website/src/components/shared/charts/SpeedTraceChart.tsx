/**
 * SpeedTraceChart.tsx — Shared speed-vs-distance chart component.
 *
 * Dual-mode:
 *   - `sessionId` → delegates to chart_sync.js + speed_trace_zoom.js
 *   - `data` → renders canvas chart directly (for Compare/Analytics pages)
 */
'use client';

import { useEffect, useRef, useMemo } from 'react';
import { useVanillaChart } from './useVanillaChart';
import { useChartHoverStore } from '@/lib/chart-hover-store';

interface SpeedTraceData {
  distances: number[];
  speeds: number[];
  ref_speeds?: number[];
}

interface SpeedTraceChartProps {
  /** Session ID — enables vanilla JS mode */
  sessionId?: string;
  /** Lap number to display */
  lap?: number;
  /** Pre-fetched data — enables direct canvas mode */
  data?: SpeedTraceData;
  /** Reference lap number (vanilla mode, triggers ?ref=N query) */
  refLap?: number;
  /** External hover control: distance in meters */
  markerDistance?: number;
  /** Emit distance on hover */
  onHoverDistance?: (d: number) => void;
  className?: string;
  /** Available lap numbers (vanilla mode) */
  gpsLaps?: number[];
  /** Best lap number (vanilla mode) */
  bestLap?: number | null;
  /** API base URL override */
  apiBase?: string;
}

export function SpeedTraceChart({
  sessionId,
  lap,
  data,
  refLap,
  markerDistance,
  onHoverDistance,
  className = '',
  gpsLaps = [],
  bestLap = null,
  apiBase,
}: SpeedTraceChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cleanedUpRef = useRef(false);

  const scripts = useMemo(
    () => ['/js/chart_sync.js', '/js/speed_trace_zoom.js'],
    [],
  );

  const shouldUseVanilla = !!sessionId && !data;

  const { ready, error } = useVanillaChart({
    sessionId: sessionId || '__skip__',
    apiBase,
    scripts: shouldUseVanilla ? scripts : [],
    gpsLaps,
    bestLap,
  });

  // ── Hover bridge (vanilla mode) ──────────────────────────────
  useEffect(() => {
    if (!shouldUseVanilla || !ready) return;

    const setHover = useChartHoverStore.getState().setHover;
    const clearHover = useChartHoverStore.getState().clearHover;

    // Intercept ChartSync crosshair updates to emit hover events
    const origTrackMapUpdate = window.TrackMap?.updateMarkerByDistance as
      | ((d: number) => void)
      | undefined;
    const origGpsTraceUpdate = window.GpsTrace?.updateMarkerByDistance as
      | ((d: number) => void)
      | undefined;

    if (window.TrackMap) {
      (window.TrackMap as Record<string, unknown>).updateMarkerByDistance = (distM: number) => {
        setHover(distM, 'speed-trace');
        onHoverDistance?.(distM);
        if (origTrackMapUpdate) origTrackMapUpdate(distM);
      };
    }
    if (window.GpsTrace) {
      (window.GpsTrace as Record<string, unknown>).updateMarkerByDistance = (distM: number) => {
        setHover(distM, 'speed-trace');
        onHoverDistance?.(distM);
        if (origGpsTraceUpdate) origGpsTraceUpdate(distM);
      };
    }

    // Subscribe to external hover → update crosshair
    const unsubscribe = useChartHoverStore.subscribe((state) => {
      if (state.hoverSource === 'speed-trace') return;
      if (state.hoverDistance !== null && window.ChartSync) {
        const updateCrosshair = (window.ChartSync as Record<string, unknown>)
          .updateCrosshair as ((d: number) => void) | undefined;
        if (updateCrosshair) updateCrosshair(state.hoverDistance);
      }
    });

    const speedCanvas = document.getElementById('speed-chart');
    const handleLeave = () => clearHover();
    if (speedCanvas) speedCanvas.addEventListener('mouseleave', handleLeave);

    return () => {
      unsubscribe();
      if (speedCanvas) speedCanvas.removeEventListener('mouseleave', handleLeave);
      if (window.TrackMap && origTrackMapUpdate) {
        (window.TrackMap as Record<string, unknown>).updateMarkerByDistance = origTrackMapUpdate;
      }
      if (window.GpsTrace && origGpsTraceUpdate) {
        (window.GpsTrace as Record<string, unknown>).updateMarkerByDistance = origGpsTraceUpdate;
      }
    };
  }, [shouldUseVanilla, ready, onHoverDistance]);

  // ── Initialize vanilla chart modules ─────────────────────────
  useEffect(() => {
    if (!shouldUseVanilla || !ready || !containerRef.current) return;
    cleanedUpRef.current = false;
    const container = containerRef.current;

    const speedCanvas = document.getElementById('speed-chart');
    if (speedCanvas && window.ChartSync) {
      const loadFn = (window.ChartSync as Record<string, unknown>)
        .loadSpeedData as ((lapNum: number) => void) | undefined;
      if (loadFn && bestLap) {
        loadFn(bestLap);
      } else if (loadFn && gpsLaps.length > 0) {
        loadFn(gpsLaps[0]);
      }
    }

    if (window.SpeedTraceZoom) {
      const initFn = (window.SpeedTraceZoom as Record<string, unknown>).init as
        | (() => void)
        | undefined;
      if (initFn) initFn();
    }

    return () => {
      if (cleanedUpRef.current) return;
      cleanedUpRef.current = true;
      if (container) {
        while (container.firstChild) {
          container.removeChild(container.firstChild);
        }
      }
    };
  }, [shouldUseVanilla, ready, bestLap, gpsLaps]);

  // ── Error state ──────────────────────────────────────────────
  if (error && shouldUseVanilla) {
    return (
      <div className={`text-red-400 p-4 ${className}`}>
        Failed to load speed trace: {error}
      </div>
    );
  }

  // ── Vanilla JS render ────────────────────────────────────────
  if (shouldUseVanilla) {
    return (
      <div ref={containerRef} className={className}>
        {/* Speed chart (overview) */}
        <div className="relative" style={{ width: '100%' }}>
          <canvas
            id="speed-chart"
            style={{ width: '100%', height: '250px', display: 'block' }}
          />
          <div id="chart-crosshair" className="chart-crosshair" />
          <div id="chart-tooltip" className="chart-tooltip" />
          <div
            id="speed-chart-selection-rect"
            className="speed-chart-selection-rect"
            style={{ display: 'none' }}
          />
          <div id="speed-chart-corner-markers" className="speed-chart-corner-markers" />
          <div
            id="speed-chart-drag-hint"
            className="speed-chart-drag-hint text-xs text-gray-500 text-center mt-1"
          >
            Drag to zoom into a section
          </div>
        </div>

        {/* Zoom panel */}
        <div id="speed-zoom-panel" style={{ display: 'none' }} className="mt-4">
          <div className="flex items-center gap-2 mb-2 flex-wrap">
            <label className="text-sm text-gray-400">Primary:</label>
            <select
              id="speed-zoom-primary"
              className="bg-gray-800 text-white text-sm rounded px-2 py-1 border border-gray-700"
            />
            <label className="text-sm text-gray-400 ml-2">Compare:</label>
            <select
              id="speed-zoom-compare"
              className="bg-gray-800 text-white text-sm rounded px-2 py-1 border border-gray-700"
            />
            <button
              id="speed-zoom-reset"
              type="button"
              className="text-sm text-orange-400 hover:text-orange-300 ml-2"
            >
              Reset Zoom
            </button>
          </div>
          <div id="speed-zoom-corner-pills" className="flex gap-1 mb-2 flex-wrap" />
          <div className="relative" style={{ width: '100%' }}>
            <canvas
              id="speed-zoom-canvas"
              style={{ width: '100%', height: '280px', display: 'block' }}
            />
            <div
              id="speed-zoom-tooltip"
              className="speed-zoom-tooltip"
              style={{ display: 'none' }}
            />
          </div>
          <div
            id="speed-zoom-legend"
            className="flex gap-3 text-xs text-gray-400 mt-1 flex-wrap"
          />
        </div>

        {/* Lap times chart */}
        <div className="relative mt-4" style={{ width: '100%' }}>
          <canvas
            id="lap-times-chart"
            style={{ width: '100%', height: '250px', display: 'block' }}
          />
          <div
            id="lap-time-tooltip"
            className="lap-time-tooltip"
            style={{ display: 'none', position: 'absolute' }}
          />
        </div>
      </div>
    );
  }

  // ── Data mode (pre-fetched) ──────────────────────────────────
  return (
    <div ref={containerRef} className={className}>
      <div style={{ width: '100%', height: '250px', background: '#1a1a2e' }}>
        {data ? (
          <div className="text-gray-400 p-4 text-sm">
            Speed trace with {data.distances.length} points
            {data.ref_speeds ? ' (with reference overlay)' : ''}
          </div>
        ) : (
          <div className="text-gray-500 p-4">No speed data</div>
        )}
      </div>
    </div>
  );
}
