export type Currency = 'eur' | 'usd' | 'gbp';

export interface PriceSet {
  symbol: string;
  racer_monthly: string;
  racer_annual: string;
  racer_annual_per_month: string;
  racer_annual_total: string;
  racer_savings: string;
  worldClass_monthly: string;
  worldClass_annual: string;
  worldClass_annual_per_month: string;
  worldClass_annual_total: string;
  worldClass_savings: string;
}

export const currencyPrices: Record<Currency, PriceSet> = {
  eur: {
    symbol: '€',
    racer_monthly: '€8.99',
    racer_annual: '€69',
    racer_annual_per_month: '€5.75',
    racer_annual_total: '€69/yr',
    racer_savings: '36',
    worldClass_monthly: '€13.99',
    worldClass_annual: '€109',
    worldClass_annual_per_month: '€9.08',
    worldClass_annual_total: '€109/yr',
    worldClass_savings: '35',
  },
  usd: {
    symbol: '$',
    racer_monthly: '$9.99',
    racer_annual: '$79',
    racer_annual_per_month: '$6.58',
    racer_annual_total: '$79/yr',
    racer_savings: '34',
    worldClass_monthly: '$15.99',
    worldClass_annual: '$119',
    worldClass_annual_per_month: '$9.92',
    worldClass_annual_total: '$119/yr',
    worldClass_savings: '38',
  },
  gbp: {
    symbol: '£',
    racer_monthly: '£7.99',
    racer_annual: '£59',
    racer_annual_per_month: '£4.92',
    racer_annual_total: '£59/yr',
    racer_savings: '38',
    worldClass_monthly: '£11.99',
    worldClass_annual: '£99',
    worldClass_annual_per_month: '£8.25',
    worldClass_annual_total: '£99/yr',
    worldClass_savings: '31',
  },
};
