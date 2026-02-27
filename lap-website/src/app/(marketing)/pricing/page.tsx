'use client';

import { useState, useCallback } from 'react';
import { PageShell } from '@/components/site/PageShell';
import { PricingTable } from '@/components/ui/PricingTable';
import { StampButton } from '@/components/ui/StampButton';
import {
  b2cPlans,
  b2bCard,
  featureEligibilityMatrix,
  dataLifecycle,
} from '@/data/pricing';
import type { EligibilityRow } from '@/data/pricing';
import { trackCtaClick, trackPricingToggle } from '@/lib/analytics';

const GROUP_LABELS: Record<EligibilityRow['group'], string> = {
  engineer: 'ENGINEER',
  strategist: 'STRATEGIST',
  data: 'DATA & OPS',
};

const GROUP_ORDER: EligibilityRow['group'][] = ['engineer', 'strategist', 'data'];

export default function PricingPage() {
  const [billing, setBilling] = useState<'monthly' | 'annual'>('annual');

  const toggleBilling = useCallback(() => {
    const next = billing === 'monthly' ? 'annual' : 'monthly';
    setBilling(next);
    trackPricingToggle(next);
  }, [billing]);

  /* Group rows by their group field, preserving order */
  const groupedRows = GROUP_ORDER.map((group) => ({
    group,
    label: GROUP_LABELS[group],
    rows: featureEligibilityMatrix.filter((r) => r.group === group),
  }));

  /* JSON-LD structured data for SEO — hardcoded, no user input */
  const jsonLd = {
    '@context': 'https://schema.org',
    '@type': 'WebPage',
    name: 'LAP Pricing',
    url: 'https://www.lap-coach.racing/pricing',
  };

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />
      <PageShell
        eyebrow="Pricing"
        title="Choose Your Depth"
        description="Three tiers for individual drivers. Custom pricing for teams and circuits."
      >
        {/* Billing toggle */}
        <div className="flex items-center justify-center gap-3 mb-8">
          <span
            className={`font-telemetry text-[11px] ${
              billing === 'monthly' ? 'text-chalk' : 'text-steel'
            }`}
          >
            MONTHLY
          </span>
          <button
            className="relative w-12 h-6 bg-concrete border border-steel/30"
            onClick={toggleBilling}
            aria-label={`Switch to ${billing === 'monthly' ? 'annual' : 'monthly'} billing`}
          >
            <span
              className="absolute top-1 w-4 h-4 bg-pit-orange transition-all duration-300"
              style={{ left: billing === 'annual' ? 'calc(100% - 20px)' : '4px' }}
            />
          </button>
          <span
            className={`font-telemetry text-[11px] ${
              billing === 'annual' ? 'text-chalk' : 'text-steel'
            }`}
          >
            ANNUAL
          </span>
        </div>

        {/* Pricing Table + B2B card */}
        <section className="mb-10 grid grid-cols-1 lg:grid-cols-[3fr_1fr] gap-0">
          <PricingTable
            plans={b2cPlans}
            billingPeriod={billing}
            onCtaClick={(planName) => trackCtaClick(planName, 'pricing', 'b2c')}
          />

          {/* B2B card */}
          <div className="p-6 bg-concrete border border-steel/20 lg:border-l-0">
            <p className="font-telemetry text-[10px] tracking-[0.12em] text-steel uppercase mb-2">
              B2B
            </p>
            <h3 className="font-monument text-[var(--text-h3)] mb-4">{b2bCard.name}</h3>
            <ul className="space-y-2 mb-6">
              {b2bCard.features.map((feature) => (
                <li key={feature} className="flex items-start gap-2 font-body text-sm text-steel">
                  <span className="text-pit-orange mt-0.5 shrink-0">&bull;</span>
                  {feature}
                </li>
              ))}
            </ul>
            <StampButton
              href={b2bCard.ctaHref}
              onClick={() => trackCtaClick('contact_sales', 'pricing', 'b2b')}
              className="w-full"
            >
              {b2bCard.cta}
            </StampButton>
          </div>
        </section>

        {/* Feature Eligibility Matrix */}
        <section className="mb-10 overflow-x-auto">
          <h2 className="font-monument text-[var(--text-h2)] mb-4">Feature Eligibility Matrix</h2>
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="bg-concrete">
                <th className="border border-steel/20 p-2 text-left text-steel">Feature</th>
                <th className="border border-steel/20 p-2 text-left text-steel">Demo</th>
                <th className="border border-steel/20 p-2 text-left text-steel">Racer</th>
                <th className="border border-steel/20 p-2 text-left text-steel">World-Class</th>
              </tr>
            </thead>
            <tbody>
              {groupedRows.map(({ group, label, rows }) => (
                <>
                  <tr key={`group-${group}`}>
                    <td
                      colSpan={4}
                      className="bg-asphalt/60 font-monument text-xs tracking-[0.12em] uppercase p-2 text-chalk border border-steel/20"
                    >
                      {label}
                    </td>
                  </tr>
                  {rows.map((row) => (
                    <tr key={row.feature}>
                      <td className="border border-steel/20 p-2 text-steel">{row.feature}</td>
                      <td className="border border-steel/20 p-2 text-chalk">{row.demo}</td>
                      <td className="border border-steel/20 p-2 text-chalk">{row.racer}</td>
                      <td className="border border-steel/20 p-2 text-chalk">{row.worldClass}</td>
                    </tr>
                  ))}
                </>
              ))}
            </tbody>
          </table>
        </section>

        {/* Data Lifecycle Transparency */}
        <section className="mb-10">
          <h2 className="font-monument text-[var(--text-h2)] mb-4">
            Data Lifecycle Transparency
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {dataLifecycle.map((item) => (
              <article
                key={item.category}
                className="border border-steel/20 bg-concrete/40 p-5"
              >
                <h3 className="font-monument text-xs tracking-[0.12em] uppercase text-chalk mb-1">
                  {item.category}
                </h3>
                <p className="text-steel text-sm mb-4">{item.description}</p>
                <div className="space-y-2 mb-4">
                  {item.tiers.map((tier) => (
                    <div
                      key={tier.label}
                      className="flex justify-between text-sm font-body"
                    >
                      <span className="text-steel">{tier.label}</span>
                      <span className="text-chalk">{tier.value}</span>
                    </div>
                  ))}
                </div>
                <p className="text-steel/60 text-xs italic">{item.note}</p>
              </article>
            ))}
          </div>
        </section>
      </PageShell>
    </>
  );
}
