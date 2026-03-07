'use client';

import { useState, useEffect, useRef } from 'react';
import { MonumentText } from '@/components/ui/MonumentText';
import { PitButton } from '@/components/ui/PitButton';
import { StampButton } from '@/components/ui/StampButton';
import { trackCtaClick, trackDemoCtaClick, trackPodiumReach, trackRestartLap } from '@/lib/analytics';
import { getVariantForKey } from '@/lib/experiments';
import { useTranslation } from '@/i18n';

export function Podium() {
  const [showRestart, setShowRestart] = useState(false);
  const [ctaVariant, setCtaVariant] = useState<'demo_first' | 'book_first'>('demo_first');
  const trackedRef = useRef(false);
  const startTimeRef = useRef(Date.now());
  const { t } = useTranslation();

  useEffect(() => {
    const variant = getVariantForKey('cta', 'demo_first');
    setCtaVariant(variant === 'book_first' ? 'book_first' : 'demo_first');
  }, []);

  // Track podium reach
  useEffect(() => {
    if (trackedRef.current) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !trackedRef.current) {
          trackedRef.current = true;
          trackPodiumReach(Date.now() - startTimeRef.current, 11);
        }
      },
      { threshold: 0.5 },
    );

    const el = document.getElementById('podium');
    if (el) observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // Show restart after 3s
  useEffect(() => {
    const timer = setTimeout(() => setShowRestart(true), 3000);
    return () => clearTimeout(timer);
  }, []);

  const handleRestart = () => {
    trackRestartLap();
    // Lenis intercepts native smooth scroll
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  return (
    <section
      id="podium"
      data-accent="orange"
      className="room relative py-16 md:py-24"
      aria-label="Podium — Final action"
    >
      <div className="grid-lap">
        <div className="col-span-full flex flex-col items-center justify-center text-center gap-8">
          <MonumentText size="xl" as="h2" reveal>
            {t('home.podium.monument1')}<br />{t('home.podium.monument2')}
          </MonumentText>

          <div className="flex flex-col sm:flex-row items-center gap-4">
            {ctaVariant === 'book_first' ? (
              <>
                <PitButton
                  href="/book"
                  onClick={() => trackCtaClick('book', 'podium', 'mixed')}
                >
                  {t('cta.bookNow')}
                </PitButton>
                <StampButton
                  href="/demo"
                  onClick={() => { trackCtaClick('try_demo', 'podium', 'mixed'); trackDemoCtaClick('podium'); }}
                >
                  {t('cta.tryDemo')}
                </StampButton>
              </>
            ) : (
              <>
                <PitButton
                  href="/register?source=free-report&redirect=/free-report/analyze"
                  onClick={() => trackCtaClick('start_free_report', 'podium', 'b2c')}
                >
                  {t('cta.startFreeReport')}
                </PitButton>
                <StampButton
                  href="/contact"
                  onClick={() => trackCtaClick('talk', 'podium', 'b2b')}
                >
                  {t('cta.talkToSales')}
                </StampButton>
              </>
            )}
          </div>

          <p className="font-telemetry text-steel max-w-lg">
            {t('home.podium.subtext')}
          </p>

          {showRestart && (
            <button
              className="font-telemetry text-steel/50 hover:text-steel transition-opacity duration-[420ms] mt-8"
              onClick={handleRestart}
            >
              {t('home.podium.restart')}
            </button>
          )}
        </div>
      </div>
    </section>
  );
}
