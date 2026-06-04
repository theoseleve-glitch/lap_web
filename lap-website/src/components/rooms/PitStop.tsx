'use client';

import { MonumentText } from '@/components/ui/MonumentText';
import { PricingTable } from '@/components/ui/PricingTable';
import { FaqAccordion } from '@/components/ui/FaqAccordion';
import { trackFaqExpand, trackCtaClick } from '@/lib/analytics';
import { useCurrency } from '@/hooks/useCurrency';

/* ── FAQ ────────────────────────────────────────────────── */

const FAQ_ITEMS = [
  {
    question: 'How does the free trial work?',
    answer: 'Every membership starts with a 30-day free trial with full access — nothing is held back. You are only charged when the trial ends, and you can cancel any time before then at no cost.',
  },
  {
    question: 'What is the Founding offer?',
    answer: 'The first 50 members lock in €14.90/mo for as long as their membership stays active — €5/mo below the standard €19.90. Once the 50 founding places are taken, new memberships are €19.90/mo.',
  },
  {
    question: 'What makes Lap different from other tools?',
    answer: 'Most tools show you data. Lap tells you what to change. Our analysis pipeline doesn’t just visualize telemetry — it identifies specific corner losses, diagnoses causes (brake point, apex speed, throttle timing), and gives you prioritised next steps. Every session ends with a debrief, not a dashboard.',
  },
  {
    question: 'Do I need engineering knowledge to use Lap?',
    answer: 'No. Lap is built specifically for drivers who don’t want to become data engineers. The analysis pipeline handles the complexity: GPS filtering, track detection, corner segmentation, scoring. You upload a session and read a structured report.',
  },
  {
    question: 'What formats and platforms are supported?',
    answer: 'RaceChrono CSV, RaceBox CSV, AiM CSV, and MoTeC CSV with GPS data. The system auto-detects formats, headers, and encoding — no manual configuration needed.',
  },
  {
    question: 'Is my data private and exportable?',
    answer: 'Your telemetry data is yours. We never share individual session data or driver profiles. All data is encrypted in transit and at rest. You can export your full dataset or delete your account at any time. GDPR compliant.',
  },
];

/* ── Trust indicators ──────────────────────────────────── */

const TRUST_STRIP = [
  'GDPR COMPLIANT',
  'EXPORTABLE DATA',
  'NO LOCK-IN',
  'ENCRYPTED STORAGE',
  'CANCEL ANYTIME',
  'FOUNDING PRICE LOCKED',
];

export function PitStop() {
  const { localizedPlans } = useCurrency();

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
        <div className="col-span-full text-center mb-8">
          <p className="font-body text-body text-steel max-w-prose mx-auto">
            One membership unlocks the entire product. Start with a 30-day free trial &mdash;
            no card charged until it ends.
          </p>
        </div>

        {/* Single membership card */}
        <div className="col-span-full mb-12">
          <PricingTable
            plans={localizedPlans}
            onCtaClick={(plan) => trackCtaClick(plan, 'pit-stop', 'b2c')}
          />
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
