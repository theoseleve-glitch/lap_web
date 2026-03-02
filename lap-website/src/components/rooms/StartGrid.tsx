'use client';

import { useState } from 'react';
import Link from 'next/link';
import { MonumentText } from '@/components/ui/MonumentText';
import { StartLights } from '@/components/mechanisms/StartLights';
import { useReducedMotion } from '@/hooks/useReducedMotion';
import { trackStartGridComplete, trackCtaClick } from '@/lib/analytics';
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
      className="room relative"
      aria-label="Hero — what is Lap Coach"
    >
      <div className="grid-lap">
        <div className="col-span-full flex flex-col items-center justify-center text-center gap-4 md:gap-6">
          {/* Brand headline — always visible */}
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

          {/* Product subtitle — always visible, explains what the product does */}
          <p className="font-body text-steel text-base md:text-lg max-w-2xl leading-relaxed">
            {t('home.startGrid.subtitle')}
          </p>

          {/* Dual CTAs — always visible */}
          <div className="flex flex-col sm:flex-row items-center gap-3 mt-2">
            <Link
              href="/register?source=free-report&redirect=/free-report/analyze"
              className="inline-flex items-center justify-center min-h-[44px] px-6 py-3 font-telemetry text-xs tracking-[0.12em] uppercase bg-pit-orange border border-pit-orange text-asphalt hover:bg-[#D4B35A] transition-colors duration-200 cursor-pointer"
              onClick={() => trackCtaClick('try_free_report', 'hero', 'b2c')}
            >
              {t('cta.startFreeReport')}
            </Link>
            <Link
              href="/contact?plan=b2b"
              className="inline-flex items-center justify-center min-h-[44px] px-6 py-3 font-telemetry text-xs tracking-[0.12em] uppercase border border-chalk/40 text-chalk hover:border-chalk hover:text-white transition-colors duration-200 cursor-pointer"
              onClick={() => trackCtaClick('book_pilot', 'hero', 'b2b')}
            >
              {t('home.startGrid.ctaVenue')}
            </Link>
          </div>

          {/* Trust micro-strip */}
          <p className="font-telemetry text-steel/60 text-[11px] tracking-widest mt-1">
            {t('home.startGrid.trustStrip')}
          </p>

          {/* F1 start lights — auto-play 5 red lights sequence */}
          <div className="mt-4" aria-hidden="true">
            <StartLights
              onComplete={() => {
                setLightsOut(true);
                trackStartGridComplete();
              }}
              reducedMotion={reducedMotion}
            />
          </div>
        </div>
      </div>
    </section>
  );
}
