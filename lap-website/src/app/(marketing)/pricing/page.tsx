'use client';

import { useEffect, useState } from 'react';
import { PageShell } from '@/components/site/PageShell';
import { PricingTable } from '@/components/ui/PricingTable';
import { StatusPill } from '@/components/site/StatusPill';
import {
  addons,
  b2bPlans,
  b2cPlans,
  featureEligibilityMatrix,
} from '@/data/pricing';
import { claimsByStatus } from '@/data/claim-registry';
import { trackCtaClick, trackPricingToggle } from '@/lib/analytics';
import { getVariantForKey } from '@/lib/experiments';

export default function PricingPage() {
  const [audience, setAudience] = useState<'b2c' | 'b2b'>('b2c');
  const [billing, setBilling] = useState<'monthly' | 'annual'>('annual');
  const [pricingVariant, setPricingVariant] = useState<'standard_table' | 'comparison_first'>(
    'standard_table',
  );

  useEffect(() => {
    const variant = getVariantForKey('pricing', 'standard_table');
    setPricingVariant(variant === 'comparison_first' ? 'comparison_first' : 'standard_table');
  }, []);

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify({
            '@context': 'https://schema.org',
            '@type': 'WebPage',
            name: 'LAP Pricing',
            url: 'https://www.lap-coach.racing/pricing',
          }),
        }}
      />
      <PageShell
        eyebrow="Pricing"
        title="Plans for Drivers, Coaches, and Circuits"
        description="Self-serve plans for individual drivers. Contact us for team, circuit, and enterprise setups."
      >
      <section className="mb-8 flex flex-wrap items-center gap-3">
        <button
          className={`px-4 py-2 border font-telemetry text-[11px] tracking-[0.12em] uppercase ${
            audience === 'b2c' ? 'border-pit-orange text-chalk' : 'border-steel/30 text-steel'
          }`}
          onClick={() => setAudience('b2c')}
        >
          Drivers
        </button>
        <button
          className={`px-4 py-2 border font-telemetry text-[11px] tracking-[0.12em] uppercase ${
            audience === 'b2b' ? 'border-pit-orange text-chalk' : 'border-steel/30 text-steel'
          }`}
          onClick={() => setAudience('b2b')}
        >
          Circuits / Teams
        </button>
        {audience === 'b2c' && (
          <button
            className="px-4 py-2 border border-steel/30 text-steel font-telemetry text-[11px] tracking-[0.12em] uppercase"
            onClick={() => {
              const next = billing === 'monthly' ? 'annual' : 'monthly';
              setBilling(next);
              trackPricingToggle(next);
            }}
          >
            Billing: {billing}
          </button>
        )}
      </section>

      {pricingVariant === 'standard_table' && (
        <section className="mb-10">
          <PricingTable
            plans={audience === 'b2c' ? b2cPlans : b2bPlans}
            billingPeriod={billing}
            onCtaClick={(planName) => trackCtaClick(planName, 'pricing', audience)}
          />
        </section>
      )}

      <section className="mb-10">
        <h2 className="font-monument text-[var(--text-h2)] mb-4">Add-ons and Availability</h2>
        <div className="grid md:grid-cols-2 gap-3">
          {addons.map((addon) => (
            <article key={addon.name} className="border border-steel/20 bg-concrete/40 p-4">
              <div className="flex items-start justify-between gap-2 mb-2">
                <h3 className="font-body text-chalk">{addon.name}</h3>
                <StatusPill status={addon.status} />
              </div>
              <p className="text-steel text-sm">{addon.price}</p>
              {addon.note && <p className="text-pit-orange text-xs mt-2">{addon.note}</p>}
            </article>
          ))}
        </div>
      </section>

      <section className="mb-10 overflow-x-auto">
        <h2 className="font-monument text-[var(--text-h2)] mb-4">Feature Eligibility Matrix</h2>
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="bg-concrete">
              <th className="border border-steel/20 p-2 text-left">Feature</th>
              <th className="border border-steel/20 p-2 text-left">Starter</th>
              <th className="border border-steel/20 p-2 text-left">Performance</th>
              <th className="border border-steel/20 p-2 text-left">Pro Racer</th>
              <th className="border border-steel/20 p-2 text-left">Circuit Pro</th>
              <th className="border border-steel/20 p-2 text-left">Enterprise</th>
            </tr>
          </thead>
          <tbody>
            {featureEligibilityMatrix.map((row) => (
              <tr key={row.feature}>
                <td className="border border-steel/20 p-2">{row.feature}</td>
                <td className="border border-steel/20 p-2">{row.starter}</td>
                <td className="border border-steel/20 p-2">{row.performance}</td>
                <td className="border border-steel/20 p-2">{row.proRacer}</td>
                <td className="border border-steel/20 p-2">{row.circuitPro}</td>
                <td className="border border-steel/20 p-2">{row.enterprise}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {pricingVariant === 'comparison_first' && (
        <section className="mb-10">
          <PricingTable
            plans={audience === 'b2c' ? b2cPlans : b2bPlans}
            billingPeriod={billing}
            onCtaClick={(planName) => trackCtaClick(planName, 'pricing', audience)}
          />
        </section>
      )}

        <section className="grid md:grid-cols-3 gap-4">
          <article className="border border-steel/20 p-4">
            <h2 className="font-monument text-[var(--text-h3)] mb-3">Available Now</h2>
            <ul className="space-y-2 text-sm text-steel">
              {claimsByStatus.available_now.map((claim) => (
                <li key={claim.id}>{claim.claim}</li>
              ))}
            </ul>
          </article>
          <article className="border border-steel/20 p-4">
            <h2 className="font-monument text-[var(--text-h3)] mb-3">Enterprise / On Request</h2>
            <ul className="space-y-2 text-sm text-steel">
              {claimsByStatus.enterprise_on_request.map((claim) => (
                <li key={claim.id}>{claim.claim}</li>
              ))}
            </ul>
          </article>
          <article className="border border-steel/20 p-4">
            <h2 className="font-monument text-[var(--text-h3)] mb-3">Roadmap / Coming Soon</h2>
            <ul className="space-y-2 text-sm text-steel">
              {claimsByStatus.roadmap.map((claim) => (
                <li key={claim.id}>{claim.claim}</li>
              ))}
            </ul>
          </article>
        </section>
      </PageShell>
    </>
  );
}
