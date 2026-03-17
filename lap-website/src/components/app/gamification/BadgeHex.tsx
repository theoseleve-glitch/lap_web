'use client';

import { useMemo } from 'react';

export type BadgeIcon = 'helmet' | 'trophy' | 'stopwatch' | 'wheel' | 'shield' | 'lock';
export type BadgeTier = 'gold' | 'silver' | 'bronze' | 'locked';

interface BadgeHexProps {
  icon: BadgeIcon;
  tier: BadgeTier;
  size?: number;
  glow?: boolean;
  animate?: boolean;
  className?: string;
}

const TIER_GRADIENTS: Record<BadgeTier, [string, string]> = {
  gold: ['#FFD700', '#FFA500'],
  silver: ['#E8E8E8', '#A0A0A0'],
  bronze: ['#CD7F32', '#8B4513'],
  locked: ['#333333', '#222222'],
};

const TIER_GLOW_COLORS: Record<BadgeTier, string> = {
  gold: '#FFD700',
  silver: '#C0C0C0',
  bronze: '#CD7F32',
  locked: '#333333',
};

const HEX_POINTS = '40,2 74,21 74,59 40,78 6,59 6,21';
const HEX_PERIMETER = 175.2;

function HelmetIcon() {
  return (
    <g transform="translate(24, 22) scale(0.4)">
      <path
        d="M40 8C22 8 8 22 8 40c0 10 4 18 10 24h8l4-10c0 0 10-4 20-4s20 4 20 4l4 10h8c6-6 10-14 10-24C82 22 68 8 50 8z"
        fill="currentColor"
        opacity={0.9}
      />
      <path
        d="M20 50c0 0 15-6 30-6s30 6 30 6"
        fill="none"
        stroke="currentColor"
        strokeWidth="3"
        opacity={0.5}
      />
      <ellipse cx="28" cy="38" rx="8" ry="6" fill="currentColor" opacity={0.4} />
    </g>
  );
}

function TrophyIcon() {
  return (
    <g transform="translate(26, 20) scale(0.36)">
      <path
        d="M20 10h40v30c0 14-10 24-20 24S20 54 20 40V10z"
        fill="currentColor"
        opacity={0.9}
      />
      <path
        d="M20 18H8c0 14 6 22 12 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="4"
        strokeLinecap="round"
      />
      <path
        d="M60 18h12c0 14-6 22-12 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="4"
        strokeLinecap="round"
      />
      <polygon
        points="40,22 43,31 52,31 45,37 47,46 40,41 33,46 35,37 28,31 37,31"
        fill="currentColor"
        opacity={0.4}
      />
      <rect x="32" y="64" width="16" height="4" rx="2" fill="currentColor" opacity={0.7} />
      <rect x="26" y="68" width="28" height="5" rx="2" fill="currentColor" opacity={0.7} />
    </g>
  );
}

function StopwatchIcon() {
  return (
    <g transform="translate(25, 20) scale(0.38)">
      <circle
        cx="40"
        cy="46"
        r="28"
        fill="currentColor"
        opacity={0.9}
      />
      <circle
        cx="40"
        cy="46"
        r="22"
        fill="currentColor"
        opacity={0.3}
      />
      <line
        x1="40" y1="46" x2="40" y2="30"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
        opacity={0.5}
      />
      <line
        x1="40" y1="46" x2="52" y2="46"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        opacity={0.5}
      />
      <rect x="36" y="8" width="8" height="10" rx="2" fill="currentColor" opacity={0.8} />
      <line
        x1="56" y1="20" x2="62" y2="14"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
        opacity={0.7}
      />
    </g>
  );
}

function WheelIcon() {
  return (
    <g transform="translate(24, 22) scale(0.4)">
      <circle cx="40" cy="40" r="30" fill="none" stroke="currentColor" strokeWidth="6" opacity={0.9} />
      <circle cx="40" cy="40" r="8" fill="currentColor" opacity={0.8} />
      <line x1="40" y1="12" x2="40" y2="32" stroke="currentColor" strokeWidth="5" strokeLinecap="round" opacity={0.7} />
      <line x1="15.8" y1="54" x2="33" y2="44" stroke="currentColor" strokeWidth="5" strokeLinecap="round" opacity={0.7} />
      <line x1="64.2" y1="54" x2="47" y2="44" stroke="currentColor" strokeWidth="5" strokeLinecap="round" opacity={0.7} />
    </g>
  );
}

