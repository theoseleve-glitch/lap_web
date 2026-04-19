'use client';

import { useState, useCallback, useEffect } from 'react';
import { MonumentText } from '@/components/ui/MonumentText';
import { PricingTable } from '@/components/ui/PricingTable';
import { FaqAccordion } from '@/components/ui/FaqAccordion';
import Link from 'next/link';
import {
  trackPricingToggle,
  trackFaqExpand,
  trackCtaClick,
} from '@/lib/analytics';
import { useCurrency } from '@/hooks/useCurrency';

/* ── Tier summaries (outcome-based, not feature-list) ─────── */

const TIER_SUMMARIES = [
  {
    name: 'DEMO',
    price: 'Free',
    positioning: 'Start improving immediately',
    outcomes: [
      '1 full analysis report per month',
      '4-pillar scoring & corner coaching',
      'Session intelligence & debrief',
      '4h race strategy',
      '5-year report retention',
    ],
    cta: 'Start free',
    ctaHref: '/register?plan=demo&source=pit-stop',
    highlight: false,
  },
  {
    name: 'RACER',
    price: null,
    positioning: 'Serious progression',
    outcomes: [
      '10 reports per month',
      'Full visualization suite',
      'Comparison & progress tracking',
      '24h race strategy + live monitoring',
      'Coaching plans & PDF reports',
    ],
    cta: 'Upgrade to Racer',
    ctaHref: '/register?plan=racer&source=pit-stop',
    highlight: true,
  },
  {
    name: 'WORLD-CLASS',
    price: null,
    positioning: 'Full ecosystem & optimization',
    outcomes: [
      'Unlimited reports',
      'All optimizer modes',
      '12-month raw telemetry retention',
      'API access & data export',
      'Priority pipeline processing',
    ],
    cta: 'Go World-Class',
    ctaHref: '/register?plan=world-class&source=pit-stop',
    highlight: false,
  },
];

/* ── Feature matrix ─────────────────────────────────────── */

const FEATURES: { label: string; demo: string; racer: string; worldClass: string }[] = [
  { label: 'Analysis Reports', demo: '1/mo', racer: '10/mo', worldClass: 'Unlimited' },
  { label: '4-Pillar Scoring', demo: 'Full', racer: 'Full', worldClass: 'Full' },
  { label: 'Corner Coaching', demo: 'Full', racer: 'Full', worldClass: 'Full' },
  { label: 'Session Intelligence', demo: 'Full', racer: 'Full', worldClass: 'Full' },
  { label: 'Visualization Suite', demo: '\u2014', racer: 'Full', worldClass: 'Full' },
  { label: 'Comparison & Progress', demo: '\u2014', racer: 'Full', worldClass: 'Full' },
  { label: 'Race Strategy', demo: '4h limit', racer: 'Up to 24h', worldClass: 'Unlimited' },
  { label: 'Live Race Monitoring', demo: '\u2014', racer: 'Full', worldClass: 'Full' },
  { label: 'Coaching Plans', demo: '\u2014', racer: 'Full', worldClass: 'Full' },
  { label: 'PDF Reports', demo: '\u2014', racer: 'Full', worldClass: 'Full' },
  { label: 'Raw Telemetry Retention', demo: '1 month', racer: '3 months', worldClass: '12 months' },
  { label: 'Report Retention', demo: '5 years', racer: '5 years', worldClass: '5 years' },
  { label: 'API Access', demo: '\u2014', racer: '\u2014', worldClass: 'Full' },
];

/* ── FAQ ────────────────────────────────────────────────── */

