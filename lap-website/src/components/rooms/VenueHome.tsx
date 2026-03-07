'use client';

import { MonumentText } from '@/components/ui/MonumentText';
import { TrackCard } from '@/components/ui/TrackCard';
import { StampButton } from '@/components/ui/StampButton';
import { PitButton } from '@/components/ui/PitButton';
import { StartGrid } from '@/components/rooms/StartGrid';
import { Garage } from '@/components/rooms/Garage';
import { trackCtaClick, trackDemoCtaClick } from '@/lib/analytics';

/* ── Inline SVG Icons ────────────────────────── */

function QrIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="7" height="7" />
      <rect x="14" y="3" width="7" height="7" />
      <rect x="3" y="14" width="7" height="7" />
      <path d="M14 14h3v3h-3z" />
      <path d="M20 14v7h-3" />
      <path d="M14 20h3" />
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

/* ── Channel cards ────────────────────────────── */
const CHANNELS = [
  {
    title: 'QR RECAP',
    eyebrow: 'MASS MARKET',
    description:
      'Every driver scans a QR after their session. Instant recap: lap times, best corner, session score. Autonomous delivery — no staff needed.',
    icon: <QrIcon />,
    badge: 'ZERO STAFF',
    badgeDetail: 'AUTONOMOUS',
  },
  {
    title: 'DEEP COACHING',
    eyebrow: 'PREMIUM UPSELL',
    description:
      'Serious drivers unlock the full report. Corner-by-corner Coaching, score breakdown, improvement plan. Same quality as individual plans.',
    icon: <ChartIcon />,
    badge: 'FULL GRADE',
    badgeDetail: 'SAME ENGINE',
  },
  {
    title: 'OPS DASHBOARD',
    eyebrow: 'OPERATIONS',
    description:
      'Battery SOC monitoring. Device health. Report delivery status. Weekly battery workflow with slide-in/out swap. Designed around staff, not against them.',
    icon: <BatteryIcon />,
    badge: 'ZERO PAIN',
    badgeDetail: 'OPS-FIRST',
  },
];

export function VenueHome() {
  return (
    <main id="main-content">
      {/* 1. Shared hero */}
      <StartGrid />

      {/* 2. Venue hero section */}
      <section
        data-accent="orange"
        className="relative py-24 px-6 md:px-12 lg:px-20"
      >
        <div className="max-w-6xl mx-auto">
          <MonumentText size="h1" as="h2" className="text-chalk mb-2" reveal>
            ONE ENGINE.
          </MonumentText>
          <MonumentText size="h1" as="h2" className="text-pit-orange mb-6" reveal>
            YOUR VENUE.
          </MonumentText>
          <p className="font-body text-steel text-lg max-w-2xl mb-0 leading-relaxed">
            The same 14-stage analysis that powers individual drivers runs at scale for your venue.
            Three channels. One quality bar. Zero staff overhead.
          </p>
        </div>
      </section>

      {/* 3. Channel cards */}
      <section className="relative py-16 px-6 md:px-12 lg:px-20">
        <div className="max-w-6xl mx-auto">
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
                      {ch.badge}
                    </span>
                    <span className="block font-telemetry text-[8px] tracking-[0.12em] uppercase text-steel mt-0.5">
                      {ch.badgeDetail}
                    </span>
                  </div>
                </TrackCard>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* 4. Unified engine strip */}
      <section className="relative px-6 md:px-12 lg:px-20 pb-16">
        <div className="max-w-6xl mx-auto">
          <div className="border border-chalk/10 bg-concrete/50 p-6 flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
            <div>
              <h3 className="font-monument text-[var(--text-h3)] text-chalk mb-1">
                SAME ENGINE. SAME INSIGHTS.
              </h3>
              <p className="font-body text-sm text-steel max-w-xl">
                We run the same 14-stage pipeline everywhere &mdash; individual drivers get the same depth as venue operations.
              </p>
            </div>
            <span className="inline-block border border-chalk/30 px-3 py-1 shrink-0">
              <span className="font-telemetry text-[11px] tracking-[0.12em] uppercase text-chalk">UNIFIED</span>
              <span className="block font-telemetry text-[9px] tracking-[0.12em] uppercase text-steel mt-0.5">14-STAGE PIPELINE</span>
            </span>
          </div>
        </div>
      </section>

      {/* 5. Venue pricing — Contact Sales */}
      <section
        data-accent="orange"
        className="relative py-24 px-6 md:px-12 lg:px-20"
      >
        <div className="max-w-3xl mx-auto text-center">
          <MonumentText size="h1" as="h2" className="mb-6">
            BUILT FOR YOUR SCALE
          </MonumentText>
          <p className="font-body text-steel text-base mb-8 max-w-lg mx-auto leading-relaxed">
            Custom hardware, branded reports, dedicated onboarding. Pricing is based on fleet size and event volume.
          </p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
            <PitButton
              href="/contact?plan=venues"
              onClick={() => trackCtaClick('contact_sales', 'venue-home', 'venues')}
            >
              CONTACT SALES
            </PitButton>
            <StampButton
              href="/book"
              onClick={() => { trackCtaClick('book_demo', 'venue-home', 'venues'); trackDemoCtaClick('venue-home'); }}
            >
              BOOK A DEMO
            </StampButton>
          </div>
        </div>
      </section>

      {/* 6. Roadmap teaser */}
      <section className="relative px-6 md:px-12 lg:px-20 py-12">
        <div className="max-w-6xl mx-auto border-t border-chalk/5 pt-6">
          <span className="font-telemetry text-[10px] tracking-[0.2em] uppercase text-steel/60 block mb-2">
            ROADMAP
          </span>
          <p className="font-body text-sm text-steel/60 max-w-xl">
            <strong className="text-chalk/60">Event Pit Wall</strong> &mdash;
            live race strategy that adapts to telemetry in real time.
            Stint plans, pit windows, fuel models &mdash; powered by the same engine.
          </p>
        </div>
      </section>

      {/* 7. Garage (shared) */}
      <Garage />

      {/* 8. Podium — venue-specific */}
      <section
        id="podium"
        data-accent="orange"
        className="room relative py-16 md:py-24"
        aria-label="Venue — Final action"
      >
        <div className="grid-lap">
          <div className="col-span-full flex flex-col items-center justify-center text-center gap-8">
            <MonumentText size="xl" as="h2" reveal>
              READY TO EQUIP<br />YOUR VENUE?
            </MonumentText>

            <div className="flex flex-col sm:flex-row items-center gap-4">
              <PitButton
                href="/contact?plan=venues"
                onClick={() => trackCtaClick('contact_sales', 'venue-podium', 'venues')}
              >
                CONTACT SALES
              </PitButton>
              <StampButton
                href="/book"
                onClick={() => { trackCtaClick('book_demo', 'venue-podium', 'venues'); trackDemoCtaClick('venue-podium'); }}
              >
                BOOK A DEMO
              </StampButton>
            </div>

            <p className="font-telemetry text-steel max-w-lg">
              CUSTOM HARDWARE // BRANDED REPORTS // DEDICATED ONBOARDING
            </p>
          </div>
        </div>
      </section>
    </main>
  );
}
