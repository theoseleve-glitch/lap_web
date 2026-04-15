'use client';

import { MonumentText } from '@/components/ui/MonumentText';
import { useCountUp } from '@/hooks/useCountUp';
import { useReducedMotion } from '@/hooks/useReducedMotion';

const FOUNDER_RESULTS = [
  {
    stat: '+2,000',
    label: 'IRATING GAINED',
    detail: 'From mid-field to fighting for podiums using the same analysis approach that powers Lap.',
  },
  {
    stat: 'PODIUM',
    label: 'FIGHTS',
    detail: 'From back-of-grid in both sim and real-life kart racing to consistent championship contention.',
  },
  {
    stat: '14-STAGE',
    label: 'PIPELINE',
    detail: 'Not a wrapper on generic AI. Purpose-built motorsport analysis refined across thousands of sessions.',
  },
];

export function Garage() {
  const { reducedMotion } = useReducedMotion();
  const { ref: iratingRef, display: iratingDisplay } = useCountUp({
    end: 2000,
    prefix: '+',
    duration: 2500,
    disabled: reducedMotion,
  });

  return (
    <section
      id="garage"
      data-accent="none"
      className="relative py-24 md:py-32"
      aria-label="Proof and credibility"
    >
      <div className="grid-lap">
        <div className="col-span-full text-center mb-4">
          <MonumentText size="h1" as="h2" split>
            BUILT FROM<br />
            <span className="text-gold">REAL PROGRESSION.</span>
          </MonumentText>
        </div>
        <div className="col-span-full text-center mb-12">
          <p className="font-body text-body text-steel max-w-prose mx-auto">
            Lap exists because improving as a driver should not require becoming your own engineer.
          </p>
        </div>

        {/* Founder story panel */}
        <div className="col-span-full max-w-4xl mx-auto mb-12">
          <div className="border border-chalk/15 bg-concrete p-6 md:p-8">
            <div className="grid grid-cols-1 md:grid-cols-[1fr,auto] gap-6 items-start">
              <div>
                <span className="font-telemetry text-[10px] tracking-[0.2em] uppercase text-gold block mb-4">
                  FOUNDER STORY
                </span>
                <p className="font-body text-body text-chalk leading-relaxed mb-4">
                  I built Lap because I lived the problem. I spent years analysing my own karting telemetry
                  and sim sessions&nbsp;&mdash; manually comparing corners, guessing at brake points,
                  building spreadsheets that were outdated by the next track day.
                </p>
                <p className="font-body text-body text-steel leading-relaxed mb-4">
                  The turning point was building a structured analysis system for myself: consistent scoring,
                  corner-by-corner breakdowns, and clear priorities for the next session. Not more data&nbsp;&mdash;
                  better debriefs.
                </p>
                <p className="font-body text-body text-steel leading-relaxed">
                  The results were measurable. Over 2,000 iRating gained. From back-of-grid in kart races
                  to fighting for podiums and championships. Not through natural talent&nbsp;&mdash; through
                  clearer feedback and faster iteration.
                </p>
              </div>
              <div className="flex flex-col items-center gap-2 shrink-0 md:-mt-12 md:mr-[-20px] relative z-10">
                <div className="w-20 h-20 bg-gold/10 border-2 border-gold/40 flex items-center justify-center font-monument text-h2 text-gold shadow-e3">
                  L
                </div>
                <span className="font-telemetry text-[10px] text-chalk text-center">FOUNDER</span>
                <span className="font-telemetry text-[9px] text-steel text-center">Data engineer<br />Kart racer<br />Sim driver</span>
              </div>
            </div>
          </div>
        </div>

        {/* Result cards */}
        <div className="col-span-full grid grid-cols-1 md:grid-cols-3 gap-6 max-w-4xl mx-auto mb-12">
          {FOUNDER_RESULTS.map((r, i) => (
            <div key={r.label} data-stagger className="card-lift border border-chalk/10 bg-concrete/50 p-6 text-center">
              <span
                ref={i === 0 ? iratingRef as React.RefObject<HTMLSpanElement> : undefined}
                className="font-monument text-h2 text-gold block mb-1"
              >
                {i === 0 ? iratingDisplay : r.stat}
              </span>
              <span className="font-telemetry text-[10px] tracking-[0.2em] uppercase text-chalk block mb-3">
                {r.label}
              </span>
              <p className="font-body text-sm text-steel leading-relaxed">
                {r.detail}
              </p>
            </div>
          ))}
        </div>

        {/* Beta user results placeholder */}
        <div className="col-span-full max-w-4xl mx-auto">
          <div className="border border-steel/15 bg-asphalt p-6">
            <span className="font-telemetry text-[10px] tracking-[0.2em] uppercase text-steel mb-4 block">
              EARLY ACCESS RESULTS
            </span>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="card-lift border border-steel/10 p-4 relative overflow-hidden">
                <span className="absolute -top-2 -left-1 font-monument text-[64px] leading-none text-gold/[0.06]">&ldquo;</span>
                <span className="font-monument text-h3 text-chalk block mb-1">CLEARER</span>
                <span className="font-telemetry text-[10px] text-steel uppercase block mb-2">DEBRIEFS</span>
                <p className="font-body text-sm text-steel/60">
                  &ldquo;First time I knew exactly which corner to work on, not just that I was slow.&rdquo;
                </p>
              </div>
              <div className="card-lift border border-steel/10 p-4 relative overflow-hidden">
                <span className="absolute -top-2 -left-1 font-monument text-[64px] leading-none text-gold/[0.06]">&ldquo;</span>
                <span className="font-monument text-h3 text-chalk block mb-1">FASTER</span>
                <span className="font-telemetry text-[10px] text-steel uppercase block mb-2">PROGRESS</span>
                <p className="font-body text-sm text-steel/60">
                  &ldquo;Dropped 1.2s at Spa in three sessions. The scoring showed me exactly what changed.&rdquo;
                </p>
              </div>
              <div className="card-lift border border-steel/10 p-4 relative overflow-hidden">
                <span className="absolute -top-2 -left-1 font-monument text-[64px] leading-none text-gold/[0.06]">&ldquo;</span>
                <span className="font-monument text-h3 text-chalk block mb-1">LESS</span>
                <span className="font-telemetry text-[10px] text-steel uppercase block mb-2">GUESSWORK</span>
                <p className="font-body text-sm text-steel/60">
                  &ldquo;I used to stare at traces. Now I read a report and know what to practice.&rdquo;
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
