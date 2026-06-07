'use client';

const TIER_COLOR: Record<string, string> = {
  bronze: '#C9A84C', silver: '#949494', gold: '#FACC15',
};

/** Small star pip for a corner's mastery tier (null/none → hollow pip). */
export function MasteryStars({ tier, size = 12 }: { tier?: string | null; size?: number }) {
  const color = tier ? TIER_COLOR[tier] : undefined;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24"
      fill={color ?? 'none'} stroke={color ?? '#94949466'} strokeWidth="2"
      aria-label={tier ? `${tier} star` : 'no star'}>
      <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
    </svg>
  );
}
