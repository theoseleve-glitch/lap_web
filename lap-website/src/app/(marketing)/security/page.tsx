import { PageShell } from '@/components/site/PageShell';
import { StatusPill } from '@/components/site/StatusPill';

export default function SecurityPage() {
  return (
    <PageShell
      eyebrow="Security and Compliance"
      title="Security, Residency, Retention, and Incident Response"
      description="Detailed trust posture for encryption, data controls, and operational process."
    >
      <section className="grid md:grid-cols-2 gap-4 mb-8">
        <article className="border border-steel/20 p-4">
          <h2 className="font-monument text-[var(--text-h3)] mb-2">Encryption</h2>
          <p className="text-sm text-steel">
            Data is encrypted in transit with TLS and encrypted at rest through managed storage
            controls. Access is role-scoped and audited.
          </p>
        </article>
        <article className="border border-steel/20 p-4">
          <h2 className="font-monument text-[var(--text-h3)] mb-2">Residency</h2>
          <p className="text-sm text-steel">
            EU-first data residency is available. Regional routing options are handled on request
            for enterprise contracts.
          </p>
        </article>
        <article className="border border-steel/20 p-4">
          <h2 className="font-monument text-[var(--text-h3)] mb-2">Retention Controls</h2>
          <p className="text-sm text-steel">
            Retention windows can be configured by workspace. Deletion requests are tracked with
            irreversible processing logs.
          </p>
        </article>
        <article className="border border-steel/20 p-4">
          <h2 className="font-monument text-[var(--text-h3)] mb-2">Incident Process</h2>
          <p className="text-sm text-steel">
            Incidents are triaged by severity, assigned an incident commander, and followed by
            postmortem documentation and customer communication.
          </p>
        </article>
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
