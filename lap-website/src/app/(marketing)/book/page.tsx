import { Suspense } from 'react';
import { LeadForm } from '@/components/forms/LeadForm';
import { PageShell } from '@/components/site/PageShell';

export default function BookPage() {
  return (
    <PageShell
      eyebrow="Booking"
      title="Book Sales or Onboarding Time"
      description="Use this route for pricing-qualified leads, pilot discussions, and onboarding planning."
    >
      <section className="grid lg:grid-cols-[2fr_1fr] gap-6">
        <article className="border border-steel/20 bg-concrete/40 p-5">
          <Suspense fallback={<p className="text-steel text-sm">Loading form...</p>}>
            <LeadForm type="book" submitLabel="Book Session" />
          </Suspense>
        </article>
        <aside className="border border-steel/20 p-4 bg-concrete/20">
          <h2 className="font-monument text-[var(--text-h3)] mb-2">Booking Coverage</h2>
          <ul className="space-y-2 text-sm text-steel">
            <li>Pilot event scoping</li>
            <li>Plan fit and upgrade path</li>
            <li>Team rollout and roles</li>
            <li>Data residency and security review</li>
          </ul>
        </aside>
      </section>
    </PageShell>
  );
}
