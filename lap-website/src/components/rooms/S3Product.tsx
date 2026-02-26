'use client';

import { useState, useCallback } from 'react';
import { MonumentText } from '@/components/ui/MonumentText';
import { ModeSelector } from '@/components/ui/ModeSelector';
import { Placard } from '@/components/ui/Placard';
import { StampButton } from '@/components/ui/StampButton';
import { ReportScrubber } from '@/components/mechanisms/ReportScrubber';
import { s3Product } from '@/data/copy';
import { trackS3ModeSelect, trackCtaClick } from '@/lib/analytics';

export function S3Product() {
  const [mode, setMode] = useState<'b2c' | 'b2b'>('b2c');

  const handleModeChange = useCallback((newMode: 'b2c' | 'b2b') => {
    setMode(newMode);
    trackS3ModeSelect(newMode);
  }, []);

  return (
    <section
      id="s3-product"
      data-accent="green"
      className="room relative py-16 md:py-24"
      aria-label="Sector 3 — The product"
    >
      <div className="grid-lap">
        <div className="col-span-full text-center mb-8">
          <MonumentText size="xl" as="h2" reveal>
            {s3Product.monument}
          </MonumentText>
        </div>

        <div className="col-span-full flex justify-center mb-12">
          <ModeSelector value={mode} onChange={handleModeChange} />
        </div>

        {/* B2C Content */}
        <div
          className="col-span-full transition-opacity duration-[420ms]"
          style={{ display: mode === 'b2c' ? 'block' : 'none' }}
        >
          <p className="font-telemetry text-steel text-center mb-8">{s3Product.b2c.subhead}</p>

          <ReportScrubber className="max-w-3xl mx-auto mb-8" />

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 max-w-3xl mx-auto">
            {s3Product.b2c.tiles.map((tile) => (
              <div key={tile.label} className="bg-concrete p-6 border border-steel/20">
                <h4 className="font-monument text-[var(--text-h3)] mb-2">{tile.label}</h4>
                <p className="font-body text-steel text-sm">{tile.detail}</p>
              </div>
            ))}
          </div>
        </div>

        {/* B2B Content */}
        <div
          className="col-span-full transition-opacity duration-[420ms]"
          style={{ display: mode === 'b2b' ? 'block' : 'none' }}
        >
          <p className="font-telemetry text-steel text-center mb-8">{s3Product.b2b.subhead}</p>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 max-w-3xl mx-auto mb-8">
            {s3Product.b2b.placards.map((placard) => (
              <Placard key={placard.title} title={placard.title}>
                <p>{placard.body}</p>
              </Placard>
            ))}
          </div>

          <div className="text-center">
            <StampButton onClick={() => trackCtaClick('request_pilot', 's3', 'b2b')}>
              {s3Product.b2b.cta}
            </StampButton>
          </div>
        </div>
      </div>
    </section>
  );
}
