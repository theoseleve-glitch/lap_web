/**
 * Numbers formatting helpers for marketing content.
 *
 * Enforces the NUMBERS_POLICY defined in brand.ts:
 *  - Speed: km/h (not kph/kmh/KPH)
 *  - Lap time: 1:23.45 (mm:ss.cc) for display, 83.45s for inline
 *  - Deltas: +0.32s or -0.15s (always sign, 2 decimal places)
 *  - Percentages: 36% (no decimal unless < 1%)
 *  - Grip/confidence: 1% increments (e.g., 87%)
 *  - Currency: EUR with symbol prefix (e.g., \u20ac8.99)
 *  - Decimal separator: "." for EN, "," for FR
 *  - Thousands separator: none for < 10,000; thin space for >= 10,000
 */

export type Locale = 'en' | 'fr';

const DECIMAL_SEP: Record<Locale, string> = { en: '.', fr: ',' };

function decSep(locale: Locale): string {
  return DECIMAL_SEP[locale];
}

/** Format a speed value in km/h. Input assumed m/s or km/h based on `unit`. */
export function formatSpeed(
  value: number,
  opts?: { unit?: 'ms' | 'kmh'; decimals?: number; locale?: Locale },
): string {
  const { unit = 'kmh', decimals = 0, locale = 'en' } = opts ?? {};
  const kmh = unit === 'ms' ? value * 3.6 : value;
  const formatted = kmh.toFixed(decimals).replace('.', decSep(locale));
  return `${formatted}\u00a0km/h`;
}

/** Format a lap time. Input in seconds. Returns mm:ss.cc */
export function formatLapTime(seconds: number, locale: Locale = 'en'): string {
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  const secsStr = secs.toFixed(2).padStart(5, '0').replace('.', decSep(locale));
  return mins > 0 ? `${mins}:${secsStr}` : `${secsStr}s`;
}

/** Format a time delta. Always includes sign. 2 decimal places. */
export function formatDelta(seconds: number, locale: Locale = 'en'): string {
  const sign = seconds >= 0 ? '+' : '';
  return `${sign}${seconds.toFixed(2).replace('.', decSep(locale))}s`;
}

/**
 * Format a percentage. No decimal unless < 1%.
 * FR locale adds narrow no-break space before % per typographic rules.
 */
export function formatPercent(value: number, locale: Locale = 'en'): string {
  const spacer = locale === 'fr' ? '\u202F' : '';
  if (value > 0 && value < 1) return `${value.toFixed(1).replace('.', decSep(locale))}${spacer}%`;
  return `${Math.round(value)}${spacer}%`;
}

/** Format EUR currency. Symbol prefix, 2 decimals. */
export function formatEUR(value: number, locale: Locale = 'en'): string {
  return `\u20ac${value.toFixed(2).replace('.', decSep(locale))}`;
}

/** Format a large number with thin space thousands separator. */
export function formatNumber(
  value: number,
  opts?: { decimals?: number; locale?: Locale },
): string {
  const { decimals = 0, locale = 'en' } = opts ?? {};
  const fixed = value.toFixed(decimals);
  const [intPart = '0', decPart] = fixed.split('.');
  const absInt = intPart.replace('-', '');

  let formatted = absInt;
  if (parseInt(absInt, 10) >= 10_000) {
    formatted = absInt.replace(/\B(?=(\d{3})+(?!\d))/g, '\u2009');
  }

  if (intPart.startsWith('-')) formatted = `-${formatted}`;
  if (decPart !== undefined) {
    formatted += `${decSep(locale)}${decPart}`;
  }
  return formatted;
}

/**
 * Format a value with unit, respecting locale spacing.
 * FR uses narrow no-break space before units (km/h, s, etc.).
 * EN uses non-breaking space before units.
 */
export function formatWithUnit(value: string, unit: string, locale: Locale = 'en'): string {
  const spacer = locale === 'fr' ? '\u202F' : '\u00a0';
  return `${value}${spacer}${unit}`;
}

/**
 * Format seconds for display. Uses "s" suffix.
 * For sub-second engineering contexts only — marketing should use formatLapTime.
 */
export function formatSeconds(value: number, opts?: { decimals?: number; locale?: Locale }): string {
  const { decimals = 2, locale = 'en' } = opts ?? {};
  return `${value.toFixed(decimals).replace('.', decSep(locale))}s`;
}

/**
 * Apply FR typographic punctuation spacing.
 * Adds narrow no-break space before : ; ! ? and after opening guillemets.
 */
export function frPunctuation(text: string): string {
  return text
    .replace(/\s*([;:!?])/g, '\u202F$1')
    .replace(/\u00AB\s*/g, '\u00AB\u202F')
    .replace(/\s*\u00BB/g, '\u202F\u00BB');
}
