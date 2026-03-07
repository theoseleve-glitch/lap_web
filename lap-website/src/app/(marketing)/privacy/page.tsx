import Link from 'next/link';
import { JsonLd } from '@/components/seo/JsonLd';
import { PageIntro } from '@/components/ui/PageIntro';
import { generateSeoMetadata } from '@/lib/seo';

export const metadata = generateSeoMetadata('/privacy');

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-8">
      <h2 className="font-monument text-[var(--text-h3)] mb-3">{title}</h2>
      <div className="text-steel text-sm leading-relaxed space-y-3">{children}</div>
    </section>
  );
}

export default function PrivacyPage() {
  return (
    <>
    <JsonLd pathname="/privacy" />
    <main className="mx-auto max-w-4xl px-4 py-10 md:py-14">
      <PageIntro
        eyebrow="Legal"
        title="Privacy Policy"
        subtitle="How LAP collects, processes, and protects your data. Effective: 2026-02-01. Last updated: 2026-03-06."
      />
      <Section title="Data We Collect">
        <p>
          Account information (email, name, password hash), telemetry CSV files (GPS traces, speed,
          throttle, brake data), usage analytics (feature usage, session counts), and payment
          information (processed by Stripe — we never store card numbers).
        </p>
      </Section>

      <Section title="How We Use Your Data">
        <p>
          Telemetry data is processed to generate analysis reports, scoring, coaching plans, and
          visualizations. Account data supports authentication, billing, and support. Usage data
          helps us improve the platform. We do not sell your data.
        </p>
      </Section>

      <Section title="Data Retention">
        <p>
          Raw telemetry retention depends on your plan: Demo (30 days), Racer (90 days), World-Class
          (365 days). Reports, scores, and lap data are retained indefinitely while your account is
          active. Account data is retained while your account is active and for 30 days after a
          deletion request.
        </p>
      </Section>

      <Section title="Third-Party Processors">
        <p>
          We use the following sub-processors, each operating under data processing agreements:
        </p>
        <ul className="list-disc list-inside space-y-1 ml-2">
          <li>Stripe — payment processing (PCI DSS compliant)</li>
          <li>Resend — transactional email</li>
          <li>Cloudflare — CDN, DNS, DDoS protection</li>
          <li>Hetzner — server hosting (EU data center, Falkenstein, Germany)</li>
        </ul>
        <p>
          The full list is maintained at{' '}
          <Link href="/subprocessors" className="text-pit-orange hover:underline">
            /subprocessors
          </Link>
          .
        </p>
      </Section>

      <Section title="Your Rights (GDPR)">
        <p>You have the right to:</p>
        <ul className="list-disc list-inside space-y-1 ml-2">
          <li>Access your data (Data Export)</li>
          <li>Rectification (update profile)</li>
          <li>Erasure (delete account)</li>
          <li>Data portability (ZIP export with GPS precision reduction)</li>
          <li>Restriction of processing</li>
          <li>Object to processing</li>
        </ul>
        <p>
          Exercise rights via Settings &gt; Data &amp; Privacy or contact our DPO at{' '}
          <span className="text-chalk">dpo@lap-coach.racing</span>.
        </p>
      </Section>

      <Section title="Cookies">
        <p>
          We use necessary cookies for authentication and security. Analytics and marketing cookies
          are only activated with your explicit consent. You can manage preferences at any time via
          the cookie settings in the footer.
        </p>
      </Section>

      <Section title="Data Security">
        <ul className="list-disc list-inside space-y-1 ml-2">
          <li>Passwords are hashed with Argon2id (time cost 3, memory 64 KiB)</li>
          <li>JWTs are signed with HS256 with short-lived access tokens</li>
          <li>All connections use TLS 1.2+</li>
          <li>Database access is controlled with PostgreSQL Row-Level Security</li>
          <li>Two-factor authentication is available for all accounts</li>
          <li>Daily encrypted backups with 7-day retention</li>
        </ul>
      </Section>

      <Section title="Contact">
        <p>
          Data Protection Officer:{' '}
          <span className="text-chalk">dpo@lap-coach.racing</span>. For privacy inquiries, support
          tickets, or to exercise your data rights, contact us through Settings &gt; Support or email
          directly.
        </p>
      </Section>

      <div className="mt-8 text-center text-xs text-steel font-body space-x-4">
        <Link href="/terms" className="hover:text-chalk transition">
          Terms of Service
        </Link>
        <Link href="/pricing" className="hover:text-chalk transition">
          Plans &amp; Retention
        </Link>
        <Link href="/app/account/data" className="hover:text-chalk transition">
          Manage Your Data
        </Link>
      </div>
    </main>
    </>
  );
}
