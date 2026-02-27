import Link from 'next/link';
import { PageShell } from '@/components/site/PageShell';
import { ReversibleCard } from '@/components/ui/ReversibleCard';

export default function TermsPage() {
  return (
    <PageShell
      eyebrow="Legal"
      title="Terms of Service"
      description="Terms governing your use of the LAP platform. Last updated: February 2026."
      tone="document"
    >
      <section className="grid gap-6">
        <ReversibleCard
          title="Account & Access"
          description="You must be 16+ to create an account. You're responsible for maintaining the security of your credentials. Access is governed by your active subscription plan and its usage limits (reports, uploads, storage, API calls)."
        />
        <ReversibleCard
          title="Subscriptions & Billing"
          description="Paid plans are billed monthly or annually via Stripe. Subscriptions auto-renew unless cancelled before the period end. Downgrading may reduce data retention and feature access. Refunds are handled per our cancellation policy."
        />
        <ReversibleCard
          title="Data Ownership & License"
          description="You retain full ownership of all telemetry data you upload. By uploading, you grant LAP a limited license to process your data solely for providing analysis, reports, and platform features. We do not use your data for any other purpose."
        />
        <ReversibleCard
          title="Data Retention & Deletion"
          description="Raw telemetry data is retained per your plan tier (30/90/365 days). Reports and derived data are retained indefinitely while your account is active. Account deletion triggers a 30-day grace period, after which all data is permanently removed."
        />
        <ReversibleCard
          title="Acceptable Use"
          description="You may not use LAP to process data you don't have rights to, attempt to reverse-engineer the platform, exceed rate limits programmatically, or distribute analysis reports as a competing service. API access is limited to plans that include it."
        />
        <ReversibleCard
          title="Service Availability"
          description="LAP targets 99.5% uptime for the analysis API. Scheduled maintenance windows will be communicated in advance. We are not liable for temporary service interruptions or data loss caused by factors beyond our control."
        />
        <ReversibleCard
          title="Support & SLA"
          description="All plans include email support with 24-hour target response time. Enterprise customers receive priority support and custom SLAs. Support covers platform issues, not motorsport coaching or telemetry interpretation."
        />
        <ReversibleCard
          title="Limitation of Liability"
          description="LAP provides telemetry analysis as-is. We are not responsible for racing decisions made based on analysis outputs. Our total liability is limited to the fees paid in the 12 months preceding any claim."
        />
      </section>

      <div className="mt-8 text-center text-xs text-steel font-body space-x-4">
        <Link href="/privacy" className="hover:text-chalk transition">Privacy Policy</Link>
        <Link href="/pricing" className="hover:text-chalk transition">Plans & Pricing</Link>
        <Link href="/app/account/support" className="hover:text-chalk transition">Contact Support</Link>
      </div>
    </PageShell>
  );
}
