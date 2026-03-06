/**
 * FAQ registry — single source of truth for all FAQ entries.
 * Pages reference questions by id; inline questions are forbidden.
 */

export interface FaqEntry {
  id: string;
  question: string;
  answer: string;
  scope: 'global' | 'pricing' | 'product' | 'venue' | 'legal';
  canonicalPage: string;
}

export const FAQ_REGISTRY: FaqEntry[] = [
  {
    id: 'faq-payment-methods',
    question: 'What payment methods do you accept?',
    answer: 'Card via Stripe. Bank transfer for venue and team annual plans.',
    scope: 'pricing',
    canonicalPage: '/pricing',
  },
  {
    id: 'faq-switch-plans',
    question: 'Can I switch plans?',
    answer: 'Upgrade or downgrade anytime. Changes are prorated.',
    scope: 'pricing',
    canonicalPage: '/pricing',
  },
  {
    id: 'faq-data-formats',
    question: 'What data formats are supported?',
    answer: 'Available now: RaceChrono CSV and RaceBox exports. Roadmap: additional sim telemetry connectors through waitlist.',
    scope: 'global',
    canonicalPage: '/pricing',
  },
  {
    id: 'faq-data-privacy',
    question: 'Is my data private?',
    answer: 'Your data. Encrypted at rest. Never shared with third parties. Delete anytime.',
    scope: 'global',
    canonicalPage: '/pricing',
  },
  {
    id: 'faq-devices',
    question: 'What devices are supported?',
    answer: 'Upload from any device. Analysis runs in the cloud.',
    scope: 'global',
    canonicalPage: '/pricing',
  },
  {
    id: 'faq-sim-racing',
    question: 'Do you support sim racing?',
    answer: 'Roadmap only at this time. Join the waitlist for early access.',
    scope: 'product',
    canonicalPage: '/pricing',
  },
  {
    id: 'faq-data-retention',
    question: 'How long is my data retained?',
    answer: 'Raw telemetry: 30 days (Demo), 90 days (Racer), 365 days (World-Class). Reports are retained indefinitely while your account is active.',
    scope: 'pricing',
    canonicalPage: '/pricing',
  },
  {
    id: 'faq-cancel-anytime',
    question: 'Can I cancel anytime?',
    answer: 'Yes. Cancel before period end and you keep access until expiry. No lock-in.',
    scope: 'pricing',
    canonicalPage: '/pricing',
  },
  {
    id: 'faq-refund-policy',
    question: 'What is your refund policy?',
    answer: '30-day money back guarantee on all paid plans.',
    scope: 'pricing',
    canonicalPage: '/pricing',
  },
  {
    id: 'faq-venue-hardware',
    question: 'What hardware do venues need?',
    answer: 'Slide-in/out GPS+IMU units with battery SOC dashboard. We handle provisioning.',
    scope: 'venue',
    canonicalPage: '/pricing',
  },
  {
    id: 'faq-gdpr',
    question: 'Is LAP GDPR compliant?',
    answer: 'Yes. EU data residency (Hetzner, Germany), full DPA available, deletion/export support, Argon2id passwords, encrypted backups.',
    scope: 'global',
    canonicalPage: '/privacy',
  },
  {
    id: 'faq-api-access',
    question: 'Which plans include API access?',
    answer: 'API access is available on the World-Class plan. Enterprise venues get custom API access.',
    scope: 'pricing',
    canonicalPage: '/pricing',
  },
];

export function getFaqById(id: string): FaqEntry | undefined {
  return FAQ_REGISTRY.find((f) => f.id === id);
}

export function getFaqsByScope(scope: FaqEntry['scope']): FaqEntry[] {
  return FAQ_REGISTRY.filter((f) => f.scope === scope || f.scope === 'global');
}
