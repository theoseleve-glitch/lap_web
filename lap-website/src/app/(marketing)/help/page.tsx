import Link from 'next/link';
import { JsonLd } from '@/components/seo/JsonLd';
import { PageIntro } from '@/components/ui/PageIntro';
import { generateSeoMetadata } from '@/lib/seo';

export const metadata = generateSeoMetadata('/help');

const gettingStarted = [
  { step: '01', text: 'Record your session with RaceChrono or RaceBox' },
  { step: '02', text: 'Export the CSV file from the app' },
  { step: '03', text: 'Upload to LAP via the dashboard or free report tool' },
  { step: '04', text: 'Review your analysis: pace, consistency, corner coaching, and more' },
];

const faq = [
  {
    q: 'Which data loggers are supported?',
    a: 'LAP supports RaceChrono and RaceBox CSV exports. GPS-only and GPS+OBD sessions are both accepted.',
  },
  {
    q: 'How large can my files be?',
    a: 'The streaming pipeline handles files over 10 GB with under 1 GB of peak memory. There is no practical size limit.',
  },
  {
    q: 'Is my data private?',
    a: 'Yes. Each workspace is isolated with row-level security. Your data is never shared with other users or used for training.',
  },
  {
    q: 'Can I compare sessions from different tracks?',
    a: 'Comparison works best between sessions on the same track. Cross-track comparison is on our roadmap.',
  },
  {
    q: 'How do I cancel or change my plan?',
    a: 'Go to Account > Billing in the app, or contact us at contact@lap-coach.racing.',
  },
];

export default function HelpPage() {
  return (
    <>
    <JsonLd
      pathname="/help"
      faqItems={[
        { question: 'How do I upload my first session?', answer: 'Export a CSV from RaceChrono or RaceBox, then drag it into the Sessions page. LAP processes it automatically.' },
        { question: 'Which data loggers are supported?', answer: 'LAP supports RaceChrono and RaceBox CSV exports. More formats are planned.' },
      ]}
    />
    <main className="mx-auto max-w-6xl px-4 py-10 md:py-14">
      <PageIntro
        eyebrow="Support"
        title="Help Center"
        subtitle="Everything you need to get started and get answers."
      />
      {/* Getting Started */}
      <section className="mb-10">
        <h2 className="font-monument text-[var(--text-h3)] mb-4">Getting Started</h2>
        <ol className="grid md:grid-cols-2 gap-3">
          {gettingStarted.map((item) => (
            <li key={item.step} className="border border-steel/20 bg-concrete/30 p-4 flex gap-3">
              <span className="font-telemetry text-pit-orange shrink-0">{item.step}</span>
              <span className="text-sm text-chalk">{item.text}</span>
            </li>
          ))}
        </ol>
      </section>

      {/* FAQ */}
      <section className="mb-10">
        <h2 className="font-monument text-[var(--text-h3)] mb-4">Frequently Asked Questions</h2>
        <dl className="space-y-4">
          {faq.map((item) => (
            <div key={item.q} className="border border-steel/20 bg-concrete/30 p-4">
              <dt className="font-monument text-sm text-chalk mb-1">{item.q}</dt>
              <dd className="text-sm text-steel">{item.a}</dd>
            </div>
          ))}
        </dl>
      </section>

      {/* Contact & Status */}
      <section className="grid md:grid-cols-2 gap-4">
        <div className="border border-steel/20 bg-concrete/30 p-5">
          <h2 className="font-monument text-[var(--text-h3)] mb-2">Contact Support</h2>
          <p className="text-sm text-steel mb-3">
            Need help with your account, data, or a technical issue?
          </p>
          <Link
            href="/contact"
            className="border border-pit-orange bg-pit-orange/10 px-4 py-2 text-sm text-chalk hover:bg-pit-orange/20 transition-colors inline-block"
          >
            Contact Us
          </Link>
        </div>
        <div className="border border-steel/20 bg-concrete/30 p-5">
          <h2 className="font-monument text-[var(--text-h3)] mb-2">System Status</h2>
          <p className="text-sm text-steel mb-3">
            Check current platform availability and incident history.
          </p>
          <Link
            href="/status"
            className="border border-steel/30 px-4 py-2 text-sm text-steel hover:text-chalk hover:border-chalk transition-colors inline-block"
          >
            View Status
          </Link>
        </div>
      </section>
    </main>
    </>
  );
}
