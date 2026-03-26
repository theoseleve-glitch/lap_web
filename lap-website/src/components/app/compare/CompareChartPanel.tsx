'use client';

import { useState } from 'react';
import SpeedOverlayPanel from './SpeedOverlayPanel';
import GpsOverlayPanel from './GpsOverlayPanel';
import SectorDeltaPanel from './SectorDeltaPanel';
import CornerComparePanel from './CornerComparePanel';

type ChartMode = 'speed' | 'gps' | 'sectors' | 'corners';

const MODES: { key: ChartMode; label: string; icon: string }[] = [
  { key: 'speed',   label: 'Speed Overlay', icon: '~' },
  { key: 'gps',     label: 'GPS Overlay',   icon: '\u25CE' },
  { key: 'sectors', label: 'Sector Delta',  icon: '\u25A6' },
  { key: 'corners', label: 'Corner Detail', icon: '\u2197' },
];

const COLOR_A = '#22C55E';
const COLOR_B = '#C9A84C';

export default function CompareChartPanel({
  sessionAId,
  sessionBId,
}: {
  sessionAId: string;
  sessionBId: string;
}) {
  const [mode, setMode] = useState<ChartMode>('speed');

  return (
    <div className="flex rounded-xl border border-steel/10 overflow-hidden bg-concrete">
      {/* Left rail */}
      <div className="w-40 shrink-0 flex flex-col border-r border-steel/10 bg-zinc-900/50">
        {MODES.map((m) => {
          const active = m.key === mode;
          return (
            <button
              key={m.key}
              type="button"
              onClick={() => setMode(m.key)}
              className={`flex items-center gap-2 px-3 py-3 text-left text-sm font-body transition-colors ${
                active
                  ? 'bg-zinc-700 text-zinc-100 border-l-2 border-acid-green'
                  : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 border-l-2 border-transparent'
              }`}
            >
              <span className="text-base leading-none">{m.icon}</span>
              <span>{m.label}</span>
            </button>
          );
        })}
      </div>

      {/* Right panel */}
      <div className="flex-1 min-w-0">
        {mode === 'speed' && (
          <SpeedOverlayPanel
            sessionAId={sessionAId}
            sessionBId={sessionBId}
            colorA={COLOR_A}
            colorB={COLOR_B}
          />
        )}
        {mode === 'gps' && (
          <GpsOverlayPanel
            sessionAId={sessionAId}
            sessionBId={sessionBId}
            colorA={COLOR_A}
            colorB={COLOR_B}
          />
        )}
        {mode === 'sectors' && (
          <SectorDeltaPanel
            sessionAId={sessionAId}
            sessionBId={sessionBId}
            colorA={COLOR_A}
            colorB={COLOR_B}
          />
        )}
        {mode === 'corners' && (
          <CornerComparePanel
            sessionAId={sessionAId}
            sessionBId={sessionBId}
            colorA={COLOR_A}
            colorB={COLOR_B}
          />
        )}
      </div>
    </div>
  );
}
