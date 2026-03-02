'use client';

import { useState, useCallback } from 'react';
import { MonumentText } from '@/components/ui/MonumentText';
import { trackGaragePanelExpand } from '@/lib/analytics';
import { useTranslation } from '@/i18n';

export function Garage() {
  const [openPanel, setOpenPanel] = useState<number | null>(null);
  const { t } = useTranslation();

  const panels = [
    { titleKey: 'home.garage.stackTitle', contentKey: 'home.garage.stackContent' },
    { titleKey: 'home.garage.dataTitle', contentKey: 'home.garage.dataContent' },
    { titleKey: 'home.garage.methodTitle', contentKey: 'home.garage.methodContent' },
    { titleKey: 'home.garage.privacyTitle', contentKey: 'home.garage.privacyContent' },
  ];

  const togglePanel = useCallback((index: number) => {
    const next = openPanel === index ? null : index;
    setOpenPanel(next);
    if (next !== null) trackGaragePanelExpand(t(panels[next].titleKey));
  }, [openPanel, t, panels]);

  return (
    <section
      id="garage"
      data-accent="none"
      className="relative py-16 md:py-24"
      style={{
        minHeight: '100vh',
        backgroundImage: `
          linear-gradient(rgba(240, 237, 229, 0.04) 1px, transparent 1px),
          linear-gradient(90deg, rgba(240, 237, 229, 0.04) 1px, transparent 1px)
        `,
        backgroundSize: '48px 48px',
      }}
      aria-label="Garage — Technical documentation"
    >
      <div className="grid-lap">
        <div className="col-span-full text-center mb-4">
          <MonumentText size="h1" as="h2">
            {t('home.garage.monument')}
          </MonumentText>
        </div>
        <div className="col-span-full text-center mb-12">
          <p className="font-telemetry text-steel">{t('home.garage.subhead')}</p>
        </div>

        <div className="col-span-full max-w-3xl mx-auto">
          {panels.map((panel, i) => (
            <div key={panel.titleKey} className="border-b border-chalk/15">
              <button
                className="w-full flex items-center justify-between py-4 text-left font-monument text-[var(--text-h3)] hover:text-chalk transition-colors duration-300"
                onClick={() => togglePanel(i)}
                aria-expanded={openPanel === i}
              >
                {t(panel.titleKey)}
                <span
                  className="text-steel text-xl transition-transform duration-[420ms]"
                  style={{ transform: openPanel === i ? 'rotate(45deg)' : 'rotate(0deg)' }}
                >
                  +
                </span>
              </button>
              <div
                className="grid transition-all duration-[420ms] ease-[cubic-bezier(0.16,1,0.3,1)]"
                style={{ gridTemplateRows: openPanel === i ? '1fr' : '0fr' }}
              >
                <div className="overflow-hidden">
                  <div className="pb-6 font-telemetry text-steel text-[11px] tracking-[0.12em] leading-relaxed whitespace-pre-line">
                    {t(panel.contentKey)}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
