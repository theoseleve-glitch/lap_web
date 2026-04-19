'use client';

import { useEffect, useRef } from 'react';
import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { MonumentText } from '@/components/ui/MonumentText';
import { useReducedMotion } from '@/hooks/useReducedMotion';

gsap.registerPlugin(ScrollTrigger);

const PIPELINE_STAGES = [
  {
    step: '01',
    name: 'LOG',
    headline: 'Record the session',
    detail: 'Upload from iRacing, ACC, or F1. Or connect a GPS logger for real-world sessions. One entry point for all data.',
  },
  {
    step: '02',
    name: 'PROCESS',
    headline: 'Clean and structure the data',
    detail: 'GPS filtering, derived channels, track detection, lap splitting, and resampling. A 14-stage pipeline handles the engineering so you don\u2019t have to.',
  },
  {
    step: '03',
    name: 'ANALYZE',
    headline: 'Corner-by-corner breakdown',
    detail: 'Every corner scored for entry, apex, and exit. Speed traces, GG diagrams, and GPS overlay reveal exactly where time was lost and why.',
  },
  {
    step: '04',
    name: 'SCORE',
    headline: 'Build your driver profile',
    detail: 'Pace, Consistency, Execution, Robustness \u2014 four pillars scored out of 25 each. One session gives you a number. Ten sessions give you a pattern.',
  },
  {
    step: '05',
    name: 'TRACK',
    headline: 'Measure progression over time',
    detail: 'Session-over-session comparison, plateau detection, and improvement velocity. See whether your changes are actually working.',
  },
  {
    step: '06',
    name: 'STRATEGIZE',
    headline: 'Support race day decisions',
    detail: 'Stint planning, fuel management, pit windows, and live monitoring. Race strategy tools that connect to your driver data.',
  },
  {
    step: '07',
    name: 'PREPARE',
    headline: 'Enter the next session with a plan',
    detail: 'Coaching priorities, focus areas, and measurable targets. Every session debrief ends with what to change next.',
  },
];

export function S3Product() {
  const sectionRef = useRef<HTMLElement>(null);
  const trackRef = useRef<HTMLDivElement>(null);
  const progressRef = useRef<HTMLDivElement>(null);
  const { reducedMotion } = useReducedMotion();

  useEffect(() => {
    if (reducedMotion || !sectionRef.current || !trackRef.current) return;

    const totalWidth = trackRef.current.scrollWidth - window.innerWidth;

    // Pin the section and scrub the horizontal track
    const mainSt = ScrollTrigger.create({
      trigger: sectionRef.current,
      start: 'top top',
      end: () => `+=${totalWidth}`,
      pin: true,
      scrub: 1,
      anticipatePin: 1,
      animation: gsap.to(trackRef.current, {
        x: -totalWidth,
        ease: 'none',
      }),
      onUpdate: (self) => {
        if (progressRef.current) {
          progressRef.current.style.width = `${self.progress * 100}%`;
        }
      },
    });

    // Each card fades in during horizontal scroll
    const cards = trackRef.current.querySelectorAll('.pipeline-card');
    cards.forEach((card) => {
      gsap.fromTo(card, {
        opacity: 0.3,
        scale: 0.95,
      }, {
        opacity: 1,
        scale: 1,
        duration: 0.5,
        ease: 'power2.out',
        scrollTrigger: {
          trigger: card,
          containerAnimation: mainSt.animation!,
          start: 'left 80%',
          end: 'left 40%',
          scrub: 1,
        },
      });
    });

    return () => {
      ScrollTrigger.getAll().forEach((t) => t.kill());
    };
  }, [reducedMotion]);

  // Fallback: vertical stack for reduced motion
  if (reducedMotion) {
    return (
      <section id="s3-product" data-accent="none" className="relative py-16 md:py-24" aria-label="Product ecosystem">
        <div className="grid-lap">
          <div className="col-span-full text-center mb-12">
            <MonumentText size="h1" as="h2">
              ONE SYSTEM FROM RAW SESSION<br />
              <span className="text-gold">TO NEXT-SESSION ACTION.</span>
            </MonumentText>
          </div>
          <div className="col-span-full max-w-4xl mx-auto space-y-4">
            {PIPELINE_STAGES.map((stage) => (
              <div key={stage.step} className="border border-chalk/10 bg-concrete/40 p-5">
                <div className="flex items-center gap-3 mb-2">
                  <span className="font-telemetry text-[10px] text-gold">{stage.step}</span>
                  <span className="font-monument text-xs text-gold tracking-widest">{stage.name}</span>
                  <span className="font-monument text-xs text-chalk">{stage.headline}</span>
                </div>
                <p className="font-body text-sm text-steel leading-relaxed">{stage.detail}</p>
              </div>
            ))}
          </div>
        </div>
      </section>
    );
  }

  return (
    <section
      ref={sectionRef}
      id="s3-product"
      data-accent="none"
      className="relative min-h-screen overflow-hidden"
      aria-label="Product ecosystem"
    >
      {/* Header — stays visible during pin */}
      <div className="pt-16 pb-8 px-grid-margin text-center">
        <MonumentText size="h1" as="h2" split>
          ONE SYSTEM FROM RAW SESSION<br />
          <span className="text-gold">TO NEXT-SESSION ACTION.</span>
        </MonumentText>
        <p className="font-body text-body text-steel max-w-prose mx-auto mt-4">
          Logging, analysis, progression, and race tools&nbsp;&mdash; connected.
        </p>
      </div>

      {/* Progress bar */}
      <div className="mx-grid-margin mb-6">
        <div className="h-px bg-steel/20 relative">
          <div ref={progressRef} className="absolute top-0 left-0 h-full bg-gold transition-none" style={{ width: 0 }} />
        </div>
        <div className="flex justify-between mt-2">
          {PIPELINE_STAGES.map((s) => (
            <span key={s.step} className="font-telemetry text-[9px] text-steel/40 tracking-[0.12em]">
              {s.step}
            </span>
          ))}
        </div>
      </div>

      {/* Horizontal scroll track */}
      <div ref={trackRef} className="flex gap-6 pl-grid-margin pr-[50vw]" style={{ width: 'max-content' }}>
        {PIPELINE_STAGES.map((stage) => (
          <div
            key={stage.step}
            className="pipeline-card shrink-0 w-[min(420px,80vw)] border border-chalk/10 bg-concrete/40 p-8 flex flex-col"
          >
            <div className="flex items-center gap-3 mb-4">
              <div className="w-12 h-12 border border-gold/40 bg-concrete flex items-center justify-center">
                <span className="font-telemetry text-sm text-gold">{stage.step}</span>
              </div>
              <span className="font-monument text-sm text-gold tracking-widest">
                {stage.name}
              </span>
            </div>
            <h3 className="font-monument text-h3 text-chalk mb-3">
              {stage.headline}
            </h3>
            <p className="font-body text-body text-steel leading-relaxed flex-1">
              {stage.detail}
            </p>
          </div>
        ))}
      </div>

    </section>
  );
}
