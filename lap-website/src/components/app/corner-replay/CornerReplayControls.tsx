'use client';

import type { ReplayMode, PlaybackSpeed, CornerReplayCorner } from '@/types/corner-replay';

interface CornerReplayControlsProps {
  mode: ReplayMode;
  corners: CornerReplayCorner[];
  cornerIndex: number;
  laps: Array<{ lap_number: number; lap_time_s: number | null }>;
  lapA: number;
  lapB: number;
  frame: number;
  totalFrames: number;
  playing: boolean;
  speed: PlaybackSpeed;
  onModeChange: (mode: ReplayMode) => void;
  onCornerChange: (index: number) => void;
  onPrevCorner: () => void;
  onNextCorner: () => void;
  onLapAChange: (lap: number) => void;
  onLapBChange: (lap: number) => void;
  onScrub: (frame: number) => void;
  onTogglePlay: () => void;
  onSpeedChange: (speed: PlaybackSpeed) => void;
}

const MODES: { value: ReplayMode; label: string }[] = [
  { value: 'review', label: 'Review' },
  { value: 'split', label: 'Split' },
  { value: 'top3', label: 'Top 3' },
];

const SPEEDS: PlaybackSpeed[] = [0.25, 0.5, 1, 2];

export function CornerReplayControls({
  mode,
  corners,
  cornerIndex,
  laps,
  lapA,
  lapB,
  frame,
  totalFrames,
  playing,
  speed,
  onModeChange,
  onCornerChange,
  onPrevCorner,
  onNextCorner,
  onLapAChange,
  onLapBChange,
  onScrub,
  onTogglePlay,
  onSpeedChange,
}: CornerReplayControlsProps) {
  const progress = totalFrames > 1 ? frame / (totalFrames - 1) : 0;

  return (
    <div className="space-y-3">
      {/* Mode tabs */}
      <div className="flex items-center gap-1">
        {MODES.map((m) => (
          <button
            key={m.value}
            onClick={() => onModeChange(m.value)}
            className={`px-3 py-1.5 rounded text-xs font-telemetry transition-colors ${
              mode === m.value
                ? 'bg-acid-green/20 text-acid-green'
                : 'text-steel hover:text-chalk hover:bg-white/5'
            }`}
          >
            {m.label}
          </button>
        ))}
      </div>

      {/* Corner pills + navigation */}
      <div className="flex items-center gap-2 flex-wrap">
        <button
          onClick={onPrevCorner}
          className="w-7 h-7 flex items-center justify-center rounded bg-steel/10 text-steel hover:text-chalk transition-colors text-sm"
          aria-label="Previous corner"
        >
          &larr;
        </button>
        <div className="flex gap-1 flex-wrap">
          {corners.map((c, i) => (
            <button
              key={c.corner_id}
              onClick={() => onCornerChange(i)}
              className={`min-w-[28px] h-7 px-1.5 rounded text-xs font-telemetry transition-colors ${
                cornerIndex === i
                  ? 'bg-gold text-carbon font-bold'
                  : 'bg-steel/10 text-steel hover:text-chalk'
              }`}
              title={c.label}
            >
              {c.label || `C${c.corner_id}`}
            </button>
          ))}
        </div>
        <button
          onClick={onNextCorner}
          className="w-7 h-7 flex items-center justify-center rounded bg-steel/10 text-steel hover:text-chalk transition-colors text-sm"
          aria-label="Next corner"
        >
          &rarr;
        </button>
      </div>

      {/* Lap selectors (Split mode only) */}
      {mode === 'split' && (
        <div className="flex items-center gap-4">
          <label className="flex items-center gap-2 text-xs">
            <span className="text-acid-green font-telemetry">Lap A</span>
            <select
              value={lapA}
              onChange={(e) => onLapAChange(Number(e.target.value))}
              className="rounded border border-steel/20 bg-asphalt px-2 py-1 text-xs text-chalk font-telemetry"
            >
              {laps.map((l) => (
                <option key={l.lap_number} value={l.lap_number}>
                  Lap {l.lap_number}{l.lap_time_s ? ` (${l.lap_time_s.toFixed(2)}s)` : ''}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 text-xs">
            <span className="text-safety-red font-telemetry">Lap B</span>
            <select
              value={lapB}
              onChange={(e) => onLapBChange(Number(e.target.value))}
              className="rounded border border-steel/20 bg-asphalt px-2 py-1 text-xs text-chalk font-telemetry"
            >
              {laps.map((l) => (
                <option key={l.lap_number} value={l.lap_number}>
                  Lap {l.lap_number}{l.lap_time_s ? ` (${l.lap_time_s.toFixed(2)}s)` : ''}
                </option>
              ))}
            </select>
          </label>
        </div>
      )}

      {/* Scrubber + play controls */}
      <div className="bg-concrete rounded-lg border border-steel/20 px-4 py-3">
        {/* Progress bar */}
        <div className="mb-3">
          <div className="relative h-1.5 bg-asphalt rounded-full overflow-hidden cursor-pointer group">
            <div
              className="absolute inset-y-0 left-0 bg-acid-green rounded-full transition-[width] duration-75"
              style={{ width: `${progress * 100}%` }}
            />
            <input
              type="range"
              min={0}
              max={Math.max(totalFrames - 1, 0)}
              value={frame}
              onChange={(e) => onScrub(parseInt(e.target.value, 10))}
              className="absolute inset-0 w-full opacity-0 cursor-pointer"
              aria-label="Replay scrubber"
            />
            <div
              className="absolute top-1/2 -translate-y-1/2 w-3 h-3 bg-acid-green rounded-full border-2 border-concrete opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none"
              style={{ left: `calc(${progress * 100}% - 6px)` }}
            />
          </div>
        </div>

        {/* Controls row */}
        <div className="flex items-center justify-between gap-4">
          {/* Play/pause */}
          <button
            onClick={onTogglePlay}
            className="w-8 h-8 flex items-center justify-center rounded-md bg-asphalt hover:bg-steel/20 transition-colors text-chalk"
            aria-label={playing ? 'Pause' : 'Play'}
          >
            {playing ? (
              <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor">
                <rect x="2" y="1" width="3.5" height="12" rx="0.5" />
                <rect x="8.5" y="1" width="3.5" height="12" rx="0.5" />
              </svg>
            ) : (
              <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor">
                <path d="M3 1.5v11l9-5.5z" />
              </svg>
            )}
          </button>

          <span className="font-telemetry text-[10px] text-steel/60 tabular-nums">
            F{frame + 1}/{totalFrames}
          </span>

          {/* Speed selector */}
          <div className="flex items-center gap-1">
            {SPEEDS.map((s) => (
              <button
                key={s}
                onClick={() => onSpeedChange(s)}
                className={`px-2 py-1 rounded text-xs font-telemetry transition-colors ${
                  speed === s
                    ? 'bg-acid-green/20 text-acid-green'
                    : 'text-steel hover:text-chalk'
                }`}
              >
                {s}x
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
