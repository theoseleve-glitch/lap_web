'use client';

import { useRef, useEffect, useState } from 'react';
import { MonumentText } from '@/components/ui/MonumentText';

const TESTIMONIALS = [
  {
    role: 'Head Coach, Regional Kart Championship',
    quote:
      'Drivers returned more often once reports were shared after each session. The scoring system gave them a target to beat \u2014 not just a lap time, but a breakdown of where the time was.',
  },
  {
    role: 'Race Engineer, GT Endurance Team',
    quote:
      'Control room overlays improved stint decisions under pressure. Having degradation trends and pit windows on one screen meant fewer radio calls and faster reactions.',
  },
  {
    role: 'Team Principal, Junior Formula Academy',
    quote:
      'The Corner Coaching table is where the real value is. Instead of arguing about feel, we pointed to the data and focused on one corner per session. Progress was measurable.',
  },
  {
    role: 'Private Kart Driver, Club Racing',
    quote:
      'I shaved 1.2 seconds in three sessions just by following the corner coaching hints. The scoring system keeps me motivated between track days.',
  },
  {
    role: 'Data Analyst, Touring Car Team',
    quote:
      'The comparison view side-by-side with the radar chart made setup changes quantifiable. We could finally see which changes improved which dimensions.',
  },
  {
    role: 'Driving Instructor, Performance Driving School',
    quote:
      'Students understand visual feedback better than verbal coaching. The GG diagram animation and speed trace overlays are worth more than a thousand words.',
  },
];

const METRICS = [
  { value: '18%', label: 'Faster onboarding' },
  { value: '11%', label: 'Tighter lap spreads' },
  { value: '2 fewer', label: 'Unplanned pit stops' },
];

export function SocialProof() {
  const sectionRef = useRef<HTMLElement>(null);
  const [visible, setVisible] = useState(false);
  const [activeIdx, setActiveIdx] = useState(0);

  useEffect(() => {
    const el = sectionRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting) setVisible(true); },
      { threshold: 0.2 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // Auto-rotate testimonials every 5 seconds
  useEffect(() => {
    if (!visible) return;
    const interval = setInterval(() => {
      setActiveIdx((prev) => (prev + 1) % TESTIMONIALS.length);
    }, 5000);
    return () => clearInterval(interval);
  }, [visible]);

  return (
    <section
      ref={sectionRef}
      id="social-proof"
      data-accent="green"
      className="room relative py-16 md:py-24"
      aria-label="What teams achieve with LAP"
    >
      <div className="grid-lap">
        {/* Heading */}
        <div className="col-span-full text-center mb-4">
          <MonumentText size="h1" as="h2" reveal>
            Measured Results
          </MonumentText>
        </div>
        <div className="col-span-full text-center mb-12">
          <p className="font-telemetry text-steel text-sm">
            Real outcomes from teams using LAP in competition
          </p>
        </div>

        {/* Metric cards */}
        <div className="col-span-full grid grid-cols-1 sm:grid-cols-3 gap-4 mb-12">
          {METRICS.map((m, i) => (
            <div
              key={m.label}
              className={`border border-acid-green/30 bg-concrete/20 p-6 text-center transition-all duration-700 ${
                visible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'
              }`}
              style={{ transitionDelay: `${i * 150}ms` }}
            >
              <p className="font-monument text-acid-green text-2xl md:text-3xl mb-1">
                {m.value}
              </p>
              <p className="font-telemetry text-[11px] tracking-[0.12em] uppercase text-steel">
                {m.label}
              </p>
            </div>
          ))}
        </div>

        {/* Testimonial carousel */}
        <div className="col-span-full">
          <div className="overflow-hidden relative">
            <div
              className="flex transition-transform duration-500 ease-out"
              style={{ transform: `translateX(-${activeIdx * (100 / 3)}%)` }}
            >
              {TESTIMONIALS.map((t, i) => (
                <blockquote
                  key={t.role}
                  className={`flex-shrink-0 w-full md:w-1/3 px-3 transition-all duration-700 ${
                    visible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'
                  }`}
                  style={{ transitionDelay: `${300 + i * 100}ms` }}
                >
                  <div className="border border-steel/20 bg-concrete/10 p-6 h-full">
                    <p className="text-chalk text-sm leading-relaxed mb-4">
                      &ldquo;{t.quote}&rdquo;
                    </p>
                    <footer className="font-telemetry text-[10px] tracking-[0.12em] uppercase text-steel">
                      &mdash; {t.role}
                    </footer>
                  </div>
                </blockquote>
              ))}
            </div>
          </div>
          {/* Dot indicators */}
          <div className="flex justify-center gap-2 mt-4">
            {TESTIMONIALS.map((_, i) => (
              <button
                key={i}
                type="button"
                onClick={() => setActiveIdx(i)}
                className={`w-2 h-2 rounded-full transition-colors ${
                  i === activeIdx ? 'bg-acid-green' : 'bg-steel/30 hover:bg-steel/50'
                }`}
                aria-label={`Show testimonial ${i + 1}`}
              />
            ))}
          </div>
        </div>

        {/* Link to full case studies */}
        <div className="col-span-full text-center mt-8">
          <a
            href="/customers"
            className="font-telemetry text-[11px] tracking-[0.12em] uppercase text-pit-orange hover:text-acid-green transition-colors"
          >
            Read full case studies &rarr;
          </a>
        </div>
      </div>
    </section>
  );
}
