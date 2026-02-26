import { Suspense } from 'react';
import { LeadForm } from '@/components/forms/LeadForm';
import { PageShell } from '@/components/site/PageShell';
import { StatusPill } from '@/components/site/StatusPill';

export default function WaitlistPage() {
  return (
    <PageShell
      eyebrow="Roadmap Waitlist"
      title="Join the Coming-Soon Waitlist"
      description="Roadmap-only modules, including sim telemetry ingestion and webhook tiering, are captured through this waitlist flow."
    >
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
              <li>Webhook tiering by plan</li>
            </ul>
          </article>
          <article className="border border-steel/20 p-4">
            <h2 className="font-monument text-[var(--text-h3)] mb-2">Status</h2>
            <StatusPill status="roadmap" />
          </article>
        </aside>
      </section>
    </PageShell>
  );
}
