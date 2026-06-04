'use client';

import { useEffect } from 'react';
import { JsonLd } from '@/components/seo/JsonLd';
import { BreadcrumbJsonLd } from '@/components/seo/BreadcrumbJsonLd';
import { PageJsonLd } from '@/components/seo/PageJsonLd';
import { PageIntro } from '@/components/ui/PageIntro';
import { PricingTable } from '@/components/ui/PricingTable';
import { RelatedPages } from '@/components/marketing/RelatedPages';
import { trackCtaClick, trackB2CFunnel } from '@/lib/analytics';
import { useTranslation } from '@/i18n';
import { useCurrency } from '@/hooks/useCurrency';
import { featureEligibilityMatrix, dataLifecycle } from '@/data/pricing';

/** Section labels for the single "what's included" list. */
const GROUP_LABELS: Record<string, string> = {
  coaching: 'Coaching & analysis',
  strategy: 'Race strategy & live',
  data: 'Data, reports & devices',
};
const GROUP_ORDER = ['coaching', 'strategy', 'data'] as const;

const FAQ_ITEMS = [
  {
    q: 'How does the free trial work?',
    a: 'Every membership starts with a 30-day free trial. You get full access to everything from day one — no feature is held back. You are only charged when the trial ends, and you can cancel any time before then at no cost.',
  },
  {
    q: 'What is the Founding offer?',
    a: 'The first 50 members lock in €14.90/mo for as long as their membership stays active — €5/mo below the standard €19.90. Once the 50 founding places are taken, new memberships are €19.90/mo.',
  },
  {
    q: 'Is there a free tier?',
    a: 'No. There is one membership that unlocks the entire product, with a 30-day free trial so you can try it in full before paying.',
  },
  {
    q: 'Which GPS loggers are supported?',
    a: 'RaceChrono, RaceBox, AiM, MoTeC, VBOX, and any logger that exports standard CSV with GPS coordinates.',
  },
  {
    q: 'Is my data private?',
    a: 'Yes. All data is isolated per workspace using row-level security. Your telemetry is never shared with other users.',
  },
  {
    q: 'Can I cancel any time?',
    a: 'Yes. Cancel during the trial and you are never charged. Cancel after and your membership runs to the end of the paid month.',
  },
];

