'use client';

import { Fragment, useState, useCallback, useEffect } from 'react';
import { JsonLd } from '@/components/seo/JsonLd';
import { PageIntro } from '@/components/ui/PageIntro';
import { PricingTable } from '@/components/ui/PricingTable';
import { StampButton } from '@/components/ui/StampButton';
import { ChartTooltip } from '@/components/ui/ChartTooltip';
import { PromoCountdown } from '@/components/marketing/PromoCountdown';
import { RelatedPages } from '@/components/marketing/RelatedPages';
import { venueCard } from '@/data/pricing';
import { trackCtaClick, trackPricingToggle } from '@/lib/analytics';
import { useTranslation } from '@/i18n';
import { useCurrency } from '@/hooks/useCurrency';

/** Brief explanations for feature matrix rows */
const FEATURE_TIPS: Record<string, string> = {
  'pricing.matrix.uploadAnalyze': 'Upload a CSV from RaceChrono, RaceBox, AiM, or MoTeC and receive a full coaching report within seconds.',
  'pricing.matrix.fourPillar': 'Scores your driving across Pace, Consistency, Execution, and Robustness — each out of 25 for a total out of 100.',
  'pricing.matrix.cornerCoaching': 'Per-corner analysis showing time loss, coaching hints, and direction-specific feedback.',
  'pricing.matrix.sessionTabs': 'Speed traces, G-G diagrams, pedal traces, sector analysis, and more in a unified session view.',
  'pricing.matrix.comparisonProgress': 'Compare two sessions side-by-side to see exactly where you improved or lost time.',
  'pricing.matrix.coachingDrills': 'Targeted practice drills generated from your weaknesses to accelerate improvement.',
  'pricing.matrix.vizWorkspace': 'Interactive visualization workspace with chart theming, annotations, and custom overlays.',
  'pricing.matrix.strategyDashboard': 'Real-time race strategy view with pit windows, stint pacing, and degradation trends.',
  'pricing.matrix.livePace': 'Live telemetry monitoring during a race — see pace deltas and stint performance as they happen.',
  'pricing.matrix.pitPlanning': 'Optimal pit stop timing based on tire degradation, fuel, and race position.',
  'pricing.matrix.incidentAlert': 'Automated alerts for safety car, red flags, and unusual pace drops.',
  'pricing.matrix.trackManagement': 'Manage your tracks, drivers, and karts in one workspace.',
  'pricing.matrix.pdfReports': 'Download professional PDF reports to share with coaches, sponsors, or team engineers.',
  'pricing.matrix.apiAccess': 'Programmatic access to your telemetry data for custom integrations and dashboards.',
  'pricing.matrix.rawRetention': 'How long your original uploaded CSV files are stored before automatic cleanup.',
  'pricing.matrix.reportRetention': 'Processed coaching reports are lightweight and stored indefinitely on all plans.',
};

interface MatrixRow {
  featureKey: string;
  group: 'coaching' | 'strategy' | 'data';
  demoKey: string;
  racerKey: string;
  worldClassKey: string;
}

