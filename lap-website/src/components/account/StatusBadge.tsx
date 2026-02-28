'use client';

type BadgeVariant = 'success' | 'warning' | 'error' | 'info' | 'neutral';

const variantClasses: Record<BadgeVariant, string> = {
  success: 'bg-acid-green/20 text-acid-green',
  warning: 'bg-marshal-yellow/20 text-marshal-yellow',
  error: 'bg-safety-red/20 text-safety-red',
  info: 'bg-racing-purple/20 text-racing-purple',
  neutral: 'bg-steel/20 text-steel',
};

const tierVariants: Record<string, BadgeVariant> = {
  demo: 'neutral',
  racer: 'success',
  'world-class': 'info',
  b2b: 'info',
};

const statusVariants: Record<string, BadgeVariant> = {
  active: 'success',
  trialing: 'success',
  past_due: 'warning',
  canceled: 'error',
  free: 'neutral',
};

interface StatusBadgeProps {
  label: string;
  variant?: BadgeVariant;
  /** Auto-detect variant from plan tier slug. */
  tier?: string;
  /** Auto-detect variant from subscription status. */
  status?: string;
}

export function StatusBadge({ label, variant, tier, status }: StatusBadgeProps) {
  const resolvedVariant =
    variant ??
    (tier ? tierVariants[tier] : undefined) ??
    (status ? statusVariants[status] : undefined) ??
    'neutral';

  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-telemetry uppercase tracking-wide ${variantClasses[resolvedVariant]}`}
    >
      {label}
    </span>
  );
}
