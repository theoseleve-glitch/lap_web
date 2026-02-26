import { PageShell } from '@/components/site/PageShell';
import { ReversibleCard } from '@/components/ui/ReversibleCard';

export default function TermsPage() {
  return (
    <PageShell
      eyebrow="Legal"
      title="Terms of Service"
      description="Commercial and operational terms for using the LAP platform."
      tone="document"
    >
      <section className="grid gap-4">
        <ReversibleCard
          title="Access and Entitlements"
          description="Platform access follows active subscription terms and plan-specific usage limits."
        />
        <ReversibleCard
          title="Data Ownership"
          description="You retain ownership of uploaded telemetry. LAP only processes data to provide analysis and support."
        />
        <ReversibleCard
          title="Support and SLA"
          description="Response targets depend on your plan and contract. Enterprise terms override default SLA ranges."
        />
      </section>
    </PageShell>
  );
}
