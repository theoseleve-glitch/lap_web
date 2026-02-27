import Link from 'next/link';
import { PageShell } from '@/components/site/PageShell';
import { ReversibleCard } from '@/components/ui/ReversibleCard';

export default function PrivacyPage() {
  return (
    <PageShell
      eyebrow="Legal"
      title="Privacy Policy"
      description="How LAP collects, processes, and protects your data. Last updated: February 2026."
      tone="document"
    >
      <section className="grid gap-6">
        <ReversibleCard
          title="Data We Collect"
          description="Account information (email, name, password hash), telemetry CSV files (GPS traces, speed, throttle, brake data), usage analytics (feature usage, session counts), and payment information (processed by Stripe — we never store card numbers)."
        />
        <ReversibleCard
          title="How We Use Your Data"
          description="Telemetry data is processed to generate analysis reports, scoring, coaching plans, and visualizations. Account data supports authentication, billing, and support. Usage data helps us improve the platform. We do not sell your data."
        />
        <ReversibleCard
          title="Data Retention"
          description="Raw telemetry retention depends on your plan: Demo (30 days), Racer (90 days), World-Class (365 days). Reports, scores, and lap data are retained indefinitely. Account data is retained while your account is active and for 30 days after deletion request."
        />
        <ReversibleCard
          title="Third-Party Processors"
          description="Stripe (payment processing, PCI DSS compliant), Resend (transactional email), Cloudflare (CDN, DNS, DDoS protection), Hetzner (server hosting, EU data center). All processors operate under data processing agreements."
        />
        <ReversibleCard
          title="Your Rights (GDPR)"
          description="You have the right to: Access your data (data export), Rectification (update profile), Erasure (delete account), Data portability (ZIP export with GPS precision reduction), Restriction of processing, and Object to processing. Exercise rights via Settings > Data & Privacy or contact our DPO."
        />
        <ReversibleCard
          title="Cookies"
          description="We use necessary cookies for authentication and security. Analytics and marketing cookies are only activated with your explicit consent. You can manage preferences at any time via the cookie settings in the footer."
        />
        <ReversibleCard
          title="Data Security"
          description="Passwords are hashed with Argon2id. JWTs are signed with HS256. All connections use TLS. Database access is controlled with row-level security. Two-factor authentication is available for all accounts."
        />
        <ReversibleCard
          title="Contact"
          description="Data Protection Officer: dpo@lap-coach.racing. For privacy inquiries, support tickets, or to exercise your data rights, contact us through Settings > Support or email directly."
        />
      </section>

      <div className="mt-8 text-center text-xs text-steel font-body space-x-4">
        <Link href="/terms" className="hover:text-chalk transition">Terms of Service</Link>
        <Link href="/pricing" className="hover:text-chalk transition">Plans & Retention</Link>
        <Link href="/app/account/data" className="hover:text-chalk transition">Manage Your Data</Link>
      </div>
    </PageShell>
  );
}
