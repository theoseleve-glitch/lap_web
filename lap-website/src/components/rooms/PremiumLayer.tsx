'use client';

import { MonumentText } from '@/components/ui/MonumentText';

const PREMIUM_FEATURES = [
  {
    name: 'DEEP CORNER ANALYSIS',
    outcome: 'Find the tenths hiding inside corners',
    desc: 'Entry, apex, and exit phase separation for every corner. Braking point precision, minimum speed delta, throttle application timing, exit drive efficiency.',
    glyph: '\u2316', // position indicator
  },
  {
    name: 'ADVANCED DRIVER PROFILING',
    outcome: 'See how your driving DNA evolves',
    desc: 'Multi-session pattern recognition across all four scoring pillars. Plateau detection, improvement velocity, and cross-track consistency mapping.',
    glyph: '\u2261', // identical to (triple bar)
  },
  {
    name: 'DYNAMIC RACE STRATEGY',
    outcome: 'Win races, not just practice sessions',
    desc: 'Full stint planning with fuel load, driver rotation, and pit window modelling. Live race monitoring with real-time stint tracking for endurance events.',
    glyph: '\u21BB', // clockwise arrow
  },
  {
    name: 'SETUP UNDERSTANDING',
    outcome: 'Connect setup changes to driving data',
    desc: 'Correlate setup adjustments with corner-level behaviour. Quantify how spring rates, aero balance, or gear ratios affect your performance.',
    glyph: '\u2699', // gear
  },
  {
    name: 'PROGRESSION INTELLIGENCE',
    outcome: 'Turn sessions into a training programme',
    desc: 'Long-term coaching plans with measurable targets. Session-over-session comparison. Identify where progress stalls before it costs you months.',
    glyph: '\u2197', // arrow NE (trend up)
  },
  {
    name: 'UNLIMITED ANALYSIS',
    outcome: 'No caps, no waiting, no compromises',
    desc: 'Unlimited monthly reports. 12-month raw telemetry retention. Downloadable PDF debriefs. Comparison tools. Priority pipeline processing.',
    glyph: '\u221E', // infinity
  },
];

export function PremiumLayer() {
  return (
    <section
      id="premium"
      data-accent="none"
      className="relative py-24 md:py-32"
      aria-label="Premium performance layer"
    >
      <div className="grid-lap">
        <div className="col-span-full text-center mb-4">
          <MonumentText size="h1" as="h2" split>
            PREMIUM UNLOCKS THE<br />
            <span className="text-gold">PERFORMANCE LAYER.</span>
          </MonumentText>
        </div>
        <div className="col-span-full text-center mb-4">
          <p className="font-body text-body text-steel max-w-prose mx-auto">
            Go beyond visibility. Understand patterns, optimize decisions, and improve faster.
          </p>
        </div>

        {/* Premium feature cards */}
        <div className="col-span-full grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 max-w-5xl mx-auto">
          {PREMIUM_FEATURES.map((f) => (
            <div
              key={f.name}
              data-cursor="VIEW"
              className="card-lift border border-gold/15 bg-concrete/60 p-5 relative overflow-hidden group"
            >
              {/* Hover glow */}
              <div className="absolute inset-0 bg-gradient-to-br from-gold/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-500" />
              {/* Ghost glyph */}
              <span className="absolute top-3 right-4 text-[40px] leading-none text-gold/[0.06] group-hover:text-gold/[0.12] transition-colors duration-500">
                {f.glyph}
              </span>
              <div className="relative">
                <h3 className="font-monument text-xs text-chalk tracking-widest mb-1">
                  {f.name}
                </h3>
                <p className="font-telemetry text-[10px] text-gold tracking-[0.08em] uppercase mb-3">
                  {f.outcome}
                </p>
                <p className="font-body text-sm text-steel leading-relaxed">
                  {f.desc}
                </p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
