'use client';

import { Suspense, useEffect } from 'react';
import { LeadForm } from '@/components/forms/LeadForm';
import { PageIntro } from '@/components/ui/PageIntro';
import { StatusPill } from '@/components/site/StatusPill';
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
    <main className="mx-auto max-w-6xl px-4 py-10 md:py-14">
      <PageIntro
        eyebrow={t('demo.eyebrow')}
        title={t('demo.title')}
        subtitle={t('demo.description')}
      />
      <section className="grid lg:grid-cols-2 gap-6 mb-8">
        <article className="border border-steel/20 bg-concrete/40 p-5">
          <h2 className="font-monument text-[var(--text-h3)] mb-3">{t('demo.b2cTitle')}</h2>
          <ReversibleCard
            title={t('demo.b2cCardTitle')}
            description={t('demo.b2cCardDesc')}
            className="mb-4"
          />
          <DemoCtaSection />
        </article>

        <article className="border border-steel/20 bg-concrete/40 p-5">
          <h2 className="font-monument text-[var(--text-h3)] mb-3">{t('demo.b2bTitle')}</h2>
          <Suspense fallback={<p className="text-steel text-sm">{t('demo.loadingForm')}</p>}>
            <LeadForm type="demo" submitLabel={t('demo.b2bSubmit')} />
          </Suspense>
        </article>
      </section>

      <section className="grid md:grid-cols-2 gap-4">
        <article className="border border-steel/20 p-4">
          <h2 className="font-monument text-[var(--text-h3)] mb-2">{t('demo.coverageTitle')}</h2>
          <ol className="space-y-2 text-sm text-steel">
            <li>{t('demo.coverage1')}</li>
            <li>{t('demo.coverage2')}</li>
            <li>{t('demo.coverage3')}</li>
          </ol>
        </article>
        <article className="border border-steel/20 p-4">
          <h2 className="font-monument text-[var(--text-h3)] mb-2">{t('demo.capabilityTitle')}</h2>
          <div className="flex flex-wrap gap-2">
            <StatusPill status="available_now" />
            <StatusPill status="enterprise_on_request" />
          </div>
        </article>
      </section>
    </main>
  );
}
