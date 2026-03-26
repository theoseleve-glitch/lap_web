'use client';

import { useState, useCallback } from 'react';
import { MonumentText } from '@/components/ui/MonumentText';
import { RadioCard } from '@/components/ui/RadioCard';
import { CornerDrag } from '@/components/mechanisms/CornerDrag';
import { ReversibleCard } from '@/components/ui/ReversibleCard';
import { colors } from '@/lib/tokens';
import { trackS1CornerInteract } from '@/lib/analytics';
import { useTranslation } from '@/i18n';

export function S1Pain() {
  const [delta, setDelta] = useState(0);
  const [hasInteracted, setHasInteracted] = useState(false);
  const { t } = useTranslation();

  const handleDeltaChange = useCallback((newDelta: number) => {
    setDelta(newDelta);
    if (!hasInteracted && newDelta !== 0) {
      setHasInteracted(true);
    }
    trackS1CornerInteract(newDelta);
  }, [hasInteracted]);

  return (
    <section
      id="s1-pain"
      data-accent="green"
      className="room relative py-16 md:py-24"
      aria-label="Sector 1 — Why time is lost"
    >
      <div className="grid-lap">
        <div className="col-span-full md:col-span-6 flex flex-col justify-center gap-6">
          <MonumentText size="h1" as="h2" reveal>
            {t('home.pain.monument1')}<br />{t('home.pain.monument2')}
          </MonumentText>

          <ReversibleCard
            title={t('home.pain.cardTitle')}
            description={t('home.pain.body')}
            className="max-w-lg"
          />

          <div className="flex flex-col gap-2 mt-2">
            <RadioCard label="ENTRY">
              {t('home.pain.tooltipEntry')}
            </RadioCard>
            <RadioCard label="APEX">
              {t('home.pain.tooltipApex')}
            </RadioCard>
            <RadioCard label="EXIT">
              {t('home.pain.tooltipExit')}
            </RadioCard>
          </div>

        </div>

        <div className="col-span-full md:col-span-6 flex flex-col items-center justify-center gap-4">
          <CornerDrag onDeltaChange={handleDeltaChange} />

          {/* Live delta readout */}
          <div
            className="font-monument text-[var(--text-h2)] text-center"
            style={{ color: delta <= 0 ? colors.acidGreen : colors.safetyRed }}
            aria-live="polite"
            aria-label={`Corner delta: ${delta >= 0 ? '+' : ''}${delta.toFixed(2)} seconds`}
          >
            {delta >= 0 ? '+' : ''}{delta.toFixed(2)}s
          </div>

          <p className="font-telemetry text-steel text-center">
            {t('home.pain.dragHint')}
          </p>
        </div>
      </div>
    </section>
  );
}
