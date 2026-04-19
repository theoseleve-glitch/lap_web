'use client';

import { useState } from 'react';
import { TrackSurface3D, type HeatmapMode } from './TrackSurface3D';
import { useTrackSurfaceData } from './useTrackSurfaceData';

/* ── Types ────────────────────────────────────────────── */

interface TrackSurfacePanelProps {
  sessionId: string;
  className?: string;
}

/* ── Mode config ──────────────────────────────────────── */

const MODES: { key: HeatmapMode; label: string }[] = [
  { key: 'grip', label: 'Grip' },
  { key: 'elevation', label: 'Elevation' },
  { key: 'line-delta', label: 'Line Delta' },
];

/* ── Legend color stops (matching WebGL palette) ──────── */

const LEGEND: Record<HeatmapMode, { lowLabel: string; highLabel: string; lowHex: string; highHex: string }> = {
  grip: { lowLabel: 'Low', highLabel: 'High', lowHex: '#FF2A2A', highHex: '#22C55E' },
  elevation: { lowLabel: 'Low', highLabel: 'High', lowHex: '#3B82F6', highHex: '#F0EDE5' },
  'line-delta': { lowLabel: 'Off-line', highLabel: 'On-line', lowHex: '#FF2A2A', highHex: '#22C55E' },
};

/* ── Component ────────────────────────────────────────── */

export default function TrackSurfacePanel({ sessionId, className }: TrackSurfacePanelProps) {
  const [mode, setMode] = useState<HeatmapMode>('grip');
  const [showOptimal, setShowOptimal] = useState(true);
  const [showActual, setShowActual] = useState(false);
  const { surface, isLoading } = useTrackSurfaceData(sessionId);

  const legend = LEGEND[mode];
  const qualityTier = surface?.quality_tier ?? null;

  return (
    <div className={`bg-concrete border border-steel/20 rounded-lg overflow-hidden ${className ?? ''}`}>
      {/* Header row */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-steel/10">
        <h3 className="font-monument text-chalk text-sm tracking-wide uppercase">
          Track Surface
        </h3>

        {qualityTier && (
          <span className="font-telemetry text-xs text-steel bg-steel/10 border border-steel/30 rounded px-2 py-0.5">
            {qualityTier}
          </span>
        )}
      </div>

      {/* Mode selector */}
      <div className="flex items-center gap-1 px-4 py-2 border-b border-steel/10">
        {MODES.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setMode(key)}
            className={`font-telemetry text-xs px-3 py-1.5 rounded transition-colors ${
              mode === key
                ? 'text-gold'
                : 'text-steel hover:text-chalk'
            }`}
          >
            {label}
          </button>
        ))}

        <div className="ml-auto flex items-center gap-3">
          <label className="flex items-center gap-1.5 cursor-pointer">
            <input
              type="checkbox"
              checked={showOptimal}
              onChange={(e) => setShowOptimal(e.target.checked)}
              className="sr-only peer"
            />
            <span className="block w-3 h-3 rounded-sm border border-steel/40 peer-checked:bg-gold peer-checked:border-gold transition-colors" />
            <span className="font-telemetry text-xs text-steel">Optimal</span>
          </label>
          <label className="flex items-center gap-1.5 cursor-pointer">
            <input
              type="checkbox"
              checked={showActual}
              onChange={(e) => setShowActual(e.target.checked)}
              className="sr-only peer"
            />
            <span className="block w-3 h-3 rounded-sm border border-steel/40 peer-checked:bg-chalk peer-checked:border-chalk transition-colors" />
            <span className="font-telemetry text-xs text-steel">Actual</span>
          </label>
        </div>
      </div>

      {/* 3D canvas */}
      <TrackSurface3D
        sessionId={sessionId}
        mode={mode}
        showOptimalLine={showOptimal}
        showActualLine={showActual}
        className="w-full aspect-[16/9]"
      />

      {/* Legend bar */}
      {!isLoading && (
        <div className="flex items-center gap-2 px-4 py-2 border-t border-steel/10">
          <span className="font-telemetry text-xs text-steel">{legend.lowLabel}</span>
          <div
            className="flex-1 h-2 rounded-full"
            style={{
              background: `linear-gradient(to right, ${legend.lowHex}, ${legend.highHex})`,
            }}
          />
          <span className="font-telemetry text-xs text-steel">{legend.highLabel}</span>
        </div>
      )}
    </div>
  );
}
