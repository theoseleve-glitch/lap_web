export interface FaqItem {
  question: string;
  answer: string;
}

export const faqItems: FaqItem[] = [
  {
    question: 'What payment methods do you accept?',
    answer: 'Card via Stripe. Bank transfer for venue and team annual plans.',
  },
  {
    question: 'Can I switch plans?',
    answer: 'Upgrade or downgrade anytime. Changes are prorated.',
  },
  {
    question: 'What data formats are supported?',
    answer:
      'Available now: RaceChrono CSV and RaceBox exports. Roadmap: additional sim telemetry connectors through waitlist.',
  },
  {
    question: 'Is my data private?',
    answer: 'Your data. Encrypted at rest. Never shared with third parties. Delete anytime.',
  },
  {
    question: 'What devices are supported?',
    answer: 'Upload from any device. Analysis runs in the cloud.',
  },
  {
    question: 'Do you support sim racing?',
    answer: 'Roadmap only at this time. Join the waitlist for early access.',
  },
];
