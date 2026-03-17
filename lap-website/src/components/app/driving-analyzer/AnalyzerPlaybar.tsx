'use client';

import { useRef, useCallback } from 'react';
import type { PlaybackSpeed } from './types';
import { PLAYBACK_SPEEDS } from './types';

interface AnalyzerPlaybarProps {
  playing: boolean;
  currentDistance: number;
  minDistance: number;
  maxDistance: number;
  playbackSpeed: PlaybackSpeed;
  lapTime: number | null;
  currentTime: number | null;
  onTogglePlay: () => void;
  onScrub: (distance: number) => void;
  onSpeedChange: (speed: PlaybackSpeed) => void;
}

function formatTime(s: number | null): string {
  if (s == null || isNaN(s)) return '--:--.---';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}

function formatDist(m: number): string {
  return m >= 1000 ? `${(m / 1000).toFixed(2)} km` : `${Math.round(m)} m`;
}

export function AnalyzerPlaybar({
  playing,
  currentDistance,
  minDistance,
  maxDistance,
  playbackSpeed,
  lapTime,
  onTogglePlay,
  onScrub,
  onSpeedChange,
}: AnalyzerPlaybarProps) {
  const scrubberRef = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);

  const range = maxDistance - minDistance || 1;
  const progress = ((currentDistance - minDistance) / range) * 100;

  const handleScrub = useCallback(
    (clientX: number) => {
      const bar = scrubberRef.current;
      if (!bar) return;
      const rect = bar.getBoundingClientRect();
      const frac = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
      onScrub(minDistance + frac * range);
    },
    [minDistance, range, onScrub],
  );

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      dragging.current = true;
      handleScrub(e.clientX);

      const handleMove = (ev: MouseEvent) => handleScrub(ev.clientX);
      const handleUp = () => {
        dragging.current = false;
        window.removeEventListener('mousemove', handleMove);
        window.removeEventListener('mouseup', handleUp);
      };
      window.addEventListener('mousemove', handleMove);
      window.addEventListener('mouseup', handleUp);
    },
    [handleScrub],
  );

  const handleTouchStart = useCallback(
    (e: React.TouchEvent) => {
      dragging.current = true;
      if (e.touches[0]) handleScrub(e.touches[0].clientX);

      const handleMove = (ev: TouchEvent) => {
        ev.preventDefault(); // prevent scroll during scrub
        if (ev.touches[0]) handleScrub(ev.touches[0].clientX);
      };
      const handleEnd = () => {
        dragging.current = false;
        window.removeEventListener('touchmove', handleMove);
        window.removeEventListener('touchend', handleEnd);
      };
      window.addEventListener('touchmove', handleMove, { passive: false });
      window.addEventListener('touchend', handleEnd);
    },
    [handleScrub],
  );

  return (
    <div className="flex items-center gap-3 px-4 py-2.5 bg-concrete border-t border-steel/10">
      {/* Play/Pause */}
      <button
        type="button"
        onClick={onTogglePlay}
        className="w-8 h-8 flex items-center justify-center rounded bg-asphalt border border-steel/20 text-chalk hover:bg-steel/10 transition-colors"
        aria-label={playing ? 'Pause' : 'Play'}
        title={playing ? 'Pause (Space)' : 'Play (Space)'}
      >
        {playing ? (
          <svg width="12" height="14" viewBox="0 0 12 14" fill="currentColor">
            <rect x="1" y="1" width="3" height="12" rx="0.5" />
            <rect x="8" y="1" width="3" height="12" rx="0.5" />
          </svg>
        ) : (
          <svg width="12" height="14" viewBox="0 0 12 14" fill="currentColor">
            <path d="M1 1.5L11 7L1 12.5V1.5Z" />
          </svg>
        )}
      </button>

      {/* Speed selector */}
      <div className="flex items-center gap-0.5">
        {PLAYBACK_SPEEDS.map((s) => (
          <button
            type="button"
            key={s}
            onClick={() => onSpeedChange(s)}
            className={`px-1.5 py-0.5 text-[10px] font-telemetry rounded transition-colors ${
              playbackSpeed === s
                ? 'bg-gold text-white'
                : 'text-steel hover:text-chalk'
            }`}
          >
            {s}x
          </button>
        ))}
      </div>

      {/* Scrubber bar */}
      <div
        ref={scrubberRef}
        className="flex-1 h-6 flex items-center cursor-pointer group touch-none"
        onMouseDown={handleMouseDown}
        onTouchStart={handleTouchStart}
      >
        <div className="w-full h-1.5 bg-asphalt rounded-full relative overflow-hidden">
          {/* Progress fill */}
          <div
            className="absolute inset-y-0 left-0 bg-acid-green/60 rounded-full"
            style={{ width: `${Math.max(0, Math.min(100, progress))}%` }}
          />
          {/* Thumb */}
          <div
            className="absolute top-1/2 -translate-y-1/2 w-3 h-3 rounded-full bg-chalk border-2 border-acid-green opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none"
            style={{ left: `calc(${Math.max(0, Math.min(100, progress))}% - 6px)` }}
          />
        </div>
      </div>

      {/* Distance display */}
      <div className="flex items-center gap-2 text-[11px] font-telemetry tabular-nums shrink-0">
        <span className="text-chalk">{formatDist(currentDistance)}</span>
        <span className="text-steel/60">/</span>
        <span className="text-steel">{formatDist(maxDistance)}</span>
      </div>

      {/* Lap time */}
      <div className="text-[11px] font-telemetry tabular-nums text-steel shrink-0">
        {formatTime(lapTime)}
      </div>
    </div>
  );
}
