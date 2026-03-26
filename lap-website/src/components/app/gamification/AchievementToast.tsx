'use client';

import { useEffect, useState } from 'react';
import type { Achievement } from './types';

const ICON_MAP: Record<string, string> = {
  flag: '\u{1F3C1}',
  calendar: '\u{1F4C5}',
  star: '\u2B50',
  trophy: '\u{1F3C6}',
  medal: '\u{1F3C5}',
  shield: '\u{1F6E1}\uFE0F',
  crown: '\u{1F451}',
  fire: '\u{1F525}',
  'check-circle': '\u2705',
  'list-check': '\u{1F4CB}',
  zap: '\u26A1',
  'trending-up': '\u{1F4C8}',
};

function resolveIcon(icon: string): string {
  return ICON_MAP[icon] ?? icon;
}

interface AchievementToastProps {
  achievement: Achievement | null;
  onDismiss: () => void;
}

export default function AchievementToast({
  achievement,
  onDismiss,
}: AchievementToastProps) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (!achievement) {
      setVisible(false);
      return;
    }

    // Trigger slide-in on next frame so the transition fires
    const enterFrame = requestAnimationFrame(() => setVisible(true));

    // Auto-dismiss after 5 seconds
    const timer = setTimeout(() => {
      setVisible(false);
      // Wait for slide-out animation to finish before calling onDismiss
      setTimeout(onDismiss, 300);
    }, 5000);

    return () => {
      cancelAnimationFrame(enterFrame);
      clearTimeout(timer);
    };
  }, [achievement, onDismiss]);

  if (!achievement) return null;

  return (
    <div
      className="fixed top-4 right-4 z-50 max-w-sm w-full pointer-events-auto"
      style={{
        transform: visible ? 'translateX(0)' : 'translateX(120%)',
        opacity: visible ? 1 : 0,
        transition: 'transform 0.3s cubic-bezier(0.22, 1, 0.36, 1), opacity 0.3s ease',
      }}
    >
      <div
        className="rounded-lg p-4 shadow-xl flex items-start gap-3"
        style={{
          backgroundColor: '#141414',
          border: '2px solid #C9A84C',
        }}
      >
        {/* Icon */}
        <div className="text-3xl flex-shrink-0" role="img" aria-label={achievement.label}>
          {resolveIcon(achievement.icon)}
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          <p
            className="font-monument text-xs font-bold uppercase tracking-wider mb-0.5"
            style={{ color: '#C9A84C' }}
          >
            Achievement Unlocked
          </p>
          <p className="font-monument text-sm font-semibold text-chalk">
            {achievement.label}
          </p>
          <p className="text-xs text-steel mt-1">
            {achievement.description}
          </p>
        </div>

        {/* Dismiss button */}
        <button
          type="button"
          onClick={() => {
            setVisible(false);
            setTimeout(onDismiss, 300);
          }}
          className="flex-shrink-0 text-steel hover:text-chalk transition-colors text-lg leading-none"
          aria-label="Dismiss"
        >
          &times;
        </button>
      </div>
    </div>
  );
}
