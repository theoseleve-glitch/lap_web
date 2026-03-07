'use client';

import { Suspense } from 'react';
import { LeadForm } from '@/components/forms/LeadForm';
import { PageIntro } from '@/components/ui/PageIntro';
import { useTranslation } from '@/i18n';

export default function ContactPage() {
  const { t } = useTranslation();

  return (
    <main className="mx-auto max-w-6xl px-4 py-10 md:py-14">
      <PageIntro
        eyebrow={t('contact.eyebrow')}
        title={t('contact.title')}
        subtitle={t('contact.description')}
      />
      <section className="grid lg:grid-cols-[2fr_1fr] gap-6">
        <article className="border border-steel/20 bg-concrete/40 p-5">
          <Suspense fallback={<p className="text-steel text-sm">{t('contact.loadingForm')}</p>}>
            <LeadForm type="contact" submitLabel={t('contact.submitLabel')} />
          </Suspense>
        </article>
        <aside className="border border-steel/20 p-4 bg-concrete/20">
          <h2 className="font-monument text-[var(--text-h3)] mb-2">{t('contact.responseTitle')}</h2>
          <ul className="space-y-2 text-sm text-steel">
            <li>{t('contact.response1')}</li>
            <li>{t('contact.response2')}</li>
            <li>{t('contact.response3')}</li>
          </ul>
        </aside>
      </section>
    </main>
  );
}
