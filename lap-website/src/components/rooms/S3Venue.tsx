'use client';

import { MonumentText } from '@/components/ui/MonumentText';
import { TrackCard } from '@/components/ui/TrackCard';

/* ── SVG Icons (inline, 24x24 viewBox) ───────────────────── */

function QrIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="7" height="7" />
      <rect x="14" y="3" width="7" height="7" />
      <rect x="3" y="14" width="7" height="7" />
      <path d="M14 14h3v3h-3z" />
      <path d="M20 14v7h-3" />
      <path d="M14 20h3" />
      <path d="M20 17h1" />
    </svg>
  );
}

function ChartIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 3v18h18" />
      <path d="M7 16l4-8 4 4 5-9" />
    </svg>
  );
}

function BatteryIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="7" width="18" height="10" rx="1" />
      <path d="M22 11v2" />
      <path d="M6 11v2" />
      <path d="M10 11v2" />
      <path d="M14 11v2" />
    </svg>
  );
}

/* ── Channel cards data ──────────────────────────────────── */
const CHANNELS = [
  {
    title: 'QR RECAP',
    eyebrow: 'MASS MARKET',
    description:
      'Every driver scans a QR after their session. Instant recap: lap times, best corner, session score. Autonomous delivery \u2014 no staff needed.',
    icon: <QrIcon />,
    stamp: 'ZERO STAFF',
    stampDetail: 'AUTONOMOUS',
  },
  {
    title: 'DEEP COACHING',
    eyebrow: 'PREMIUM UPSELL',
    description:
      'Serious drivers unlock the full report. Corner-by-corner coaching, score breakdown, improvement plan. Same quality as individual plans.',
    icon: <ChartIcon />,
    stamp: 'FULL GRADE',
    stampDetail: 'SAME ENGINE',
  },
  {
    title: 'OPS DASHBOARD',
    eyebrow: 'OPERATIONS',
    description:
      'Battery SOC monitoring. Device health. Report delivery status. Weekly battery workflow with slide-in/out swap. Designed around staff, not against them.',
    icon: <BatteryIcon />,
    stamp: 'ZERO PAIN',
    stampDetail: 'OPS-FIRST',
  },
];

export function S3Venue() {
  return (
    <section
      data-room="s3-venue"
      data-accent="orange"
      className="relative py-24 px-6 md:px-12 lg:px-20"
    >
      <div className="max-w-6xl mx-auto">
        {/* ── Headline ───────────────────────────────────── */}
        <MonumentText size="h1" as="h2" className="text-chalk mb-2" reveal>
          ONE ENGINE.
        </MonumentText>
        <MonumentText size="h1" as="h2" className="text-pit-orange mb-4" reveal>
          TWO CHANNELS.
        </MonumentText>
        <p className="font-body text-steel text-base max-w-2xl mb-16 leading-relaxed">
          The same analysis that powers serious individual drivers runs at scale for your venue.
          Two distribution channels. One quality bar.
        </p>

        {/* ── Channel cards ──────────────────────────────── */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-12">
          {CHANNELS.map((ch) => (
            <div key={ch.title} className="relative">
              <span className="font-telemetry text-[10px] tracking-[0.2em] uppercase text-pit-orange mb-3 block">
                {ch.eyebrow}
              </span>
              <TrackCard
                title={ch.title}
                description={ch.description}
                icon={ch.icon}
              >
                <div className="mt-3 inline-block border border-pit-orange/30 px-2 py-0.5">
                  <span className="font-telemetry text-[10px] tracking-[0.12em] uppercase text-pit-orange">
                    {ch.stamp}
                  </span>
                  <span className="block font-telemetry text-[8px] tracking-[0.12em] uppercase text-steel mt-0.5">
                    {ch.stampDetail}
                  </span>
                </div>
              </TrackCard>
            </div>
          ))}
        </div>

        {/* ── Unified engine strip ───────────────────────── */}
        <div className="border border-chalk/10 bg-concrete/50 p-6 flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
          <div>
            <h3 className="font-monument text-[var(--text-h3)] text-chalk mb-1">
              SAME ENGINE. SAME INSIGHTS.
            </h3>
            <p className="font-body text-sm text-steel max-w-xl">
              Competitors often have one &ldquo;venue tool&rdquo; and a weak &ldquo;driver tool.&rdquo;
              We run the same 14-stage pipeline everywhere &mdash; individual drivers get the same depth as venue operations.
            </p>
          </div>
          <span className="inline-block border border-chalk/30 px-3 py-1 shrink-0">
            <span className="font-telemetry text-[11px] tracking-[0.12em] uppercase text-chalk">UNIFIED</span>
            <span className="block font-telemetry text-[9px] tracking-[0.12em] uppercase text-steel mt-0.5">14-STAGE PIPELINE</span>
          </span>
        </div>

        {/* ── Roadmap teaser ─────────────────────────────── */}
        <div className="mt-8 border-t border-chalk/5 pt-6">
          <span className="font-telemetry text-[10px] tracking-[0.2em] uppercase text-steel/40 block mb-2">
            ROADMAP
          </span>
          <p className="font-body text-sm text-steel/60 max-w-xl">
            <strong className="text-chalk/60">Event Pit Wall</strong> &mdash;
            live race strategy that adapts to telemetry in real time.
            Stint plans, pit windows, fuel models &mdash; powered by the same engine.
          </p>
        </div>
      </div>
    </section>
  );
}
