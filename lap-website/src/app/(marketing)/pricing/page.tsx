'use client';

import { useState, useCallback, useEffect } from 'react';
import { JsonLd } from '@/components/seo/JsonLd';
import { BreadcrumbJsonLd } from '@/components/seo/BreadcrumbJsonLd';
import { PageJsonLd } from '@/components/seo/PageJsonLd';
import { PageIntro } from '@/components/ui/PageIntro';
import { PricingTable } from '@/components/ui/PricingTable';
import { ChartTooltip } from '@/components/ui/ChartTooltip';
import { RelatedPages } from '@/components/marketing/RelatedPages';
import { trackCtaClick, trackPricingToggle, trackB2CFunnel } from '@/lib/analytics';
import { useTranslation } from '@/i18n';
import { useCurrency } from '@/hooks/useCurrency';

/** Brief explanations for feature matrix rows */
const FEATURE_TIPS: Record<string, string> = {
  'pricing.matrix.uploadAnalyze': 'Upload a CSV from RaceChrono, RaceBox, AiM, or MoTeC and receive a full coaching report within seconds.',
  'pricing.matrix.strategyDashboard': 'Real-time race strategy view with pit windows, stint pacing, and degradation trends.',
  'pricing.matrix.vizWorkspace': 'Interactive visualization workspace with chart theming, annotations, and custom overlays.',
  'pricing.matrix.rawRetention': 'How long your original uploaded CSV files are stored before automatic cleanup.',
  'pricing.matrix.reportRetention': 'Processed coaching reports stored for 5 years (GDPR compliant).',
  'pricing.matrix.fourPillar': 'Scores your driving across Pace, Consistency, Execution, and Robustness — each out of 25 for a total out of 100.',
  'pricing.matrix.cornerCoaching': 'Per-corner analysis showing time loss, coaching hints, and direction-specific feedback.',
  'pricing.matrix.sessionTabs': 'Speed traces, G-G diagrams, pedal traces, sector analysis, and more in a unified session view.',
  'pricing.matrix.comparisonProgress': 'Compare two sessions side-by-side to see exactly where you improved or lost time.',
  'pricing.matrix.coachingDrills': 'Targeted practice drills generated from your weaknesses to accelerate improvement.',
  'pricing.matrix.livePace': 'Live telemetry monitoring during a race — see pace deltas and stint performance as they happen.',
  'pricing.matrix.pitPlanning': 'Optimal pit stop timing based on tire degradation, fuel, and race position.',
  'pricing.matrix.incidentAlert': 'Automated alerts for safety car, red flags, and unusual pace drops.',
  'pricing.matrix.trackManagement': 'Manage your tracks, drivers, and karts in one workspace.',
  'pricing.matrix.pdfReports': 'Download professional PDF reports to share with coaches, sponsors, or team engineers.',
  'pricing.matrix.apiAccess': 'Programmatic access to your telemetry data for custom integrations and dashboards.',
};

interface MatrixRow {
  featureKey: string;
  group: 'core' | 'detail';
  demoKey: string;
  racerKey: string;
  worldClassKey: string;
}

/**
 * Core rows: always visible — race strategy, reports, visualization, retention.
 * Values cross-checked against PLAN_ENTITLEMENTS in telemetry_tool/auth/entitlements.py
 */
