'use client';

import { useEffect, useState } from 'react';
import type { Plan } from '@/data/pricing';
import { PitButton } from './PitButton';
import { StampButton } from './StampButton';
import { StatusPill } from '@/components/site/StatusPill';

interface PricingTableProps {
  plans: Plan[];
  billingPeriod: 'monthly' | 'annual';
  onCtaClick?: (planName: string) => void;
  className?: string;
}

function convertPriceLabel(label: string, currency: 'eur' | 'usd'): string {
  if (currency === 'eur') return label;
  if (!label.toUpperCase().includes('EUR')) return label;

  return label.replace(/EUR\s*([\d,.]+)/gi, (_, amount) => {
    const normalized = Number(amount.replace(/,/g, ''));
    if (!Number.isFinite(normalized)) return `USD ${amount}`;
    const converted = normalized * 1.08;
    return `USD ${converted.toFixed(converted >= 100 ? 0 : 2)}`;
  });
}

export function PricingTable({
  plans,
  billingPeriod,
  onCtaClick,
  className = '',
}: PricingTableProps) {
  const [currency, setCurrency] = useState<'eur' | 'usd'>('eur');

  useEffect(() => {
    const cookie = document.cookie
      .split(';')
      .map((part) => part.trim())
      .find((part) => part.startsWith('lap_currency='));
    if (!cookie) return;
    const value = cookie.split('=').slice(1).join('=');
    if (value === 'usd' || value === 'eur') {
      setCurrency(value);
    }
  }, []);

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
          {plan.highlighted && (
            <p className="inline-flex mb-3 border border-pit-orange bg-pit-orange/18 px-2 py-1 font-telemetry text-[10px] tracking-[0.12em] uppercase text-pit-orange">
              Most Popular
            </p>
          )}
          <div className="flex items-start justify-between gap-2 mb-2">
            <h3 className="font-monument text-[var(--text-h3)]">{plan.name}</h3>
            <StatusPill status={plan.availability} />
          </div>
          <p className="font-monument text-[clamp(34px,4vw,52px)] text-chalk mb-4 leading-[0.95]">
            {convertPriceLabel(
              billingPeriod === 'monthly' ? plan.priceMonthly : plan.priceAnnual,
              currency,
            )}
          </p>

          <div className="space-y-2 mb-6">
            {Object.entries(plan.features).map(([key, val], j) => (
              <div
                key={key}
                className={`flex justify-between py-2 px-2 font-body text-base ${
                  j % 2 === 0 ? 'bg-asphalt/40' : ''
                }`}
              >
                <span className="text-steel">{key}</span>
                <span className="text-chalk">{val}</span>
              </div>
            ))}
          </div>

          {plan.highlighted ? (
            <PitButton
              href={plan.ctaHref}
              onClick={() => onCtaClick?.(plan.name)}
              className="w-full"
            >
              {plan.cta}
            </PitButton>
          ) : (
            <StampButton
              href={plan.ctaHref}
              onClick={() => onCtaClick?.(plan.name)}
              className="w-full"
            >
              {plan.cta}
            </StampButton>
          )}

          <a
            href={plan.personaHref}
            className="mt-3 inline-block font-telemetry text-[10px] tracking-[0.12em] uppercase text-steel hover:text-chalk"
          >
            {plan.personaLabel}
          </a>
        </div>
      ))}
    </div>
  );
}
