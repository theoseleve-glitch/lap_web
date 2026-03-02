'use client';

import { MonumentText } from '@/components/ui/MonumentText';

/* ── Mock timing table (what competitors show) ──────────── */
const TIMING_ROWS = [
  { pos: 'P1', name: 'Luca M.', time: '1:23.456' },
  { pos: 'P2', name: 'Max R.', time: '1:23.789' },
  { pos: 'P3', name: 'You', time: '1:24.102' },
  { pos: 'P4', name: 'Oscar P.', time: '1:24.344' },
];

/* ── Mock coaching card (what we show) ──────────────────── */
const COACHING_LINES = [
  { label: 'CORNER 7', delta: '+0.31s', detail: 'Brake point 12 m late' },
  { label: 'CORNER 3', delta: '+0.18s', detail: 'Apex speed 4 km/h low' },
  { label: 'CORNER 11', delta: '+0.09s', detail: 'Early throttle lift' },
];

/* ── Bottom differentiator cards ────────────────────────── */
const PILLARS = [
  {
    heading: 'SAME DATA',
    body: 'GPS + IMU @ 25 Hz from the same device. The difference is what you do with it.',
  },
  {
    heading: 'DIFFERENT QUESTION',
    body: '\u201CWhere did you lose time?\u201D not \u201CWho won?\u201D \u2014 that\u2019s the shift.',
  },
  {
    heading: 'ACTIONABLE OUTPUT',
    body: 'Every report ends with what to change next session. Not just numbers \u2014 next steps.',
  },
];

export function S2Versus() {
  return (
    <section
      data-room="s2-versus"
      data-accent="yellow"
      className="relative py-24 px-6 md:px-12 lg:px-20"
    >
      <div className="max-w-6xl mx-auto">
        {/* ── Headline ───────────────────────────────────── */}
        <MonumentText size="h1" as="h2" className="text-chalk mb-2" reveal>
          THEY TIME LAPS.
        </MonumentText>
        <MonumentText size="h1" as="h2" className="text-pit-orange mb-12" reveal>
          WE COACH DRIVERS.
        </MonumentText>

        {/* ── Comparison columns ──────────────────────────── */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-16">

          {/* LEFT: Timing-First (competitor mock) */}
          <div className="border border-steel/20 bg-asphalt p-6 relative">
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
                    <span className="w-8 text-steel/30">{r.pos}</span>
                    <span>{r.name}</span>
                  </div>
                  <span className="tabular-nums">{r.time}</span>
                </div>
              ))}
            </div>
            <p className="text-steel/40 font-body text-sm mt-6 max-w-xs">
              You know you&apos;re P3.<br />
              You don&apos;t know <em>why</em>.
            </p>
            <div className="absolute top-4 right-4">
              <span className="font-telemetry text-[10px] tracking-[0.12em] uppercase text-steel/30 border border-steel/20 px-2 py-0.5">
                POSITIONS ONLY
              </span>
            </div>
          </div>

          {/* RIGHT: Telemetry-First (our approach) */}
          <div className="beam-card border border-chalk/15 bg-concrete p-6 relative">
            <span className="font-telemetry text-[10px] tracking-[0.2em] uppercase text-pit-orange mb-4 block">
              TELEMETRY-FIRST
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
                  <span className="font-telemetry text-sm text-safety-red shrink-0 ml-4">{c.delta}</span>
                </div>
              ))}
            </div>
            <p className="text-chalk font-body text-sm mt-6 max-w-xs">
              You know the exact corner.<br />
              You leave with <strong className="text-pit-orange">the fix</strong>.
            </p>
            <div className="absolute top-4 right-4">
              <span className="font-telemetry text-[10px] tracking-[0.12em] uppercase text-pit-orange border border-pit-orange/40 px-2 py-0.5">
                COACHING READY
              </span>
            </div>
          </div>
        </div>

        {/* ── Three pillars ──────────────────────────────── */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {PILLARS.map((p) => (
            <div
              key={p.heading}
              className="border border-chalk/10 bg-concrete/50 p-5"
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
