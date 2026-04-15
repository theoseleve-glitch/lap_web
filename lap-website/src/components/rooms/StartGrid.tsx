'use client';

import { useEffect, useRef } from 'react';
import Link from 'next/link';
import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { MonumentText } from '@/components/ui/MonumentText';
import { trackCtaClick } from '@/lib/analytics';
import { useMagnetic } from '@/hooks/useMagnetic';
import { useReducedMotion } from '@/hooks/useReducedMotion';

gsap.registerPlugin(ScrollTrigger);

export function StartGrid() {
  const sectionRef = useRef<HTMLElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const productCardRef = useRef<HTMLDivElement>(null);
  const ctaRef = useMagnetic<HTMLAnchorElement>();
  const secondaryCtaRef = useMagnetic<HTMLAnchorElement>({ strength: 0.2 });
  const { reducedMotion } = useReducedMotion();

  // Scroll-scrubbed parallax on entire hero
  useEffect(() => {
    if (reducedMotion || !sectionRef.current || !contentRef.current || !productCardRef.current) return;

    const tl = gsap.timeline({
      scrollTrigger: {
        trigger: sectionRef.current,
        start: 'top top',
        end: 'bottom top',
        scrub: 1.5,
      },
    });

    tl.to(contentRef.current, {
      y: -120,
      opacity: 0.2,
      scale: 0.95,
      ease: 'none',
    }, 0);

    tl.to(productCardRef.current, {
      y: -60,
      opacity: 0,
      ease: 'none',
    }, 0);

    // Staggered entrance for non-headline elements
    const elements = contentRef.current.querySelectorAll('[data-hero-stagger]');
    gsap.fromTo(elements, {
      opacity: 0,
      y: 30,
      filter: 'blur(6px)',
    }, {
      opacity: 1,
      y: 0,
      filter: 'blur(0px)',
      duration: 0.8,
      ease: 'power3.out',
      stagger: 0.1,
      delay: 0.3,
    });

    return () => ScrollTrigger.getAll().forEach((st) => st.kill());
  }, [reducedMotion]);

  return (
    <section
      ref={sectionRef}
      id="start-grid"
      data-accent="none"
      className="relative min-h-[calc(100dvh-3rem)] flex items-center justify-center overflow-hidden"
      aria-label="Hero — What is Lap"
    >
      <div ref={contentRef} className="flex flex-col items-center justify-center text-center gap-6 px-grid-margin">
        {/* Split-text headline — viewport-filling */}
        <MonumentText size="xl" as="h1" className="text-chalk" split>
          RUN A LAP.<br />
          GET YOUR <span className="text-gold">REPORT</span>.<br />
          TRANSFORM YOUR DRIVING.
        </MonumentText>

        {/* Subheadline */}
        <p data-hero-stagger className="font-body text-body text-steel max-w-prose mt-2">
          Professional-grade driver analysis for amateurs.
        </p>

        {/* CTAs — magnetic */}
        <div data-hero-stagger className="flex flex-col sm:flex-row items-center gap-4 mt-2">
          <Link
            ref={ctaRef}
            href="/demo"
            data-cursor="GO"
            className="cta-glow inline-flex items-center justify-center min-h-[48px] px-8 py-3.5 bg-gold text-white font-telemetry text-[12px] tracking-[0.12em] uppercase font-bold transition-all duration-[420ms] hover:brightness-110 hover:shadow-[0_0_32px_rgba(201,168,76,0.25)]"
            onClick={() => trackCtaClick('try_demo', 'hero', 'b2c')}
          >
            Try the demo dashboard
          </Link>
          <Link
            ref={secondaryCtaRef}
            href="#session-proof"
            className="inline-flex items-center justify-center min-h-[48px] px-8 py-3.5 border border-steel/30 text-chalk font-telemetry text-[12px] tracking-[0.12em] uppercase transition-all duration-[420ms] hover:bg-concrete"
            onClick={() => trackCtaClick('see_how', 'hero', 'b2c')}
          >
            See how it works
          </Link>
        </div>

        {/* Early access badge */}
        <span data-hero-stagger className="font-telemetry text-[11px] tracking-[0.15em] uppercase text-gold mt-2">
          SIM-RACING EARLY ACCESS NOW OPEN
        </span>

        {/* Hero product preview — asymmetric offset */}
        <div
          ref={productCardRef}
          data-hero-stagger
          data-cursor="VIEW"
          className="mt-8 w-full max-w-xl border border-chalk/10 bg-concrete p-4 md:translate-x-8 md:rotate-[0.5deg] transition-all duration-500 hover:rotate-0 hover:translate-x-0 hover:shadow-e3 hover:border-gold/20"
          style={{ perspective: '800px' }}
        >
          <div className="flex items-center justify-between mb-3">
            <span className="font-telemetry text-[10px] tracking-[0.2em] uppercase text-steel">
              SAMPLE SESSION OUTPUT
            </span>
            <span className="font-telemetry text-[10px] tracking-[0.12em] uppercase text-gold border border-gold/30 px-2 py-0.5">
              LIVE ANALYSIS
            </span>
          </div>
          <div className="grid grid-cols-[auto,1fr,auto] gap-3 items-center border border-chalk/10 bg-asphalt p-3">
            <div className="text-center">
              <span className="font-monument text-h3 text-safety-red block">+0.32s</span>
              <span className="font-telemetry text-[9px] text-steel uppercase">TIME LOST</span>
            </div>
            <div className="border-l border-chalk/10 pl-3">
              <span className="font-telemetry text-xs text-chalk block">TURN 4 — COPSE</span>
              <span className="font-body text-sm text-steel">Braked 12m past the 50m board. Apex speed 6 km/h below reference.</span>
            </div>
            <div className="text-right border-l border-chalk/10 pl-3">
              <span className="font-telemetry text-[9px] text-acid-green uppercase block">ACTION</span>
              <span className="font-body text-sm text-chalk">Brake at the 50m board.</span>
              <span className="font-body text-sm text-steel block">Carry speed, trust the grip.</span>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
