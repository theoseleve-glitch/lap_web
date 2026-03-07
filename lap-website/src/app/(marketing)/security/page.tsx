import { PageIntro } from '@/components/ui/PageIntro';
import { StatusPill } from '@/components/site/StatusPill';
import Link from 'next/link';
import { generateSeoMetadata } from '@/lib/seo';

export const metadata = generateSeoMetadata('/security');

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-8">
      <h2 className="font-monument text-[var(--text-h3)] mb-3">{title}</h2>
      <div className="text-steel text-sm leading-relaxed space-y-3">{children}</div>
    </section>
  );
}

export default function SecurityPage() {
  return (
    <main className="mx-auto max-w-4xl px-4 py-10 md:py-14">
      <PageIntro
        eyebrow="Security and Compliance"
        title="Security, Residency, Retention, and Incident Response"
        subtitle="Detailed trust posture for encryption, data controls, and operational process."
      />
      <Section title="Encryption">
        <p>
          All traffic between the browser and LAP servers is protected by TLS 1.2+ via Caddy
          automatic HTTPS. Data at rest in PostgreSQL is stored on encrypted volumes. Backups are
          encrypted with AES-256.
        </p>
        <ul className="list-disc list-inside space-y-1 ml-2">
          <li>Passwords: Argon2id (time cost 3, memory 64 KiB, parallelism 1)</li>
          <li>Authentication tokens: JWT signed with HS256, short-lived access tokens (15 min)</li>
          <li>Refresh tokens: httpOnly Secure SameSite=Lax cookies with single-use rotation</li>
          <li>API transport: HTTPS-only with HSTS headers</li>
        </ul>
      </Section>

      <Section title="Data Isolation">
        <p>
          LAP uses PostgreSQL Row-Level Security (RLS) for workspace-level data isolation. Every
          workspace-scoped table (44 tables) has RLS policies that automatically filter rows based on
          the authenticated workspace context, set via <code className="text-chalk">SET LOCAL</code>{' '}
          at the start of each request transaction.
        </p>
        <p>
          This means one workspace can never query, modify, or delete data belonging to another —
          even if application-layer code has a bug. The database enforces the boundary.
        </p>
      </Section>

      <Section title="Data Residency">
        <p>
          Primary data processing and storage is located in the EU: Hetzner cloud, Falkenstein,
          Germany (EU). Redis and PostgreSQL run on the same EU infrastructure. The frontend is served
          globally via Cloudflare Workers edge locations, but no user data is stored at the edge.
        </p>
        <p>
          Third-party sub-processors and their data locations are documented on the{' '}
          <Link href="/subprocessors" className="text-pit-orange hover:underline">
            subprocessors page
          </Link>
          . Enterprise customers may request region-locked processing.
        </p>
      </Section>

      <Section title="Retention Controls">
        <p>
          Data retention is configurable at the workspace level. Default retention windows apply:
        </p>
        <ul className="list-disc list-inside space-y-1 ml-2">
          <li>Telemetry session data: retained for the lifetime of the workspace</li>
          <li>Account data: retained while the account is active, deleted on erasure request</li>
          <li>Backups: 7-day rolling retention, daily snapshots at 03:00 UTC</li>
          <li>Rate limit and idempotency cache: 24-hour TTL in Redis</li>
        </ul>
        <p>
          Self-service data export and account erasure are available through the application settings.
          GDPR erasure requests are processed via Celery background tasks to ensure complete removal
          across all storage systems.
        </p>
      </Section>

      <Section title="Incident Response">
        <p>
          Incidents are triaged by severity with accountable ownership:
        </p>
        <ul className="list-disc list-inside space-y-1 ml-2">
          <li>
            <strong className="text-chalk">P1 (Critical):</strong> Service down or data breach —
            4-hour response target, continuous updates until resolved
          </li>
          <li>
            <strong className="text-chalk">P2 (High):</strong> Degraded service or security
            vulnerability — 1 business day response target
          </li>
          <li>
            <strong className="text-chalk">P3 (Medium):</strong> Non-critical issues — 3 business
            day response target
          </li>
        </ul>
        <p>
          Data breaches are reported to affected controllers within 72 hours of confirmed detection,
          per GDPR Article 33. Post-incident reviews are conducted and documented for all P1 and P2
          incidents.
        </p>
      </Section>

      <Section title="Vulnerability Disclosure">
        <p>
          If you discover a security vulnerability, please report it responsibly by emailing{' '}
          <span className="text-chalk">security@lap-coach.racing</span>. We commit to acknowledging
          reports within 48 hours and providing an initial assessment within 5 business days.
        </p>
        <p>
          We do not pursue legal action against researchers who act in good faith and follow
          responsible disclosure practices.
        </p>
      </Section>

      <section className="border border-steel/20 p-4 mb-8">
        <h2 className="font-monument text-[var(--text-h3)] mb-2">Auditability and Traceability</h2>
        <p className="text-sm text-steel mb-3">
          Pipeline runs include job identifiers, run state changes, and operator trace logs for
          compliance review. Ingestion jobs track throughput, peak memory, and completion status.
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
    </main>
  );
}