const coreRows: MatrixRow[] = [
  // free: 1 report/mo | racer: 10/mo | world_class: unlimited
  { featureKey: 'pricing.matrix.uploadAnalyze', group: 'core', demoKey: 'pricing.matrix.1report', racerKey: 'pricing.matrix.10mo', worldClassKey: 'pricing.value.unlimited' },
  // free: 4h_basic | racer: 24h_complex | world_class: unlimited
  { featureKey: 'pricing.matrix.strategyDashboard', group: 'core', demoKey: 'pricing.matrix.3hLimit', racerKey: 'pricing.matrix.24hLimit', worldClassKey: 'pricing.value.unlimited' },
  // free: False | racer: True | world_class: True
  { featureKey: 'pricing.matrix.vizWorkspace', group: 'core', demoKey: 'pricing.value.none', racerKey: 'pricing.value.full', worldClassKey: 'pricing.value.full' },
  // free: 30d | racer: 90d | world_class: 365d
  { featureKey: 'pricing.matrix.rawRetention', group: 'core', demoKey: 'pricing.value.1month', racerKey: 'pricing.value.3months', worldClassKey: 'pricing.value.12months' },
  // all plans: 5 years (GDPR)
  { featureKey: 'pricing.matrix.reportRetention', group: 'core', demoKey: 'pricing.value.indefinite', racerKey: 'pricing.value.indefinite', worldClassKey: 'pricing.value.indefinite' },
];

/**
 * Detail rows: revealed on expand.
 * Values cross-checked against PLAN_ENTITLEMENTS in telemetry_tool/auth/entitlements.py
 */
const detailRows: MatrixRow[] = [
  // All plans: scoring always available
  { featureKey: 'pricing.matrix.fourPillar', group: 'detail', demoKey: 'pricing.value.full', racerKey: 'pricing.value.full', worldClassKey: 'pricing.value.full' },
  { featureKey: 'pricing.matrix.cornerCoaching', group: 'detail', demoKey: 'pricing.value.full', racerKey: 'pricing.value.full', worldClassKey: 'pricing.value.full' },
  { featureKey: 'pricing.matrix.sessionTabs', group: 'detail', demoKey: 'pricing.value.full', racerKey: 'pricing.value.full', worldClassKey: 'pricing.value.full' },
  // free: False | racer: True | world_class: True
  { featureKey: 'pricing.matrix.comparisonProgress', group: 'detail', demoKey: 'pricing.value.none', racerKey: 'pricing.value.full', worldClassKey: 'pricing.value.full' },
  // free: False | racer: True | world_class: True
  { featureKey: 'pricing.matrix.coachingDrills', group: 'detail', demoKey: 'pricing.value.none', racerKey: 'pricing.value.full', worldClassKey: 'pricing.value.full' },
  // free: ["equal"] | racer: ["equal"] | world_class: ["equal","performance"]
  { featureKey: 'pricing.matrix.optimizer', group: 'detail', demoKey: 'pricing.value.equalOnly', racerKey: 'pricing.value.equalOnly', worldClassKey: 'pricing.value.allModes' },
  // free: False | racer: True | world_class: True
  { featureKey: 'pricing.matrix.livePace', group: 'detail', demoKey: 'pricing.value.none', racerKey: 'pricing.value.full', worldClassKey: 'pricing.value.full' },
  { featureKey: 'pricing.matrix.pitPlanning', group: 'detail', demoKey: 'pricing.value.none', racerKey: 'pricing.value.full', worldClassKey: 'pricing.value.full' },
  // free: "basic" | racer: "full" | world_class: "full"
  { featureKey: 'pricing.matrix.trackManagement', group: 'detail', demoKey: 'pricing.matrix.basic', racerKey: 'pricing.value.full', worldClassKey: 'pricing.value.full' },
  // free: no pdf | racer: pdf | world_class: pdf
  { featureKey: 'pricing.matrix.pdfReports', group: 'detail', demoKey: 'pricing.value.none', racerKey: 'pricing.value.full', worldClassKey: 'pricing.value.full' },
  // free: False | racer: False | world_class: True
  { featureKey: 'pricing.matrix.apiAccess', group: 'detail', demoKey: 'pricing.value.none', racerKey: 'pricing.value.none', worldClassKey: 'pricing.value.full' },
];