const FAQ_ITEMS = [
  {
    question: 'What can I do for free?',
    answer: 'The free tier includes one full analysis report per month with 4-pillar scoring, corner coaching, session intelligence, and 4-hour race strategy. No credit card required. What many competitors charge for \u2014 scoring, corner-level analysis, session debriefs \u2014 Lap includes from the start.',
  },
  {
    question: 'What makes Lap different from other tools?',
    answer: 'Most tools show you data. Lap tells you what to change. Our 14-stage analysis pipeline doesn\u2019t just visualize telemetry \u2014 it identifies specific corner losses, diagnoses causes (brake point, apex speed, throttle timing), and gives you prioritised next steps. Every session ends with a debrief, not a dashboard.',
  },
  {
    question: 'Do I need engineering knowledge to use Lap?',
    answer: 'No. Lap is built specifically for drivers who don\u2019t want to become data engineers. The analysis pipeline handles the complexity: GPS filtering, track detection, corner segmentation, scoring. You upload a session and read a structured report.',
  },
  {
    question: 'Is Lap for sim racing, real-life motorsport, or both?',
    answer: 'Both, ultimately. Early access starts with sim racing (iRacing, ACC, F1) because it\u2019s the fastest path to giving drivers immediate value. Real-world GPS logger support (RaceChrono, RaceBox) and kart-specific analysis are being added as the ecosystem expands. The analysis engine and driver profile work identically across platforms.',
  },
  {
    question: 'What formats and platforms are supported?',
    answer: 'Currently: iRacing telemetry, ACC data files, and F1 series exports. On the real-world side: RaceChrono CSV and RaceBox CSV with GPS + IMU data. The system auto-detects formats, headers, and encoding \u2014 no manual configuration needed.',
  },
  {
    question: 'Is my data private and exportable?',
    answer: 'Your telemetry data is yours. We never share individual session data or driver profiles. All data is encrypted in transit and at rest. You can export your full dataset or delete your account at any time. GDPR compliant.',
  },
  {
    question: 'What happens as the platform evolves?',
    answer: 'Lap is under active development. New modules (Setup Intelligence, Progression Engine) are on the roadmap. Early access pricing is locked in \u2014 you keep your tier pricing as the platform grows. We ship improvements continuously, not in annual releases.',
  },
];

/* ── Trust indicators ──────────────────────────────────── */

const TRUST_STRIP = [
  'GDPR COMPLIANT',
  'EXPORTABLE DATA',
  'NO LOCK-IN',
  'ENCRYPTED STORAGE',
  'CANCEL ANYTIME',
  'EARLY ACCESS PRICING LOCKED',
];

