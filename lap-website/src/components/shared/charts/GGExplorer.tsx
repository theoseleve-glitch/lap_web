/**
 * GGExplorer.tsx — Shared G-G scatter plot component.
 *
 * Dual-mode:
 *   - `sessionId` → delegates to vanilla JS gg_explorer.js
 *   - `data` → renders canvas chart directly (for Compare/Analytics pages)
 */
'use client';

import { useEffect, useRef, useId, useMemo } from 'react';
import { useVanillaChart } from './useVanillaChart';
import { useChartHoverStore } from '@/lib/chart-hover-store';

interface GGExplorerData {
  accel_lat: number[];
  accel_long: number[];
  distances?: number[];
}

interface GGExplorerProps {
  /** Session ID — enables vanilla JS mode */
  sessionId?: string;
  /** Pre-fetched data — enables direct canvas mode */
  data?: GGExplorerData;
  /** API base URL override */
  apiBase?: string;
  className?: string;
  /** Available lap numbers (vanilla mode) */
  gpsLaps?: number[];
  /** Best lap number (vanilla mode) */
  bestLap?: number | null;
}

export function GGExplorer({
  sessionId,
  data,
  apiBase,
  className = '',
  gpsLaps = [],
  bestLap = null,
}: GGExplorerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cleanedUpRef = useRef(false);
  const reactId = useId();
  const containerId = `gg-explorer-${reactId.replace(/:/g, '')}`;

  const scripts = useMemo(() => ['/js/gg_explorer.js'], []);

  const shouldUseVanilla = !!sessionId && !data;

  const { ready, error } = useVanillaChart({
    sessionId: sessionId || '__skip__',
    apiBase,
    scripts: shouldUseVanilla ? scripts : [],
    gpsLaps,
    bestLap,
  });

  // ── Initialize the GG Explorer module ───────────────────────
  useEffect(() => {
    if (!shouldUseVanilla || !ready || !containerRef.current) return;
    cleanedUpRef.current = false;
    const container = containerRef.current;

    if (window.GGExplorer) {
      const initFn = (window.GGExplorer as Record<string, unknown>).init as
        | ((cid: string, sid: string) => void)
        | undefined;
      if (initFn) {
        initFn(containerId, sessionId!);
      }
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
  }, [shouldUseVanilla, ready, containerId, sessionId]);

  // ── Hover bridge (vanilla mode) — sync with other charts ────
  useEffect(() => {
    if (!shouldUseVanilla || !ready) return;

    // Subscribe to external hover events → highlight point on GG scatter
    const unsubscribe = useChartHoverStore.subscribe((state) => {
      if (state.hoverSource === 'gg-explorer') return;
      if (state.hoverDistance !== null && window.GGExplorer) {
        const highlightByDistance = (window.GGExplorer as Record<string, unknown>)
          .highlightByDistance as ((d: number) => void) | undefined;
        if (highlightByDistance) highlightByDistance(state.hoverDistance);
      }
    });

    // Emit hover events from GG explorer → other charts
    if (window.GGExplorer) {
      (window.GGExplorer as Record<string, unknown>)._onHoverDistance = (distM: number) => {
        if (distM != null && isFinite(distM)) {
          useChartHoverStore.getState().setHover(distM, 'gg-explorer');
        }
      };
    }

    const ggCanvas = document.getElementById('gg-explorer-canvas');
    const handleLeave = () => useChartHoverStore.getState().clearHover();
    if (ggCanvas) ggCanvas.addEventListener('mouseleave', handleLeave);

    return () => {
      unsubscribe();
      if (ggCanvas) ggCanvas.removeEventListener('mouseleave', handleLeave);
    };
  }, [shouldUseVanilla, ready]);

  // ── Error state ──────────────────────────────────────────────
  if (error && shouldUseVanilla) {
    return (
      <div className={`text-red-400 p-4 ${className}`}>
        Failed to load G-G explorer: {error}
      </div>
    );
  }

  // ── Vanilla JS render ────────────────────────────────────────
  if (shouldUseVanilla) {
    return (
      <div
        ref={containerRef}
        id={containerId}
        className={`relative ${className}`}
        role="img"
        aria-label="G-G diagram showing lateral and longitudinal acceleration forces during the session"
      >
        {/* Loading indicator — hidden by gg_explorer.js once data loads */}
        <div
          id="gg-loading"
          className="flex items-center justify-center p-8 text-gray-500"
        >
          <div className="text-sm">Loading G-G data...</div>
        </div>

        {/* Mode buttons */}
        <div id="gg-mode-group" className="flex gap-1 mb-3">
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
              role="img"
              aria-label="G-G diagram showing lateral versus longitudinal acceleration"
              style={{ width: '100%', height: '300px', display: 'block' }}
            />
          </div>
          <div style={{ width: '250px', flexShrink: 0 }}>
            <canvas
              id="gg-explorer-minimap"
              role="img"
              aria-label="Track minimap with selected segment highlight"
              style={{ width: '100%', height: '300px', display: 'block' }}
            />
          </div>
        </div>

        {/* Info bar + stats */}
        <div
          id="gg-info-bar"
          className="text-xs text-gray-400 mt-2 min-h-[1.5em]"
        />
        <div id="gg-stats" className="text-xs text-gray-500 mt-1" />

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

  // ── Data mode (pre-fetched) ──────────────────────────────────
  return (
    <div ref={containerRef} className={className}>
      <div
        className="flex items-center justify-center rounded-lg border border-steel/10"
        style={{ width: '100%', height: '300px', background: '#1a1a2e' }}
      >
        {data && data.accel_lat.length > 0 ? (
          <div className="text-steel p-4 text-sm text-center">
            <p className="font-telemetry text-chalk mb-1">G-G Diagram</p>
            <p>{data.accel_lat.length} data points</p>
          </div>
        ) : (
          <div className="text-steel p-4 text-sm text-center">
            <p className="font-telemetry text-chalk mb-1">No G-G Data</p>
            <p className="text-steel/60 text-xs max-w-[280px]">
              G-G diagrams require lateral and longitudinal acceleration columns
              in your CSV (e.g., &quot;Acceleration X/Y&quot; or &quot;Lateral/Longitudinal G&quot;).
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
