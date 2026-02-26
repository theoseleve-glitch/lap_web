import { Suspense } from 'react';
import Link from 'next/link';
import { LeadForm } from '@/components/forms/LeadForm';
import { PageShell } from '@/components/site/PageShell';
import { StatusPill } from '@/components/site/StatusPill';
import { ReversibleCard } from '@/components/ui/ReversibleCard';
import { PitButton } from '@/components/ui/PitButton';

export default function DemoPage() {
  return (
    <PageShell
      eyebrow="Demo"
      title="Pick the Right Demo Path"
      description="B2C drivers start with a free account and one report. B2B teams book guided demos with our sales and onboarding team."
    >
      <section className="grid lg:grid-cols-2 gap-6 mb-8">
        <article className="border border-steel/20 bg-concrete/40 p-5">
          <h2 className="font-monument text-[var(--text-h3)] mb-3">B2C Driver Demo</h2>
          <ReversibleCard
            title="Free 1-Report Flow"
            description="Create your account, upload one session, and get your first free analysis report. No sales call required."
            className="mb-4"
          />
          <div className="flex flex-wrap gap-3">
            <PitButton href="/register?source=demo">Create Account</PitButton>
            <Link href="/app/analyze" className="border border-steel/30 px-4 py-3 text-sm">
              Go to Analysis Page
            </Link>
          </div>
        </article>

        <article className="border border-steel/20 bg-concrete/40 p-5">
          <h2 className="font-monument text-[var(--text-h3)] mb-3">B2B Guided Demo</h2>
          <Suspense fallback={<p className="text-steel text-sm">Loading form...</p>}>
            <LeadForm type="demo" submitLabel="Request B2B Demo" />
          </Suspense>
        </article>
      </section>

      <section className="grid md:grid-cols-2 gap-4">
        <article className="border border-steel/20 p-4">
          <h2 className="font-monument text-[var(--text-h3)] mb-2">B2B Demo Coverage</h2>
          <ol className="space-y-2 text-sm text-steel">
            <li>Operator workflow walk-through and implementation fit.</li>
            <li>Race strategy dashboard, corner replay, and map modules review.</li>
            <li>Pilot rollout plan with pricing and onboarding scope.</li>
          </ol>
        </article>
        <article className="border border-steel/20 p-4">
          <h2 className="font-monument text-[var(--text-h3)] mb-2">Capability Status</h2>
          <div className="flex flex-wrap gap-2">
            <StatusPill status="available_now" />
            <StatusPill status="enterprise_on_request" />
          </div>
        </article>
      </section>
    </PageShell>
  );
}
