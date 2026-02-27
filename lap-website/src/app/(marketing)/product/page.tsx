'use client';

import Link from 'next/link';
import { PageShell } from '@/components/site/PageShell';
import { WorkflowCoverage } from '@/components/site/WorkflowCoverage';
import { ReversibleCard } from '@/components/ui/ReversibleCard';
import { useTranslation } from '@/i18n';

export default function ProductPage() {
  const { t } = useTranslation();

  const engineerViews = [
    {
      titleKey: 'product.engineerView1Title',
      descKey: 'product.engineerView1Desc',
      image: '/images/screenshots/corner-replay.png',
    },
    {
      titleKey: 'product.engineerView2Title',
      descKey: 'product.engineerView2Desc',
      image: '/images/screenshots/score-overview.png',
    },
  ];

  const strategistViews = [
    {
      titleKey: 'product.strategistView1Title',
      descKey: 'product.strategistView1Desc',
      image: '/images/screenshots/dashboard-hero.png',
    },
    {
      titleKey: 'product.strategistView2Title',
      descKey: 'product.strategistView2Desc',
      image: '/images/screenshots/lap-table.png',
    },
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
        <h2 className="font-monument text-[var(--text-h2)] mb-2 text-acid-green">{t('product.engineerTitle')}</h2>
        <p className="text-steel mb-4">{t('product.engineerSubtitle')}</p>
        <div className="grid md:grid-cols-2 gap-4">
          {engineerViews.map((view) => (
            <article key={view.titleKey} className="border border-steel/20 bg-concrete/30 p-4">
              <img src={view.image} alt={t(view.titleKey)} className="w-full h-52 object-cover mb-3 border border-steel/20" />
              <ReversibleCard title={t(view.titleKey)} description={t(view.descKey)} />
            </article>
          ))}
        </div>
      </section>

      <section className="mb-10">
        <h2 className="font-monument text-[var(--text-h2)] mb-2 text-pit-orange">{t('product.strategistTitle')}</h2>
        <p className="text-steel mb-4">{t('product.strategistSubtitle')}</p>
        <div className="grid md:grid-cols-2 gap-4">
          {strategistViews.map((view) => (
            <article key={view.titleKey} className="border border-steel/20 bg-concrete/30 p-4">
              <img src={view.image} alt={t(view.titleKey)} className="w-full h-52 object-cover mb-3 border border-steel/20" />
              <ReversibleCard title={t(view.titleKey)} description={t(view.descKey)} />
            </article>
          ))}
        </div>
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
