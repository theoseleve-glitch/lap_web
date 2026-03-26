'use client';

import { useEffect, useState, useCallback } from 'react';
import { BadgeHex } from './BadgeHex';
import { ParticleBurst } from './ParticleBurst';
import type { BadgeIcon, BadgeTier } from './BadgeHex';

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

const TIER_COLORS: Record<string, string> = {
  gold: '#FFD700',
  silver: '#C0C0C0',
  bronze: '#CD7F32',
  locked: '#949494',
};

const TIER_ORDER = ['bronze', 'silver', 'gold'] as const;

const VALID_ICONS = new Set<string>(['helmet', 'trophy', 'stopwatch', 'wheel', 'shield', 'lock']);
const VALID_TIERS = new Set<string>(['gold', 'silver', 'bronze', 'locked']);

function resolveIcon(icon: string): BadgeIcon {
  return VALID_ICONS.has(icon) ? (icon as BadgeIcon) : 'trophy';
}

function resolveTier(tier: string): BadgeTier {
  return VALID_TIERS.has(tier) ? (tier as BadgeTier) : 'bronze';
}

export function AchievementUnlockOverlay({
  achievement,
  onDismiss,
}: AchievementUnlockOverlayProps) {
  const [phase, setPhase] = useState<'hidden' | 'backdrop' | 'card' | 'badge' | 'text' | 'done'>('hidden');
  const [particles, setParticles] = useState(false);

  const dismiss = useCallback(() => {
    setPhase('hidden');
    setParticles(false);
    const timer = setTimeout(onDismiss, 300);
    return () => clearTimeout(timer);
  }, [onDismiss]);

  useEffect(() => {
    if (!achievement) {
      setPhase('hidden');
      setParticles(false);
      return;
    }

    setPhase('backdrop');

    const timers = [
      setTimeout(() => setParticles(true), 300),
      setTimeout(() => setPhase('card'), 300),
      setTimeout(() => setPhase('badge'), 500),
      setTimeout(() => setPhase('text'), 800),
      setTimeout(() => setPhase('done'), 1500),
    ];

    return () => timers.forEach(clearTimeout);
  }, [achievement]);

  if (!achievement && phase === 'hidden') return null;

  const tier = resolveTier(achievement?.tier ?? 'bronze');
  const icon = resolveIcon(achievement?.icon ?? 'trophy');
  const tierColor = TIER_COLORS[tier] ?? TIER_COLORS.bronze;
  const tierIndex = TIER_ORDER.indexOf(tier as typeof TIER_ORDER[number]);

  const phaseGte = (target: typeof phase): boolean => {
    const order = ['hidden', 'backdrop', 'card', 'badge', 'text', 'done'];
    return order.indexOf(phase) >= order.indexOf(target);
  };

  return (
    <>
      <ParticleBurst active={particles} color={tierColor} count={30} />

      {/* Backdrop */}
      <div
        onClick={dismiss}
        style={{
          position: 'fixed',
          inset: 0,
          zIndex: 100,
          backgroundColor: 'rgba(0, 0, 0, 0.88)',
          opacity: phaseGte('backdrop') ? 1 : 0,
          transition: 'opacity 0.3s ease',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          cursor: 'pointer',
        }}
        role="dialog"
        aria-modal="true"
        aria-label="Achievement unlocked"
      >
        {/* Card */}
        <div
          onClick={(e) => e.stopPropagation()}
          style={{
            maxWidth: '28rem',
            width: '90%',
            borderRadius: '1rem',
            padding: '2.5rem 2rem 2rem',
            background: 'linear-gradient(135deg, #141414 0%, #000000 100%)',
            border: `1px solid ${tierColor}33`,
            textAlign: 'center',
            cursor: 'default',
            transform: phaseGte('card') ? 'scale(1)' : 'scale(0)',
            opacity: phaseGte('card') ? 1 : 0,
            transition: 'transform 0.5s cubic-bezier(0.34, 1.56, 0.64, 1), opacity 0.3s ease',
          }}
        >
          {/* Badge */}
          <div
            style={{
              display: 'flex',
              justifyContent: 'center',
              marginBottom: '1.5rem',
              transform: phaseGte('badge') ? 'scale(1)' : 'scale(0)',
              transition: 'transform 0.5s cubic-bezier(0.34, 1.56, 0.64, 1)',
            }}
          >
            <BadgeHex
              icon={icon}
              tier={tier}
              size={120}
              glow={true}
              animate={true}
            />
          </div>

          {/* "ACHIEVEMENT UNLOCKED" label */}
          <p
            style={{
              fontFamily: '"Space Mono", "Fira Code", monospace',
              fontSize: '0.7rem',
              fontWeight: 700,
              textTransform: 'uppercase',
              letterSpacing: '0.2em',
              color: tierColor,
              marginBottom: '0.5rem',
              opacity: phaseGte('text') ? 1 : 0,
              transform: phaseGte('text') ? 'translateY(0)' : 'translateY(10px)',
              transition: 'opacity 0.4s ease, transform 0.4s ease',
              transitionDelay: '0s',
            }}
          >
            ACHIEVEMENT UNLOCKED
          </p>

          {/* Title */}
          <h2
            style={{
              fontSize: '1.5rem',
              fontWeight: 900,
              color: '#F0EDE5',
              marginBottom: '0.5rem',
              margin: '0 0 0.5rem 0',
              opacity: phaseGte('text') ? 1 : 0,
              transform: phaseGte('text') ? 'translateY(0)' : 'translateY(10px)',
              transition: 'opacity 0.4s ease 0.1s, transform 0.4s ease 0.1s',
            }}
          >
            {achievement?.label}
          </h2>

          {/* Description */}
          <p
            style={{
              fontFamily: '"Space Mono", "Fira Code", monospace',
              fontSize: '0.85rem',
              color: '#949494',
              marginBottom: '1.25rem',
              lineHeight: 1.5,
              opacity: phaseGte('text') ? 1 : 0,
              transform: phaseGte('text') ? 'translateY(0)' : 'translateY(10px)',
              transition: 'opacity 0.4s ease 0.2s, transform 0.4s ease 0.2s',
            }}
          >
            {achievement?.description}
          </p>

          {/* Tier dots */}
          <div
            style={{
              display: 'flex',
              justifyContent: 'center',
              gap: '0.5rem',
              marginBottom: '1.5rem',
              opacity: phaseGte('done') ? 1 : 0,
              transition: 'opacity 0.4s ease',
            }}
          >
            {TIER_ORDER.map((t, i) => (
              <div
                key={t}
                style={{
                  width: 10,
                  height: 10,
                  borderRadius: '50%',
                  backgroundColor: i <= tierIndex ? TIER_COLORS[t] : 'rgba(148, 148, 148, 0.25)',
                  boxShadow: i <= tierIndex ? `0 0 6px ${TIER_COLORS[t]}80` : 'none',
                  transition: 'background-color 0.3s ease, box-shadow 0.3s ease',
                }}
                title={t}
              />
            ))}
          </div>

          {/* Continue button */}
          <button
            type="button"
            onClick={dismiss}
            style={{
              padding: '0.6rem 2rem',
              borderRadius: '0.5rem',
              border: `1px solid ${tierColor}66`,
              backgroundColor: 'transparent',
              color: tierColor,
              fontFamily: '"Space Mono", "Fira Code", monospace',
              fontSize: '0.85rem',
              fontWeight: 600,
              textTransform: 'uppercase',
              letterSpacing: '0.1em',
              cursor: 'pointer',
              opacity: phaseGte('done') ? 1 : 0,
              transform: phaseGte('done') ? 'translateY(0)' : 'translateY(10px)',
              transition: 'opacity 0.4s ease, transform 0.4s ease, background-color 0.2s ease',
            }}
            onMouseEnter={(e) => {
              (e.target as HTMLButtonElement).style.backgroundColor = `${tierColor}1a`;
            }}
            onMouseLeave={(e) => {
              (e.target as HTMLButtonElement).style.backgroundColor = 'transparent';
            }}
          >
            Continue
          </button>
        </div>
      </div>
    </>
  );
}
