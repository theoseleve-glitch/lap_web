import { PageShell } from '@/components/site/PageShell';
import { ReversibleCard } from '@/components/ui/ReversibleCard';

export default function PrivacyPage() {
  return (
    <PageShell
      eyebrow="Legal"
      title="Privacy Policy"
      description="Summary privacy terms for telemetry data processing, retention, and user rights."
      tone="document"
    >
      <section className="grid gap-4">
        <ReversibleCard
          title="What We Process"
          description="Telemetry and account data are used to deliver analysis, support your account, and protect platform security."
        />
        <ReversibleCard
          title="Your Rights"
          description="You can request export, correction, or deletion of your data. Requests are processed with auditable workflows."
        />
        <ReversibleCard
          title="Service Providers"
          description="Hosting, observability, and billing vendors operate under processing obligations and access controls."
        />
      </section>
    </PageShell>
  );
}
