import Link from 'next/link';
import { PageShell } from '@/components/site/PageShell';

export default function StatusPage() {
  return (
    <PageShell
      eyebrow="Operations"
      title="Status and SLA Definitions"
      description="Operational status source, uptime expectations, and support SLA definitions."
    >
      <section className="grid md:grid-cols-2 gap-4 mb-8">
        <article className="border border-steel/20 p-4">
          <h2 className="font-monument text-[var(--text-h3)] mb-2">Status Source</h2>
          <p className="text-sm text-steel">
            Public incident updates and maintenance windows are published on the dedicated status
            source.
          </p>
          <Link
            href="https://status.lap.racing"
            className="inline-block mt-3 text-sm border border-steel/30 px-3 py-1 hover:border-chalk"
          >
            status.lap.racing
          </Link>
        </article>
        <article className="border border-steel/20 p-4">
          <h2 className="font-monument text-[var(--text-h3)] mb-2">Uptime Targets</h2>
          <ul className="space-y-2 text-sm text-steel">
            <li>Core platform target: 99.9% monthly availability.</li>
            <li>Maintenance windows are announced in advance.</li>
            <li>Incident updates include impact scope and ETA.</li>
          </ul>
        </article>
      </section>

      <section className="border border-steel/20 p-4 mb-8">
        <h2 className="font-monument text-[var(--text-h3)] mb-2">SLA Definitions</h2>
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-concrete">
              <th className="text-left p-2 border border-steel/20">Tier</th>
              <th className="text-left p-2 border border-steel/20">P1 Response</th>
              <th className="text-left p-2 border border-steel/20">P2 Response</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td className="p-2 border border-steel/20">Standard</td>
              <td className="p-2 border border-steel/20">1 business day</td>
              <td className="p-2 border border-steel/20">2 business days</td>
            </tr>
            <tr>
              <td className="p-2 border border-steel/20">Premium</td>
              <td className="p-2 border border-steel/20">4 hours</td>
              <td className="p-2 border border-steel/20">1 business day</td>
            </tr>
            <tr>
              <td className="p-2 border border-steel/20">Enterprise</td>
              <td className="p-2 border border-steel/20">Contract defined</td>
              <td className="p-2 border border-steel/20">Contract defined</td>
            </tr>
          </tbody>
        </table>
      </section>

      <section className="border border-steel/20 p-4">
        <h2 className="font-monument text-[var(--text-h3)] mb-2">Auditability</h2>
        <p className="text-sm text-steel">
          Every pipeline job can be traced by job ID, source upload, processing stage transitions,
          and report publication timestamp for compliance audits.
        </p>
      </section>
    </PageShell>
  );
}
