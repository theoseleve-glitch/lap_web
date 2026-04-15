'use client';

import { MonumentText } from '@/components/ui/MonumentText';

const WHY_SIM_FIRST = [
  {
    label: 'FASTER ONBOARDING',
    detail: 'No hardware setup, no weather delays, no travel. Upload a session and get your first report in minutes.',
  },
  {
    label: 'UNLIMITED REPETITION',
    detail: 'Run the same corner fifty times in an evening. The fastest path to measurable change is doing more laps, more often.',
  },
  {
    label: 'IDEAL FOR PROGRESSION',
    detail: 'Controlled conditions make it easier to isolate what changed between sessions. Real improvement needs consistent variables.',
  },
  {
    label: 'SAME ANALYSIS ENGINE',
    detail: 'The 14-stage pipeline, 4-pillar scoring, and corner coaching work identically in sim and real-life. Your driver profile carries over.',
  },
];

const SIM_PLATFORMS = [
  'iRacing',
  'Assetto Corsa Competizione',
  'F1 Series',
];

const REAL_LIFE_PLATFORMS = [
  'RaceChrono GPS',
  'RaceBox GPS',
  'Kart-specific envelope analysis',
  'Track day & race weekend workflows',
];

export function SimFirst() {
  return (
    <section
      id="sim-first"
      data-accent="none"
      className="relative py-24 md:py-32"
      aria-label="Sim-racing early access"
    >
      <div className="grid-lap">
        <div className="col-span-full text-center mb-4">
          <MonumentText size="h1" as="h2" split>
            BUILT FOR PROGRESSION.<br />
            <span className="text-gold">STARTING WITH SIM RACING.</span>
          </MonumentText>
        </div>
        <div className="col-span-full text-center mb-12">
          <p className="font-body text-body text-steel max-w-prose mx-auto">
            Early access focuses on sim drivers first. The full ecosystem expands from there.
          </p>
        </div>

        {/* Why sim first — rationale cards with numbered accent */}
        <div className="col-span-full grid grid-cols-1 sm:grid-cols-2 gap-4 max-w-5xl mx-auto mb-12">
          {WHY_SIM_FIRST.map((item, i) => (
            <div key={item.label} data-stagger className="card-lift border border-chalk/10 bg-concrete/50 p-5 relative overflow-hidden">
              <span className="absolute top-3 right-4 font-monument text-[48px] leading-none text-chalk/[0.03]">
                {String(i + 1).padStart(2, '0')}
              </span>
              <h3 className="font-monument text-xs text-gold tracking-widest mb-2">
                {item.label}
              </h3>
              <p className="font-body text-sm text-steel leading-relaxed">
                {item.detail}
              </p>
            </div>
          ))}
        </div>

        {/* Split: sim active / real-life expanding */}
        <div className="col-span-full grid grid-cols-1 md:grid-cols-2 gap-8 max-w-5xl mx-auto">

          {/* Sim — active */}
          <div className="border border-gold/30 bg-concrete p-6 relative">
            <div className="absolute top-4 right-4">
              <span className="font-telemetry text-[10px] tracking-[0.12em] uppercase text-gold border border-gold/40 px-2 py-0.5">
                ACTIVE NOW
              </span>
            </div>
            <h3 className="font-monument text-[var(--text-h3)] text-chalk mb-4">
              SIM RACING
            </h3>
            <div className="space-y-2 mb-4">
              {SIM_PLATFORMS.map((p) => (
                <div key={p} className="flex items-center gap-3 py-2 border-b border-chalk/10">
                  <span className="w-1.5 h-1.5 bg-acid-green shrink-0" />
                  <span className="font-telemetry text-xs text-chalk">{p}</span>
                </div>
              ))}
            </div>
            <p className="font-body text-sm text-steel">
              Full corner-by-corner analysis, scoring, and progression tracking on every session.
            </p>
          </div>

          {/* Real-life — expanding */}
          <div className="border border-steel/20 bg-asphalt p-6 relative">
            <div className="absolute top-4 right-4">
              <span className="font-telemetry text-[10px] tracking-[0.12em] uppercase text-steel/50 border border-steel/20 px-2 py-0.5">
                EXPANDING NEXT
              </span>
            </div>
            <h3 className="font-monument text-[var(--text-h3)] text-steel mb-4">
              REAL-LIFE MOTORSPORT
            </h3>
            <div className="space-y-2 mb-4">
              {REAL_LIFE_PLATFORMS.map((p) => (
                <div key={p} className="flex items-center gap-3 py-2 border-b border-steel/10">
                  <span className="w-1.5 h-1.5 bg-steel/40 shrink-0" />
                  <span className="font-telemetry text-xs text-steel">{p}</span>
                </div>
              ))}
            </div>
            <p className="font-body text-sm text-steel/60">
              Same philosophy, same scoring, same driver profile. One progression system across sim and real.
            </p>
          </div>
        </div>

      </div>
    </section>
  );
}
