'use client';

import { useEffect, useRef, useId, useMemo } from 'react';
import { useVanillaChart } from '@/components/shared/charts/useVanillaChart';

interface LapSpeedOverlayProps {
  sessionId: string;
  apiBase?: string;
  gpsLaps: number[];
  bestLap: number | null;
  className?: string;
}

/**
 * LapSpeedOverlay — Vanilla JS wrapper for lap_overlay.js.
 *
 * Renders a multi-lap speed overlay chart with per-lap checkboxes.
 * Unlike LapDistribution/LapProgress, lap_overlay.js expects specific
 * DOM element IDs pre-rendered:
 *   - #speed-overlay-chart (canvas)
 *   - #overlay-legend
 *   - .lap-overlay-cb (checkboxes)
 *   - #overlay-select-all / #overlay-clear-all buttons
 */
export function LapSpeedOverlay({
  sessionId,
  apiBase,
  gpsLaps,
  bestLap,
  className = '',
}: LapSpeedOverlayProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cleanedUpRef = useRef(false);
  const reactId = useId();
  const containerId = `lap-overlay-${reactId.replace(/:/g, '')}`;

  const scripts = useMemo(() => ['/js/lap_overlay.js'], []);

  const { ready, error } = useVanillaChart({
    sessionId,
    apiBase,
    scripts,
    gpsLaps,
    bestLap,
  });

  useEffect(() => {
    if (!ready || !containerRef.current) return;
    cleanedUpRef.current = false;

    if (window.LapOverlay) {
      const initFn = (window.LapOverlay as Record<string, unknown>).init as
        | (() => void)
        | undefined;
      if (initFn) initFn();
    }

    return () => {
      if (cleanedUpRef.current) return;
      cleanedUpRef.current = true;
      // Clear dynamic content but preserve the static structure
      const legend = document.getElementById('overlay-legend');
      if (legend) legend.textContent = '';
    };
  }, [ready, sessionId]);

  if (error) {
    return (
      <div className={`text-red-400 p-4 ${className}`}>
        Failed to load speed overlay: {error}
      </div>
    );
  }

  if (gpsLaps.length === 0) {
    return (
      <div className={`text-steel p-4 text-sm text-center ${className}`}>
        No lap data available for speed overlay.
      </div>
    );
  }

  return (
    <div ref={containerRef} id={containerId} className={`relative ${className}`}>
      {/* Controls: select/clear all + per-lap checkboxes */}
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <button
          type="button"
          id="overlay-select-all"
          className="px-2 py-1 text-xs rounded bg-gray-700 text-white hover:bg-gray-600"
        >
          All
        </button>
        <button
          type="button"
          id="overlay-clear-all"
          className="px-2 py-1 text-xs rounded bg-gray-800 text-gray-400 hover:bg-gray-700"
        >
          None
        </button>
        <div className="flex flex-wrap gap-x-3 gap-y-1 ml-2">
          {gpsLaps.map((lap) => (
            <label key={lap} className="flex items-center gap-1 text-xs text-gray-300 cursor-pointer">
              <span className="lap-color-swatch" />
              <input
                type="checkbox"
                className="lap-overlay-cb"
                data-lap={lap}
                defaultChecked={lap === bestLap}
              />
              Lap {lap}
            </label>
          ))}
        </div>
      </div>

      {/* Chart canvas */}
      <canvas id="speed-overlay-chart" style={{ width: '100%', display: 'block' }} />

      {/* Legend (populated by vanilla JS) */}
      <div id="overlay-legend" className="text-xs text-gray-400 mt-2" />
    </div>
  );
}
