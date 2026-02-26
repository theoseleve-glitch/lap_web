import { PageShell } from '@/components/site/PageShell';
import { ReversibleCard } from '@/components/ui/ReversibleCard';

export default function DpaPage() {
  return (
    <PageShell
      eyebrow="Legal"
      title="Data Processing Addendum"
      description="Data processing terms, subprocessors, and transfer controls."
      tone="document"
    >
      <section className="grid gap-4">
        <ReversibleCard
          title="Controller and Processor Roles"
          description="The DPA defines responsibilities, lawful processing boundaries, and operational safeguards."
        />
        <ReversibleCard
          title="Subprocessors and Transfers"
          description="Subprocessor usage is documented and transfer safeguards are applied when cross-border processing is required."
        />
        <ReversibleCard
          title="Signed Agreements"
          description="Signed DPA packages, including enterprise addenda, are available through the contact route."
        />
      </section>
    </PageShell>
  );
}
