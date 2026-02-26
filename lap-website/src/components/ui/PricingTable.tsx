'use client';

import type { Plan } from '@/data/pricing';
import { PitButton } from './PitButton';
import { StampButton } from './StampButton';

interface PricingTableProps {
  plans: Plan[];
  billingPeriod: 'monthly' | 'annual';
  onCtaClick?: (planName: string) => void;
  className?: string;
}

export function PricingTable({
  plans,
  billingPeriod,
  onCtaClick,
  className = '',
}: PricingTableProps) {
  return (
    <div className={`grid grid-cols-1 md:grid-cols-3 gap-0 ${className}`}>
      {plans.map((plan, i) => (
        <div
          key={plan.name}
          className={`
            p-6 bg-concrete
            ${plan.highlighted ? 'border-2 border-pit-orange' : 'border border-steel/20'}
            ${i > 0 ? 'md:border-l-0' : ''}
          `}
        >
          <h3 className="font-monument text-[var(--text-h3)] mb-2">{plan.name}</h3>
          <p className="font-monument text-[var(--text-h2)] text-chalk mb-4">
            {billingPeriod === 'monthly' ? plan.priceMonthly : plan.priceAnnual}
          </p>

          <div className="space-y-2 mb-6">
            {Object.entries(plan.features).map(([key, val], j) => (
              <div
                key={key}
                className={`flex justify-between py-2 px-2 font-body text-sm ${
                  j % 2 === 0 ? 'bg-asphalt/40' : ''
                }`}
              >
                <span className="text-steel">{key}</span>
                <span className="text-chalk">{val}</span>
              </div>
            ))}
          </div>

          {plan.highlighted ? (
            <PitButton onClick={() => onCtaClick?.(plan.name)} className="w-full">
              {plan.cta}
            </PitButton>
          ) : (
            <StampButton onClick={() => onCtaClick?.(plan.name)} className="w-full">
              {plan.cta}
            </StampButton>
          )}
        </div>
      ))}
    </div>
  );
}
