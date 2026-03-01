/**
 * GGExplorer.tsx — React wrapper for the Old Tool's gg_explorer.js.
 *
 * This module renders:
 *  - A G-G scatter plot (lateral vs longitudinal acceleration) with density heatmap
 *  - A mini track map showing the selected point's position
 *  - Mode switching (All / Single / Compare)
 *  - Click-to-map interaction in Single/Compare modes
 *
 * The vanilla JS init signature: GGExplorer.init(containerId, sessionId)
 * It creates/finds canvases and controls inside the container by ID.
 */
'use client';

import { useEffect, useRef, useId, useMemo } from 'react';
import { useVanillaChart } from './useVanillaChart';
import { useChartHoverStore } from '@/lib/chart-hover-store';

interface GGExplorerProps {
  sessionId: string;
  apiBase?: string;
  className?: string;
  gpsLaps?: number[];
  bestLap?: number | null;
}

export function GGExplorer({
  sessionId,
  apiBase,
  className = '',
  gpsLaps = [],
  bestLap = null,
}: GGExplorerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cleanedUpRef = useRef(false);
  // Use a stable unique ID for the container
  const reactId = useId();
  const containerId = `gg-explorer-${reactId.replace(/:/g, '')}`;

  const scripts = useMemo(() => ['/js/gg_explorer.js'], []);

  const { ready, error } = useVanillaChart({
    sessionId,
    apiBase,
    scripts,
    gpsLaps,
    bestLap,
  });

  // Initialize the GG Explorer module
  useEffect(() => {
    if (!ready || !containerRef.current) return;
    cleanedUpRef.current = false;
    const container = containerRef.current;

    // GGExplorer.init(containerId, sessionId)
    if (window.GGExplorer) {
      const initFn = (window.GGExplorer as Record<string, unknown>).init as
        | ((cid: string, sid: string) => void)
        | undefined;
      if (initFn) {
        initFn(containerId, sessionId);
      }
    }

    return () => {
      if (cleanedUpRef.current) return;
      cleanedUpRef.current = true;

      // Destroy via ModuleManager
      if (window.ModuleManager) {
        window.ModuleManager.deactivateAll();
      }

      // Clean container DOM
      if (container) {
        while (container.firstChild) {
          container.removeChild(container.firstChild);
        }
      }
    };
  }, [ready, containerId, sessionId]);

  // Bridge: GG Explorer click → Zustand hover store (for cross-chart sync)
  // GGExplorer uses an internal mini-map, but we can bridge distance info.
  useEffect(() => {
    if (!ready) return;

    // Subscribe to external hover → no direct integration needed for GG Explorer
    // (it doesn't have a distance-based crosshair, it has a click-to-position)
    // But we can still listen and highlight if the GG module ever supports it.

    const unsubscribe = useChartHoverStore.subscribe(() => {
      // GGExplorer doesn't have a updateMarkerByDistance equivalent,
      // so we don't bridge incoming hover events to it.
    });

    return () => {
      unsubscribe();
    };
  }, [ready]);

  if (error) {
    return (
      <div className={`text-red-400 p-4 ${className}`}>
        Failed to load G-G explorer: {error}
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      id={containerId}
      className={`relative ${className}`}
    >
      {/* Loading indicator — hidden by gg_explorer.js once data loads */}
      <div
        id="gg-loading"
        className="flex items-center justify-center p-8 text-gray-500"
      >
        <div className="text-sm">Loading G-G data...</div>
      </div>

      {/* Mode buttons */}
      <div
        id="gg-mode-group"
        className="flex gap-1 mb-3"
      >
        <button
          type="button"
          className="gg-mode-btn active px-3 py-1 text-xs rounded bg-gray-700 text-white hover:bg-gray-600"
          data-mode="all"
        >
          All
        </button>
        <button
          type="button"
          className="gg-mode-btn px-3 py-1 text-xs rounded bg-gray-800 text-gray-400 hover:bg-gray-700"
          data-mode="single"
        >
          Single
        </button>
        <button
          type="button"
          className="gg-mode-btn px-3 py-1 text-xs rounded bg-gray-800 text-gray-400 hover:bg-gray-700"
          data-mode="compare"
        >
          Compare
        </button>
      </div>

      {/* Dropdowns */}
      <div className="flex items-center gap-2 mb-2 text-sm flex-wrap">
        <label
          id="gg-primary-label"
          className="text-gray-400"
          style={{ display: 'none' }}
        >
          Primary:
          <select
            id="gg-primary-select"
            className="bg-gray-800 text-white text-sm rounded px-2 py-1 border border-gray-700 ml-1"
          />
        </label>
        <label
          id="gg-compare-label"
          className="text-gray-400"
          style={{ display: 'none' }}
        >
          Compare:
          <select
            id="gg-compare-select"
            className="bg-gray-800 text-white text-sm rounded px-2 py-1 border border-gray-700 ml-1"
          />
        </label>
      </div>

      {/* Main chart area: GG scatter + mini map side-by-side */}
      <div className="flex gap-4">
        <div className="flex-1 min-w-0">
          <canvas
            id="gg-explorer-canvas"
            style={{ width: '100%', display: 'block' }}
          />
        </div>
        <div style={{ width: '250px', flexShrink: 0 }}>
          <canvas
            id="gg-explorer-minimap"
            style={{ width: '100%', display: 'block' }}
          />
        </div>
      </div>

      {/* Info bar + stats */}
      <div
        id="gg-info-bar"
        className="text-xs text-gray-400 mt-2 min-h-[1.5em]"
      />
      <div
        id="gg-stats"
        className="text-xs text-gray-500 mt-1"
      />

      {/* Tooltip (positioned absolutely by the module) */}
      <div
        className="gg-explorer-tooltip"
        style={{
          display: 'none',
          position: 'absolute',
          pointerEvents: 'none',
          background: 'rgba(0,0,0,0.85)',
          color: '#e6edf3',
          padding: '4px 8px',
          borderRadius: '4px',
          fontSize: '11px',
          zIndex: 10,
          whiteSpace: 'nowrap',
        }}
      />
    </div>
  );
}
