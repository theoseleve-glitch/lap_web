import { PageShell } from '@/components/site/PageShell';

export default function TermsPage() {
  return (
    <PageShell
      eyebrow="Legal"
      title="Terms of Service"
      description="Commercial and operational terms for using the LAP platform."
    >
      <section className="space-y-4 text-sm text-steel">
        <p>
          Service access is provided under active subscription terms. Plan entitlements and usage
          limits are defined in the pricing and eligibility matrix.
        </p>
        <p>
          Customers retain ownership of uploaded telemetry. LAP receives a limited license to
          process data for analysis, reporting, and support obligations.
        </p>
        <p>
          SLA tiers, support windows, and availability commitments are defined by plan and contract.
          Enterprise riders supersede standard terms where applicable.
        </p>
      </section>
    </PageShell>
  );
}
