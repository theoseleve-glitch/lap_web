'use client';

import { MonumentText } from '@/components/ui/MonumentText';
import { ReportScrubber } from '@/components/mechanisms/ReportScrubber';
import { useTranslation } from '@/i18n';

export function S3Product() {
  const { t } = useTranslation();

  const engineerTiles = [
    { labelKey: 'home.product.engineerTile1Label', detailKey: 'home.product.engineerTile1Detail' },
    { labelKey: 'home.product.engineerTile2Label', detailKey: 'home.product.engineerTile2Detail' },
    { labelKey: 'home.product.engineerTile3Label', detailKey: 'home.product.engineerTile3Detail' },
  ];

  const strategistTiles = [
    { labelKey: 'home.product.strategistTile1Label', detailKey: 'home.product.strategistTile1Detail' },
    { labelKey: 'home.product.strategistTile2Label', detailKey: 'home.product.strategistTile2Detail' },
    { labelKey: 'home.product.strategistTile3Label', detailKey: 'home.product.strategistTile3Detail' },
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

        {/* Engineer / Strategist dual columns */}
        <div className="col-span-full grid grid-cols-1 lg:grid-cols-2 gap-6 max-w-5xl mx-auto">
          {/* Engineer Mode — left */}
          <div className="border border-steel/20 p-6">
            <h3 className="font-monument text-xs text-acid-green tracking-widest mb-1">
              {t('home.product.engineerSubhead')}
            </h3>
            <p className="font-body text-steel text-sm mb-6">
              {t('home.product.engineerTagline')}
            </p>

            <ReportScrubber className="mb-6" />

            <div className="space-y-3">
              {engineerTiles.map((tile) => (
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

          {/* Strategist Mode — right */}
          <div className="border border-steel/20 p-6">
            <h3 className="font-monument text-xs text-pit-orange tracking-widest mb-1">
              {t('home.product.strategistSubhead')}
            </h3>
            <p className="font-body text-steel text-sm mb-6">
              {t('home.product.strategistTagline')}
            </p>

            <div className="space-y-3">
              {strategistTiles.map((tile) => (
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
