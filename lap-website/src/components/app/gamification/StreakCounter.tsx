'use client';

import { useEffect, useRef } from 'react';

interface StreakCounterProps {
  currentStreak: number;
  longestStreak?: number;
  className?: string;
}

const STREAK_STYLE_ID = 'gamification-streak-pulse';

/**
 * Inject a CSS @keyframes rule for the streak pulse animation
 * via DOM API (avoids dangerouslySetInnerHTML).
 */
function useStreakPulseStyle(enabled: boolean) {
  const injectedRef = useRef(false);

  useEffect(() => {
    if (!enabled || injectedRef.current) return;
    if (typeof document === 'undefined') return;
    if (document.getElementById(STREAK_STYLE_ID)) {
      injectedRef.current = true;
      return;
    }

    const style = document.createElement('style');
    style.id = STREAK_STYLE_ID;
    style.textContent = [
      '@keyframes streak-pulse {',
      '  0%, 100% { transform: scale(1); opacity: 1; }',
      '  50% { transform: scale(1.08); opacity: 0.85; }',
      '}',
    ].join('\n');
    document.head.appendChild(style);
    injectedRef.current = true;
  }, [enabled]);
}

export default function StreakCounter({
  currentStreak,
  longestStreak,
  className = '',
}: StreakCounterProps) {
  const shouldPulse = currentStreak >= 3;
  useStreakPulseStyle(shouldPulse);

  if (currentStreak <= 0) return null;

  return (
    <div
      className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-full ${className}`}
      style={{
        backgroundColor: 'rgba(245, 158, 11, 0.15)',
        border: '1px solid rgba(245, 158, 11, 0.4)',
        animation: shouldPulse
          ? 'streak-pulse 2s ease-in-out infinite'
          : undefined,
      }}
      title={
        longestStreak != null ? `Longest: ${longestStreak} days` : undefined
      }
    >
      <span className="text-lg" role="img" aria-label="fire">
        🔥
      </span>
      <span
        className="font-telemetry text-sm font-semibold"
        style={{ color: '#f59e0b' }}
      >
        {currentStreak} day streak
      </span>
    </div>
  );
}
