'use client';

import { useEffect, useState } from 'react';
import type { Achievement } from './types';

interface AchievementToastProps {
  achievement: Achievement | null;
  onDismiss: () => void;
}

export default function AchievementToast({
  achievement,
  onDismiss,
}: AchievementToastProps) {
  const [visible, setVisible] = useState(false);
  const accent = '#C9A84C';

  useEffect(() => {
    if (!achievement) {
      setVisible(false);
      return;
    }

    const enterFrame = requestAnimationFrame(() => setVisible(true));

    const timer = setTimeout(() => {
      setVisible(false);
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
      className="fixed top-6 right-6 z-[60] w-[380px] max-w-[92vw] rounded-[20px] overflow-hidden"
      style={{
        background: '#141414',
        border: '1px solid rgba(240,237,229,0.06)',
        boxShadow: `0 20px 60px rgba(0,0,0,0.6), 0 0 40px ${accent}10`,
        transform: visible ? 'translateX(0) translateY(0)' : 'translateX(60px) translateY(-10px)',
        opacity: visible ? 1 : 0,
        transition: 'transform 0.4s cubic-bezier(0.22, 1, 0.36, 1), opacity 0.3s ease',
      }}
    >
      {/* Top accent line */}
      <div
        className="h-[2px]"
        style={{ background: `linear-gradient(90deg, ${accent}, ${accent}60, transparent)` }}
      />

      <div className="flex gap-4 items-start p-5">
        {/* Hexagonal mini badge */}
        <div className="shrink-0 relative w-10 h-11">
          <svg viewBox="0 0 40 44" className="w-full h-full">
            <path
              d="M20 2 L37 11 L37 33 L20 42 L3 33 L3 11 Z"
              fill={`${accent}0A`}
              stroke={accent}
              strokeWidth="1"
              strokeDasharray="6 4"
              opacity="0.6"
            />
            {/* Small trophy */}
            <g transform="translate(12, 13)" opacity="0.9">
              <path d="M4 3.5v2.5a2 2 0 004 0V3.5H4z" fill={accent} opacity="0.2" />
              <path d="M3 1l1 2.5h4l1-2.5" stroke={accent} strokeWidth="0.8" fill="none" strokeLinejoin="round" />
              <path d="M4 3.5v2.5a2 2 0 004 0V3.5" stroke={accent} strokeWidth="0.8" fill="none" />
              <path d="M5 8.5v1h2v-1" stroke={accent} strokeWidth="0.8" fill="none" />
              <path d="M4 10.5h4" stroke={accent} strokeWidth="0.8" strokeLinecap="round" fill="none" />
            </g>
          </svg>
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          <p className="font-telemetry text-[9px] uppercase tracking-[0.15em] mb-1 text-gold">
            Achievement Unlocked
          </p>
          <p className="font-monument text-[15px] font-bold text-chalk uppercase tracking-tight mb-1.5">
            {achievement.label}
          </p>
          <p className="font-body text-[12px] text-steel leading-relaxed">
            {achievement.description}
          </p>
        </div>

        {/* Close button */}
        <button
          type="button"
          onClick={() => {
            setVisible(false);
            setTimeout(onDismiss, 300);
          }}
          className="shrink-0 w-7 h-7 rounded-lg flex items-center justify-center text-steel hover:text-chalk transition-colors cursor-pointer"
          style={{
            backgroundColor: 'rgba(240,237,229,0.04)',
            border: '1px solid rgba(240,237,229,0.06)',
          }}
          aria-label="Dismiss"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M18 6L6 18M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Bottom micro detail */}
      <div className="px-5 pb-3 flex items-center gap-2">
        <div className="h-[1px] flex-1" style={{ background: `linear-gradient(90deg, ${accent}20, transparent)` }} />
        <span className="font-telemetry text-[7px] uppercase tracking-[0.2em] text-steel opacity-40">
          +50 XP
        </span>
      </div>
    </div>
  );
}
