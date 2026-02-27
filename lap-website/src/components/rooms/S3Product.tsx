'use client';

import { MonumentText } from '@/components/ui/MonumentText';
import { ReportScrubber } from '@/components/mechanisms/ReportScrubber';
import { s3Product } from '@/data/copy';

export function S3Product() {
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
            {s3Product.monument}
          </MonumentText>
        </div>

        {/* Engineer / Strategist dual columns */}
        <div className="col-span-full grid grid-cols-1 lg:grid-cols-2 gap-6 max-w-5xl mx-auto">
          {/* Engineer Mode — left */}
          <div className="border border-steel/20 p-6">
            <h3 className="font-monument text-xs text-acid-green tracking-widest mb-1">
              {s3Product.engineer.subhead}
            </h3>
            <p className="font-body text-steel text-sm mb-6">
              {s3Product.engineer.tagline}
            </p>

            <ReportScrubber className="mb-6" />

            <div className="space-y-3">
              {s3Product.engineer.tiles.map((tile) => (
                <div
                  key={tile.label}
                  className="bg-asphalt/40 p-4 border border-steel/10"
                >
                  <h4 className="font-monument text-xs mb-1">{tile.label}</h4>
                  <p className="font-body text-steel text-sm">{tile.detail}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Strategist Mode — right */}
          <div className="border border-steel/20 p-6">
            <h3 className="font-monument text-xs text-pit-orange tracking-widest mb-1">
              {s3Product.strategist.subhead}
            </h3>
            <p className="font-body text-steel text-sm mb-6">
              {s3Product.strategist.tagline}
            </p>

            <div className="space-y-3">
              {s3Product.strategist.tiles.map((tile) => (
                <div
                  key={tile.label}
                  className="bg-asphalt/40 p-4 border border-steel/10"
                >
                  <h4 className="font-monument text-xs mb-1">{tile.label}</h4>
                  <p className="font-body text-steel text-sm">{tile.detail}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
