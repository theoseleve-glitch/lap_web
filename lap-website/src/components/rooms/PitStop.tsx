'use client';

import { useState, useCallback } from 'react';
import { MonumentText } from '@/components/ui/MonumentText';
import { ScrutineeringStamp } from '@/components/ui/ScrutineeringStamp';
import { PricingTable } from '@/components/ui/PricingTable';
import { FaqAccordion } from '@/components/ui/FaqAccordion';
import { PitButton } from '@/components/ui/PitButton';
import { StampButton } from '@/components/ui/StampButton';
import { b2cPlans, b2bPlans, addons } from '@/data/pricing';
import { faqItems } from '@/data/faq';
import { pitStop } from '@/data/copy';
import { getClaimsForSurface } from '@/data/claim-registry';
import {
  trackPricingToggle,
  trackAddonExpand,
  trackFaqExpand,
  trackCtaClick,
} from '@/lib/analytics';
import { StatusPill } from '@/components/site/StatusPill';

export function PitStop() {
  const [billingPeriod, setBillingPeriod] = useState<'monthly' | 'annual'>('annual');
  const [audience, setAudience] = useState<'b2c' | 'b2b'>('b2c');
  const [addonsOpen, setAddonsOpen] = useState(false);
  const homeClaims = getClaimsForSurface('home');

  const toggleBilling = useCallback(() => {
    const next = billingPeriod === 'monthly' ? 'annual' : 'monthly';
    setBillingPeriod(next);
    trackPricingToggle(next);
  }, [billingPeriod]);

  return (
    <section
      id="pit-stop"
      data-accent="orange"
      className="relative py-16 md:py-24"
      style={{ minHeight: '100vh' }}
      aria-label="Pit Stop — Pricing and demo"
    >
      <div className="grid-lap">
        {/* Header */}
        <div className="col-span-full text-center mb-4">
          <MonumentText size="h1" as="h2">
            {pitStop.monument}
          </MonumentText>
        </div>
        <div className="col-span-full text-center mb-12">
          <p className="font-telemetry text-steel">{pitStop.subhead}</p>
        </div>

        {/* Audience + Billing toggles */}
        <div className="col-span-full flex flex-col md:flex-row items-center justify-center gap-6 mb-8">
          <div className="flex items-center gap-4">
            <button
              className={`font-telemetry text-[11px] tracking-[0.12em] uppercase px-4 py-2 border transition-colors duration-300 ${
                audience === 'b2c' ? 'border-pit-orange text-chalk' : 'border-steel/30 text-steel'
              }`}
              onClick={() => { setAudience('b2c'); }}
            >
              DRIVERS
            </button>
            <button
              className={`font-telemetry text-[11px] tracking-[0.12em] uppercase px-4 py-2 border transition-colors duration-300 ${
                audience === 'b2b' ? 'border-pit-orange text-chalk' : 'border-steel/30 text-steel'
              }`}
              onClick={() => { setAudience('b2b'); }}
            >
              CIRCUITS
            </button>
          </div>

          {audience === 'b2c' && (
            <div className="flex items-center gap-3">
              <span className={`font-telemetry text-[11px] ${billingPeriod === 'monthly' ? 'text-chalk' : 'text-steel'}`}>
                MONTHLY
              </span>
              <button
                className="relative w-12 h-6 bg-concrete border border-steel/30"
                onClick={toggleBilling}
                aria-label={`Switch to ${billingPeriod === 'monthly' ? 'annual' : 'monthly'} billing`}
              >
                <span
                  className="absolute top-1 w-4 h-4 bg-pit-orange transition-all duration-300"
                  style={{ left: billingPeriod === 'annual' ? 'calc(100% - 20px)' : '4px' }}
                />
              </button>
              <span className={`font-telemetry text-[11px] ${billingPeriod === 'annual' ? 'text-chalk' : 'text-steel'}`}>
                ANNUAL
              </span>
            </div>
          )}
        </div>

        {/* Pricing Table */}
        <div className="col-span-full mb-8">
          <PricingTable
            plans={audience === 'b2c' ? b2cPlans : b2bPlans}
            billingPeriod={billingPeriod}
            onCtaClick={(plan) => trackCtaClick(plan, 'pit-stop', audience)}
          />
        </div>

        {/* Add-ons */}
        <div className="col-span-full mb-8">
          <button
            className="font-telemetry text-steel hover:text-chalk transition-colors w-full text-left py-3 border-b border-steel/20"
            onClick={() => {
              setAddonsOpen(!addonsOpen);
              if (!addonsOpen) trackAddonExpand();
            }}
          >
            OPTIONS BOARD {addonsOpen ? '\u2212' : '+'}
          </button>
          {addonsOpen && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-4">
              {addons.map((addon) => (
                <div key={addon.name} className="flex items-center justify-between gap-3 py-2 px-4 bg-concrete">
                  <div>
                    <span className="font-body text-sm text-chalk">{addon.name}</span>
                    {addon.note && <p className="text-xs text-steel mt-1">{addon.note}</p>}
                  </div>
                  <div className="text-right">
                    <span className="font-telemetry text-[var(--accent)] block">{addon.price}</span>
                    <StatusPill status={addon.status} />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* CTAs */}
        <div className="col-span-full flex flex-col md:flex-row items-center justify-center gap-4 mb-12">
          <PitButton
            href={audience === 'b2c' ? '/register?source=free-report&redirect=/free-report/analyze' : '/demo?audience=b2b'}
            onClick={() => trackCtaClick('try_demo', 'pit-stop', audience)}
          >
            {audience === 'b2c' ? 'START FREE REPORT' : 'BOOK B2B DEMO'}
          </PitButton>
          <StampButton
            href="/contact"
            onClick={() => trackCtaClick('talk_sales', 'pit-stop', audience)}
          >
            TALK TO SALES
          </StampButton>
          <StampButton
            href="/waitlist?feature=sim-telemetry"
            onClick={() => trackCtaClick('sim_waitlist', 'pit-stop', audience)}
          >
            JOIN SIM WAITLIST
          </StampButton>
        </div>

        {/* Risk reversal */}
        <div className="col-span-full flex flex-wrap justify-center gap-4 mb-12">
          {pitStop.riskReversal.map((item) => (
            <ScrutineeringStamp key={item} label={item} />
          ))}
        </div>

        {/* FAQ */}
        <div className="col-span-full max-w-2xl mx-auto mb-12">
          <h3 className="font-monument text-[var(--text-h3)] mb-4">FAQ</h3>
          <FaqAccordion items={faqItems} onExpand={trackFaqExpand} />
        </div>

        {/* Trust strip */}
        <div className="col-span-full flex flex-wrap justify-center gap-4 border-t border-steel/20 pt-8">
          {pitStop.trustStrip.map((item) => (
            <ScrutineeringStamp key={item} label={item} />
          ))}
        </div>

        <div className="col-span-full mt-8">
          <h3 className="font-monument text-[var(--text-h3)] mb-4">Claim Registry (Mapped)</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {homeClaims.map((claim) => (
              <article key={claim.id} className="bg-concrete/40 border border-steel/20 p-4">
                <div className="flex items-start justify-between gap-2 mb-2">
                  <p className="text-sm text-chalk">{claim.claim}</p>
                  <StatusPill status={claim.status} />
                </div>
                <p className="text-xs text-steel">{claim.capability}</p>
              </article>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
