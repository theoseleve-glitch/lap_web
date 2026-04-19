'use client';

import { useEffect, useRef } from 'react';
import Link from 'next/link';
import { MonumentText } from '@/components/ui/MonumentText';
import { trackCtaClick, trackPodiumReach } from '@/lib/analytics';
import { useMagnetic } from '@/hooks/useMagnetic';

export function Podium() {
  const trackedRef = useRef(false);
  const startTimeRef = useRef(Date.now());
  const magneticRef = useMagnetic<HTMLAnchorElement>();

  useEffect(() => {
    if (trackedRef.current) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !trackedRef.current) {
          trackedRef.current = true;
          trackPodiumReach(Date.now() - startTimeRef.current, 10);
        }
      },
      { threshold: 0.5 },
    );

    const el = document.getElementById('podium');
    if (el) observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return (
    <section
      id="podium"
      data-accent="none"
      className="relative py-24 md:py-32"
      aria-label="Final CTA"
    >
      <div className="grid-lap">
        <div className="col-span-full flex flex-col items-center justify-center text-center gap-6">
          <MonumentText size="xl" as="h2" split>
            YOUR DRIVING<br />
            <span className="text-gold mix-blend-difference">DESERVES BETTER</span><br />
            THAN GUESSWORK.
          </MonumentText>

          <p className="font-body text-body text-steel max-w-prose">
            Run a lap. Get your report. See what changes.
          </p>

          <Link
            ref={magneticRef}
            href="/register?source=podium"
            data-cursor="GO"
            className="cta-glow inline-flex items-center justify-center min-h-[48px] px-10 py-4 bg-gold text-white font-telemetry text-[12px] tracking-[0.12em] uppercase font-bold transition-all duration-[420ms] hover:brightness-110 hover:shadow-[0_0_32px_rgba(201,168,76,0.25)] mt-4"
            onClick={() => trackCtaClick('start_free', 'podium', 'b2c')}
          >
            Start free — try the demo dashboard
          </Link>

        </div>
      </div>
    </section>
  );
}
