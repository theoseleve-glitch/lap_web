'use client';

type PlaybackSpeed = 0.5 | 1 | 2;
type ViewMode = 'split' | 'cockpit' | 'map';

interface CornerReplayControlsProps {
  isPlaying: boolean;
  currentFrame: number;
  totalFrames: number;
  playbackSpeed: PlaybackSpeed;
  viewMode: ViewMode;
  currentTime: number; // seconds into the corner
  totalTime: number; // total corner duration in seconds
  onTogglePlay: () => void;
  onScrub: (frame: number) => void;
  onSpeedChange: (speed: PlaybackSpeed) => void;
  onViewModeChange: (mode: ViewMode) => void;
}

const speeds: PlaybackSpeed[] = [0.5, 1, 2];
const viewModes: { value: ViewMode; label: string }[] = [
  { value: 'split', label: 'Split' },
  { value: 'cockpit', label: 'Cockpit' },
  { value: 'map', label: 'Map' },
];

function formatTime(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  if (mins > 0) {
    return `${mins}:${secs.toFixed(2).padStart(5, '0')}`;
  }
  return secs.toFixed(2) + 's';
}

export function CornerReplayControls({
  isPlaying,
  currentFrame,
  totalFrames,
  playbackSpeed,
  viewMode,
  currentTime,
  totalTime,
  onTogglePlay,
  onScrub,
  onSpeedChange,
  onViewModeChange,
}: CornerReplayControlsProps) {
  const progress = totalFrames > 1 ? currentFrame / (totalFrames - 1) : 0;

  return (
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
            value={currentFrame}
            onChange={(e) => onScrub(parseInt(e.target.value, 10))}
            className="absolute inset-0 w-full opacity-0 cursor-pointer"
            aria-label="Replay scrubber"
          />
          {/* Thumb indicator */}
          <div
            className="absolute top-1/2 -translate-y-1/2 w-3 h-3 bg-acid-green rounded-full border-2 border-concrete opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none"
            style={{ left: `calc(${progress * 100}% - 6px)` }}
          />
        </div>
      </div>

      {/* Controls row */}
      <div className="flex items-center justify-between gap-4">
        {/* Left: play/pause + time */}
        <div className="flex items-center gap-3">
          <button
            onClick={onTogglePlay}
            className="w-8 h-8 flex items-center justify-center rounded-md bg-asphalt hover:bg-steel/20 transition-colors text-chalk"
            aria-label={isPlaying ? 'Pause' : 'Play'}
          >
            {isPlaying ? (
              // Pause icon
              <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor">
                <rect x="2" y="1" width="3.5" height="12" rx="0.5" />
                <rect x="8.5" y="1" width="3.5" height="12" rx="0.5" />
              </svg>
            ) : (
              // Play icon
              <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor">
                <path d="M3 1.5v11l9-5.5z" />
              </svg>
            )}
          </button>

          <span className="font-telemetry text-xs text-steel tabular-nums">
            {formatTime(currentTime)} / {formatTime(totalTime)}
          </span>

          <span className="font-telemetry text-[10px] text-steel/60 tabular-nums">
            F{currentFrame + 1}/{totalFrames}
          </span>
        </div>

        {/* Center: speed selector */}
        <div className="flex items-center gap-1">
          {speeds.map((s) => (
            <button
              key={s}
              onClick={() => onSpeedChange(s)}
              className={`px-2.5 py-1 rounded text-xs font-telemetry transition-colors ${
                playbackSpeed === s
                  ? 'bg-acid-green/20 text-acid-green'
                  : 'text-steel hover:text-chalk'
              }`}
            >
              {s}x
            </button>
          ))}
        </div>

        {/* Right: view mode tabs */}
        <div className="flex items-center gap-1">
          {viewModes.map((m) => (
            <button
              key={m.value}
              onClick={() => onViewModeChange(m.value)}
              className={`px-3 py-1 rounded text-xs font-telemetry transition-colors ${
                viewMode === m.value
                  ? 'bg-acid-green/20 text-acid-green'
                  : 'text-steel hover:text-chalk'
              }`}
            >
              {m.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
