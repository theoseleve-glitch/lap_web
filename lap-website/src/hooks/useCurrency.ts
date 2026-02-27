'use client';

import { useEffect, useState, useMemo } from 'react';
import { currencyPrices, type Currency, type PriceSet } from '@/data/pricing-currencies';
import { b2cPlans, type Plan } from '@/data/pricing';

function getCookie(name: string): string | undefined {
  if (typeof document === 'undefined') return undefined;
  const raw = document.cookie
    .split(';')
    .map((p) => p.trim())
    .find((p) => p.startsWith(`${name}=`));
  return raw ? raw.split('=').slice(1).join('=') : undefined;
}

/**
 * Returns the active currency, its price set, and b2cPlans with
 * price fields overridden for the active currency.
 */
export function useCurrency(): {
  currency: Currency;
  prices: PriceSet;
  localizedPlans: Plan[];
} {
  const [currency, setCurrency] = useState<Currency>('eur');

  useEffect(() => {
    const cookie = getCookie('lap_currency');
    if (cookie === 'eur' || cookie === 'usd' || cookie === 'gbp') {
      setCurrency(cookie);
    }
  }, []);

  const prices = currencyPrices[currency];

  const localizedPlans = useMemo(() => {
    return b2cPlans.map((plan) => {
      if (plan.slug === 'demo') return plan;

      if (plan.slug === 'racer') {
        return {
          ...plan,
          priceMonthly: `${prices.racer_monthly} / mo`,
          priceAnnual: `${prices.racer_annual} / yr`,
          priceAnnualPerMonth: `${prices.racer_annual_per_month} / mo`,
          annualTotal: prices.racer_annual_total,
          savingsPercent: prices.racer_savings,
        };
      }

      if (plan.slug === 'world-class') {
        return {
          ...plan,
          priceMonthly: `${prices.worldClass_monthly} / mo`,
          priceAnnual: `${prices.worldClass_annual} / yr`,
          priceAnnualPerMonth: `${prices.worldClass_annual_per_month} / mo`,
          annualTotal: prices.worldClass_annual_total,
          savingsPercent: prices.worldClass_savings,
        };
      }

      return plan;
    });
  }, [prices]);

  return { currency, prices, localizedPlans };
}
