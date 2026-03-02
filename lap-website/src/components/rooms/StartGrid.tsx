'use client';

import { useState } from 'react';
import { MonumentText } from '@/components/ui/MonumentText';
import { StartLights } from '@/components/mechanisms/StartLights';
import { useReducedMotion } from '@/hooks/useReducedMotion';
import { trackStartGridComplete } from '@/lib/analytics';
import { colors } from '@/lib/tokens';
import { useTranslation } from '@/i18n';

export function StartGrid() {
  const [lightsOut, setLightsOut] = useState(false);
  const { reducedMotion } = useReducedMotion();
  const { t } = useTranslation();

  return (
    <section
      id="start-grid"
      data-accent="none"
      className="relative min-h-[calc(100vh-3rem)] flex items-center justify-center"
      aria-label="Hero — what is Lap Coach"
    >
      <div className="flex flex-col items-center justify-center text-center gap-3">
        {/* Brand headline */}
        <MonumentText size="xl" as="h1" className="text-center">
          <span className="text-shimmer">
            {t('home.startGrid.heading1')}
          </span>{' '}
          <span
            style={{
              color: colors.safetyRed,
              textShadow: `0 0 20px ${colors.safetyRed}80, 0 0 50px ${colors.safetyRed}40`,
            }}
          >
            {t('home.startGrid.heading2')}
          </span>
          <br />
          <span className="text-shimmer">
            {t('home.startGrid.heading3')}
          </span>
        </MonumentText>

        {/* F1 start lights — auto-play 5 red lights sequence */}
        <div aria-hidden="true">
          <StartLights
            onComplete={() => {
              setLightsOut(true);
              trackStartGridComplete();
            }}
            reducedMotion={reducedMotion}
          />
        </div>
      </div>
    </section>
  );
}
