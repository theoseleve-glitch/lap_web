import { notFound } from 'next/navigation';
import { PageIntro } from '@/components/ui/PageIntro';
import { SuccessPage } from '@/components/site/SuccessPage';
import { ThankYouTracker } from '@/components/site/ThankYouTracker';
import { generateSeoMetadata } from '@/lib/seo';

export const metadata = generateSeoMetadata('/thank-you');

interface SuccessConfig {
  eyebrow: string;
  title: string;
  summary: string;
  nextSteps: string[];
  actions: { label: string; href: string; primary?: boolean }[];
}

const FORM_CONFIG: Record<string, SuccessConfig> = {
  contact: {
    eyebrow: 'Contact Received',
    title: 'We\'ll be in touch',
    summary: 'Your message has been received and our team has been notified. We typically respond within one business day.',
    nextSteps: [
      'Check your inbox for a confirmation email',
      'Our team will review your request and respond',
      'Explore the product while you wait',
    ],
    actions: [
      { label: 'Explore Product', href: '/product', primary: true },
      { label: 'View Pricing', href: '/pricing' },
      { label: 'Return Home', href: '/' },
    ],
  },
  demo: {
    eyebrow: 'Demo Requested',
    title: 'Demo request confirmed',
    summary: 'A member of our team will reach out to schedule your personalized demo session.',
    nextSteps: [
      'Check your inbox for a confirmation email',
      'We\'ll contact you within 24 hours to schedule',
      'Prepare a sample CSV if you\'d like a live walkthrough',
    ],
    actions: [
      { label: 'Start Free', href: '/register?source=thank-you', primary: true },
      { label: 'View Pricing', href: '/pricing' },
      { label: 'Return Home', href: '/' },
    ],
  },
  book: {
    eyebrow: 'Booking Confirmed',
    title: 'Booking request received',
    summary: 'We\'ll confirm your preferred date and send calendar details shortly.',
    nextSteps: [
      'Check your inbox for a confirmation email',
      'We\'ll confirm or suggest alternative times',
      'Add the meeting to your calendar once confirmed',
    ],
    actions: [
      { label: 'Explore Product', href: '/product', primary: true },
      { label: 'View Pricing', href: '/pricing' },
      { label: 'Return Home', href: '/' },
    ],
  },
  waitlist: {
    eyebrow: 'Waitlist Joined',
    title: 'You\'re on the list',
    summary: 'We\'ll notify you as soon as your spot opens up. Early access members get priority onboarding.',
    nextSteps: [
      'Check your inbox for a confirmation email',
      'We\'ll notify you when access is available',
      'Follow us on social media for updates',
    ],
    actions: [
      { label: 'View Pricing', href: '/pricing', primary: true },
      { label: 'Explore Product', href: '/product' },
      { label: 'Return Home', href: '/' },
    ],
  },
};

export default function ThankYouPage({ params }: { params: { form: string } }) {
  const config = FORM_CONFIG[params.form];
  if (!config) {
    notFound();
  }

  return (
    <main className="mx-auto max-w-6xl px-4 py-10 md:py-14">
      <PageIntro
        eyebrow={config.eyebrow}
        title="Thank You"
        subtitle="Your submission has been recorded."
      />
      <ThankYouTracker formType={params.form} />
      <SuccessPage
        title={config.title}
        summary={config.summary}
        nextSteps={config.nextSteps}
        actions={config.actions}
      />
    </main>
  );
}
