'use client';

import { MonumentText } from '@/components/ui/MonumentText';

const FRAGMENTED_STACK = [
  { name: 'Telemetry overlay app', cost: '$15/mo', note: 'One app for traces' },
  { name: 'Timing & leaderboard app', cost: '$10/mo', note: 'Another for lap times' },
  { name: 'Setup spreadsheet', cost: 'Free', note: 'Manual, no analysis' },
  { name: 'Strategy calculator', cost: '$8/mo', note: 'Race day only' },
  { name: 'Progress notes', cost: 'Free', note: 'Scattered, no structure' },
  { name: 'Video sync tool', cost: '$20/mo', note: 'Separate login, separate data' },
];

const LAP_MODULES = [
  'Session Analysis',
  'Corner Coaching',
  'Driver Scoring',
  'Progression Tracking',
  'Race Strategy',
  'Setup Intelligence',
  'Data Logger',
];

export function S1Pain() {
  return (
    <section
      id="s1-pain"
      data-accent="none"
      className="relative py-24 md:py-32"
      aria-label="Fragmented tools problem"
    >
      <div className="grid-lap">
        <div className="col-span-full text-center mb-4">
          <MonumentText size="h1" as="h2" split>
            STOP STACKING TOOLS.
          </MonumentText>
        </div>
        <div className="col-span-full text-center mb-12">
          <p className="font-body text-body text-steel max-w-prose mx-auto">
            What many drivers pay for separately, Lap brings together in one system.
          </p>
        </div>

        <div className="col-span-full grid grid-cols-1 md:grid-cols-2 gap-8 max-w-5xl mx-auto">
          {/* Left — Fragmented stack */}
          <div data-skew className="border border-steel/20 bg-asphalt p-6">
            <span className="font-telemetry text-[10px] tracking-[0.2em] uppercase text-steel mb-6 block">
              THE TYPICAL DRIVER STACK
            </span>
            <div className="space-y-0">
              {FRAGMENTED_STACK.map((tool) => (
                <div key={tool.name} className="flex items-center justify-between py-3 border-b border-steel/10">
                  <div>
                    <span className="font-telemetry text-xs text-steel">{tool.name}</span>
                    <span className="block font-body text-[11px] text-steel/50 mt-0.5">{tool.note}</span>
                  </div>
                  <span className="font-telemetry text-xs text-steel/60 shrink-0 ml-4">{tool.cost}</span>
                </div>
              ))}
            </div>
            <div className="mt-4 pt-3 border-t border-steel/20">
              <div className="flex justify-between font-telemetry text-xs">
                <span className="text-steel">6 tools, 6 logins, no connection</span>
                <span className="text-safety-red">~$53/mo</span>
              </div>
            </div>
          </div>

          {/* Right — Lap ecosystem */}
          <div data-skew className="border border-chalk/15 bg-concrete p-6">
            <span className="font-telemetry text-[10px] tracking-[0.2em] uppercase text-gold mb-6 block">
              THE LAP ECOSYSTEM
            </span>
            <div className="space-y-0">
              {LAP_MODULES.map((mod) => (
                <div key={mod} className="flex items-center justify-between py-3 border-b border-chalk/10">
                  <span className="font-telemetry text-xs text-chalk">{mod}</span>
                  <span className="font-telemetry text-xs text-acid-green">INCLUDED</span>
                </div>
              ))}
            </div>
            <div className="mt-4 pt-3 border-t border-chalk/15">
              <div className="flex justify-between font-telemetry text-xs">
                <span className="text-chalk">One ecosystem. Everything connected.</span>
                <span className="text-acid-green">FROM FREE</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
