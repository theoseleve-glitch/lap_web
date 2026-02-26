import { PageShell } from '@/components/site/PageShell';

export default function PrivacyPage() {
  return (
    <PageShell
      eyebrow="Legal"
      title="Privacy Policy"
      description="Summary privacy terms for telemetry data processing, retention, and user rights."
    >
      <section className="space-y-4 text-sm text-steel">
        <p>
          We process telemetry and account information for product operation, support, and security
          monitoring. Processing is limited to contractual and legitimate-interest purposes.
        </p>
        <p>
          Data subjects can request export, correction, or deletion through account settings or the
          contact form. Deletion requests are logged and processed within defined retention windows.
        </p>
        <p>
          We use service providers for hosting, observability, and billing. Each provider is bound
          by data processing obligations and access controls.
        </p>
      </section>
    </PageShell>
  );
}
