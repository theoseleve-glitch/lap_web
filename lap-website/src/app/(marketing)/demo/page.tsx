'use client';

import { useEffect } from 'react';
import { JsonLd } from '@/components/seo/JsonLd';
import { PageIntro } from '@/components/ui/PageIntro';
import { ReversibleCard } from '@/components/ui/ReversibleCard';
import { DemoCtaSection } from '@/components/marketing/DemoCtaSection';
import { trackDemoFormView } from '@/lib/analytics';
import { useTranslation } from '@/i18n';

export default function DemoPage() {
  const { t } = useTranslation();

  useEffect(() => {
    trackDemoFormView();
  }, []);

  return (
    <>
    <JsonLd pathname="/demo" />
    <main className="mx-auto max-w-6xl px-4 py-10 md:py-14">
      <PageIntro
        eyebrow={t('demo.eyebrow')}
        title={t('demo.title')}
        subtitle={t('demo.description')}
      />
      <section className="max-w-xl mx-auto mb-8">
        <article className="border border-steel/20 bg-concrete/40 p-6">
          <ReversibleCard
            title={t('demo.b2cCardTitle')}
            description={t('demo.b2cCardDesc')}
            className="mb-4"
          />
          <DemoCtaSection />
        </article>
      </section>

      <section className="max-w-xl mx-auto">
        <article className="border border-steel/20 p-4">
          <h2 className="font-monument text-[var(--text-h3)] mb-2">{t('demo.coverageTitle')}</h2>
          <ol className="space-y-2 text-sm text-steel">
            <li>{t('demo.coverage1')}</li>
            <li>{t('demo.coverage2')}</li>
            <li>{t('demo.coverage3')}</li>
          </ol>
        </article>
      </section>
    </main>
    </>
  );
}