function ShieldIcon() {
  return (
    <g transform="translate(24, 18) scale(0.4)">
      <path
        d="M40 6L10 20v24c0 20 14 32 30 38 16-6 30-18 30-38V20L40 6z"
        fill="currentColor"
        opacity={0.9}
      />
      <path d="M30 30h10v10H30z" fill="currentColor" opacity={0.35} />
      <path d="M40 30h10v10H40z" fill="currentColor" opacity={0.55} />
      <path d="M30 40h10v10H30z" fill="currentColor" opacity={0.55} />
      <path d="M40 40h10v10H40z" fill="currentColor" opacity={0.35} />
      <path d="M20 20h10v10H20z" fill="currentColor" opacity={0.35} />
      <path d="M50 20h10v10H50z" fill="currentColor" opacity={0.35} />
      <path d="M20 50h10v10H20z" fill="currentColor" opacity={0.55} />
      <path d="M50 50h10v10H50z" fill="currentColor" opacity={0.55} />
    </g>
  );
}

function LockIcon() {
  return (
    <g transform="translate(26, 20) scale(0.37)">
      <rect x="18" y="40" width="44" height="34" rx="4" fill="currentColor" opacity={0.9} />
      <path
        d="M26 40V28c0-8 6-14 14-14s14 6 14 14v12"
        fill="none"
        stroke="currentColor"
        strokeWidth="5"
        strokeLinecap="round"
        opacity={0.7}
      />
      <circle cx="40" cy="54" r="4" fill="currentColor" opacity={0.4} />
      <rect x="38" y="56" width="4" height="8" rx="2" fill="currentColor" opacity={0.4} />
    </g>
  );
}

const ICON_COMPONENTS: Record<BadgeIcon, React.FC> = {
  helmet: HelmetIcon,
  trophy: TrophyIcon,
  stopwatch: StopwatchIcon,
  wheel: WheelIcon,
  shield: ShieldIcon,
  lock: LockIcon,
};

export function BadgeHex({
  icon,
  tier,
  size = 64,
  glow = false,
  animate = false,
  className = '',
}: BadgeHexProps) {
  const gradId = useMemo(() => `hex-grad-${tier}-${Math.random().toString(36).slice(2, 8)}`, [tier]);
  const filterId = useMemo(() => `hex-glow-${Math.random().toString(36).slice(2, 8)}`, []);
  const [colorStart, colorEnd] = TIER_GRADIENTS[tier];
  const glowColor = TIER_GLOW_COLORS[tier];
  const showGlow = glow && tier !== 'locked';
  const resolvedIcon = tier === 'locked' ? 'lock' : icon;
  const IconComponent = ICON_COMPONENTS[resolvedIcon];

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 80 80"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      role="img"
      aria-label={`${tier} ${icon} badge`}
    >
      <defs>
        <linearGradient id={gradId} x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor={colorStart} />
          <stop offset="100%" stopColor={colorEnd} />
        </linearGradient>
        {showGlow && (
          <filter id={filterId} x="-40%" y="-40%" width="180%" height="180%">
            <feGaussianBlur in="SourceGraphic" stdDeviation="3" />
          </filter>
        )}
      </defs>

      {/* Glow layer */}
      {showGlow && (
        <polygon
          points={HEX_POINTS}
          fill="none"
          stroke={glowColor}
          strokeWidth="4"
          filter={`url(#${filterId})`}
          opacity={0.6}
        />
      )}

      {/* Hex fill */}
      <polygon
        points={HEX_POINTS}
        fill={`url(#${gradId})`}
        opacity={0.15}
      />

      {/* Hex stroke */}
      <polygon
        points={HEX_POINTS}
        fill="none"
        stroke={`url(#${gradId})`}
        strokeWidth="2.5"
        strokeLinejoin="round"
        {...(animate ? {
          strokeDasharray: HEX_PERIMETER,
          strokeDashoffset: HEX_PERIMETER,
          style: {
            animation: 'hexDraw 1.2s ease-out forwards',
          },
        } : {})}
      />

      {/* Icon */}
      <g color={tier === 'locked' ? '#555' : colorStart}>
        <IconComponent />
      </g>

      {animate && (
        <style>{`
          @keyframes hexDraw {
            to {
              stroke-dashoffset: 0;
            }
          }
        `}</style>
      )}
    </svg>
  );
}
