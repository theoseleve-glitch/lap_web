/**
 * FeatureGate — contextual locked-feature wrapper.
 *
 * Renders children when the user's plan includes the feature.
 * When locked, shows a premium inline message with the feature name,
 * the unlocking plan, and a one-click upgrade link — no generic 403,
 * no hidden empty space.
 *
 * Usage:
 *   <FeatureGate feature="comparison" plan="racer" label="Lap comparison">
 *     <ComparisonChart ... />
 *   </FeatureGate>
 */

'use client';

import type { ReactNode } from 'react';
import { useUserPlan } from '@/hooks/useUserPlan';

interface FeatureGateProps {
  /** Feature key as defined in entitlements (e.g. "comparison", "coaching_plans"). */
  feature: string;
  /** Which plan unlocks this feature (shown in the upgrade prompt). */
  plan?: string;
  /** Human-readable label for the feature (e.g. "Cross-session comparison"). */
  label?: string;
  children: ReactNode;
  /** Optional: render a custom locked state instead of the default. */
  lockedFallback?: ReactNode;
}

export function FeatureGate({
  feature,
  plan = 'Racer',
  label,
  children,
  lockedFallback,
}: FeatureGateProps) {
  const { hasFeature, isLoading } = useUserPlan();

  // While loading, show children (optimistic) to avoid layout flicker.
  // If the feature is actually locked, the backend will 403 the API call.
  if (isLoading) return <>{children}</>;

  if (hasFeature(feature)) return <>{children}</>;

  // Locked state
  if (lockedFallback) return <>{lockedFallback}</>;

  return (
    <div className="flex flex-col items-center justify-center py-8 px-6 text-center">
      <div className="w-8 h-8 rounded-full border border-steel/20 flex items-center justify-center mb-3">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-steel/50">
          <rect x="3" y="7" width="10" height="7" rx="1.5" />
          <path d="M5 7V5a3 3 0 0 1 6 0v2" />
        </svg>
      </div>
      <p className="text-xs font-monument text-chalk mb-1">
        {label ?? feature.replace(/_/g, ' ')}
      </p>
      <p className="text-[11px] font-telemetry text-steel mb-3 max-w-xs">
        Available on the {plan} plan and above.
      </p>
      <a
        href="/pricing"
        className="inline-flex items-center gap-1.5 px-3 py-1.5 text-[10px] font-telemetry uppercase tracking-[0.15em] text-gold border border-gold/30 rounded-lg hover:bg-gold/10 transition-colors"
      >
        Upgrade to {plan}
      </a>
    </div>
  );
}
