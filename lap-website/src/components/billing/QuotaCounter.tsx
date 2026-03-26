'use client';

import { useEntitlements } from '@/hooks/useEntitlements';

interface QuotaCounterProps {
  /** Meter key (e.g., "reports"). */
  meterKey: string;
  /** Optional CSS class. */
  className?: string;
}

/**
 * Displays "X/Y remaining" badge for quota-limited features.
 * Shows nothing if quota is unlimited or entitlements not loaded.
 */
export function QuotaCounter({ meterKey, className = '' }: QuotaCounterProps) {
  const { entitlements } = useEntitlements();

  if (!entitlements) return null;

  let remaining: number | null = null;
  let limit: number | null = null;

  if (meterKey === 'analyses') {
    remaining = entitlements.analysesRemaining;
    limit = entitlements.analysesPerMonth;
  }

  // Unlimited plans don't show a counter
  if (remaining === null || limit === null) return null;

  const isLow = remaining <= Math.ceil(limit * 0.2); // <= 20% remaining
  const isZero = remaining === 0;

  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-telemetry ${
        isZero
          ? 'bg-safety-red/20 text-safety-red'
          : isLow
            ? 'bg-marshal-yellow/20 text-marshal-yellow'
            : 'bg-steel/20 text-steel'
      } ${className}`}
    >
      {remaining}/{limit}
    </span>
  );
}
