import Link from 'next/link';
import { notFound } from 'next/navigation';
import { PageShell } from '@/components/site/PageShell';
import { ThankYouTracker } from '@/components/site/ThankYouTracker';

const FORM_LABELS: Record<string, string> = {
  contact: 'Contact',
  demo: 'Demo',
  book: 'Booking',
  waitlist: 'Waitlist',
};

export default function ThankYouPage({ params }: { params: { form: string } }) {
  const label = FORM_LABELS[params.form];
  if (!label) {
    notFound();
  }

  return (
    <PageShell
      eyebrow="Thank You"
      title={`${label} Request Received`}
      description="Your submission has been recorded, conversion tracking has been fired, and the team has been notified."
    >
      <ThankYouTracker formType={params.form} />
      <section className="border border-steel/20 bg-concrete/30 p-6">
        <p className="text-steel mb-4">
          We have sent your request through the lead pipeline. A confirmation workflow is now active.
        </p>
        <div className="flex flex-wrap gap-3">
          <Link href="/pricing" className="border border-steel/30 px-4 py-2 text-sm hover:border-chalk">
            View Pricing
          </Link>
          <Link href="/product" className="border border-steel/30 px-4 py-2 text-sm hover:border-chalk">
            Explore Product
          </Link>
          <Link href="/" className="border border-steel/30 px-4 py-2 text-sm hover:border-chalk">
            Return Home
          </Link>
        </div>
      </section>
    </PageShell>
  );
}
