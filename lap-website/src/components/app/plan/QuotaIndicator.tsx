/**
 * QuotaIndicator — inline usage bar showing remaining analyses.
 *
 * Renders a thin bar + text: "3 of 10 analyses used" or "Unlimited".
 * Turns marshal-yellow at 80% used, safety-red at 100%.
 * Shows nothing while loading (avoid layout shift).
 *
 * Usage:
 *   <QuotaIndicator />                    // analyses quota
 *   <QuotaIndicator compact />            // smaller (for upload page header)
 */

'use client';

import { useUserPlan } from '@/hooks/useUserPlan';

interface QuotaIndicatorProps {
  compact?: boolean;
  className?: string;
}

export function QuotaIndicator({ compact = false, className = '' }: QuotaIndicatorProps) {
  const { plan, isLoading, isUnlimited, analysesUsed, analysesLimit, tier } = useUserPlan();

  if (isLoading || !plan) return null;

  if (isUnlimited || analysesLimit === null) {
    return (
      <div className={`flex items-center gap-2 font-telemetry ${className}`}>
        <span className={`text-acid-green ${compact ? 'text-[10px]' : 'text-xs'}`}>
          Unlimited analyses
        </span>
        <span className={`text-steel/50 ${compact ? 'text-[9px]' : 'text-[10px]'} uppercase tracking-wider`}>
          {tier}
        </span>
      </div>
    );
  }

  const pct = analysesLimit > 0 ? (analysesUsed / analysesLimit) * 100 : 0;
  const remaining = Math.max(0, analysesLimit - analysesUsed);
  const atLimit = remaining === 0;
  const nearLimit = pct >= 80 && !atLimit;

  const barColor = atLimit
    ? 'bg-safety-red'
    : nearLimit
      ? 'bg-marshal-yellow'
      : 'bg-acid-green';

  const textColor = atLimit
    ? 'text-safety-red'
    : nearLimit
      ? 'text-marshal-yellow'
      : 'text-chalk';

  return (
    <div className={`font-telemetry ${className}`}>
      <div className="flex items-center justify-between gap-3 mb-1">
        <span className={`${textColor} ${compact ? 'text-[10px]' : 'text-xs'}`}>
          {atLimit
            ? 'Quota reached'
            : `${remaining} of ${analysesLimit} analyses remaining`}
        </span>
        <span className={`text-steel/50 ${compact ? 'text-[9px]' : 'text-[10px]'} uppercase tracking-wider`}>
          {tier}
        </span>
      </div>
      <div className={`w-full bg-steel/10 rounded-full overflow-hidden ${compact ? 'h-1' : 'h-1.5'}`}>
        <div
          className={`h-full ${barColor} rounded-full transition-all duration-300`}
          style={{ width: `${Math.min(100, pct)}%` }}
        />
      </div>
      {atLimit && (
        <a
          href="/pricing"
          className="inline-block mt-1.5 text-[10px] text-gold hover:text-chalk underline underline-offset-2 transition-colors"
        >
          Upgrade to continue analysing
        </a>
      )}
    </div>
  );
}
