import { Suspense } from 'react';
import { LeadForm } from '@/components/forms/LeadForm';
import { PageIntro } from '@/components/ui/PageIntro';
import { StatusPill } from '@/components/site/StatusPill';
import { generateSeoMetadata } from '@/lib/seo';

export const metadata = generateSeoMetadata('/waitlist');

export default function WaitlistPage() {
  return (
    <main className="mx-auto max-w-6xl px-4 py-10 md:py-14">
      <PageIntro
        eyebrow="Roadmap Waitlist"
        title="Join the Coming-Soon Waitlist"
        subtitle="Upcoming capabilities — sim telemetry ingestion and multisource import — are captured through this waitlist."
      />
      <section className="grid lg:grid-cols-[2fr_1fr] gap-6">
        <article className="border border-steel/20 bg-concrete/40 p-5">
          <Suspense fallback={<p className="text-steel text-sm">Loading form...</p>}>
            <LeadForm type="waitlist" submitLabel="Join Waitlist" />
          </Suspense>
        </article>
        <aside className="space-y-4">
          <article className="border border-steel/20 p-4">
            <h2 className="font-monument text-[var(--text-h3)] mb-2">Roadmap Items</h2>
            <ul className="space-y-2 text-sm text-steel">
              <li>Sim telemetry ingestion</li>
              <li>Multisource import</li>
            </ul>
          </article>
          <article className="border border-steel/20 p-4">
            <h2 className="font-monument text-[var(--text-h3)] mb-2">Status</h2>
            <StatusPill status="roadmap" />
          </article>
        </aside>
      </section>
    </main>
  );
}
