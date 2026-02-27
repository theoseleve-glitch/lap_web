'use client';

import { MonumentText } from '@/components/ui/MonumentText';
import { Placard } from '@/components/ui/Placard';
import { useTranslation } from '@/i18n';

export function S2Proof() {
  const { t } = useTranslation();

  const plates = [
    {
      titleKey: 'home.proof.repeatableTitle',
      frontKey: 'home.proof.repeatableFront',
      revealKey: 'home.proof.repeatableReveal',
      stampLabel: 'home.proof.repeatableStampLabel',
      stampDetail: 'home.proof.repeatableStampDetail',
    },
    {
      titleKey: 'home.proof.realisticTitle',
      frontKey: 'home.proof.realisticFront',
      revealKey: 'home.proof.realisticReveal',
      stampLabel: 'home.proof.realisticStampLabel',
      stampDetail: 'home.proof.realisticStampDetail',
    },
    {
      titleKey: 'home.proof.contextTitle',
      frontKey: 'home.proof.contextFront',
      revealKey: 'home.proof.contextReveal',
      stampLabel: 'home.proof.contextStampLabel',
      stampDetail: 'home.proof.contextStampDetail',
    },
  ];

  return (
    <section
      id="s2-proof"
      data-accent="yellow"
      className="room relative py-16 md:py-24"
      aria-label="Sector 2 — Scrutineering and proof"
    >
      <div className="grid-lap">
        <div className="col-span-full text-center mb-4">
          <MonumentText size="h1" as="h2" reveal>
            {t('home.proof.monument')}
          </MonumentText>
        </div>

        <div className="col-span-full text-center mb-12">
          <p className="font-telemetry text-steel">{t('home.proof.subhead')}</p>
        </div>

        <div className="col-span-full grid grid-cols-1 md:grid-cols-3 gap-6">
          {plates.map((plate) => (
            <Placard
              key={plate.titleKey}
              title={t(plate.titleKey)}
              revealContent={
                <p className="text-sm leading-relaxed">{t(plate.revealKey)}</p>
              }
              stamp={{ label: t(plate.stampLabel), detail: t(plate.stampDetail) }}
            >
              <p>{t(plate.frontKey)}</p>
            </Placard>
          ))}
        </div>
      </div>
    </section>
  );
}
