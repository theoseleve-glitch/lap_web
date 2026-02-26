'use client';

import { useState, useEffect, useRef } from 'react';
import { MonumentText } from '@/components/ui/MonumentText';
import { PitButton } from '@/components/ui/PitButton';
import { StampButton } from '@/components/ui/StampButton';
import { podium } from '@/data/copy';
import { trackCtaClick, trackPodiumReach, trackRestartLap } from '@/lib/analytics';
import { getVariantForKey } from '@/lib/experiments';

export function Podium() {
  const [showRestart, setShowRestart] = useState(false);
  const [ctaVariant, setCtaVariant] = useState<'demo_first' | 'book_first'>('demo_first');
  const trackedRef = useRef(false);
  const startTimeRef = useRef(Date.now());

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

  const handleRestart = async () => {
    trackRestartLap();
    const { gsap } = await import('gsap');
    const { ScrollToPlugin } = await import('gsap/ScrollToPlugin');
    gsap.registerPlugin(ScrollToPlugin);
    gsap.to(window, {
      scrollTo: 0,
      duration: 1.4,
      ease: 'power3.out',
    });
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
            {podium.monument[0]}<br />{podium.monument[1]}
          </MonumentText>

          <div className="flex flex-col sm:flex-row items-center gap-4">
            {ctaVariant === 'book_first' ? (
              <>
                <PitButton
                  href="/book"
                  onClick={() => trackCtaClick('book', 'podium', 'mixed')}
                >
                  BOOK NOW
                </PitButton>
                <StampButton
                  href="/demo"
                  onClick={() => trackCtaClick('try_demo', 'podium', 'mixed')}
                >
                  {podium.ctaPrimary}
                </StampButton>
              </>
            ) : (
              <>
                <PitButton
                  href="/demo"
                  onClick={() => trackCtaClick('try_demo', 'podium', 'b2c')}
                >
                  {podium.ctaPrimary}
                </PitButton>
                <StampButton
                  href="/contact"
                  onClick={() => trackCtaClick('talk', 'podium', 'b2b')}
                >
                  {podium.ctaSecondary}
                </StampButton>
              </>
            )}
          </div>

          <p className="font-telemetry text-steel max-w-lg">
            {podium.subtext}
          </p>

          {showRestart && (
            <button
              className="font-telemetry text-steel/50 hover:text-steel transition-opacity duration-[420ms] mt-8"
              onClick={handleRestart}
            >
              {podium.restart}
            </button>
          )}
        </div>
      </div>
    </section>
  );
}
