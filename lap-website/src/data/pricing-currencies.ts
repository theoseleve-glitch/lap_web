export type Currency = 'eur' | 'usd' | 'gbp';

export interface PriceSet {
  symbol: string;
  standard_monthly: string;
  founding_monthly: string;
}

/**
 * One membership, monthly only (June-8 model). EUR is the real charge currency —
 * the Stripe prices are €19.90 standard / €14.90 Founding-50, and the backend
 * always creates a EUR checkout session. usd/gbp here are localized marketing
 * display only (the buyer sees the true EUR amount at Stripe checkout).
 */
export const currencyPrices: Record<Currency, PriceSet> = {
  eur: { symbol: '€', standard_monthly: '€19.90', founding_monthly: '€14.90' },
  usd: { symbol: '$', standard_monthly: '$21.90', founding_monthly: '$15.90' },
  gbp: { symbol: '£', standard_monthly: '£17.90', founding_monthly: '£12.90' },
};
