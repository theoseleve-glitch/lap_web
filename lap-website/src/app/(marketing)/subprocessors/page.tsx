import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Subprocessors | LAP",
  description:
    "List of third-party subprocessors used by LAP for data processing.",
};

const subprocessors = [
  {
    name: "Stripe",
    purpose: "Payment processing and subscription management",
    location: "Ireland (EU)",
    data: "Name, email, payment method, billing address",
    url: "https://stripe.com/privacy",
  },
  {
    name: "Resend",
    purpose: "Transactional email delivery",
    location: "United States",
    data: "Email address, email content",
    url: "https://resend.com/legal/privacy-policy",
  },
  {
    name: "Cloudflare",
    purpose: "CDN, DNS, DDoS protection, frontend hosting (Workers)",
    location: "Global (EU-compliant)",
    data: "IP address, request headers, page content served",
    url: "https://www.cloudflare.com/privacypolicy/",
  },
  {
    name: "Hetzner",
    purpose: "API server hosting, database hosting",
    location: "Germany (EU)",
    data: "All telemetry data, user accounts, analysis results",
    url: "https://www.hetzner.com/legal/privacy-policy",
  },
  {
    name: "Redis (self-hosted on Hetzner)",
    purpose: "Rate limiting, caching, job queue",
    location: "Germany (EU)",
    data: "Session tokens, rate limit counters, job metadata",
    url: null,
  },
];

export default function SubprocessorsPage() {
  return (
    <div className="mx-auto max-w-3xl px-4 py-16">
      <h1 className="mb-2 text-3xl font-bold text-chalk">Subprocessors</h1>
      <p className="mb-8 text-steel">
        LAP uses the following third-party subprocessors to deliver our service.
        This list is maintained as part of our GDPR compliance obligations.
      </p>

      <p className="mb-6 text-sm text-steel">
        Last updated: February 2026. We will notify customers at least 30 days
        before adding a new subprocessor.
      </p>

      <div className="space-y-4">
        {subprocessors.map((sp) => (
          <div
            key={sp.name}
            className="rounded-lg border border-steel/20 bg-concrete/20 p-5"
          >
            <div className="mb-2 flex items-center justify-between">
              <h2 className="text-lg font-semibold text-chalk">{sp.name}</h2>
              <span className="rounded bg-steel/10 px-2 py-0.5 text-xs text-steel">
                {sp.location}
              </span>
            </div>
            <p className="mb-1 text-sm text-steel">{sp.purpose}</p>
            <p className="text-xs text-steel/60">
              <strong>Data processed:</strong> {sp.data}
            </p>
            {sp.url && (
              <a
                href={sp.url}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-2 inline-block text-xs text-lap-green hover:underline"
              >
                Privacy Policy →
              </a>
            )}
          </div>
        ))}
      </div>

      <div className="mt-10 border-t border-steel/20 pt-6">
        <h2 className="mb-2 text-lg font-semibold text-chalk">
          Data Residency
        </h2>
        <p className="text-sm text-steel">
          All primary data (telemetry, user accounts, analysis results) is stored
          on servers located in Germany (Hetzner, Falkenstein data center).
          Payment data is processed by Stripe (Ireland). Email delivery uses
          Resend (US-based, with EU data processing agreements in place).
        </p>
      </div>

      <div className="mt-6">
        <h2 className="mb-2 text-lg font-semibold text-chalk">
          Questions?
        </h2>
        <p className="text-sm text-steel">
          If you have questions about our subprocessors or data processing,
          contact us at{" "}
          <a
            href="mailto:privacy@lap-coach.racing"
            className="text-lap-green hover:underline"
          >
            privacy@lap-coach.racing
          </a>
          .
        </p>
      </div>
    </div>
  );
}
