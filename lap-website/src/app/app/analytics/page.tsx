'use client';

import Link from 'next/link';
import { PageHeader } from '@/components/app';

const analyticsCards = [
  {
    title: 'Weather Analysis',
    description: 'Explore how temperature, wind, and precipitation conditions affect lap times and driving performance.',
    href: '/app/analytics/weather',
    icon: '~',
  },
  {
    title: 'Performance Trends',
    description: 'Track your score progression and best lap times over time to spot improvement patterns.',
    href: '/app/analytics/trends',
    icon: '/',
  },
  {
    title: 'Meteo Correlation',
    description: 'Deep dive into atmospheric correlations: temperature, humidity, and pressure vs performance metrics.',
    href: '/app/analytics/meteo',
    icon: '%',
  },
  {
    title: 'Weight Simulator',
    description: 'Simulate the impact of driver weight, kart weight, and ballast changes on lap time.',
    href: '/app/analytics/weight-simulator',
    icon: '#',
  },
  {
    title: 'Pace Predictor',
    description: 'Predict target lap times for a given track and conditions based on historical data.',
    href: '/app/analytics/pace-predictor',
    icon: '>',
  },
];

export default function AnalyticsHubPage() {
  return (
    <div>
      <PageHeader
        title="Analytics"
        subtitle="Advanced analysis tools and predictive insights"
      />

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mt-2">
        {analyticsCards.map((card) => (
          <Link
            key={card.href}
            href={card.href}
            className="group bg-concrete rounded-lg border border-steel/20 p-5 hover:border-acid-green/40 transition-colors flex flex-col"
          >
            <div className="flex items-center gap-3 mb-3">
              <span className="font-telemetry text-2xl text-acid-green w-8 text-center">
                {card.icon}
              </span>
              <h2 className="font-monument text-base text-chalk group-hover:text-acid-green transition-colors">
                {card.title}
              </h2>
            </div>
            <p className="text-steel font-body text-sm leading-relaxed flex-1">
              {card.description}
            </p>
            <div className="mt-3 text-right">
              <span className="font-telemetry text-xs text-steel group-hover:text-acid-green transition-colors">
                Explore →
              </span>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
