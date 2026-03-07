'use client';

import { MonumentText } from '@/components/ui/MonumentText';
import { ReportScrubber } from '@/components/mechanisms/ReportScrubber';
import { useTranslation } from '@/i18n';

export function S3Product() {
  const { t } = useTranslation();

  const strategyPanels = [
    {
      label: t('home.product.strategyTile1Label'),
      description: t('home.product.strategyTile1Detail'),
      image: '/images/screenshots/dashboard-hero.png',
      alt: 'Race Strategy Dashboard with stint and pit planning widgets',
    },
    {
      label: t('home.product.strategyTile2Label'),
      description: t('home.product.strategyTile2Detail'),
      image: '/images/screenshots/lap-table.png',
      alt: 'Live lap table with pace deltas and stint progress indicators',
    },
    {
      label: t('home.product.strategyTile3Label'),
      description: t('home.product.strategyTile3Detail'),
      image: '/images/screenshots/score-overview.png',
      alt: 'Pit call planning board with projected outcomes and decision support',
    },
  ];

  const coachingTiles = [
    { labelKey: 'home.product.coachingTile1Label', detailKey: 'home.product.coachingTile1Detail' },
    { labelKey: 'home.product.coachingTile2Label', detailKey: 'home.product.coachingTile2Detail' },
    { labelKey: 'home.product.coachingTile3Label', detailKey: 'home.product.coachingTile3Detail' },
  ];

  const strategyTiles = [
    { labelKey: 'home.product.strategyTile1Label', detailKey: 'home.product.strategyTile1Detail' },
    { labelKey: 'home.product.strategyTile2Label', detailKey: 'home.product.strategyTile2Detail' },
    { labelKey: 'home.product.strategyTile3Label', detailKey: 'home.product.strategyTile3Detail' },
  ];

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

        {/* Coaching / Strategy dual columns */}
        <div className="col-span-full grid grid-cols-1 lg:grid-cols-2 gap-6 max-w-5xl mx-auto">
          {/* Coaching Mode — left */}
          <div className="border border-chalk/15 p-6">
            <h3 className="font-monument text-xs text-chalk tracking-widest mb-1">
              {t('home.product.coachingSubhead')}
            </h3>
            <p className="font-body text-steel text-sm mb-6">
              {t('home.product.coachingTagline')}
            </p>

            <ReportScrubber className="mb-6" accentColor="var(--chalk)" />

            <div className="space-y-3">
              {coachingTiles.map((tile) => (
                <div
                  key={tile.labelKey}
                  className="bg-asphalt/40 p-4 border border-steel/10"
                >
                  <h4 className="font-monument text-xs mb-1">{t(tile.labelKey)}</h4>
                  <p className="font-body text-steel text-sm">{t(tile.detailKey)}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Strategy Mode — right */}
          <div className="border border-chalk/15 p-6">
            <h3 className="font-monument text-xs text-gold tracking-widest mb-1">
              {t('home.product.strategySubhead')}
            </h3>
            <p className="font-body text-steel text-sm mb-6">
              {t('home.product.strategyTagline')}
            </p>

            <ReportScrubber
              className="mb-6"
              panels={strategyPanels}
              ariaLabel="Scrub through strategy views"
              accentColor="var(--pit-orange)"
            />

            <div className="space-y-3">
              {strategyTiles.map((tile) => (
                <div
                  key={tile.labelKey}
                  className="bg-asphalt/40 p-4 border border-steel/10"
                >
                  <h4 className="font-monument text-xs mb-1">{t(tile.labelKey)}</h4>
                  <p className="font-body text-steel text-sm">{t(tile.detailKey)}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
