'use client';

import Link from 'next/link';
import { PageShell } from '@/components/site/PageShell';
import { WorkflowCoverage } from '@/components/site/WorkflowCoverage';
import { ScreenshotGallery } from '@/components/site/ScreenshotGallery';
import { useTranslation } from '@/i18n';

export default function ProductPage() {
  const { t } = useTranslation();

  const engineerScreenshots = [
    { title: 'Score Overview', description: 'Pace, Consistency, Execution, Robustness — each scored /25.', src: '/images/screenshots/score-overview.png' },
    { title: 'Corner Replay', description: 'Entry, apex, and exit traces to spot where the lap was won or lost.', src: '/images/screenshots/corner-replay.png' },
    { title: 'Session Intelligence', description: 'Overview, Corners, Timeline, Analytics, and Lap Data tabs.', src: '/images/screenshots/score-overview.png' },
    { title: 'Comparison Suite', description: 'Session-vs-session and driver-vs-driver overlays.', src: '/images/screenshots/corner-replay.png' },
  ];

  const strategistScreenshots = [
    { title: 'Race Strategy Dashboard', description: 'Live operational board for stint calls and pit-window decisions.', src: '/images/screenshots/dashboard-hero.png' },
    { title: 'Live Monitoring', description: 'Real-time pace deltas and stint progress.', src: '/images/screenshots/lap-table.png' },
    { title: 'Pit Stop Planning', description: 'Plan pit windows based on fuel, tire, and driver rotation.', src: '/images/screenshots/dashboard-hero.png' },
    { title: 'Lap Analysis Table', description: 'Detailed lap-by-lap data with sector splits.', src: '/images/screenshots/lap-table.png' },
  ];

  return (
    <PageShell
      eyebrow={t('product.eyebrow')}
      title={t('product.title')}
      description={t('product.description')}
    >
      <section className="mb-10">
        <WorkflowCoverage />
      </section>

      <section className="mb-10">
        <h2 className="font-monument text-[var(--text-h2)] mb-2 text-acid-green">{t('product.engineer.title', 'Engineer Mode')}</h2>
        <p className="text-steel mb-4">{t('product.engineer.subtitle', 'Upload. Score. Coach. Compare. Visualize.')}</p>
        <ScreenshotGallery items={engineerScreenshots} accentColor="var(--color-acid-green)" />
      </section>

      <section className="mb-10">
        <h2 className="font-monument text-[var(--text-h2)] mb-2 text-pit-orange">{t('product.strategist.title', 'Strategist Mode')}</h2>
        <p className="text-steel mb-4">{t('product.strategist.subtitle', 'Control Room. Live Monitoring. Pit Planning. Incidents.')}</p>
        <ScreenshotGallery items={strategistScreenshots} accentColor="var(--color-pit-orange)" />
      </section>

      <section className="mb-10 border border-steel/20 bg-concrete/20 p-5">
        <h2 className="font-monument text-[var(--text-h3)] mb-3">{t('product.connectTitle')}</h2>
        <p className="text-steel text-sm leading-relaxed">
          {t('product.connectBody')}
        </p>
      </section>

      <section className="mt-10 border border-steel/20 p-5 bg-concrete/20">
        <h2 className="font-monument text-[var(--text-h3)] mb-2">{t('product.nextActions')}</h2>
        <div className="flex flex-wrap gap-3">
          <Link href="/demo" className="border border-pit-orange px-4 py-2 text-sm">
            {t('cta.tryDemo')}
          </Link>
          <Link href="/pricing" className="border border-steel/30 px-4 py-2 text-sm">
            {t('cta.comparePlans')}
          </Link>
          <Link href="/contact" className="border border-steel/30 px-4 py-2 text-sm">
            {t('cta.contactSales')}
          </Link>
        </div>
      </section>
    </PageShell>
  );
}