export default function PricingPage() {
  const [billing, setBilling] = useState<'monthly' | 'annual'>('annual');
  const [matrixExpanded, setMatrixExpanded] = useState(false);
  const { t } = useTranslation();
  const { localizedPlans } = useCurrency();

  const [ctaVariant, setCtaVariant] = useState<string | undefined>();

  useEffect(() => {
    const match = document.cookie.match(/(?:^|;\s*)lap_exp_cta=([^;]+)/);
    if (match) setCtaVariant(match[1]);
    trackB2CFunnel('pricing_visit');
  }, []);

  const toggleBilling = useCallback(() => {
    const next = billing === 'monthly' ? 'annual' : 'monthly';
    setBilling(next);
    trackPricingToggle(next);
  }, [billing]);

  return (
    <>
    <BreadcrumbJsonLd pathname="/pricing" />
    <PageJsonLd
      type="FAQPage"
      title="Pricing"
      description="Choose the right LAP plan for your racing programme."
      pathname="/pricing"
      faqItems={[
        { question: 'What file formats does LAP support?', answer: 'RaceChrono CSV, RaceBox CSV, AiM CSV, and MoTeC CSV with GPS data.' },
        { question: 'Can I switch plans?', answer: 'Yes, you can upgrade or downgrade at any time. Changes take effect on your next billing cycle.' },
        { question: 'Is there a free trial?', answer: 'The Demo tier is free forever with 3 analyses per month. No credit card required.' },
      ]}
    />
    <JsonLd
      pathname="/pricing"
      faqItems={[
        { question: 'What is included in the free demo?', answer: 'The free demo lets you upload one session and receive a full coaching report with speed traces, corner analysis, and scoring.' },
        { question: 'Can I switch plans at any time?', answer: 'Yes. Upgrade or downgrade between Racer and World-Class at any time. Changes apply at your next billing cycle.' },
        { question: 'Which GPS loggers are supported?', answer: 'RaceChrono, RaceBox, AiM, MoTeC, VBOX, and any logger that exports standard CSV with GPS coordinates.' },
        { question: 'Is my data private?', answer: 'Yes. All data is isolated per workspace using row-level security. Your telemetry is never shared with other users.' },
        { question: 'Can I use LAP for karts?', answer: 'Absolutely. LAP supports both kart and car telemetry with dedicated analysis pipelines for each.' },
        { question: 'Do you offer team or circuit plans?', answer: 'Yes — venue and team plans are available separately. See the For Venues & Teams page for details.' },
      ]}
    />
    <main className="mx-auto max-w-6xl px-4 py-10 md:py-14">
      <PageIntro
        eyebrow={t('pricing.eyebrow')}
        title={t('pricing.title')}
        subtitle={t('pricing.description')}
      />

      {/* Billing toggle */}
      <div className="flex items-center justify-center gap-3 mb-8">
        <span
          className={`font-telemetry text-[11px] ${
            billing === 'monthly' ? 'text-chalk' : 'text-steel'
          }`}
        >
          {t('pricing.toggleMonthly')}
        </span>
        <button
          type="button"
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
          {t('pricing.toggleAnnual')}
        </span>
      </div>

      {/* SEO-visible, visually hidden heading */}
      <h2 className="sr-only">Plans</h2>

      {/* Pricing Table */}
      <section className="mb-10">
        <PricingTable
          plans={localizedPlans}
          billingPeriod={billing}
          onCtaClick={(planName) => trackCtaClick(planName, 'pricing', 'b2c')}
          ctaVariant={ctaVariant}
        />
      </section>

      {/* SEO-visible, visually hidden heading */}
      <h2 className="sr-only">Features</h2>

      {/* Feature Eligibility Matrix — core features always visible, details in collapsible */}
      <section className="mb-10 overflow-x-auto">
        <h3 className="font-monument text-[var(--text-h2)] mb-4">{t('pricing.matrixTitle')}</h3>
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="bg-concrete">
              <th className="border border-steel/20 p-2 text-left text-steel">{t('pricing.matrixFeature')}</th>
              <th className="border border-steel/20 p-2 text-left text-steel">{t('pricing.matrixDemo')}</th>
              <th className="border border-steel/20 p-2 text-left text-steel">{t('pricing.matrixRacer')}</th>
              <th className="border border-steel/20 p-2 text-left text-steel">{t('pricing.matrixWorldClass')}</th>
            </tr>
          </thead>
          <tbody>
            {/* Core rows — always visible */}
            {coreRows.map((row) => (
              <tr key={row.featureKey}>
                <td className="border border-steel/20 p-2 text-steel">
                  <span className="inline-flex items-center gap-1.5">
                    {t(row.featureKey)}
                    {FEATURE_TIPS[row.featureKey] && (
                      <ChartTooltip title={t(row.featureKey)} description={FEATURE_TIPS[row.featureKey]} />
                    )}
                  </span>
                </td>
                <td className="border border-steel/20 p-2 text-chalk">{t(row.demoKey)}</td>
                <td className="border border-steel/20 p-2 text-chalk">{t(row.racerKey)}</td>
                <td className="border border-steel/20 p-2 text-chalk">{t(row.worldClassKey)}</td>
              </tr>
            ))}

            {/* Detail rows — collapsible */}
            {matrixExpanded && detailRows.map((row) => (
              <tr key={row.featureKey} className="bg-concrete/20 animate-in fade-in">
                <td className="border border-steel/20 p-2 text-steel">
                  <span className="inline-flex items-center gap-1.5">
                    {t(row.featureKey)}
                    {FEATURE_TIPS[row.featureKey] && (
                      <ChartTooltip title={t(row.featureKey)} description={FEATURE_TIPS[row.featureKey]} />
                    )}
                  </span>
                </td>
                <td className="border border-steel/20 p-2 text-chalk">{t(row.demoKey)}</td>
                <td className="border border-steel/20 p-2 text-chalk">{t(row.racerKey)}</td>
                <td className="border border-steel/20 p-2 text-chalk">{t(row.worldClassKey)}</td>
              </tr>
            ))}

            {/* Expand/collapse row inside table */}
            <tr>
              <td colSpan={4} className="border border-steel/20 p-0">
                <button
                  type="button"
                  className="w-full py-3 font-telemetry text-[11px] tracking-[0.12em] uppercase text-steel hover:text-chalk hover:bg-concrete/40 transition-colors duration-300 flex items-center justify-center gap-2"
                  onClick={() => setMatrixExpanded(!matrixExpanded)}
                >
                  {matrixExpanded ? 'Show key features' : 'See all features'}
                  <span
                    className="inline-block transition-transform duration-300"
                    style={{ transform: matrixExpanded ? 'rotate(180deg)' : 'rotate(0deg)' }}
                  >
                    &#9662;
                  </span>
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      {/* FAQ */}
      <section className="mb-10">
        <h2 className="font-monument text-[var(--text-h2)] mb-4">
          Frequently Asked Questions
        </h2>
        <div className="space-y-3">
          {[
            { q: 'What is included in the free demo?', a: 'The free demo lets you upload one session and receive a full coaching report with speed traces, corner analysis, and scoring.' },
            { q: 'Can I switch plans at any time?', a: 'Yes. Upgrade or downgrade between Racer and World-Class at any time. Changes apply at your next billing cycle.' },
            { q: 'Which GPS loggers are supported?', a: 'RaceChrono, RaceBox, AiM, MoTeC, VBOX, and any logger that exports standard CSV with GPS coordinates.' },
            { q: 'Is my data private?', a: 'Yes. All data is isolated per workspace using row-level security. Your telemetry is never shared with other users.' },
            { q: 'Can I use LAP for karts?', a: 'Absolutely. LAP supports both kart and car telemetry with dedicated analysis pipelines for each.' },
            { q: 'Do you offer team or circuit plans?', a: 'Yes — venue and team plans are available separately. See the For Venues & Teams page in the footer for details.' },
          ].map(({ q, a }) => (
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

      {/* SEO-visible, visually hidden heading */}
      <h2 className="sr-only">Lifecycle</h2>

      {/* Data Lifecycle Transparency */}
      <section className="mb-10">
        <h3 className="font-monument text-[var(--text-h2)] mb-4">
          {t('pricing.dataLifecycleTitle')}
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* Raw Telemetry */}
          <article className="border border-steel/20 bg-concrete/40 p-5">
            <h4 className="font-monument text-xs tracking-[0.12em] uppercase text-chalk mb-1">
              {t('pricing.lifecycle.rawTelemetry')}
            </h4>
            <p className="text-steel text-sm mb-4">{t('pricing.lifecycle.rawDesc')}</p>
            <div className="space-y-2 mb-4">
              <div className="flex justify-between text-sm font-body">
                <span className="text-steel">Demo</span>
                <span className="text-chalk">{t('pricing.lifecycle.rawDemoTier')}</span>
              </div>
              <div className="flex justify-between text-sm font-body">
                <span className="text-steel">Racer</span>
                <span className="text-chalk">{t('pricing.lifecycle.rawRacerTier')}</span>
              </div>
              <div className="flex justify-between text-sm font-body">
                <span className="text-steel">World-Class</span>
                <span className="text-chalk">{t('pricing.lifecycle.rawWorldClassTier')}</span>
              </div>
            </div>
            <p className="text-steel/60 text-xs italic">{t('pricing.lifecycle.rawNote')}</p>
          </article>

          {/* Processed Reports */}
          <article className="border border-steel/20 bg-concrete/40 p-5">
            <h4 className="font-monument text-xs tracking-[0.12em] uppercase text-chalk mb-1">
              {t('pricing.lifecycle.processedReports')}
            </h4>
            <p className="text-steel text-sm mb-4">{t('pricing.lifecycle.processedDesc')}</p>
            <div className="space-y-2 mb-4">
              <div className="flex justify-between text-sm font-body">
                <span className="text-steel">{t('pricing.lifecycle.allB2cLabel')}</span>
                <span className="text-chalk">{t('pricing.lifecycle.processedB2cTier')}</span>
              </div>
              <div className="flex justify-between text-sm font-body">
                <span className="text-steel">{t('pricing.lifecycle.b2bLabel')}</span>
                <span className="text-chalk">{t('pricing.lifecycle.processedB2bTier')}</span>
              </div>
            </div>
            <p className="text-steel/60 text-xs italic">{t('pricing.lifecycle.processedNote')}</p>
          </article>

          {/* Live Event Data */}
          <article className="border border-steel/20 bg-concrete/40 p-5">
            <h4 className="font-monument text-xs tracking-[0.12em] uppercase text-chalk mb-1">
              {t('pricing.lifecycle.liveEvent')}
            </h4>
            <p className="text-steel text-sm mb-4">{t('pricing.lifecycle.liveDesc')}</p>
            <div className="space-y-2 mb-4">
              <div className="flex justify-between text-sm font-body">
                <span className="text-steel">{t('pricing.lifecycle.rawStreamLabel')}</span>
                <span className="text-chalk">{t('pricing.lifecycle.liveStreamTier')}</span>
              </div>
              <div className="flex justify-between text-sm font-body">
                <span className="text-steel">{t('pricing.lifecycle.summariesLabel')}</span>
                <span className="text-chalk">{t('pricing.lifecycle.liveSummaryTier')}</span>
              </div>
            </div>
            <p className="text-steel/60 text-xs italic">{t('pricing.lifecycle.liveNote')}</p>
          </article>
        </div>
      </section>

      <RelatedPages pathname="/pricing" />
    </main>

    {/* Sticky mobile CTA bar */}
    <div className="fixed bottom-0 left-0 right-0 z-40 md:hidden bg-concrete/95 backdrop-blur-sm border-t border-steel/20 px-4 py-3 safe-area-bottom">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="font-monument text-xs text-chalk truncate">Start Free or from {billing === 'annual' ? '€6/mo' : '€9/mo'}</p>
        </div>
        <a
          href="/register?source=pricing-sticky"
          className="shrink-0 px-5 py-2.5 bg-pit-orange text-white font-telemetry text-xs uppercase tracking-wider rounded hover:brightness-110 transition-all"
        >
          Get Started
        </a>
      </div>
    </div>
    </>
  );
}
