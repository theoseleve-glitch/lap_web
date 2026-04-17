'use client';

import { getSupportLevel } from '@/lib/bundle-vocabulary';

const COLOR_MAP: Record<string, string> = {
  'acid-green': 'bg-acid-green/10 text-acid-green border-acid-green/30',
  gold: 'bg-gold/10 text-gold border-gold/30',
  'marshal-yellow': 'bg-marshal-yellow/10 text-marshal-yellow border-marshal-yellow/30',
  'safety-red': 'bg-safety-red/10 text-safety-red border-safety-red/30',
};

interface Props {
  tier: string | null | undefined;
  size?: 'sm' | 'md';
}

export function SupportLevelBadge({ tier, size = 'sm' }: Props) {
  const level = getSupportLevel(tier);
  const colors = COLOR_MAP[level.color] ?? COLOR_MAP['safety-red'];
  const px = size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-3 py-1 text-sm';

  return (
    <span
      className={`inline-flex items-center rounded-full border font-telemetry ${colors} ${px}`}
      title={level.description}
    >
      {level.label}
    </span>
  );
}
