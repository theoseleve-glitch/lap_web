import { PageShell } from '@/components/site/PageShell';

export default function DpaPage() {
  return (
    <PageShell
      eyebrow="Legal"
      title="Data Processing Addendum"
      description="Data processing terms, subprocessors, and transfer controls."
    >
      <section className="space-y-4 text-sm text-steel">
        <p>
          The DPA defines controller-processor obligations, data subject rights workflows, and
          security controls aligned with regional privacy regulations.
        </p>
        <p>
          Subprocessor usage is documented and reviewed. International transfers use applicable
          contractual safeguards where required.
        </p>
        <p>
          Customers can request a signed DPA through the contact route, including enterprise
          addenda for security questionnaires.
        </p>
      </section>
    </PageShell>
  );
}
