import type { CapabilityStatus } from '@/data/claim-registry';

export interface Plan {
  name: string;
  priceMonthly: string;
  priceAnnual: string;
  features: Record<string, string>;
  cta: string;
  ctaHref: string;
  personaLabel: string;
  personaHref: string;
  highlighted?: boolean;
  availability: CapabilityStatus;
}

export const b2cPlans: Plan[] = [
  {
    name: 'STARTER',
    priceMonthly: 'Free',
    priceAnnual: 'Free',
    features: {
      Sessions: '3 / month',
      Scoring: 'Preview',
      Coaching: 'Not included',
      History: '30 days',
      Reports: 'Not included',
      Team: 'Single user',
    },
    cta: 'Start Free',
    ctaHref: '/register?source=starter',
    personaLabel: 'Built for drivers',
    personaHref: '/drivers',
    availability: 'available_now',
  },
  {
    name: 'PERFORMANCE',
    priceMonthly: 'EUR 8.99 / mo',
    priceAnnual: 'EUR 69 / yr',
    features: {
      Sessions: 'Unlimited',
      Scoring: 'Full 4-pillar',
      Coaching: 'Corner-by-corner',
      History: '1 year',
      Reports: 'PDF export',
      Team: 'Single user',
    },
    cta: 'Upgrade',
    ctaHref: '/billing?plan=PERFORMANCE&billing=annual',
    personaLabel: 'Built for drivers',
    personaHref: '/drivers',
    highlighted: true,
    availability: 'available_now',
  },
  {
    name: 'PRO RACER',
    priceMonthly: 'EUR 13.99 / mo',
    priceAnnual: 'EUR 109 / yr',
    features: {
      Sessions: 'Unlimited',
      Scoring: 'Full 4-pillar',
      Coaching: 'Corner + development plans',
      History: 'Unlimited',
      Reports: 'PDF + API',
      Team: 'Up to 5 seats',
    },
    cta: 'Go Pro',
    ctaHref: '/billing?plan=PRO%20RACER&billing=annual',
    personaLabel: 'Built for drivers and coaches',
    personaHref: '/teams',
    availability: 'available_now',
  },
];

export const b2bPlans: Plan[] = [
  {
    name: 'TRACK ESSENTIAL',
    priceMonthly: 'Contact Sales',
    priceAnnual: 'Contact Sales',
    features: {
      Drivers: 'Up to 50 / event',
      Reports: 'Standard',
      Timing: 'Manual CSV',
      Support: 'Email',
      Setup: 'Self-serve docs',
    },
    cta: 'Contact Sales',
    ctaHref: '/contact?plan=TRACK%20ESSENTIAL',
    personaLabel: 'Built for circuits',
    personaHref: '/circuits',
    availability: 'available_now',
  },
  {
    name: 'CIRCUIT PRO',
    priceMonthly: 'Contact Sales',
    priceAnnual: 'Contact Sales',
    features: {
      Drivers: 'Up to 200 / event',
      Reports: 'Branded',
      Timing: 'API integration',
      Support: 'Priority',
      Setup: 'Guided onboarding',
    },
    cta: 'Contact Sales',
    ctaHref: '/demo?plan=CIRCUIT%20PRO',
    personaLabel: 'Built for circuits and operators',
    personaHref: '/circuits',
    highlighted: true,
    availability: 'available_now',
  },
  {
    name: 'CIRCUIT ENTERPRISE',
    priceMonthly: 'Contact Sales',
    priceAnnual: 'Contact Sales',
    features: {
      Drivers: 'Unlimited',
      Reports: 'White-label',
      Timing: 'Live + API',
      Support: 'Dedicated + SLA',
      Setup: 'Operator onboarding',
    },
    cta: 'Contact Sales',
    ctaHref: '/contact?plan=CIRCUIT%20ENTERPRISE',
    personaLabel: 'Built for enterprise teams',
    personaHref: '/teams',
    availability: 'enterprise_on_request',
  },
];

export interface Addon {
  name: string;
  price: string;
  status: CapabilityStatus;
  note?: string;
}

export const addons: Addon[] = [
  {
    name: 'Advanced timing integration',
    price: '+EUR 490 / yr',
    status: 'available_now',
  },
  {
    name: 'Endurance module (6h+ events)',
    price: '+EUR 390 / yr',
    status: 'enterprise_on_request',
  },
  {
    name: 'White-label reporting',
    price: '+EUR 990 / yr',
    status: 'enterprise_on_request',
  },
  {
    name: 'Premium SLA (4h response)',
    price: '+EUR 690 / yr',
    status: 'enterprise_on_request',
  },
  {
    name: 'Webhook tiering',
    price: 'Roadmap',
    status: 'roadmap',
    note: 'Coming soon',
  },
];

export interface EligibilityRow {
  feature: string;
  starter: string;
  performance: string;
  proRacer: string;
  circuitPro: string;
  enterprise: string;
}

export const featureEligibilityMatrix: EligibilityRow[] = [
  {
    feature: 'Upload and analyze wizard',
    starter: 'Yes',
    performance: 'Yes',
    proRacer: 'Yes',
    circuitPro: 'Yes',
    enterprise: 'Yes',
  },
  {
    feature: 'Session intelligence tabs',
    starter: 'Preview',
    performance: 'Yes',
    proRacer: 'Yes',
    circuitPro: 'Yes',
    enterprise: 'Yes',
  },
  {
    feature: 'Driver-vs-driver comparison',
    starter: 'No',
    performance: 'No',
    proRacer: 'Yes',
    circuitPro: 'Yes',
    enterprise: 'Yes',
  },
  {
    feature: 'Control room dashboards',
    starter: 'No',
    performance: 'No',
    proRacer: 'No',
    circuitPro: 'On request',
    enterprise: 'Yes',
  },
  {
    feature: 'Sim telemetry ingestion',
    starter: 'Roadmap',
    performance: 'Roadmap',
    proRacer: 'Roadmap',
    circuitPro: 'Roadmap',
    enterprise: 'Roadmap',
  },
];
