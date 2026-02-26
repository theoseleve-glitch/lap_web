export interface Plan {
  name: string;
  priceMonthly: string;
  priceAnnual: string;
  features: Record<string, string>;
  cta: string;
  highlighted?: boolean;
}

export const b2cPlans: Plan[] = [
  {
    name: 'STARTER',
    priceMonthly: 'Free',
    priceAnnual: 'Free',
    features: {
      Sessions: '3/month',
      Scoring: 'Preview',
      Coaching: '—',
      History: '30 days',
      Reports: '—',
      Team: '—',
    },
    cta: 'START FREE',
  },
  {
    name: 'PERFORMANCE',
    priceMonthly: '€8.99/mo',
    priceAnnual: '€69/yr',
    features: {
      Sessions: 'Unlimited',
      Scoring: 'Full 4-pillar',
      Coaching: 'Corner-by-corner',
      History: '1 year',
      Reports: 'PDF export',
      Team: '—',
    },
    cta: 'UPGRADE',
    highlighted: true,
  },
  {
    name: 'PRO RACER',
    priceMonthly: '€13.99/mo',
    priceAnnual: '€109/yr',
    features: {
      Sessions: 'Unlimited',
      Scoring: 'Full 4-pillar',
      Coaching: 'Corner + dev plans',
      History: 'Unlimited',
      Reports: 'PDF + API/webhooks',
      Team: 'Up to 5 seats',
    },
    cta: 'GO PRO',
  },
];

export const b2bPlans: Plan[] = [
  {
    name: 'TRACK ESSENTIEL',
    priceMonthly: '—',
    priceAnnual: '€1,490/yr',
    features: {
      Drivers: 'Up to 50/event',
      Reports: 'Standard',
      Timing: 'Manual CSV',
      Support: 'Email',
      Setup: 'Self-serve docs',
    },
    cta: 'GET STARTED',
  },
  {
    name: 'CIRCUIT PRO',
    priceMonthly: '—',
    priceAnnual: '€2,990/yr',
    features: {
      Drivers: 'Up to 200/event',
      Reports: 'Branded',
      Timing: 'API integration',
      Support: 'Priority',
      Setup: 'Guided setup',
    },
    cta: 'BOOK DEMO',
    highlighted: true,
  },
  {
    name: 'CIRCUIT PREMIUM',
    priceMonthly: '—',
    priceAnnual: '€4,990/yr',
    features: {
      Drivers: 'Unlimited',
      Reports: 'White-label',
      Timing: 'Full + live',
      Support: 'Dedicated + SLA',
      Setup: 'Full onboarding',
    },
    cta: 'CONTACT SALES',
  },
];

export interface Addon {
  name: string;
  price: string;
}

export const addons: Addon[] = [
  { name: 'Advanced timing integration', price: '+€490/yr' },
  { name: 'Endurance module (6h+ events)', price: '+€390/yr' },
  { name: 'White-label upgrade', price: '+€990/yr' },
  { name: 'Premium SLA (4h response)', price: '+€690/yr' },
  { name: 'Extended API + webhooks', price: '+€290/yr' },
];
