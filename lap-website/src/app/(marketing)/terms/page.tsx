import Link from 'next/link';
import { JsonLd } from '@/components/seo/JsonLd';
import { PageIntro } from '@/components/ui/PageIntro';
import { generateSeoMetadata } from '@/lib/seo';

export const metadata = generateSeoMetadata('/terms');

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-8">
      <h2 className="font-monument text-[var(--text-h3)] mb-3">{title}</h2>
      <div className="text-steel text-sm leading-relaxed space-y-3">{children}</div>
    </section>
  );
}

export default function TermsPage() {
  return (
    <>
    <JsonLd pathname="/terms" />
    <main className="mx-auto max-w-4xl px-4 py-10 md:py-14">
      <PageIntro
        eyebrow="Legal"
        title="Terms of Service"
        subtitle="Terms governing your use of the LAP platform. Effective: 2026-02-01. Last updated: 2026-03-06."
      />
      <Section title="1. Account & Access">
        <p>
          You must be 16 or older to create an account. You are responsible for maintaining the
          security of your credentials. Access is governed by your active subscription plan and its
          usage limits (reports, uploads, storage, API calls).
        </p>
      </Section>

      <Section title="2. Subscriptions & Billing">
        <p>
          Paid plans are billed monthly or annually via Stripe. Subscriptions auto-renew unless
          cancelled before the period end. Downgrading may reduce data retention and feature access.
          Refunds are handled per our cancellation policy.
        </p>
      </Section>

      <Section title="3. Data Ownership & License">
        <p>
          You retain full ownership of all telemetry data you upload. By uploading, you grant LAP a
          limited license to process your data solely for providing analysis, reports, and platform
          features. We do not use your data for any other purpose.
        </p>
      </Section>

      <Section title="4. Data Retention & Deletion">
        <p>
          Raw telemetry data is retained per your plan tier (30/90/365 days). Reports and derived
          data are retained indefinitely while your account is active. Account deletion triggers a
          30-day grace period, after which all data is permanently removed.
        </p>
      </Section>

      <Section title="5. Acceptable Use">
        <p>You may not use LAP to:</p>
        <ul className="list-disc list-inside space-y-1 ml-2">
          <li>Process data you do not have rights to</li>
          <li>Attempt to reverse-engineer the platform</li>
          <li>Exceed rate limits programmatically</li>
          <li>Distribute analysis reports as a competing service</li>
        </ul>
        <p>API access is limited to plans that include it.</p>
      </Section>

      <Section title="6. Service Availability">
        <p>
          LAP targets 99.5% uptime for the analysis API. Scheduled maintenance windows will be
          communicated in advance. We are not liable for temporary service interruptions or data loss
          caused by factors beyond our control.
        </p>
      </Section>

      <Section title="7. Support & SLA">
        <p>
          All plans include email support with a 24-hour target response time. Enterprise customers
          receive priority support and custom SLAs. Support covers platform issues, not motorsport
          coaching or telemetry interpretation.
        </p>
      </Section>

      <Section title="8. Limitation of Liability">
        <p>
          LAP provides telemetry analysis as-is. We are not responsible for racing decisions made
          based on analysis outputs. Our total liability is limited to the fees paid in the 12 months
          preceding any claim.
        </p>
      </Section>

      <div className="mt-8 text-center text-xs text-steel font-body space-x-4">
        <Link href="/privacy" className="hover:text-chalk transition">
          Privacy Policy
        </Link>
        <Link href="/pricing" className="hover:text-chalk transition">
          Plans &amp; Pricing
        </Link>
        <Link href="/app/account/support" className="hover:text-chalk transition">
          Contact Support
        </Link>
      </div>
    </main>
    </>
  );
}
