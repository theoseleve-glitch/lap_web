'use client';

import { Fragment, useState, useCallback } from 'react';
import { PageShell } from '@/components/site/PageShell';
import { PricingTable } from '@/components/ui/PricingTable';
import { StampButton } from '@/components/ui/StampButton';
import { venueCard } from '@/data/pricing';
import { trackCtaClick, trackPricingToggle } from '@/lib/analytics';
import { useTranslation } from '@/i18n';
import { useCurrency } from '@/hooks/useCurrency';

interface MatrixRow {
  featureKey: string;
  group: 'engineer' | 'strategist' | 'data';
  demoKey: string;
  racerKey: string;
  worldClassKey: string;
}

const featureMatrix: MatrixRow[] = [
  // ENGINEER
  { featureKey: 'pricing.matrix.uploadAnalyze', group: 'engineer', demoKey: 'pricing.matrix.1report', racerKey: 'pricing.matrix.10mo', worldClassKey: 'pricing.value.unlimited' },
  { featureKey: 'pricing.matrix.fourPillar', group: 'engineer', demoKey: 'pricing.value.full', racerKey: 'pricing.value.full', worldClassKey: 'pricing.value.full' },
  { featureKey: 'pricing.matrix.cornerCoaching', group: 'engineer', demoKey: 'pricing.value.full', racerKey: 'pricing.value.full', worldClassKey: 'pricing.value.full' },
  { featureKey: 'pricing.matrix.sessionTabs', group: 'engineer', demoKey: 'pricing.value.full', racerKey: 'pricing.value.full', worldClassKey: 'pricing.value.full' },
  { featureKey: 'pricing.matrix.comparisonProgress', group: 'engineer', demoKey: 'pricing.value.none', racerKey: 'pricing.value.none', worldClassKey: 'pricing.value.full' },
  { featureKey: 'pricing.matrix.coachingDrills', group: 'engineer', demoKey: 'pricing.value.none', racerKey: 'pricing.value.full', worldClassKey: 'pricing.value.full' },
  { featureKey: 'pricing.matrix.vizWorkspace', group: 'engineer', demoKey: 'pricing.value.none', racerKey: 'pricing.value.full', worldClassKey: 'pricing.value.full' },
  // STRATEGIST
  { featureKey: 'pricing.matrix.strategyDashboard', group: 'strategist', demoKey: 'pricing.matrix.3hLimit', racerKey: 'pricing.value.full', worldClassKey: 'pricing.value.full' },
  { featureKey: 'pricing.matrix.livePace', group: 'strategist', demoKey: 'pricing.value.none', racerKey: 'pricing.value.full', worldClassKey: 'pricing.value.full' },
  { featureKey: 'pricing.matrix.pitPlanning', group: 'strategist', demoKey: 'pricing.value.none', racerKey: 'pricing.value.full', worldClassKey: 'pricing.value.full' },
  { featureKey: 'pricing.matrix.incidentAlert', group: 'strategist', demoKey: 'pricing.value.none', racerKey: 'pricing.value.full', worldClassKey: 'pricing.value.full' },
  // DATA & OPS
  { featureKey: 'pricing.matrix.trackManagement', group: 'data', demoKey: 'pricing.matrix.basic', racerKey: 'pricing.value.full', worldClassKey: 'pricing.value.full' },
  { featureKey: 'pricing.matrix.pdfReports', group: 'data', demoKey: 'pricing.value.none', racerKey: 'pricing.value.full', worldClassKey: 'pricing.value.full' },
  { featureKey: 'pricing.matrix.apiAccess', group: 'data', demoKey: 'pricing.value.none', racerKey: 'pricing.value.none', worldClassKey: 'pricing.value.full' },
  { featureKey: 'pricing.matrix.rawRetention', group: 'data', demoKey: 'pricing.value.1month', racerKey: 'pricing.value.3months', worldClassKey: 'pricing.value.12months' },
  { featureKey: 'pricing.matrix.reportRetention', group: 'data', demoKey: 'pricing.value.indefinite', racerKey: 'pricing.value.indefinite', worldClassKey: 'pricing.value.indefinite' },
];

const GROUP_ORDER: Array<'engineer' | 'strategist' | 'data'> = ['engineer', 'strategist', 'data'];
const GROUP_LABEL_KEYS: Record<string, string> = {
  engineer: 'pricing.groupEngineer',
  strategist: 'pricing.groupStrategist',
  data: 'pricing.groupData',
};

export default function PricingPage() {
  const [billing, setBilling] = useState<'monthly' | 'annual'>('annual');
  const { t } = useTranslation();
  const { localizedPlans } = useCurrency();

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
    <PageShell
      eyebrow={t('pricing.eyebrow')}
      title={t('pricing.title')}
      description={t('pricing.description')}
    >
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

      {/* Pricing Table + Venue card */}
      <section className="mb-10 grid grid-cols-1 lg:grid-cols-[3fr_1fr] gap-0">
        <PricingTable
          plans={localizedPlans}
          billingPeriod={billing}
          onCtaClick={(planName) => trackCtaClick(planName, 'pricing', 'b2c')}
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
                    <td className="border border-steel/20 p-2 text-steel">{t(row.featureKey)}</td>
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
    </PageShell>
  );
}
