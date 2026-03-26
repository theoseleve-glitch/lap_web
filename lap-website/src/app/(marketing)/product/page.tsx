'use client';

import Link from 'next/link';
import { JsonLd } from '@/components/seo/JsonLd';
import { PageIntro } from '@/components/ui/PageIntro';
import { WorkflowCoverage } from '@/components/site/WorkflowCoverage';
import { ScreenshotGallery } from '@/components/site/ScreenshotGallery';
import { useTranslation } from '@/i18n';
import { RelatedPages } from '@/components/marketing/RelatedPages';
import { SocialShare } from '@/components/marketing/SocialShare';

export default function ProductPage() {
  const { t } = useTranslation();

  const coachingScreenshots = [
    {
      title: t('product.coaching.scoreTitle', 'Score Breakdown'),
      description: t('product.coaching.scoreDesc', 'Five pillars — Pace, Consistency, Execution, Robustness, Adaptation — scored with color-coded bars and a session grade.'),
      src: '/images/screenshots/report-overview.png',
    },
    {
      title: t('product.coaching.focusTitle', 'Focus Mode'),
      description: t('product.coaching.focusDesc', 'Track map, GG diagram, speed trace, and lap overlay in one immersive split-screen view. Keyboard-driven navigation.'),
      src: '/images/screenshots/focus-mode.png',
    },
    {
      title: t('product.coaching.lapDataTitle', 'Lap Data'),
      description: t('product.coaching.lapDataDesc', 'Best time, mean, median, consistency CV — plus a full lap-by-lap bar chart with best lap highlighted in green.'),
      src: '/images/screenshots/lap-data.png',
    },
    {
      title: t('product.coaching.vizTitle', 'Visualization'),
      description: t('product.coaching.vizDesc', 'Speed-colored track map with synchronized speed trace and GG diagram. Hover any point to see all charts update together.'),
      src: '/images/screenshots/visualization.png',
    },
    {
      title: t('product.coaching.dashTitle', 'Dashboard'),
      description: t('product.coaching.dashDesc', 'Your telemetry overview — sessions, drivers, tracks, total laps, personal best, and score trends at a glance.'),
      src: '/images/screenshots/main-dash.png',
    },
  ];

  const strategyScreenshots = [
    {
      title: t('product.strategy.configTitle', 'Race Configuration'),
      description: t('product.strategy.configDesc', 'Set race duration, stints, pit stop time, fuel autonomy, and build your full driver roster with weights and constraints.'),
      src: '/images/screenshots/race-config.png',
    },
    {
      title: t('product.strategy.stintsTitle', 'Stint Planning'),
      description: t('product.strategy.stintsDesc', 'Driver summary with share %, estimated laps, and average stint time. Detailed stint table with fuel start/end, ballast, and pit lap targets.'),
      src: '/images/screenshots/race-stints.png',
    },
    {
      title: t('product.strategy.liveTitle', 'Live Dashboard'),
      description: t('product.strategy.liveDesc', 'Elapsed and remaining timers, fuel level with burn rate, current and next driver cards with stint progress bars. Pit In, Re-Optimize, Pause, and Tech Stop controls.'),
      src: '/images/screenshots/live-dashboard.png',
    },
  ];

  return (
    <>
    <JsonLd pathname="/product" softwareApp organization />
    <main className="mx-auto max-w-6xl px-4 py-10 md:py-14">
      <PageIntro
        eyebrow={t('product.eyebrow')}
        title={t('product.title')}
        subtitle={t('product.description')}
      />
      <section className="mb-10">
        <WorkflowCoverage />
      </section>

      <section className="mb-10">
        <h2 className="font-monument text-[var(--text-h2)] mb-2 text-acid-green">{t('product.coaching.title', 'Coaching Mode')}</h2>
        <p className="text-steel mb-4">{t('product.coaching.subtitle', 'Upload. Score. Fix. Drill. Improve.')}</p>
        <ScreenshotGallery items={coachingScreenshots} accentColor="var(--color-acid-green)" />
      </section>

      <section className="mb-10">
        <p className="font-telemetry text-[10px] text-steel tracking-[0.12em] uppercase mb-3">ALSO INCLUDED</p>
        <h2 className="font-monument text-[var(--text-h2)] mb-2 text-gold">{t('product.strategy.title', 'Race Day Tools')}</h2>
        <p className="text-steel mb-4">{t('product.strategy.subtitle', 'Stint plans. Fuel tracking. Pit timing. Your race, organized.')}</p>
        <ScreenshotGallery items={strategyScreenshots} accentColor="var(--color-pit-orange)" />
      </section>

      <section className="mt-10 border border-steel/20 p-5 bg-concrete/20">
        <h2 className="font-monument text-[var(--text-h3)] mb-2">{t('product.nextActions')}</h2>
        <div className="flex flex-wrap gap-3">
          <Link href="/register?source=product" className="border border-pit-orange px-4 py-2 text-sm font-telemetry text-xs tracking-[0.12em] uppercase text-gold hover:bg-gold hover:text-white transition-colors">
            {t('cta.startFreeReport')}
          </Link>
          <Link href="/pricing" className="border border-steel/30 px-4 py-2 text-sm font-telemetry text-xs tracking-[0.12em] uppercase text-chalk hover:bg-concrete transition-colors">
            {t('cta.comparePlans')}
          </Link>
        </div>
      </section>

      <SocialShare title="LAP — Motorsport Telemetry Analysis" className="mb-8" />
      <RelatedPages pathname="/product" />
    </main>
    </>
  );
}
