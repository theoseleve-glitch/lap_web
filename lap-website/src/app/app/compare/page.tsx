'use client';

import Link from 'next/link';
import { PageHeader } from '@/components/app';

const compareCards = [
  {
    title: 'Compare Sessions',
    description:
      'Put two sessions side-by-side to see how lap times, scores, and driving style differ across different outings.',
    href: '/app/compare/sessions',
    icon: '◎',
  },
  {
    title: 'Compare Drivers',
    description:
      'Benchmark two drivers head-to-head with performance radar, pace metrics, and consistency analysis.',
    href: '/app/compare/drivers',
    icon: '◈',
  },
];

export default function CompareHubPage() {
  return (
    <div>
      <PageHeader
        title="Compare"
        subtitle="Side-by-side analysis of sessions and drivers"
      />

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-2">
        {compareCards.map((card) => (
          <Link
            key={card.href}
            href={card.href}
            className="group bg-concrete rounded-lg border border-steel/20 p-6 hover:border-acid-green/40 transition-colors"
          >
            <div className="flex items-start gap-4">
              <span className="font-telemetry text-3xl text-acid-green">{card.icon}</span>
              <div>
                <h2 className="font-monument text-xl text-chalk group-hover:text-acid-green transition-colors">
                  {card.title}
                </h2>
                <p className="mt-2 text-steel font-body text-sm leading-relaxed">
                  {card.description}
                </p>
              </div>
            </div>
            <div className="mt-4 text-right">
              <span className="font-telemetry text-xs text-steel group-hover:text-acid-green transition-colors">
                Open →
              </span>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
