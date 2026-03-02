'use client';

import { useEntitlements } from '@/hooks/useEntitlements';
import Link from 'next/link';

interface UpgradeBannerProps {
  /** Feature key to check (e.g., "comparison", "api_access"). */
  feature: string;
  /** Optional context string (e.g., "You've used 10/10 reports this month"). */
  context?: string;
  /** Display variant. */
  variant?: 'inline' | 'modal' | 'toast';
  /** Called when the banner is dismissed (modal/toast only). */
  onDismiss?: () => void;
}

/** Tier display names for user-facing text. */
const TIER_LABELS: Record<string, string> = {
  racer: 'Racer',
  'world-class': 'World-Class',
  b2b: 'Circuit',
};

/** Feature display names. */
const FEATURE_LABELS: Record<string, string> = {
  comparison: 'Session Comparison',
  api_access: 'API Access',
  coaching_plans: 'Coaching Plans',
  visualization: 'Visualization',
  live_monitoring: 'Live Monitoring',
  export_pdf: 'PDF Export',
  race_strategy_full: 'Full Race Strategy',
};

export function UpgradeBanner({
  feature,
  context,
  variant = 'inline',
  onDismiss,
}: UpgradeBannerProps) {
  const { requiresUpgrade, entitlements } = useEntitlements();

  const upgrade = requiresUpgrade(feature);
  if (!upgrade) return null;

  const tierLabel = TIER_LABELS[upgrade.tier] || upgrade.tier;
  const featureLabel = FEATURE_LABELS[feature] || feature;

  if (variant === 'inline') {
    return (
      <div className="rounded-lg border border-gold/30 bg-concrete/80 px-4 py-3 backdrop-blur-sm">
        <div className="flex items-center justify-between gap-4">
          <div className="min-w-0">
            <p className="text-sm font-medium text-chalk">
              {featureLabel} requires {tierLabel}
            </p>
            {context && (
              <p className="mt-0.5 text-xs text-steel">{context}</p>
            )}
            {entitlements && (
              <p className="mt-0.5 text-xs text-steel">
                Current plan: {entitlements.planTier}
              </p>
            )}
          </div>
          <Link
            href={upgrade.url}
            className="shrink-0 rounded-md bg-gold px-4 py-2 text-xs font-semibold text-asphalt transition-colors hover:bg-gold/90"
          >
            Upgrade
          </Link>
        </div>
      </div>
    );
  }

  if (variant === 'modal') {
    return (
      <div className="fixed inset-0 z-overlay flex items-center justify-center bg-asphalt/80 backdrop-blur-sm">
        <div className="mx-4 w-full max-w-md border border-chalk/15 bg-concrete p-6 shadow-xl">
          <h3 className="font-monument text-xl text-chalk">
            Upgrade to {tierLabel}
          </h3>
          <p className="mt-2 text-sm text-steel">
            {featureLabel} is available on the {tierLabel} plan and above.
          </p>
          {context && (
            <p className="mt-1 text-xs text-steel">{context}</p>
          )}
          <div className="mt-6 flex gap-3">
            <Link
              href={upgrade.url}
              className="flex-1 bg-gold px-4 py-2.5 text-center text-sm font-semibold text-asphalt transition-colors hover:bg-gold/90"
            >
              View Plans
            </Link>
            {onDismiss && (
              <button
                onClick={onDismiss}
                className="border border-chalk/20 px-4 py-2.5 text-sm text-steel transition-colors hover:border-chalk/40 hover:text-chalk"
              >
                Not Now
              </button>
            )}
          </div>
        </div>
      </div>
    );
  }

  // Toast variant
  return (
    <div className="fixed bottom-4 right-4 z-overlay max-w-sm animate-slide-up border border-gold/30 bg-concrete p-4 shadow-lg">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-chalk">
            {featureLabel} requires {tierLabel}
          </p>
          {context && (
            <p className="mt-0.5 text-xs text-steel">{context}</p>
          )}
        </div>
        <div className="flex shrink-0 gap-2">
          <Link
            href={upgrade.url}
            className="bg-gold px-3 py-1.5 text-xs font-semibold text-asphalt"
          >
            Upgrade
          </Link>
          {onDismiss && (
            <button
              onClick={onDismiss}
              className="text-xs text-steel hover:text-chalk"
              aria-label="Dismiss"
            >
              &times;
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
