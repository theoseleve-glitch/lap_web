import { Suspense } from 'react';
import { LeadForm } from '@/components/forms/LeadForm';
import { PageShell } from '@/components/site/PageShell';

export default function ContactPage() {
  return (
    <PageShell
      eyebrow="Contact"
      title="Contact Sales or Support"
      description="General contact route with validated form submission and backend lead delivery."
    >
      <section className="grid lg:grid-cols-[2fr_1fr] gap-6">
        <article className="border border-steel/20 bg-concrete/40 p-5">
          <Suspense fallback={<p className="text-steel text-sm">Loading form...</p>}>
            <LeadForm type="contact" submitLabel="Send Message" />
          </Suspense>
        </article>
        <aside className="border border-steel/20 p-4 bg-concrete/20">
          <h2 className="font-monument text-[var(--text-h3)] mb-2">Response Targets</h2>
          <ul className="space-y-2 text-sm text-steel">
            <li>Business requests: 1 business day</li>
            <li>Operational support: same day during business hours</li>
            <li>Enterprise incidents: follow SLA commitments</li>
          </ul>
        </aside>
      </section>
    </PageShell>
  );
}
