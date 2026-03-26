'use client';

import { Suspense, useEffect } from 'react';
import { JsonLd } from '@/components/seo/JsonLd';
import { PageIntro } from '@/components/ui/PageIntro';
import { LeadForm } from '@/components/forms/LeadForm';
import { RelatedPages } from '@/components/marketing/RelatedPages';
import { trackB2BFunnel } from '@/lib/analytics';

const VENUE_FEATURES = [
  {
    heading: 'HARDWARE + SOFTWARE',
    body: 'Slide-in GPS loggers with battery SOC dashboard. Zero wiring, zero staff friction.',
  },
  {
    heading: 'AUTONOMOUS REPORTS',
    body: 'Every driver gets a QR recap after their session. No operator required.',
  },
  {
    heading: 'BRANDED EXPERIENCE',
    body: 'Your logo on every report. Upsell premium analysis to your drivers.',
  },
  {
    heading: 'ZERO STAFF PAIN',
    body: 'Weekly battery swap is the only maintenance. Everything else is automatic.',
  },
];

const PROCESS_STEPS = [
  { step: '01', label: 'DISCOVERY CALL', detail: 'Understand your venue, fleet size, and driver volume.' },
  { step: '02', label: 'PILOT EVENT', detail: 'We run a live pilot at your circuit with real drivers.' },
  { step: '03', label: 'ROLLOUT', detail: 'Hardware deployment, staff training, branded reports live.' },
];

export default function VenuesPage() {
  useEffect(() => {
    trackB2BFunnel('venues_visit');
  }, []);

  return (
    <>
      <JsonLd pathname="/venues" />
      <main className="mx-auto max-w-6xl px-4 py-10 md:py-14">
        <PageIntro
          eyebrow="For Venues & Teams"
          title="Give Every Driver a Debrief"
          subtitle="Same telemetry engine that individual drivers use — deployed at your circuit with your branding, zero staff overhead."
        />

        {/* Feature grid */}
        <section className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-12">
          {VENUE_FEATURES.map((f) => (
            <article key={f.heading} className="border border-steel/20 bg-concrete/40 p-5">
              <h3 className="font-monument text-xs tracking-[0.12em] uppercase text-chalk mb-2">
                {f.heading}
              </h3>
              <p className="font-body text-sm text-steel leading-relaxed">{f.body}</p>
            </article>
          ))}
        </section>

        {/* Process */}
        <section className="mb-12">
          <h2 className="font-monument text-[var(--text-h2)] mb-6">HOW IT WORKS</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {PROCESS_STEPS.map((s) => (
              <div key={s.step} className="border border-chalk/15 p-5">
                <span className="font-monument text-2xl text-gold mb-2 block">{s.step}</span>
                <h3 className="font-telemetry text-xs tracking-[0.12em] uppercase text-chalk mb-1">{s.label}</h3>
                <p className="font-body text-sm text-steel">{s.detail}</p>
              </div>
            ))}
          </div>
        </section>

        {/* Contact form */}
        <section className="max-w-xl mx-auto mb-12">
          <h2 className="font-monument text-[var(--text-h2)] mb-4 text-center">GET IN TOUCH</h2>
          <p className="text-steel text-sm text-center mb-6">
            Tell us about your circuit or team. We&apos;ll scope a pilot and get back to you within one business day.
          </p>
          <div className="border border-steel/20 bg-concrete/40 p-6">
            <Suspense fallback={<p className="text-steel text-sm">Loading form...</p>}>
              <LeadForm type="demo" submitLabel="Request Pilot" />
            </Suspense>
          </div>
        </section>

        <RelatedPages pathname="/venues" />
      </main>
    </>
  );
}
