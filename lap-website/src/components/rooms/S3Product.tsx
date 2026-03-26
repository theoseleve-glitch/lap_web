'use client';

import { useState } from 'react';
import Image from 'next/image';
import { MonumentText } from '@/components/ui/MonumentText';
import { useTranslation } from '@/i18n';

/* ── Screenshot tab data ────────────────────────────────── */

interface ScreenTab {
  labelKey: string;
  descKey: string;
  image: string;
  alt: string;
}

const COACHING_TABS: ScreenTab[] = [
  {
    labelKey: 'home.product.coachingTab1Label',
    descKey: 'home.product.coachingTab1Desc',
    image: '/images/screenshots/report-overview.png',
    alt: 'Session score breakdown showing Pace, Consistency, Execution, Robustness, and Adaptation pillars with session info',
  },
  {
    labelKey: 'home.product.coachingTab2Label',
    descKey: 'home.product.coachingTab2Desc',
    image: '/images/screenshots/focus-mode.png',
    alt: 'Focus Mode with track map, GG diagram, speed trace, and lap overlay side by side',
  },
  {
    labelKey: 'home.product.coachingTab3Label',
    descKey: 'home.product.coachingTab3Desc',
    image: '/images/screenshots/lap-data.png',
    alt: 'Performance summary with best time, mean time, consistency, and lap times bar chart',
  },
];

const STRATEGY_TABS: ScreenTab[] = [
  {
    labelKey: 'home.product.strategyTab1Label',
    descKey: 'home.product.strategyTab1Desc',
    image: '/images/screenshots/race-config.png',
    alt: 'Race strategy config with duration, drivers, weights, fuel, and stint timeline',
  },
  {
    labelKey: 'home.product.strategyTab2Label',
    descKey: 'home.product.strategyTab2Desc',
    image: '/images/screenshots/race-stints.png',
    alt: 'Driver summary and stint table with fuel, ballast, and pit lap details',
  },
  {
    labelKey: 'home.product.strategyTab3Label',
    descKey: 'home.product.strategyTab3Desc',
    image: '/images/screenshots/live-dashboard.png',
    alt: 'Live race dashboard with elapsed time, fuel status, current and next driver cards',
  },
];

/* ── Tab viewer component ───────────────────────────────── */

function ScreenTabViewer({
  tabs,
  accent,
  t,
}: {
  tabs: ScreenTab[];
  accent: 'chalk' | 'gold';
  t: (key: string, fallback?: string) => string;
}) {
  const [active, setActive] = useState(0);
  const current = tabs[active];

  const accentBorder = accent === 'gold' ? 'border-gold' : 'border-chalk';
  const accentText = accent === 'gold' ? 'text-gold' : 'text-chalk';
  const accentBg = accent === 'gold' ? 'bg-gold' : 'bg-chalk';

  return (
    <div>
      {/* Screenshot */}
      <div className="relative w-full aspect-video bg-asphalt border border-chalk/15 overflow-hidden mb-3">
        {tabs.map((tab, i) => (
          <div
            key={tab.labelKey}
            className="absolute inset-0 transition-opacity duration-300"
            style={{ opacity: i === active ? 1 : 0 }}
            aria-hidden={i !== active}
          >
            <Image
              src={tab.image}
              alt={tab.alt}
              fill
              sizes="(max-width: 768px) 100vw, 600px"
              className="object-cover object-top"
              priority={i === 0}
            />
          </div>
        ))}
        {/* Label overlay */}
        <div className={`absolute top-2 left-2 font-telemetry text-[10px] tracking-[0.12em] uppercase ${accentText} opacity-80 bg-asphalt/60 px-1.5 py-0.5`}>
          {t(current.labelKey)}
        </div>
        {/* Progress bar */}
        <div
          className={`absolute bottom-0 left-0 h-[2px] ${accentBg} transition-all duration-300`}
          style={{ width: `${((active + 1) / tabs.length) * 100}%` }}
        />
      </div>

      {/* Tab buttons */}
      <div className="flex gap-1 mb-3">
        {tabs.map((tab, i) => (
          <button
            key={tab.labelKey}
            type="button"
            onClick={() => setActive(i)}
            className={`flex-1 py-1.5 px-2 font-telemetry text-[9px] tracking-[0.1em] uppercase transition-colors border ${
              i === active
                ? `${accentBorder} ${accentText}`
                : 'border-steel/20 text-steel hover:text-chalk hover:border-steel/40'
            }`}
          >
            {t(tab.labelKey)}
          </button>
        ))}
      </div>

      {/* Description */}
      <p className="font-body text-steel text-sm leading-relaxed min-h-[3rem]">
        {t(current.descKey)}
      </p>
    </div>
  );
}

/* ── Main section ───────────────────────────────────────── */

export function S3Product() {
  const { t } = useTranslation();

  return (
    <section
      id="s3-product"
      data-accent="green"
      className="room relative py-16 md:py-24"
      aria-label="Sector 3 — The product"
    >
      <div className="grid-lap">
        {/* Monument header */}
        <div className="col-span-full text-center mb-12">
          <MonumentText size="xl" as="h2" reveal>
            {t('home.product.monument')}
          </MonumentText>
        </div>

        {/* Coaching — primary, full width */}
        <div className="col-span-full max-w-4xl mx-auto">
          <div className="border border-chalk/15 p-5">
            <h3 className="font-monument text-xs text-chalk tracking-widest mb-1">
              {t('home.product.coachingSubhead')}
            </h3>
            <p className="font-body text-steel text-sm mb-4">
              {t('home.product.coachingTagline')}
            </p>
            <ScreenTabViewer tabs={COACHING_TABS} accent="chalk" t={t} />
          </div>
        </div>

        {/* Race Day Tools — secondary, narrower */}
        <div className="col-span-full max-w-2xl mx-auto mt-8">
          <p className="font-telemetry text-[10px] text-steel tracking-[0.12em] uppercase mb-3">ALSO INCLUDED</p>
          <div className="border border-steel/20 p-4">
            <h3 className="font-monument text-xs text-gold tracking-widest mb-1">
              {t('home.product.strategySubhead')}
            </h3>
            <p className="font-body text-steel text-sm mb-4">
              {t('home.product.strategyTagline')}
            </p>
            <ScreenTabViewer tabs={STRATEGY_TABS} accent="gold" t={t} />
          </div>
        </div>
      </div>
    </section>
  );
}