export default function PricingPage() {
  const { t } = useTranslation();
  const { localizedPlans } = useCurrency();

  useEffect(() => {
    trackB2CFunnel('pricing_visit');
  }, []);

  return (
    <>
      <BreadcrumbJsonLd pathname="/pricing" />
      <PageJsonLd
        type="FAQPage"
        title="Pricing"
        description="One LAP membership — €19.90/mo, €14.90/mo for the first 50 members, 30-day free trial."
        pathname="/pricing"
        faqItems={FAQ_ITEMS.map(({ q, a }) => ({ question: q, answer: a }))}
      />
      <JsonLd pathname="/pricing" faqItems={FAQ_ITEMS.map(({ q, a }) => ({ question: q, answer: a }))} />

      <main className="mx-auto max-w-6xl px-4 py-10 md:py-14">
        <PageIntro
          eyebrow={t('pricing.eyebrow')}
          title={t('pricing.title')}
          subtitle="One membership. Everything unlocked. 30-day free trial — no card charged until it ends."
        />

        <h2 className="sr-only">Membership</h2>

        {/* Single membership card */}
        <section id="membership" className="mb-12 scroll-mt-24">
          <PricingTable
            plans={localizedPlans}
            onCtaClick={(planName) => trackCtaClick(planName, 'pricing', 'b2c')}
          />
        </section>

        <h2 className="sr-only">What's included</h2>

        {/* Everything-included list — one membership, no per-tier columns */}
        <section className="mb-12">
          <h3 className="font-monument text-[var(--text-h2)] mb-4">Everything in your membership</h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {GROUP_ORDER.map((group) => (
              <div key={group} className="border border-steel/20 bg-concrete/40 p-5">
                <h4 className="font-monument text-xs tracking-[0.12em] uppercase text-pit-orange mb-3">
                  {GROUP_LABELS[group]}
                </h4>
                <ul className="space-y-2">
                  {featureEligibilityMatrix
                    .filter((row) => row.group === group)
                    .map((row) => (
                      <li key={row.feature} className="flex justify-between gap-3 text-sm font-body">
                        <span className="text-steel">{row.feature}</span>
                        <span className="text-chalk text-right">{row.value}</span>
                      </li>
                    ))}
                </ul>
              </div>
            ))}
          </div>
        </section>

        {/* FAQ */}
        <section className="mb-10">
          <h2 className="font-monument text-[var(--text-h2)] mb-4">Frequently asked questions</h2>
          <div className="space-y-3">
            {FAQ_ITEMS.map(({ q, a }) => (
              <details key={q} className="group border border-steel/20 bg-concrete/40">
                <summary className="flex items-center justify-between cursor-pointer p-4 font-body text-sm text-chalk hover:text-acid-green transition-colors">
                  {q}
                  <span className="text-steel group-open:rotate-45 transition-transform ml-2 shrink-0">+</span>
                </summary>
                <p className="px-4 pb-4 text-steel text-sm font-body">{a}</p>
              </details>
            ))}
          </div>
        </section>

        {/* Trust Badges */}
        <section className="mb-10">
          <div className="flex flex-wrap items-center justify-center gap-6 py-6 border-y border-steel/10">
            <div className="flex items-center gap-2 text-steel">
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
                <path d="M10 2l6 3v5c0 4-3 6.5-6 8-3-1.5-6-4-6-8V5l6-3z" />
                <path d="M7 10l2 2 4-4" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <span className="text-xs font-telemetry uppercase tracking-wider">SSL Encrypted</span>
            </div>
            <div className="flex items-center gap-2 text-steel">
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
                <circle cx="10" cy="10" r="7" />
                <path d="M10 6v4l2.5 1.5" strokeLinecap="round" />
              </svg>
              <span className="text-xs font-telemetry uppercase tracking-wider">99.9% Uptime SLA</span>
            </div>
            <div className="flex items-center gap-2 text-steel">
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
                <rect x="3" y="8" width="14" height="9" rx="1" />
                <path d="M6 8V5a4 4 0 0 1 8 0v3" />
                <circle cx="10" cy="13" r="1.5" />
              </svg>
              <span className="text-xs font-telemetry uppercase tracking-wider">Data Isolation (RLS)</span>
            </div>
            <div className="flex items-center gap-2 text-steel">
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
                <path d="M4 10a6 6 0 0 1 12 0" />
                <path d="M7 10a3 3 0 0 1 6 0" />
                <circle cx="10" cy="10" r="1" fill="currentColor" />
                <path d="M10 11v5" />
              </svg>
              <span className="text-xs font-telemetry uppercase tracking-wider">GDPR Compliant</span>
            </div>
            <div className="flex items-center gap-2 text-steel">
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
                <path d="M3 14l4-4 3 3 7-7" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <span className="text-xs font-telemetry uppercase tracking-wider">Daily Backups</span>
            </div>
          </div>
        </section>

        <h2 className="sr-only">Data lifecycle</h2>

        {/* Data Lifecycle Transparency — single membership, one value per row */}
        <section className="mb-10">
          <h3 className="font-monument text-[var(--text-h2)] mb-4">{t('pricing.dataLifecycleTitle')}</h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {dataLifecycle.map((item) => (
              <article key={item.category} className="border border-steel/20 bg-concrete/40 p-5">
                <h4 className="font-monument text-xs tracking-[0.12em] uppercase text-chalk mb-1">{item.category}</h4>
                <p className="text-steel text-sm mb-4">{item.description}</p>
                <p className="text-chalk text-sm font-body mb-4">{item.value}</p>
                <p className="text-steel/60 text-xs italic">{item.note}</p>
              </article>
            ))}
          </div>
        </section>

        <RelatedPages pathname="/pricing" />
      </main>

      {/* Sticky mobile CTA bar */}
      <div className="fixed bottom-0 left-0 right-0 z-40 md:hidden bg-concrete/95 backdrop-blur-sm border-t border-steel/20 px-4 py-3 safe-area-bottom">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="font-monument text-xs text-chalk truncate">30-day free trial · from €14.90/mo</p>
          </div>
          <a
            href="#membership"
            className="shrink-0 px-5 py-2.5 bg-pit-orange text-white font-telemetry text-xs uppercase tracking-wider rounded hover:brightness-110 transition-all"
          >
            Start free trial
          </a>
        </div>
      </div>
    </>
  );
}
