'use client';

import { Suspense } from 'react';
import { LeadForm } from '@/components/forms/LeadForm';
import { PageShell } from '@/components/site/PageShell';
import { useTranslation } from '@/i18n';

export default function BookPage() {
  const { t } = useTranslation();

  return (
    <PageShell
      eyebrow={t('book.eyebrow')}
      title={t('book.title')}
      description={t('book.description')}
    >
      <section className="grid lg:grid-cols-[2fr_1fr] gap-6">
        <article className="border border-steel/20 bg-concrete/40 p-5">
          <Suspense fallback={<p className="text-steel text-sm">{t('book.loadingForm')}</p>}>
            <LeadForm type="book" submitLabel={t('book.submitLabel')} />
          </Suspense>
        </article>
        <aside className="border border-steel/20 p-4 bg-concrete/20">
          <h2 className="font-monument text-[var(--text-h3)] mb-2">{t('book.coverageTitle')}</h2>
          <ul className="space-y-2 text-sm text-steel">
            <li>{t('book.coverage1')}</li>
            <li>{t('book.coverage2')}</li>
            <li>{t('book.coverage3')}</li>
            <li>{t('book.coverage4')}</li>
          </ul>
        </aside>
      </section>
    </PageShell>
  );
}