const featureMatrix: MatrixRow[] = [
  // COACHING
  { featureKey: 'pricing.matrix.uploadAnalyze', group: 'coaching', demoKey: 'pricing.matrix.1report', racerKey: 'pricing.matrix.10mo', worldClassKey: 'pricing.value.unlimited' },
  { featureKey: 'pricing.matrix.fourPillar', group: 'coaching', demoKey: 'pricing.value.full', racerKey: 'pricing.value.full', worldClassKey: 'pricing.value.full' },
  { featureKey: 'pricing.matrix.cornerCoaching', group: 'coaching', demoKey: 'pricing.value.full', racerKey: 'pricing.value.full', worldClassKey: 'pricing.value.full' },
  { featureKey: 'pricing.matrix.sessionTabs', group: 'coaching', demoKey: 'pricing.value.full', racerKey: 'pricing.value.full', worldClassKey: 'pricing.value.full' },
  { featureKey: 'pricing.matrix.comparisonProgress', group: 'coaching', demoKey: 'pricing.value.none', racerKey: 'pricing.value.none', worldClassKey: 'pricing.value.full' },
  { featureKey: 'pricing.matrix.coachingDrills', group: 'coaching', demoKey: 'pricing.value.none', racerKey: 'pricing.value.full', worldClassKey: 'pricing.value.full' },
  { featureKey: 'pricing.matrix.vizWorkspace', group: 'coaching', demoKey: 'pricing.value.none', racerKey: 'pricing.value.full', worldClassKey: 'pricing.value.full' },
  // STRATEGY
  { featureKey: 'pricing.matrix.strategyDashboard', group: 'strategy', demoKey: 'pricing.matrix.3hLimit', racerKey: 'pricing.value.full', worldClassKey: 'pricing.value.full' },
  { featureKey: 'pricing.matrix.livePace', group: 'strategy', demoKey: 'pricing.value.none', racerKey: 'pricing.value.full', worldClassKey: 'pricing.value.full' },
  { featureKey: 'pricing.matrix.pitPlanning', group: 'strategy', demoKey: 'pricing.value.none', racerKey: 'pricing.value.full', worldClassKey: 'pricing.value.full' },
  { featureKey: 'pricing.matrix.incidentAlert', group: 'strategy', demoKey: 'pricing.value.none', racerKey: 'pricing.value.full', worldClassKey: 'pricing.value.full' },
  // DATA & OPS
  { featureKey: 'pricing.matrix.trackManagement', group: 'data', demoKey: 'pricing.matrix.basic', racerKey: 'pricing.value.full', worldClassKey: 'pricing.value.full' },
  { featureKey: 'pricing.matrix.pdfReports', group: 'data', demoKey: 'pricing.value.none', racerKey: 'pricing.value.full', worldClassKey: 'pricing.value.full' },
  { featureKey: 'pricing.matrix.apiAccess', group: 'data', demoKey: 'pricing.value.none', racerKey: 'pricing.value.none', worldClassKey: 'pricing.value.full' },
  { featureKey: 'pricing.matrix.rawRetention', group: 'data', demoKey: 'pricing.value.1month', racerKey: 'pricing.value.3months', worldClassKey: 'pricing.value.12months' },
  { featureKey: 'pricing.matrix.reportRetention', group: 'data', demoKey: 'pricing.value.indefinite', racerKey: 'pricing.value.indefinite', worldClassKey: 'pricing.value.indefinite' },
];

const GROUP_ORDER: Array<'coaching' | 'strategy' | 'data'> = ['coaching', 'strategy', 'data'];
const GROUP_LABEL_KEYS: Record<string, string> = {
  coaching: 'pricing.groupCoaching',
  strategy: 'pricing.groupStrategy',
  data: 'pricing.groupData',
};

const USE_CASES = [
  { id: 'hobby', label: 'Hobby Driver', description: 'Track day enthusiast, a few sessions per year', recommended: 'demo' },
  { id: 'club', label: 'Club Racer', description: 'Regular race weekends, improving lap by lap', recommended: 'racer' },
  { id: 'pro', label: 'Pro / Academy', description: 'Professional driver or coaching academy', recommended: 'world-class' },
  { id: 'team', label: 'Racing Team', description: 'Multi-driver team with engineer support', recommended: 'world-class' },
] as const;

