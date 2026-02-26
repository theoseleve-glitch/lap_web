import { BillingLifecyclePanel } from '@/components/site/BillingLifecyclePanel';
import { PageShell } from '@/components/site/PageShell';

export default function BillingPage() {
  return (
    <PageShell
      eyebrow="Billing Lifecycle"
      title="Checkout, Subscription, and Invoice Operations"
      description="This page executes checkout initiation, billing portal access, and plan-switch workflows through API endpoints."
    >
      <section className="mb-8">
        <BillingLifecyclePanel />
      </section>

      <section className="grid md:grid-cols-2 gap-4">
        <article className="border border-steel/20 p-4">
          <h2 className="font-monument text-[var(--text-h3)] mb-2">VAT and Currency Handling</h2>
          <ul className="space-y-2 text-sm text-steel">
            <li>Default currency is EUR with provider-side localization support.</li>
            <li>VAT ID is collected during checkout and validated by billing provider rules.</li>
            <li>Tax-inclusive and tax-exclusive totals are emitted in invoice events.</li>
          </ul>
        </article>
        <article className="border border-steel/20 p-4">
          <h2 className="font-monument text-[var(--text-h3)] mb-2">Invoice Flow</h2>
          <ul className="space-y-2 text-sm text-steel">
            <li>Invoice issuance handled by billing provider after successful payment.</li>
            <li>Invoices are accessible in the billing portal route.</li>
            <li>Failed payment and renewal retries follow provider dunning policy.</li>
          </ul>
        </article>
      </section>
    </PageShell>
  );
}
