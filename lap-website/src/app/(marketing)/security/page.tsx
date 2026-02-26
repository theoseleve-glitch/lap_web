import { PageShell } from '@/components/site/PageShell';
import { StatusPill } from '@/components/site/StatusPill';
import { ReversibleCard } from '@/components/ui/ReversibleCard';

export default function SecurityPage() {
  return (
    <PageShell
      eyebrow="Security and Compliance"
      title="Security, Residency, Retention, and Incident Response"
      description="Detailed trust posture for encryption, data controls, and operational process."
      tone="document"
    >
      <section className="grid md:grid-cols-2 gap-4 mb-8">
        <ReversibleCard
          title="Encryption"
          description="Traffic is protected in transit and data is protected at rest, with role-scoped access and auditability."
        />
        <ReversibleCard
          title="Residency"
          description="EU-first data residency is available by default, with regional routing options for enterprise needs."
        />
        <ReversibleCard
          title="Retention Controls"
          description="Workspace-level retention windows support deletion, compliance workflows, and lifecycle governance."
        />
        <ReversibleCard
          title="Incident Process"
          description="Incidents are triaged by severity with accountable ownership, communication updates, and postmortems."
        />
      </section>

      <section className="border border-steel/20 p-4 mb-8">
        <h2 className="font-monument text-[var(--text-h3)] mb-2">Auditability and Traceability</h2>
        <p className="text-sm text-steel mb-3">
          Pipeline runs include job identifiers, run state changes, and operator trace logs for
          compliance review.
        </p>
        <StatusPill status="enterprise_on_request" />
      </section>

      <section className="border border-steel/20 p-4">
        <h2 className="font-monument text-[var(--text-h3)] mb-2">SLA Overview</h2>
        <ul className="space-y-2 text-sm text-steel">
          <li>Standard support: business-hours response target of 1 business day.</li>
          <li>Premium support: 4-hour response target for priority incidents.</li>
          <li>Enterprise support: contract-specific SLA commitments.</li>
        </ul>
      </section>
    </PageShell>
  );
}
