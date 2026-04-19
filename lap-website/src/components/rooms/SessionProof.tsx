'use client';

import { MonumentText } from '@/components/ui/MonumentText';

const SCORE_ROWS = [
  { label: 'Pace', value: '21/25', accent: false },
  { label: 'Consistency', value: '19/25', accent: false },
  { label: 'Execution', value: '20/25', accent: false },
  { label: 'Robustness', value: '18/25', accent: true },
];

const DEBRIEF_ITEMS = [
  {
    corner: 'T4 — COPSE',
    delta: '-0.38s',
    cause: 'Braked 14m past the 50m board',
    action: 'Brake at the 50m board. Carry 4 km/h more into the apex.',
  },
  {
    corner: 'T9 — STOWE',
    delta: '-0.22s',
    cause: 'Lifted throttle 30m before corner exit',
    action: 'Stay on throttle through the exit. Trust rear grip.',
  },
  {
    corner: 'T12 — VALE',
    delta: '-0.14s',
    cause: 'Turn-in 8m late, forced tight exit line',
    action: 'Turn in at the 25m marker. Open the exit radius.',
  },
];

const TRENDS = [
  { label: 'Consistency trend', change: '\u2191 12%', pct: 72, color: 'bg-acid-green', changeColor: 'text-acid-green' },
  { label: 'Braking precision', change: '\u2191 8%', pct: 64, color: 'bg-acid-green', changeColor: 'text-acid-green' },
  { label: 'Corner exits', change: '\u2192 flat', pct: 45, color: 'bg-marshal-yellow', changeColor: 'text-marshal-yellow' },
];

export function SessionProof() {
  return (
    <section
      id="session-proof"
      data-accent="none"
      className="relative py-24 md:py-32"
      aria-label="What you get after every session"
    >
      <div className="grid-lap">
        {/* Header */}
        <div className="col-span-full text-center mb-4">
          <MonumentText size="h1" as="h2" split>
            EVERY SESSION ENDS WITH<br />A CLEAR NEXT STEP.
          </MonumentText>
        </div>
        <div className="col-span-full text-center mb-12">
          <p className="font-body text-body text-steel">
            Not just telemetry. A driver-ready debrief with decisions, not dashboards.
          </p>
        </div>

        {/* 3-card layout */}
        <div className="col-span-full grid grid-cols-1 md:grid-cols-3 gap-6 max-w-5xl mx-auto">

          {/* Card 1: Session Score — offset down on desktop */}
          <div data-stagger className="card-lift border border-chalk/15 bg-concrete p-6 md:translate-y-4">
            <span className="font-telemetry text-[10px] tracking-[0.2em] uppercase text-steel mb-4 block">
              YOUR SCORE
            </span>
            <div className="flex items-baseline gap-2 mb-4">
              <span className="font-monument text-h1 text-chalk">78</span>
              <span className="font-telemetry text-steel">/100</span>
            </div>
            <div className="space-y-2">
              {SCORE_ROWS.map((row) => (
                <div key={row.label} className="flex justify-between font-telemetry text-xs">
                  <span className="text-steel">{row.label}</span>
                  <span className={row.accent ? 'text-gold' : 'text-chalk'}>{row.value}</span>
                </div>
              ))}
            </div>
            <p className="font-body text-sm text-steel mt-4">
              Where you stand&nbsp;&mdash; in one number.
            </p>
          </div>

          {/* Card 2: Loss → Cause → Action debrief — center */}
          <div data-stagger className="card-lift border border-chalk/15 bg-concrete p-6">
            <span className="font-telemetry text-[10px] tracking-[0.2em] uppercase text-steel mb-4 block">
              YOUR DEBRIEF
            </span>
            <div className="space-y-4 mb-4">
              {DEBRIEF_ITEMS.map((item) => (
                <div key={item.corner} className="border-b border-chalk/10 pb-3 last:border-0 last:pb-0">
                  <div className="flex items-center justify-between mb-1">
                    <span className="font-telemetry text-xs text-chalk">{item.corner}</span>
                    <span className="font-telemetry text-xs text-safety-red shrink-0">{item.delta}</span>
                  </div>
                  <p className="font-body text-[12px] text-steel mb-1">
                    <span className="text-steel/60">Cause:</span> {item.cause}
                  </p>
                  <p className="font-body text-[12px] text-acid-green">
                    <span className="text-acid-green/60">Fix:</span> {item.action}
                  </p>
                </div>
              ))}
            </div>
            <p className="font-body text-sm text-steel">
              Where you lost time. What caused it. <strong className="text-chalk">What to change.</strong>
            </p>
          </div>

          {/* Card 3: Progression — offset up on desktop */}
          <div data-stagger className="card-lift border border-chalk/15 bg-concrete p-6 md:-translate-y-4">
            <span className="font-telemetry text-[10px] tracking-[0.2em] uppercase text-steel mb-4 block">
              YOUR PROGRESSION
            </span>
            <div className="space-y-3 mb-4">
              {TRENDS.map((t) => (
                <div key={t.label}>
                  <div className="flex justify-between font-telemetry text-xs mb-1">
                    <span className="text-steel">{t.label}</span>
                    <span className={t.changeColor}>{t.change}</span>
                  </div>
                  <div className="w-full h-1 bg-steel/20">
                    <div className={`h-full ${t.color}`} style={{ width: `${t.pct}%` }} />
                  </div>
                </div>
              ))}
            </div>
            <div className="border-t border-chalk/10 pt-3">
              <span className="font-telemetry text-[10px] tracking-[0.12em] uppercase text-gold">
                NEXT PRIORITY
              </span>
              <p className="font-body text-sm text-chalk mt-1">
                Focus on corner exit throttle application&nbsp;&mdash; your biggest untapped gain.
              </p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
