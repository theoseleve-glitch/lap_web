'use client';

import { useState } from 'react';
import Link from 'next/link';
import { PageHeader } from '@/components/app';
import { useEntitlements } from '@/hooks/useEntitlements';
import { b2cPlans, type BillingCycle } from '@/data/pricing';

/* ── Retention & feature loss warnings ─────────────────────── */

const RETENTION_DAYS: Record<string, number> = {
  demo: 30,
  racer: 90,
  'world-class': 365,
};

const FEATURES_BY_TIER: Record<string, string[]> = {
  demo: ['1 report/month', 'Basic analysis', '30-day retention', 'CSV exports'],
  racer: ['10 reports/month', 'Coaching Plans', 'Visualization', 'PDF exports', '90-day retention'],
  'world-class': ['Unlimited reports', 'Comparison & progress', 'API access', '365-day retention'],
};

function getFeatureLoss(from: string, to: string): string[] {
  const fromFeats = FEATURES_BY_TIER[from] || [];
  const toFeats = new Set(FEATURES_BY_TIER[to] || []);
  return fromFeats.filter((f) => !toFeats.has(f));
}

/* ── Page ─────────────────────────────────────────────────── */

export default function UpgradePage() {
  const { entitlements } = useEntitlements();
  const currentTier = entitlements?.planTier || 'demo';
  const [cycle, setCycle] = useState<BillingCycle>('annual');
  const [showDowngradeWarning, setShowDowngradeWarning] = useState<string | null>(null);

  const tierOrder = ['demo', 'racer', 'world-class'];
  const currentIdx = tierOrder.indexOf(currentTier);

  return (
    <div>
      <PageHeader title="Change Plan" subtitle="Compare plans and features" />

      {/* Billing cycle toggle */}
      <div className="flex items-center justify-center gap-3 mb-8">
        <button
          type="button"
          aria-pressed={cycle === 'monthly'}
          onClick={() => setCycle('monthly')}
          className={`px-4 py-1.5 rounded-full font-telemetry text-xs transition-colors ${
            cycle === 'monthly'
              ? 'bg-gold text-asphalt'
              : 'bg-concrete text-steel hover:text-chalk'
          }`}
        >
          Monthly
        </button>
        <button
          type="button"
          aria-pressed={cycle === 'annual'}
          onClick={() => setCycle('annual')}
          className={`px-4 py-1.5 rounded-full font-telemetry text-xs transition-colors ${
            cycle === 'annual'
              ? 'bg-gold text-asphalt'
              : 'bg-concrete text-steel hover:text-chalk'
          }`}
        >
          Annual
          <span className="ml-1 text-[10px] opacity-75">(Save up to 36%)</span>
        </button>
      </div>

      {/* Plan cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {b2cPlans.map((plan) => {
          const planIdx = tierOrder.indexOf(plan.slug);
          const isCurrent = plan.slug === currentTier;
          const isUpgrade = planIdx > currentIdx;
          const isDowngrade = planIdx < currentIdx;

          const price = cycle === 'annual' ? plan.priceAnnualPerMonth : plan.priceMonthly;
          const annualNote = cycle === 'annual' && plan.annualTotal ? plan.annualTotal : null;

          return (
            <div
              key={plan.slug}
              className={`bg-concrete rounded-lg border p-6 transition-colors ${
                isCurrent
                  ? 'border-acid-green/60 ring-1 ring-acid-green/20'
                  : plan.highlighted
                    ? 'border-racing-purple/40'
                    : 'border-steel/20'
              }`}
            >
              {/* Header */}
              <div className="mb-4">
                <div className="flex items-center gap-2">
                  <h2 className="font-monument text-lg text-chalk">{plan.name}</h2>
                  {isCurrent && (
                    <span className="bg-acid-green/20 text-acid-green text-[10px] font-telemetry px-2 py-0.5 rounded-full">
                      Current
                    </span>
                  )}
                </div>
                <div className="mt-2">
                  <span className="font-telemetry text-2xl text-chalk">{price}</span>
                  {annualNote && (
                    <span className="text-steel text-xs font-body ml-2">({annualNote})</span>
                  )}
                </div>
                {plan.savingsPercent && cycle === 'annual' && (
                  <span className="text-acid-green text-xs font-telemetry">
                    Save {plan.savingsPercent}%
                  </span>
                )}
              </div>

              {/* Features */}
              <ul className="space-y-1.5 mb-6">
                {Object.entries(plan.features).map(([feature, value]) => (
                  <li key={feature} className="flex items-start gap-2 text-xs">
                    <span className={`mt-0.5 ${value === '—' ? 'text-steel/60' : 'text-acid-green'}`}>
                      {value === '—' ? '✕' : '✓'}
                    </span>
                    <span className="text-steel font-body">
                      <span className="text-chalk">{feature}:</span> {value}
                    </span>
                  </li>
                ))}
              </ul>

              {/* CTA */}
              {isCurrent ? (
                <div className="text-center py-2 text-steel font-telemetry text-sm">
                  Your current plan
                </div>
              ) : isUpgrade ? (
                <Link
                  href={`/billing?plan=${plan.slug.toUpperCase()}&billing=${cycle}`}
                  className="block w-full text-center bg-gold text-asphalt font-telemetry text-sm py-2.5 rounded-md hover:brightness-110 transition"
                >
                  Upgrade to {plan.name}
                </Link>
              ) : isDowngrade ? (
                <>
                  <button
                    onClick={() => setShowDowngradeWarning(
                      showDowngradeWarning === plan.slug ? null : plan.slug,
                    )}
                    className="block w-full text-center bg-concrete border border-steel/30 text-steel font-telemetry text-sm py-2.5 rounded-md hover:border-marshal-yellow/40 transition"
                  >
                    Downgrade to {plan.name}
                  </button>
                  {showDowngradeWarning === plan.slug && (
                    <div className="mt-3 bg-asphalt rounded-md border border-marshal-yellow/30 p-3">
                      <p className="text-marshal-yellow font-telemetry text-xs mb-2">
                        You will lose:
                      </p>
                      <ul className="space-y-1 mb-3">
                        {getFeatureLoss(currentTier, plan.slug).map((feat) => (
                          <li key={feat} className="text-xs text-steel font-body flex items-center gap-1">
                            <span className="text-safety-red">✕</span> {feat}
                          </li>
                        ))}
                      </ul>
                      {RETENTION_DAYS[plan.slug] < (RETENTION_DAYS[currentTier] || 0) && (
                        <p className="text-safety-red text-xs font-telemetry mb-3">
                          Data retention drops from {RETENTION_DAYS[currentTier]} to {RETENTION_DAYS[plan.slug]} days.
                          Older sessions&apos; raw data will be deleted.
                        </p>
                      )}
                      <Link
                        href={`/billing?plan=${plan.slug.toUpperCase()}&billing=${cycle}`}
                        className="block w-full text-center bg-marshal-yellow/20 text-marshal-yellow font-telemetry text-xs py-2 rounded hover:bg-marshal-yellow/30 transition"
                      >
                        Confirm Downgrade
                      </Link>
                    </div>
                  )}
                </>
              ) : null}
            </div>
          );
        })}
      </div>

      <div className="mt-8 text-center">
        <Link href="/app/account/billing" className="text-steel hover:text-chalk text-sm font-body transition">
          ← Back to Billing
        </Link>
      </div>
    </div>
  );
}
