import { Suspense } from 'react';
import { LeadForm } from '@/components/forms/LeadForm';
import { PageShell } from '@/components/site/PageShell';
import { StatusPill } from '@/components/site/StatusPill';

export default function DemoPage() {
  return (
    <PageShell
      eyebrow="Demo"
      title="Book a Product Demo"
      description="Submit your demo request and we route the lead to CRM plus email notifications. This flow has validation and thank-you tracking."
    >
      <section className="grid lg:grid-cols-[2fr_1fr] gap-6">
        <article className="border border-steel/20 bg-concrete/40 p-5">
          <Suspense fallback={<p className="text-steel text-sm">Loading form...</p>}>
            <LeadForm type="demo" submitLabel="Request Demo" />
          </Suspense>
        </article>
        <aside className="space-y-4">
          <article className="border border-steel/20 p-4">
            <h2 className="font-monument text-[var(--text-h3)] mb-2">What Happens Next</h2>
            <ol className="space-y-2 text-sm text-steel">
              <li>Lead enters CRM pipeline stage: Demo Requested.</li>
              <li>Email notification is sent to the go-to-market inbox.</li>
              <li>Success redirects to thank-you with conversion event.</li>
            </ol>
          </article>
          <article className="border border-steel/20 p-4">
            <h2 className="font-monument text-[var(--text-h3)] mb-2">Capability Status</h2>
            <div className="flex flex-wrap gap-2">
              <StatusPill status="available_now" />
              <StatusPill status="enterprise_on_request" />
            </div>
          </article>
        </aside>
      </section>
    </PageShell>
  );
}
