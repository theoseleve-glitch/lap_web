'use client';

import { useMemo } from 'react';

interface XPProgressBarProps {
  totalXp: number;
  level: number;
  xpForCurrentLevel?: number;
  xpForNextLevel?: number;
  className?: string;
}

export default function XPProgressBar({
  totalXp,
  level,
  xpForCurrentLevel = 0,
  xpForNextLevel = 100,
  className = '',
}: XPProgressBarProps) {
  const { progressPercent, currentInLevel, neededForNext } = useMemo(() => {
    const range = xpForNextLevel - xpForCurrentLevel;
    const current = totalXp - xpForCurrentLevel;
    const needed = range;
    const raw = range > 0 ? (current / range) * 100 : 0;
    const clamped = Math.max(0, Math.min(100, raw));
    return {
      progressPercent: clamped,
      currentInLevel: Math.max(0, current),
      neededForNext: Math.max(0, needed),
    };
  }, [totalXp, xpForCurrentLevel, xpForNextLevel]);

  return (
    <div className={`flex items-center gap-4 ${className}`}>
      {/* Level circle */}
      <div
        className="flex-shrink-0 flex items-center justify-center w-12 h-12 rounded-full border-2"
        style={{
          borderColor: '#a3e635',
          backgroundColor: 'rgba(163, 230, 53, 0.1)',
        }}
      >
        <span
          className="font-monument text-lg font-bold"
          style={{ color: '#a3e635' }}
        >
          {level}
        </span>
      </div>

      {/* Progress bar + label */}
      <div className="flex-1 min-w-0">
        <p className="text-sm font-telemetry text-chalk mb-1">
          Level {level} &mdash; {currentInLevel} / {neededForNext} XP
        </p>

        {/* Bar track */}
        <div
          className="w-full h-3 rounded-full overflow-hidden"
          style={{ backgroundColor: '#1a1a2e' }}
        >
          {/* Bar fill */}
          <div
            className="h-full rounded-full"
            style={{
              width: `${progressPercent}%`,
              backgroundColor: '#a3e635',
              transition: 'width 0.6s cubic-bezier(0.22, 1, 0.36, 1)',
            }}
          />
        </div>
      </div>
    </div>
  );
}
