'use client';

import { useEffect, useState, useCallback } from 'react';

import { BadgeIcon } from './RacingBadge';

/* ── Types ────────────────────────────────────────────────── */

interface AchievementData {
  key: string;
  label: string;
  description: string;
  icon: string;
  tier: string;
}

interface AchievementUnlockOverlayProps {
  achievement: AchievementData | null;
  onDismiss: () => void;
}

const tierColors: Record<string, string> = {
  bronze: '#C9A84C',
  silver: '#949494',
  gold: '#FACC15',
};

const tierLabels: Record<string, string> = {
  bronze: 'Pit Orange Tier',
  silver: 'Steel Tier',
  gold: 'Marshal Yellow Tier',
};

const TIER_ORDER = ['bronze', 'silver', 'gold'] as const;

function resolveTier(tier: string): 'bronze' | 'silver' | 'gold' {
  if (tier === 'gold' || tier === 'silver' || tier === 'bronze') return tier;
  return 'bronze';
}

/* ── Component ────────────────────────────────────────────── */

export function AchievementUnlockOverlay({
  achievement,
  onDismiss,
}: AchievementUnlockOverlayProps) {
  const [phase, setPhase] = useState<'hidden' | 'backdrop' | 'card' | 'badge' | 'text' | 'done'>('hidden');

  const dismiss = useCallback(() => {
    setPhase('hidden');
    const timer = setTimeout(onDismiss, 300);
    return () => clearTimeout(timer);
  }, [onDismiss]);

  useEffect(() => {
    if (!achievement) {
      setPhase('hidden');
      return;
    }

    setPhase('backdrop');
    const timers = [
      setTimeout(() => setPhase('card'), 200),
      setTimeout(() => setPhase('badge'), 400),
      setTimeout(() => setPhase('text'), 700),
      setTimeout(() => setPhase('done'), 1200),
    ];

    return () => timers.forEach(clearTimeout);
  }, [achievement]);

  if (!achievement && phase === 'hidden') return null;

  const tier = resolveTier(achievement?.tier ?? 'bronze');
  const accent = tierColors[tier];

  const phaseGte = (target: typeof phase): boolean => {
    const order = ['hidden', 'backdrop', 'card', 'badge', 'text', 'done'];
    return order.indexOf(phase) >= order.indexOf(target);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{
        opacity: phaseGte('backdrop') ? 1 : 0,
        transition: 'opacity 0.3s ease',
      }}
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-asphalt/[0.92]" onClick={dismiss} />

      {/* Scanline grid overlay */}
      <div
        className="absolute inset-0 pointer-events-none opacity-[0.03]"
        style={{
          backgroundImage: `repeating-linear-gradient(0deg, transparent, transparent 3px, ${accent} 3px, ${accent} 4px)`,
        }}
      />

      {/* Radial glow */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background: `radial-gradient(ellipse 500px 400px at 50% 42%, ${accent}0D 0%, transparent 70%)`,
        }}
      />

      {/* Card */}
      <div
        onClick={(e) => e.stopPropagation()}
        className="relative w-[480px] max-w-[92vw] rounded-[28px] overflow-hidden"
        style={{
          background: '#141414',
          border: '1px solid rgba(240,237,229,0.06)',
          transform: phaseGte('card') ? 'scale(1) translateY(0)' : 'scale(0.92) translateY(20px)',
          opacity: phaseGte('card') ? 1 : 0,
          transition: 'transform 0.5s cubic-bezier(0.34, 1.56, 0.64, 1), opacity 0.3s ease',
        }}
        role="dialog"
        aria-modal="true"
        aria-label="Achievement unlocked"
      >
        {/* Top accent bar */}
        <div className="h-[2px]" style={{ background: `linear-gradient(90deg, transparent, ${accent}, transparent)` }} />

        {/* Corner grid marks */}
        <div className="absolute top-4 left-5 flex gap-[3px] opacity-20">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="w-[3px] h-[3px] rounded-[0.5px]" style={{ backgroundColor: accent }} />
          ))}
        </div>
        <div className="absolute top-4 right-5 flex gap-[3px] opacity-20">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="w-[3px] h-[3px] rounded-[0.5px]" style={{ backgroundColor: accent }} />
          ))}
        </div>

        <div className="flex flex-col items-center px-10 pt-12 pb-10">
          {/* Hexagonal badge frame */}
          <div
            className="relative w-[140px] h-[156px] mb-8"
            style={{
              transform: phaseGte('badge') ? 'scale(1)' : 'scale(0.7)',
              opacity: phaseGte('badge') ? 1 : 0,
              transition: 'transform 0.5s cubic-bezier(0.34, 1.56, 0.64, 1), opacity 0.3s ease',
            }}
          >
            {/* Outer hex glow */}
            <svg
              viewBox="0 0 140 156"
              className="absolute inset-0 w-full h-full"
              style={{ filter: 'blur(12px)' }}
            >
              <path
                d="M70 6 L130 38 L130 118 L70 150 L10 118 L10 38 Z"
                fill="none"
                stroke={accent}
                strokeWidth="2"
                opacity="0.4"
              />
            </svg>

            {/* Dashed hex border */}
            <svg viewBox="0 0 140 156" className="absolute inset-0 w-full h-full">
              <path
                d="M70 6 L130 38 L130 118 L70 150 L10 118 L10 38 Z"
                fill={`${accent}06`}
                stroke={accent}
                strokeWidth="1.5"
                strokeDasharray="10 6"
                strokeLinejoin="round"
                opacity="0.6"
              />
            </svg>

            {/* Inner solid hex */}
            <svg viewBox="0 0 140 156" className="absolute inset-0 w-full h-full">
              <path
                d="M70 26 L112 48 L112 108 L70 130 L28 108 L28 48 Z"
                fill={`${accent}0A`}
                stroke={accent}
                strokeWidth="1"
                opacity="0.3"
              />
            </svg>

            {/* The clicked achievement's own glyph — the same per-badge icon
                the grid renders (keyed by label, star fallback), tinted with
                the tier accent. Previously a hardcoded trophy, so every
                trophy card looked identical regardless of the badge. */}
            <div className="absolute inset-0 flex items-center justify-center">
              <BadgeIcon
                title={achievement?.label ?? ''}
                color={accent}
                unlocked
                size={52}
              />
            </div>
          </div>

          {/* Micro label */}
          <p
            className="font-telemetry text-[10px] uppercase tracking-[0.18em] mb-3"
            style={{
              color: accent,
              opacity: phaseGte('text') ? 1 : 0,
              transform: phaseGte('text') ? 'translateY(0)' : 'translateY(8px)',
              transition: 'opacity 0.4s ease, transform 0.4s ease',
            }}
          >
            Achievement Unlocked
          </p>

          {/* Badge name */}
          <h2
            className="font-monument text-[26px] font-bold text-chalk uppercase tracking-tight mb-2 text-center"
            style={{
              opacity: phaseGte('text') ? 1 : 0,
              transform: phaseGte('text') ? 'translateY(0)' : 'translateY(8px)',
              transition: 'opacity 0.4s ease 0.1s, transform 0.4s ease 0.1s',
            }}
          >
            {achievement?.label}
          </h2>

          {/* Divider */}
          <div
            className="w-16 h-[1px] mb-4"
            style={{
              background: `linear-gradient(90deg, transparent, ${accent}80, transparent)`,
              transform: phaseGte('text') ? 'scaleX(1)' : 'scaleX(0)',
              transition: 'transform 0.5s ease 0.15s',
            }}
          />

          {/* Description */}
          <p
            className="font-body text-[13px] text-steel text-center max-w-[340px] leading-relaxed mb-8"
            style={{
              opacity: phaseGte('text') ? 1 : 0,
              transition: 'opacity 0.4s ease 0.2s',
            }}
          >
            {achievement?.description}
          </p>

          {/* Tier indicator */}
          <div
            className="flex items-center gap-4 mb-8"
            style={{
              opacity: phaseGte('done') ? 1 : 0,
              transition: 'opacity 0.4s ease',
            }}
          >
            <div className="h-[1px] w-8" style={{ backgroundColor: `${accent}30` }} />
            <div className="flex items-center gap-2.5">
              {TIER_ORDER.map((t) => (
                <div key={t} className="flex flex-col items-center gap-1.5">
                  <div
                    className="w-2 h-2 rounded-full transition-all"
                    style={{
                      backgroundColor: tierColors[t],
                      opacity: t === tier ? 1 : 0.2,
                      boxShadow: t === tier ? `0 0 10px ${tierColors[t]}60` : 'none',
                    }}
                  />
                  {t === tier && (
                    <span
                      className="font-telemetry text-[7px] uppercase tracking-[0.1em]"
                      style={{ color: accent }}
                    >
                      {tierLabels[t]}
                    </span>
                  )}
                </div>
              ))}
            </div>
            <div className="h-[1px] w-8" style={{ backgroundColor: `${accent}30` }} />
          </div>

          {/* Continue button */}
          <button
            type="button"
            onClick={dismiss}
            className="px-10 py-3 rounded-[14px] font-telemetry text-[10px] uppercase tracking-[0.15em] cursor-pointer transition-all hover:brightness-110"
            style={{
              color: '#000000',
              backgroundColor: accent,
              opacity: phaseGte('done') ? 1 : 0,
              transform: phaseGte('done') ? 'translateY(0)' : 'translateY(8px)',
              transition: 'opacity 0.4s ease, transform 0.4s ease, filter 0.2s ease',
            }}
          >
            Continue
          </button>
        </div>

        {/* Bottom accent bar */}
        <div className="h-[1px]" style={{ background: `linear-gradient(90deg, transparent, ${accent}30, transparent)` }} />
      </div>
    </div>
  );
}
