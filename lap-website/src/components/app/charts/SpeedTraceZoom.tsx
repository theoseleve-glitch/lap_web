/**
 * SpeedTraceZoom.tsx — React wrapper for the Old Tool's speed_trace_zoom.js.
 *
 * This module renders:
 *  - A speed-vs-distance chart (via chart_sync.js → #speed-chart)
 *  - Drag-to-zoom selection overlay
 *  - A zoomed detail view with multi-lap comparison
 *  - Corner marker pills for quick-zoom
 *
 * The vanilla JS expects hardcoded DOM IDs, so we create those elements
 * inside a scoped container and let the scripts find them.
 *
 * Hover events are bridged to the Zustand chart-hover-store.
 */
'use client';

import { useEffect, useRef, useMemo } from 'react';
import { useVanillaChart } from './useVanillaChart';
import { useChartHoverStore } from '@/lib/chart-hover-store';

interface SpeedTraceZoomProps {
  sessionId: string;
  apiBase?: string;
  className?: string;
  gpsLaps?: number[];
  bestLap?: number | null;
}

export function SpeedTraceZoom({
  sessionId,
  apiBase,
  className = '',
  gpsLaps = [],
  bestLap = null,
}: SpeedTraceZoomProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cleanedUpRef = useRef(false);

  const scripts = useMemo(
    () => ['/js/chart_sync.js', '/js/speed_trace_zoom.js'],
    [],
  );

  const { ready, error } = useVanillaChart({
    sessionId,
    apiBase,
    scripts,
    gpsLaps,
    bestLap,
  });

  // Bridge hover events: vanilla chart → Zustand store
  useEffect(() => {
    if (!ready) return;

    const setHover = useChartHoverStore.getState().setHover;
    const clearHover = useChartHoverStore.getState().clearHover;

    // ChartSync fires hover via mousemove on the speed canvas.
    // We intercept by watching for TrackMap/GpsTrace updateMarkerByDistance calls.
    const origTrackMapUpdate = window.TrackMap?.updateMarkerByDistance as
      | ((d: number) => void)
      | undefined;
    const origGpsTraceUpdate = window.GpsTrace?.updateMarkerByDistance as
      | ((d: number) => void)
      | undefined;

    if (window.TrackMap) {
      (window.TrackMap as Record<string, unknown>).updateMarkerByDistance = (distM: number) => {
        setHover(distM, 'speed-trace');
        if (origTrackMapUpdate) origTrackMapUpdate(distM);
      };
    }
    if (window.GpsTrace) {
      (window.GpsTrace as Record<string, unknown>).updateMarkerByDistance = (distM: number) => {
        setHover(distM, 'speed-trace');
        if (origGpsTraceUpdate) origGpsTraceUpdate(distM);
      };
    }

    // Subscribe to external hover (from other charts) → update crosshair
    const unsubscribe = useChartHoverStore.subscribe((state) => {
      if (state.hoverSource === 'speed-trace') return; // ignore own events
      if (state.hoverDistance !== null && window.ChartSync) {
        const updateCrosshair = (window.ChartSync as Record<string, unknown>)
          .updateCrosshair as ((d: number) => void) | undefined;
        if (updateCrosshair) updateCrosshair(state.hoverDistance);
      }
    });

    // Listen for mouseleave on the speed canvas to clear hover
    const speedCanvas = document.getElementById('speed-chart');
    const handleLeave = () => clearHover();
    if (speedCanvas) {
      speedCanvas.addEventListener('mouseleave', handleLeave);
    }

    return () => {
      unsubscribe();
      if (speedCanvas) {
        speedCanvas.removeEventListener('mouseleave', handleLeave);
      }
      // Restore original functions
      if (window.TrackMap && origTrackMapUpdate) {
        (window.TrackMap as Record<string, unknown>).updateMarkerByDistance =
          origTrackMapUpdate;
      }
      if (window.GpsTrace && origGpsTraceUpdate) {
        (window.GpsTrace as Record<string, unknown>).updateMarkerByDistance =
          origGpsTraceUpdate;
      }
    };
  }, [ready]);

  // Initialize the chart modules once scripts are loaded and DOM is ready
  useEffect(() => {
    if (!ready || !containerRef.current) return;
    cleanedUpRef.current = false;
    const container = containerRef.current;

    // ChartSync auto-inits on DOMContentLoaded, but since we're in React
    // the DOMContentLoaded has already fired. We need to manually trigger init.
    // The chart_sync.js listens for DOMContentLoaded to find #speed-chart.
    // Since our elements are now in the DOM, we simulate the init path.

    // ChartSync checks for the speed-chart element; trigger its auto-load.
    const speedCanvas = document.getElementById('speed-chart');
    if (speedCanvas && window.ChartSync) {
      // ChartSync's DOMContentLoaded handler won't fire again,
      // but we can call loadSpeedData to trigger drawing.
      const loadFn = (window.ChartSync as Record<string, unknown>)
        .loadSpeedData as ((lapNum: number) => void) | undefined;
      if (loadFn && bestLap) {
        loadFn(bestLap);
      } else if (loadFn && gpsLaps.length > 0) {
        loadFn(gpsLaps[0]);
      }
    }

    // SpeedTraceZoom.init() finds its elements by ID
    if (window.SpeedTraceZoom) {
      const initFn = (window.SpeedTraceZoom as Record<string, unknown>).init as
        | (() => void)
        | undefined;
      if (initFn) initFn();
    }

    return () => {
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

  if (error) {
    return (
      <div className={`text-red-400 p-4 ${className}`}>
        Failed to load speed trace: {error}
      </div>
    );
  }

  return (
    <div ref={containerRef} className={className}>
      {/* Speed chart (overview) — used by chart_sync.js */}
      <div className="relative" style={{ width: '100%' }}>
        <canvas
          id="speed-chart"
          style={{ width: '100%', height: '250px', display: 'block' }}
        />
        <div id="chart-crosshair" className="chart-crosshair" />
        <div id="chart-tooltip" className="chart-tooltip" />
        <div id="speed-chart-selection-rect" className="speed-chart-selection-rect" style={{ display: 'none' }} />
        <div id="speed-chart-corner-markers" className="speed-chart-corner-markers" />
        <div id="speed-chart-drag-hint" className="speed-chart-drag-hint text-xs text-gray-500 text-center mt-1">
          Drag to zoom into a section
        </div>
      </div>

      {/* Zoom panel — used by speed_trace_zoom.js */}
      <div id="speed-zoom-panel" style={{ display: 'none' }} className="mt-4">
        <div className="flex items-center gap-2 mb-2 flex-wrap">
          <label className="text-sm text-gray-400">Primary:</label>
          <select id="speed-zoom-primary" className="bg-gray-800 text-white text-sm rounded px-2 py-1 border border-gray-700" />
          <label className="text-sm text-gray-400 ml-2">Compare:</label>
          <select id="speed-zoom-compare" className="bg-gray-800 text-white text-sm rounded px-2 py-1 border border-gray-700" />
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
          <div id="speed-zoom-tooltip" className="speed-zoom-tooltip" style={{ display: 'none' }} />
        </div>
        <div id="speed-zoom-legend" className="flex gap-3 text-xs text-gray-400 mt-1 flex-wrap" />
      </div>

      {/* Lap times chart — used by chart_sync.js */}
      <div className="relative mt-4" style={{ width: '100%' }}>
        <canvas
          id="lap-times-chart"
          style={{ width: '100%', height: '250px', display: 'block' }}
        />
        <div id="lap-time-tooltip" className="lap-time-tooltip" style={{ display: 'none', position: 'absolute' }} />
      </div>
    </div>
  );
}
