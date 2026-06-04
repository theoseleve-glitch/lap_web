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
 * Returns the active currency, its price set, and the membership plan(s) with
 * the standard + founding price localized for that currency. One membership,
 * monthly only — no per-tier or annual branching.
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

  const localizedPlans = useMemo(
    () =>
      b2cPlans.map((plan) => ({
        ...plan,
        priceMonthly: `${prices.standard_monthly} / mo`,
        foundingPriceMonthly: `${prices.founding_monthly} / mo`,
      })),
    [prices],
  );

  return { currency, prices, localizedPlans };
}