export function PitStop() {
  const [billingPeriod, setBillingPeriod] = useState<'monthly' | 'annual'>('annual');
  const [matrixExpanded, setMatrixExpanded] = useState(false);
  const { localizedPlans } = useCurrency();

  const [ctaVariant, setCtaVariant] = useState<string | undefined>();
  useEffect(() => {
    const match = document.cookie.match(/(?:^|;\s*)lap_exp_cta=([^;]+)/);
    if (match) setCtaVariant(match[1]);
  }, []);

  const toggleBilling = useCallback(() => {
    const next = billingPeriod === 'monthly' ? 'annual' : 'monthly';
    setBillingPeriod(next);
    trackPricingToggle(next);
  }, [billingPeriod]);

  return (
    <section
      id="pit-stop"
      data-accent="none"
      className="relative py-24 md:py-32"
      style={{ minHeight: '100vh' }}
      aria-label="Pricing"
    >
      <div className="grid-lap relative" style={{ zIndex: 1 }}>
        {/* Header */}
        <div className="col-span-full text-center mb-4">
          <MonumentText size="h1" as="h2">
            SIMPLE PRICING.<br />
            <span className="text-gold">SERIOUS TOOLS.</span>
          </MonumentText>
        </div>
        <div className="col-span-full text-center mb-4">
          <p className="font-body text-body text-steel max-w-prose mx-auto">
            Start free with more than most tools charge for.
            Upgrade when you want the full performance layer.
          </p>
        </div>

        {/* Billing toggle */}
        <div className="col-span-full flex items-center justify-center gap-3 mb-8">
          <span className={`font-telemetry text-[11px] ${billingPeriod === 'monthly' ? 'text-chalk' : 'text-steel'}`}>
            MONTHLY
          </span>
          <button
            type="button"
            role="switch"
            aria-checked={billingPeriod === 'annual'}
            className="relative w-12 h-6 bg-concrete border border-steel/30"
            onClick={toggleBilling}
            aria-label="Annual billing"
          >
            <span
              aria-hidden="true"
              className="absolute top-1 w-4 h-4 bg-gold transition-all duration-300"
              style={{ left: billingPeriod === 'annual' ? 'calc(100% - 20px)' : '4px' }}
            />
          </button>
          <span className={`font-telemetry text-[11px] ${billingPeriod === 'annual' ? 'text-chalk' : 'text-steel'}`}>
            ANNUAL
          </span>
        </div>

        {/* Tier summary cards */}
        <div className="col-span-full grid grid-cols-1 md:grid-cols-3 gap-4 max-w-5xl mx-auto mb-8">
          {TIER_SUMMARIES.map((tier) => (
            <div
              key={tier.name}
              className={`card-lift border p-6 flex flex-col ${
                tier.highlight
                  ? 'border-gold/40 bg-concrete'
                  : 'border-chalk/10 bg-concrete/40'
              }`}
            >
              <div className="flex items-center justify-between mb-2">
                <h3 className={`font-monument text-xs tracking-widest ${tier.highlight ? 'text-gold' : 'text-chalk'}`}>
                  {tier.name}
                </h3>
                {tier.price && (
                  <span className="font-telemetry text-xs text-acid-green">{tier.price}</span>
                )}
              </div>
              <p className="font-telemetry text-[10px] tracking-[0.08em] uppercase text-steel mb-4">
                {tier.positioning}
              </p>
              <ul className="space-y-2 flex-1 mb-6">
                {tier.outcomes.map((o) => (
                  <li key={o} className="flex items-start gap-2">
                    <span className={`mt-1 shrink-0 ${tier.highlight ? 'text-gold' : 'text-steel/50'}`}>&mdash;</span>
                    <span className="font-body text-sm text-chalk">{o}</span>
                  </li>
                ))}
              </ul>
              <Link
                href={tier.ctaHref}
                data-cursor="GO"
                className={`inline-flex items-center justify-center min-h-[44px] px-6 py-3 font-telemetry text-[11px] tracking-[0.12em] uppercase font-bold transition-all duration-[420ms] text-center ${
                  tier.highlight
                    ? 'bg-gold text-white hover:brightness-110 hover:shadow-[0_0_32px_rgba(201,168,76,0.25)]'
                    : 'border border-steel/30 text-chalk hover:bg-concrete'
                }`}
                onClick={() => trackCtaClick(tier.name.toLowerCase(), 'pit-stop', 'b2c')}
              >
                {tier.cta}
              </Link>
            </div>
          ))}
        </div>

        {/* Pricing Table (existing component for compatibility) */}
        <div className="col-span-full mb-8 hidden">
          <PricingTable
            plans={localizedPlans}
            billingPeriod={billingPeriod}
            onCtaClick={(plan) => trackCtaClick(plan, 'pit-stop', 'b2c')}
            ctaVariant={ctaVariant}
          />
        </div>

        {/* Feature matrix */}
        <div className="col-span-full mb-8 max-w-5xl mx-auto">
          <button
            type="button"
            className="w-full py-3 font-telemetry text-[11px] tracking-[0.12em] uppercase text-steel hover:text-chalk transition-colors duration-300 flex items-center justify-center gap-2 border border-steel/15 bg-concrete/30"
            onClick={() => setMatrixExpanded(!matrixExpanded)}
          >
            {matrixExpanded ? 'Hide detailed comparison' : 'See full feature comparison'}
            <span
              className="inline-block transition-transform duration-300"
              style={{ transform: matrixExpanded ? 'rotate(180deg)' : 'rotate(0deg)' }}
            >
              &#9662;
            </span>
          </button>

          {matrixExpanded && (
            <div className="overflow-x-auto mt-4">
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="bg-concrete">
                    <th className="border border-steel/20 p-2 text-left text-steel">Feature</th>
                    <th className="border border-steel/20 p-2 text-center text-steel">Demo</th>
                    <th className="border border-steel/20 p-2 text-center text-gold font-monument">Racer</th>
                    <th className="border border-steel/20 p-2 text-center text-steel">World-Class</th>
                  </tr>
                </thead>
                <tbody>
                  {FEATURES.map((row) => (
                    <tr key={row.label} className="hover:bg-concrete/40 transition-colors">
                      <td className="border border-steel/20 p-2 text-chalk">{row.label}</td>
                      {[row.demo, row.racer, row.worldClass].map((val, i) => (
                        <td key={i} className="border border-steel/20 p-2 text-center">
                          {val === '\u2014'
                            ? <span className="text-steel/30">&mdash;</span>
                            : <span className="text-chalk text-xs">{val}</span>}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* FAQ */}
        <div className="col-span-full max-w-2xl mx-auto mb-12">
          <h3 className="font-monument text-[var(--text-h3)] mb-6">FREQUENTLY ASKED</h3>
          <FaqAccordion items={FAQ_ITEMS} onExpand={trackFaqExpand} />
        </div>

        {/* Trust strip */}
        <div className="col-span-full border-t border-chalk/10 pt-8">
          <div className="flex flex-wrap justify-center gap-3">
            {TRUST_STRIP.map((text) => (
              <span key={text} className="inline-block border border-chalk/15 px-3 py-1.5 font-telemetry text-[10px] tracking-[0.12em] uppercase text-steel">
                {text}
              </span>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
