'use client';

import { MonumentText } from '@/components/ui/MonumentText';

const TIMING_ROWS = [
  { pos: 'P1', name: 'Luca M.', time: '1:23.456' },
  { pos: 'P2', name: 'Max R.', time: '1:23.789' },
  { pos: 'P3', name: 'You', time: '1:24.102' },
  { pos: 'P4', name: 'Oscar P.', time: '1:24.344' },
];

const COACHING_LINES = [
  { label: 'CORNER 7', delta: '+0.31s', detail: 'Brake point 12m late — carry 4 km/h more into the apex' },
  { label: 'CORNER 3', delta: '+0.18s', detail: 'Apex speed 4 km/h low — earlier turn-in, less steering angle' },
  { label: 'CORNER 11', delta: '+0.09s', detail: 'Early throttle lift — trust the rear grip, extend commitment' },
];

const DIFFERENTIATORS = [
  {
    heading: 'KNOW WHERE YOU LOSE TIME',
    body: 'Not leaderboard positions. Corner-by-corner loss identification with specific deltas, causes, and fixes.',
  },
  {
    heading: 'FIX YOUR BRAKING AND THROTTLE',
    body: 'Brake point precision, apex speed analysis, throttle application timing. The actions that actually move your lap time.',
  },
  {
    heading: 'TRACK YOUR PROGRESSION',
    body: 'Session-over-session scoring. See whether your changes are working. Know what to focus on next, not just what happened last.',
  },
];

export function S2Versus() {
  return (
    <section
      id="s2-versus"
      data-accent="none"
      className="relative py-24 md:py-32"
      aria-label="Why Lap is different"
    >
      <div className="grid-lap">
        {/* Headline */}
        <div className="col-span-full text-center mb-12">
          <MonumentText size="h1" as="h2" className="text-chalk mb-2" split>
            THEY TIME LAPS.
          </MonumentText>
          <MonumentText size="h1" as="h2" className="text-gold" split>
            WE COACH DRIVERS.
          </MonumentText>
        </div>

        {/* Comparison columns */}
        <div className="col-span-full grid grid-cols-1 md:grid-cols-[1fr,1.1fr] gap-0 max-w-5xl mx-auto mb-16 md:-space-x-4">

          {/* LEFT: Timing-First */}
          <div data-skew className="border border-steel/20 bg-asphalt p-6 relative">
            <span className="font-telemetry text-[10px] tracking-[0.2em] uppercase text-steel mb-4 block">
              TIMING-FIRST
            </span>
            <div className="space-y-0">
              {TIMING_ROWS.map((r) => (
                <div
                  key={r.pos}
                  className={`flex items-center justify-between py-2.5 border-b border-steel/10 font-telemetry text-sm ${
                    r.name === 'You' ? 'text-steel' : 'text-steel/50'
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <span className="w-8 text-steel/50">{r.pos}</span>
                    <span>{r.name}</span>
                  </div>
                  <span className="tabular-nums">{r.time}</span>
                </div>
              ))}
            </div>
            <p className="text-steel/60 font-body text-sm mt-6 max-w-xs">
              You know you&apos;re P3.<br />
              You don&apos;t know <em>why</em>.
            </p>
            <div className="absolute top-4 right-4">
              <span className="font-telemetry text-[10px] tracking-[0.12em] uppercase text-steel/50 border border-steel/20 px-2 py-0.5">
                POSITIONS ONLY
              </span>
            </div>
          </div>

          {/* RIGHT: Coaching-First — overlaps left card */}
          <div data-skew className="border border-chalk/15 bg-concrete p-6 relative md:translate-x-[-16px] md:translate-y-[-8px] z-10 shadow-e3">
            <span className="font-telemetry text-[10px] tracking-[0.2em] uppercase text-gold mb-4 block">
              COACHING-FIRST
            </span>
            <div className="space-y-0">
              {COACHING_LINES.map((c) => (
                <div
                  key={c.label}
                  className="flex items-start justify-between py-2.5 border-b border-chalk/10"
                >
                  <div>
                    <span className="font-telemetry text-xs text-chalk">{c.label}</span>
                    <span className="block font-body text-sm text-steel mt-0.5">{c.detail}</span>
                  </div>
                  <span className="font-telemetry text-sm text-gold shrink-0 ml-4">{c.delta}</span>
                </div>
              ))}
            </div>
            <p className="text-chalk font-body text-sm mt-6 max-w-xs">
              You know the exact corner.<br />
              You leave with <strong className="text-gold">the fix</strong>.
            </p>
            <div className="absolute top-4 right-4">
              <span className="font-telemetry text-[10px] tracking-[0.12em] uppercase text-gold border border-gold/40 px-2 py-0.5">
                COACHING READY
              </span>
            </div>
          </div>
        </div>

        {/* Three pillars */}
        <div className="col-span-full grid grid-cols-1 md:grid-cols-3 gap-4 max-w-5xl mx-auto">
          {DIFFERENTIATORS.map((p) => (
            <div
              key={p.heading}
              className="card-lift border border-chalk/10 bg-concrete/50 p-5"
            >
              <h3 className="font-monument text-[var(--text-h3)] text-chalk mb-2">
                {p.heading}
              </h3>
              <p className="font-body text-sm text-steel leading-relaxed">
                {p.body}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