export default function PricingPage() {
  const [billing, setBilling] = useState<'monthly' | 'annual'>('annual');
  const [useCase, setUseCase] = useState<string | null>(null);
  const { t } = useTranslation();
  const { localizedPlans } = useCurrency();

  const [ctaVariant, setCtaVariant] = useState<string | undefined>();

  useEffect(() => {
    const match = document.cookie.match(/(?:^|;\s*)lap_exp_cta=([^;]+)/);
    if (match) setCtaVariant(match[1]);
  }, []);

  const toggleBilling = useCallback(() => {
    const next = billing === 'monthly' ? 'annual' : 'monthly';
    setBilling(next);
    trackPricingToggle(next);
  }, [billing]);

  const groupedRows = GROUP_ORDER.map((group) => ({
    group,
    labelKey: GROUP_LABEL_KEYS[group],
    rows: featureMatrix.filter((r) => r.group === group),
  }));

  return (
    <>
    <JsonLd
      pathname="/pricing"
      faqItems={[
        { question: 'What is included in the free demo?', answer: 'The free demo lets you upload one session and receive a full coaching report with speed traces, corner analysis, and scoring.' },
        { question: 'Can I switch plans at any time?', answer: 'Yes. Upgrade or downgrade between Racer and World-Class at any time. Changes apply at your next billing cycle.' },
        { question: 'Which GPS loggers are supported?', answer: 'RaceChrono, RaceBox, AiM, MoTeC, VBOX, and any logger that exports standard CSV with GPS coordinates.' },
        { question: 'Is my data private?', answer: 'Yes. All data is isolated per workspace using row-level security. Your telemetry is never shared with other users.' },
        { question: 'Can I use LAP for karts?', answer: 'Absolutely. LAP supports both kart and car telemetry with dedicated analysis pipelines for each.' },
        { question: 'Do you offer team or circuit plans?', answer: 'Yes. Contact our sales team for B2B plans with multi-seat access, API integration, and dedicated support.' },
      ]}
    />
    <main className="mx-auto max-w-6xl px-4 py-10 md:py-14">
      <PageIntro
        eyebrow={t('pricing.eyebrow')}
        title={t('pricing.title')}
        subtitle={t('pricing.description')}
      />
      {/* Promotional countdown — set endsAt to activate a time-limited offer */}
      <PromoCountdown endsAt="2026-04-01T00:00:00Z" label="Launch pricing ends in" className="mb-6" />

      {/* Use-case selector */}
      <section className="mb-8">
        <p className="text-center text-steel text-sm mb-3">I am a&hellip;</p>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 max-w-2xl mx-auto">
          {USE_CASES.map((uc) => (
            <button
              key={uc.id}
              type="button"
              onClick={() => setUseCase(useCase === uc.id ? null : uc.id)}
              className={`p-3 border rounded text-left transition-all ${
                useCase === uc.id
                  ? 'border-acid-green bg-acid-green/5 text-chalk'
                  : 'border-steel/20 text-steel hover:border-steel/40 hover:text-chalk'
              }`}
            >
              <span className="block font-monument text-xs mb-0.5">{uc.label}</span>
              <span className="block text-[11px] leading-tight opacity-70">{uc.description}</span>
            </button>
          ))}
        </div>
      </section>

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
        {billing === 'annual' && (
          <span className="inline-flex items-center px-2 py-0.5 bg-acid-green/10 border border-acid-green/30 rounded text-acid-green text-[10px] font-telemetry uppercase tracking-wider animate-pulse">
            Save 20%
          </span>
        )}
      </div>

      {/* Pricing Table + Venue card */}
      <section className="mb-10 grid grid-cols-1 lg:grid-cols-[3fr_1fr] gap-0">
        <PricingTable
          plans={localizedPlans}
          billingPeriod={billing}
          onCtaClick={(planName) => trackCtaClick(planName, 'pricing', 'b2c')}
          ctaVariant={ctaVariant}
          recommendedSlug={useCase ? USE_CASES.find((uc) => uc.id === useCase)?.recommended : null}
        />

        {/* Venue card */}
        <div className="p-6 bg-concrete border border-steel/20 lg:border-l-0">
          <p className="font-telemetry text-[10px] tracking-[0.12em] text-steel uppercase mb-2">
            {t('pricing.b2bLabel')}
          </p>
          <h3 className="font-monument text-[var(--text-h3)] mb-4">{t('pricing.b2b.name')}</h3>
          <ul className="space-y-2 mb-6">
            {[
              t('pricing.b2b.feature1'),
              t('pricing.b2b.feature2'),
              t('pricing.b2b.feature3'),
              t('pricing.b2b.feature4'),
              t('pricing.b2b.feature5'),
            ].map((feature) => (
              <li key={feature} className="flex items-start gap-2 font-body text-sm text-steel">
                <span className="text-pit-orange mt-0.5 shrink-0">&bull;</span>
                {feature}
              </li>
            ))}
          </ul>
          <StampButton
            href={venueCard.ctaHref}
            onClick={() => trackCtaClick('contact_sales', 'pricing', 'b2b')}
            className="w-full"
          >
            {t('cta.contactSales')}
          </StampButton>
        </div>
      </section>

      {/* Feature Eligibility Matrix */}
      <section className="mb-10 overflow-x-auto">
        <h2 className="font-monument text-[var(--text-h2)] mb-4">{t('pricing.matrixTitle')}</h2>
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
            {groupedRows.map(({ group, labelKey, rows }) => (
              <Fragment key={group}>
                <tr>
                  <td
                    colSpan={4}
                    className="bg-asphalt/60 font-monument text-xs tracking-[0.12em] uppercase p-2 text-chalk border border-steel/20"
                  >
                    {t(labelKey)}
                  </td>
                </tr>
                {rows.map((row) => (
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
              </Fragment>
            ))}
          </tbody>
        </table>
      </section>

      {/* Quick Comparison Checkmarks */}
      <section className="mb-10">
        <h2 className="font-monument text-[var(--text-h2)] mb-4">Quick Comparison</h2>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="bg-concrete">
                <th className="border border-steel/20 p-3 text-left text-steel w-1/2">Feature</th>
                <th className="border border-steel/20 p-3 text-center text-steel">Demo</th>
                <th className="border border-steel/20 p-3 text-center text-pit-orange font-monument">Racer</th>
                <th className="border border-steel/20 p-3 text-center text-steel">World-Class</th>
              </tr>
            </thead>
            <tbody>
              {[
                { feature: 'Upload & Analyze', demo: true, racer: true, worldClass: true },
                { feature: '4-Pillar Scoring', demo: true, racer: true, worldClass: true },
                { feature: 'Corner Coaching', demo: true, racer: true, worldClass: true },
                { feature: 'Speed Trace & G-G Diagram', demo: true, racer: true, worldClass: true },
                { feature: 'Coaching Drills', demo: false, racer: true, worldClass: true },
                { feature: 'Visualization Workspace', demo: false, racer: true, worldClass: true },
                { feature: 'Session Comparison', demo: false, racer: false, worldClass: true },
                { feature: 'Race Strategy Dashboard', demo: 'partial', racer: true, worldClass: true },
                { feature: 'Live Monitoring', demo: false, racer: true, worldClass: true },
                { feature: 'PDF Reports', demo: false, racer: true, worldClass: true },
                { feature: 'API Access', demo: false, racer: false, worldClass: true },
                { feature: 'Priority Support', demo: false, racer: false, worldClass: true },
              ].map((row) => (
                <tr key={row.feature} className="hover:bg-concrete/40 transition-colors">
                  <td className="border border-steel/20 p-3 text-chalk">{row.feature}</td>
                  {([row.demo, row.racer, row.worldClass] as (boolean | string)[]).map((val, i) => (
                    <td key={i} className="border border-steel/20 p-3 text-center">
                      {val === true && <span className="text-acid-green text-lg">&#10003;</span>}
                      {val === false && <span className="text-steel/30">&mdash;</span>}
                      {val === 'partial' && <span className="text-marshal-yellow text-xs font-telemetry">Limited</span>}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
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
            { q: 'Do you offer team or circuit plans?', a: 'Yes. Contact our sales team for B2B plans with multi-seat access, API integration, and dedicated support.' },
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

      {/* Data Lifecycle Transparency */}
      <section className="mb-10">
        <h2 className="font-monument text-[var(--text-h2)] mb-4">
          {t('pricing.dataLifecycleTitle')}
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* Raw Telemetry */}
          <article className="border border-steel/20 bg-concrete/40 p-5">
            <h3 className="font-monument text-xs tracking-[0.12em] uppercase text-chalk mb-1">
              {t('pricing.lifecycle.rawTelemetry')}
            </h3>
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
            <h3 className="font-monument text-xs tracking-[0.12em] uppercase text-chalk mb-1">
              {t('pricing.lifecycle.processedReports')}
            </h3>
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
            <h3 className="font-monument text-xs tracking-[0.12em] uppercase text-chalk mb-1">
              {t('pricing.lifecycle.liveEvent')}
            </h3>
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
